import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from imagescope import AnalysisRequest, AnalyzerError, analyze
from imagescope.contracts import MAX_EVENT_BYTES, bounded_json, validate_result
from imagescope.histograms import histogram_statistics
from imagescope.measurements import measure
from imagescope.presentation import show_result
from test_color_management import linear_rgb_profile


def encode(image, **options):
    output = io.BytesIO()
    image.save(output, 'PNG', **options)
    return output.getvalue()


def scalar_reference(pixels):
    rgb = [[0] * 256 for _ in range(3)]
    luminance = [0] * 256
    for red, green, blue, alpha in pixels:
        for histogram, channel in zip(rgb, (red, green, blue)):
            histogram[channel] += alpha
        linear = []
        for channel in (red, green, blue):
            value = channel / 255
            linear.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
        value = sum(channel * coefficient for channel, coefficient in zip(linear, (.2126, .7152, .0722)))
        luminance[min(255, int(value * 256))] += alpha
    return rgb, luminance


class HistogramTests(unittest.TestCase):
    def assert_conserved(self, histogram):
        for counts in [*histogram['rgb'].values(), histogram['luminance']]:
            self.assertEqual(len(counts), 256)
            self.assertTrue(all(type(value) is int and value >= 0 for value in counts))
            self.assertEqual(sum(counts), histogram['total_weight'])
        json.dumps(histogram, allow_nan=False)

    def test_ramps_and_asymmetric_values_match_independent_scalar_reference(self):
        for pixels in ([(i, i, i, 255) for i in range(256)],
                       [(i, 255 - i, (i * 37) % 256, (i * 13) % 256) for i in range(256)]):
            image = Image.new('RGBA', (256, 1))
            image.putdata(pixels)
            result = measure(image, histograms=True)['histograms']
            expected_rgb, expected_luminance = scalar_reference(pixels)
            self.assertEqual(list(result['rgb'].values()), expected_rgb)
            self.assertEqual(result['luminance'], expected_luminance)
            self.assert_conserved(result)

    def test_opacity_weighting_and_hidden_rgb(self):
        image = Image.new('RGBA', (4, 1))
        image.putdata([(0, 0, 0, 255), (255, 255, 255, 128),
                       (255, 0, 0, 64), (0, 255, 255, 0)])
        result = measure(image, histograms=True)['histograms']
        self.assertEqual(result['total_weight'], 447)
        self.assertEqual(result['visible_pixels'], 3)
        self.assertEqual(result['rgb']['red'][255], 192)
        endpoints = result['endpoint_occupancy']
        self.assertEqual(endpoints['all_channels_zero_fraction'], round(255 / 447, 6))
        self.assertEqual(endpoints['all_channels_max_fraction'], round(128 / 447, 6))
        self.assertEqual(endpoints['any_channel_max_fraction'], round(192 / 447, 6))
        self.assertEqual(endpoints['rgb']['green']['zero_fraction'], round(319 / 447, 6))
        self.assert_conserved(result)
        image.putpixel((3, 0), (255, 0, 128, 0))
        self.assertEqual(measure(image, histograms=True)['histograms'], result)

    def test_invisible_input_has_zero_counts_and_null_endpoint_fractions(self):
        result = measure(Image.new('RGBA', (10, 10), (255, 255, 255, 0)), histograms=True)['histograms']
        self.assertEqual(result['total_weight'], 0)
        self.assertEqual(result['visible_pixels'], 0)
        endpoints = result['endpoint_occupancy']
        for name, value in endpoints.items():
            if name == 'rgb':
                self.assertTrue(all(v is None for entry in value.values() for v in entry.values()))
            else:
                self.assertIsNone(value)
        self.assert_conserved(result)

    def test_near_endpoints_are_not_exact_black_or_white(self):
        image = Image.new('RGB', (4, 1))
        image.putdata([(0, 0, 0), (1, 1, 1), (254, 254, 254), (255, 255, 255)])
        result = measure(image, histograms=True)['histograms']
        self.assertEqual(result['luminance'][0], 510)
        self.assertEqual(result['endpoint_occupancy']['all_channels_zero_fraction'], .25)
        self.assertEqual(result['endpoint_occupancy']['all_channels_max_fraction'], .25)
        # Bright red is at a channel endpoint, but is neither white nor black.
        red = measure(Image.new('RGB', (1, 1), 'red'), histograms=True)['histograms']
        self.assertEqual(red['endpoint_occupancy']['any_channel_max_fraction'], 1)
        self.assertEqual(red['endpoint_occupancy']['all_channels_max_fraction'], 0)
        self.assertEqual(red['luminance'][54], 255)

    def test_sample_bound_alpha_modes_and_input_immutability(self):
        for mode, color, resampling in (('RGB', (80, 120, 200), 'pillow-bicubic'),
                                        ('RGBA', (80, 120, 200, 128), 'pillow-premultiplied-srgb8-lanczos')):
            image = Image.new(mode, (1200, 400), color)
            before = image.tobytes()
            result = measure(image, histograms=True)['histograms']
            self.assertEqual(result['sampling']['working_size'], [1200, 400])
            self.assertEqual(result['sampling']['sample_size'], [256, 85])
            self.assertEqual(result['sampling']['resampling'], resampling)
            self.assertTrue(result['sampling']['downsampled'])
            self.assertEqual(image.tobytes(), before)
            self.assertEqual(result, measure(image, histograms=True)['histograms'])
            self.assert_conserved(result)
        with self.assertRaises(ValueError):
            histogram_statistics(Image.new('RGB', (257, 1)), working_size=(257, 1), opaque=True)

    def test_default_results_unchanged_and_opt_in_versions_explicit(self):
        data = encode(Image.new('RGB', (16, 8), 'blue'))
        old = analyze(AnalysisRequest(data, task='inspect'))
        new = analyze(AnalysisRequest(data, task='inspect', histograms=True))
        self.assertEqual(new['status'], 'ok', new)
        validate_result(new)
        histograms = new['measurements'].pop('histograms')
        self.assertEqual(old['measurements'], new['measurements'])
        self.assertEqual(old['provenance']['measurements_version'], 6)
        self.assertEqual(new['provenance']['measurements_version'], 7)
        self.assertNotIn('histograms', old['provenance']['measurement_settings'])
        self.assertTrue(new['provenance']['measurement_settings']['histograms'])
        self.assertEqual(histograms['version'], 1)
        with patch('imagescope.histograms.histogram_statistics') as histogram:
            measure(Image.new('RGB', (2, 2)))
            histogram.assert_not_called()

    def test_roi_histograms_do_not_include_pixels_outside_crop(self):
        image = Image.new('RGB', (20, 10), 'red')
        image.paste('blue', (5, 2, 15, 8))
        result = analyze(AnalysisRequest(encode(image), task='inspect', region=(5, 2, 15, 8), histograms=True))
        self.assertEqual(result['status'], 'ok', result)
        histogram = result['measurements']['histograms']
        self.assertEqual(histogram['sampling']['working_size'], [10, 6])
        self.assertEqual(histogram['rgb']['blue'][255], 10 * 6 * 255)
        self.assertEqual(histogram['rgb']['red'][255], 0)
        self.assertEqual(result['provenance']['preprocessing']['version'], 5)
        self.assert_conserved(histogram)

    def test_color_policy_is_applied_before_histograms(self):
        data = encode(Image.new('RGB', (8, 4), (128, 128, 128)), icc_profile=linear_rgb_profile())
        legacy = analyze(AnalysisRequest(data, task='inspect', histograms=True))
        managed = analyze(AnalysisRequest(data, task='inspect', histograms=True, color_policy='srgb-v1'))
        self.assertEqual(managed['status'], 'ok', managed)
        self.assertEqual(legacy['measurements']['histograms']['rgb']['red'][128], 8 * 4 * 255)
        expected = round(255 * (1.055 * (128 / 255) ** (1 / 2.4) - .055))
        counts = managed['measurements']['histograms']['rgb']['red']
        self.assertEqual(sum(counts[expected - 1:expected + 2]), 8 * 4 * 255)
        self.assertEqual(managed['provenance']['preprocessing']['version'], 4)

    def test_describe_requires_measurements_and_retains_histograms_on_backend_failure(self):
        data = encode(Image.new('RGB', (8, 8)))
        backend = Mock()
        invalid = analyze(AnalysisRequest(data, histograms=True), backend=backend)
        self.assertEqual(invalid['error']['code'], 'invalid_request')
        backend.check_model.assert_not_called()
        backend.check_model.side_effect = AnalyzerError('backend_unavailable', 'offline')
        result = analyze(AnalysisRequest(data, measurements=True, histograms=True), backend=backend)
        self.assertEqual(result['error']['code'], 'backend_unavailable')
        self.assertIn('histograms', result['measurements'])
        self.assertEqual(result['provenance']['measurements_version'], 7)
        validate_result(result)
        for invalid_value in (1, 'true', None):
            result = analyze(AnalysisRequest(data, task='inspect', histograms=invalid_value))
            self.assertEqual(result['error']['code'], 'invalid_request')
            with self.assertRaises(ValueError):
                measure(Image.new('RGB', (1, 1)), histograms=invalid_value)

    def test_cli_api_jsonl_discovery_output_budget_and_human_summary(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            path = Path(directory) / 'source.png'
            data = encode(Image.new('RGB', (16, 8), 'white'))
            path.write_bytes(data)
            api = analyze(AnalysisRequest(path, task='inspect', histograms=True))
            command = [sys.executable, '-m', 'imagescope', 'inspect', str(path), '--histograms']
            process = subprocess.run(command + ['--json'], capture_output=True, text=True, timeout=30)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(process.stderr, '')
            cli = json.loads(process.stdout)
            self.assertEqual(cli['measurements'], api['measurements'])
            self.assertEqual(cli['provenance'], api['provenance'])
            events = subprocess.run(command + ['--events=jsonl'], capture_output=True, text=True, timeout=30)
            self.assertEqual(events.returncode, 0, events.stderr)
            records = [json.loads(line) for line in events.stdout.splitlines()]
            self.assertEqual(sum(row['type'] == 'result' for row in records), 1)
            self.assertEqual(records[-1]['result']['measurements'], api['measurements'])
            self.assertLess(len(bounded_json(api).encode()), MAX_EVENT_BYTES)
            output = io.StringIO()
            show_result(api, stream=output)
            self.assertIn('Histograms: 256 bins', output.getvalue())
            self.assertIn('not proof of clipping', output.getvalue())
            discovery = subprocess.run([sys.executable, '-m', 'imagescope', 'info', '--json'],
                                       capture_output=True, text=True, timeout=30)
            self.assertEqual(json.loads(discovery.stdout)['histograms']['version'], 1)
            self.assertEqual(path.read_bytes(), data)


if __name__ == '__main__':
    unittest.main()
