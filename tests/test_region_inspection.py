import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageCms

from imagescope import AnalysisRequest, AnalyzerError, MetadataRequest, analyze, inspect_metadata
from imagescope.contracts import validate_result
from imagescope.decode_worker import decode
from imagescope.images import prepare_image
from imagescope.measurements import measure
from imagescope.presentation import show_result
from cmyk_fixture import cmyk_profile


def encode(image, fmt='PNG', **options):
    data = io.BytesIO()
    image.save(data, fmt, **options)
    return data.getvalue()


def patterned_image():
    image = Image.new('RGB', (7, 5))
    image.putdata([(x * 30, y * 40, (x + y) * 20)
                   for y in range(5) for x in range(7)])
    return image


class RegionInspectionTests(unittest.TestCase):
    def test_oriented_original_coordinates_all_eight_orientations(self):
        source = patterned_image()
        transforms = {2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180,
                      4: Image.Transpose.FLIP_TOP_BOTTOM, 5: Image.Transpose.TRANSPOSE,
                      6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE,
                      8: Image.Transpose.ROTATE_90}
        for fmt in ('PNG', 'TIFF', 'JPEG'):
            # JPEG reference uses decoded samples, not the precompression input.
            with Image.open(io.BytesIO(encode(source, fmt))) as decoded:
                base = decoded.convert('RGB')
            for orientation in range(1, 9):
                with self.subTest(fmt=fmt, orientation=orientation):
                    exif = Image.Exif()
                    exif[274] = orientation
                    data = encode(source, fmt, exif=exif)
                    oriented = base.transpose(transforms[orientation]) if orientation != 1 else base
                    bounds = (1, 1, oriented.width, oriented.height - 1)
                    expected = oriented.crop(bounds)
                    metadata, actual = prepare_image(data, region=bounds)
                    self.assertEqual(actual.size, expected.size)
                    self.assertEqual(actual.tobytes(), expected.tobytes())
                    self.assertEqual((metadata['width'], metadata['height']), oriented.size)
                    self.assertEqual(metadata['sha256'], hashlib.sha256(data).hexdigest())
                    self.assertEqual(metadata['preprocessing']['region']['bounds'], list(bounds))
                    if fmt == 'TIFF':
                        headers = inspect_metadata(MetadataRequest(data))
                        self.assertEqual(headers['metadata']['stored_size'], {'width': 7, 'height': 5})
                        self.assertEqual(headers['metadata']['oriented_size'],
                                         {'width': oriented.width, 'height': oriented.height})
                        whole_metadata, whole = prepare_image(data)
                        self.assertEqual((whole_metadata['width'], whole_metadata['height']), oriented.size)
                        self.assertEqual(whole.size, oriented.size)

    def test_palette_luminance_transparency_match_independent_crop(self):
        image = Image.new('RGBA', (14, 10), (255, 0, 255, 0))
        image.paste((10, 100, 30, 128), (4, 2, 10, 8))
        image.paste((20, 40, 200, 255), (6, 4, 8, 6))
        region = (3, 1, 11, 9)
        backend = Mock()
        result = analyze(AnalysisRequest(encode(image), task='inspect', region=region,
                                        palette_size=8), backend=backend)
        self.assertEqual(result['status'], 'ok', result)
        validate_result(result)
        self.assertEqual(result['measurements'], measure(image.crop(region), 8))
        self.assertEqual(result['measurements']['transparency']['visible_bounds'], [1, 1, 7, 7])
        self.assertEqual(result['input']['width'], 14)
        self.assertEqual(result['provenance']['preprocessing']['version'], 5)
        self.assertEqual(result['provenance']['measurements_version'], 6)
        backend.check_model.assert_not_called()
        backend.describe.assert_not_called()

    def test_one_pixel_crop_from_large_source_is_not_from_reduced_preview(self):
        image = Image.new('RGB', (6000, 80), 'red')
        image.putpixel((3101, 21), (0, 255, 0))
        for fmt in ('PNG', 'JPEG'):
            with self.subTest(fmt=fmt):
                data = encode(image, fmt)
                with Image.open(io.BytesIO(data)) as original:
                    expected = original.convert('RGB').crop((3101, 21, 3102, 22))
                metadata, actual = prepare_image(data, region=(3101, 21, 3102, 22))
                self.assertEqual(actual.size, (1, 1))
                self.assertEqual(actual.tobytes(), expected.tobytes())
                self.assertFalse(metadata['preprocessing']['downsampled'])
                self.assertEqual(metadata['preprocessing']['decoder'], 'pillow-bounded')

    def test_downsampling_mapping_uses_crop_dimensions_and_rational_edges(self):
        image = Image.new('RGBA', (5010, 104), (250, 0, 100, 0))
        image.paste((0, 180, 60, 255), (5, 3, 5005, 103))
        bounds = (5, 3, 5005, 103)
        data = encode(image)
        metadata, actual = prepare_image(data, region=bounds)
        expected = image.crop(bounds)
        expected.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
        self.assertEqual(actual.tobytes(), expected.tobytes())
        prep = metadata['preprocessing']
        region = prep['region']
        self.assertTrue(prep['downsampled'])
        self.assertEqual(region['crop_size'], [5000, 100])
        self.assertEqual(region['working_size'], list(actual.size))
        self.assertFalse(region['visible_bounds_are_source_bounds'])
        from fractions import Fraction
        for axis, start, end, size in (('x', 5, 5005, actual.width), ('y', 3, 103, actual.height)):
            mapping = region['working_to_source'][axis]
            self.assertEqual(mapping['offset'], start)
            self.assertEqual(mapping['offset'] + size * Fraction(mapping['numerator'], mapping['denominator']), end)
        # All outside pixels are magenta but cannot bleed into a crop resized
        # after selection; all emitted visible colors are green.
        result = analyze(AnalysisRequest(data, task='inspect', region=bounds))
        self.assertEqual(result['measurements']['palette'][0]['rgb'], [0, 180, 60])

    def test_empty_alpha_and_palette_transparency_are_crop_local(self):
        rgba = Image.new('RGBA', (10, 10), (200, 30, 90, 0))
        rgba.paste((0, 0, 255, 255), (0, 0, 3, 3))
        result = analyze(AnalysisRequest(encode(rgba), task='inspect', region=(5, 5, 10, 10)))
        self.assertEqual(result['measurements']['palette'], [])
        self.assertIsNone(result['measurements']['transparency']['visible_bounds'])
        self.assertEqual(result['measurements']['transparency']['transparent_fraction'], 1)
        palette = Image.new('P', (4, 1))
        palette.putpalette([255, 0, 0, 0, 255, 0] + [0] * 762)
        palette.putdata([0, 1, 0, 1])
        data = encode(palette, transparency=0)
        _, crop = prepare_image(data, region=(1, 0, 3, 1))
        self.assertEqual(crop.getpixel((0, 0)), (0, 255, 0, 255))
        self.assertEqual(crop.getpixel((1, 0))[3], 0)

    def test_profiled_rgba_and_cmyk_regions(self):
        rgba = Image.new('RGBA', (5, 4), (40, 80, 160, 128))
        srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        data = encode(rgba, icc_profile=srgb)
        metadata, actual = prepare_image(data, region=(1, 1, 4, 3), color_policy='srgb-v1')
        self.assertEqual(actual.tobytes(), rgba.crop((1, 1, 4, 3)).tobytes())
        self.assertEqual(metadata['preprocessing']['color_management']['status'], 'converted')
        cmyk = Image.new('CMYK', (10, 10), (255, 255, 255, 255))
        cmyk.paste((0, 0, 0, 128), (3, 2, 8, 6))
        metadata, actual = prepare_image(encode(cmyk, 'TIFF', icc_profile=cmyk_profile()),
                                         region=(3, 2, 8, 6), color_policy='srgb-v1')
        self.assertEqual(actual.size, (5, 4))
        self.assertTrue(all(abs(value - 224) <= 2 for value in actual.getpixel((0, 0))))
        self.assertEqual(metadata['preprocessing']['color_management']['source_mode'], 'CMYK')

    def test_invalid_region_shape_is_rejected_before_starting_worker(self):
        invalid = ((0, 0, 0, 1), (2, 0, 1, 1), (0, 1, 1, 1), (-1, 0, 1, 1),
                   (False, 0, 1, 1), (0.0, 0, 1, 1), (0, 0, 1), [0, 0, 1, 1],
                   '0,0,1,1', (0, 0, 10**100, 1))
        for region in invalid:
            with self.subTest(region=region), patch('imagescope.images.subprocess.run') as run:
                result = analyze(AnalysisRequest(b'', task='inspect', region=region))
                self.assertEqual(result['error']['code'], 'invalid_request')
                run.assert_not_called()
        result = analyze(AnalysisRequest(b'', task='describe', region=(0, 0, 1, 1)))
        self.assertEqual(result['error']['code'], 'invalid_request')

    def test_out_of_bounds_uses_oriented_dimensions_before_color_conversion(self):
        exif = Image.Exif()
        exif[274] = 6
        data = encode(Image.new('RGB', (8, 3)), 'JPEG', exif=exif)
        for region in ((0, 0, 4, 2), (0, 0, 2, 9)):
            with patch('imagescope.color_management.apply_color_policy') as convert:
                with self.assertRaises(AnalyzerError) as error:
                    decode(data, 500_000_000, region=region)
                self.assertEqual(error.exception.code, 'invalid_request')
                convert.assert_not_called()
        result = analyze(AnalysisRequest(data, task='inspect', region=(0, 0, 4, 2)))
        self.assertEqual(result['error']['code'], 'invalid_request')
        self.assertEqual(result['provenance']['preprocessing']['region']['bounds'], [0, 0, 4, 2])

    def test_other_supported_formats_and_first_animation_frame(self):
        source = patterned_image()
        for fmt in ('BMP', 'GIF', 'WEBP'):
            with self.subTest(fmt=fmt):
                data = encode(source, fmt)
                with Image.open(io.BytesIO(data)) as original:
                    expected = original.convert('RGB').crop((2, 1, 6, 4))
                _, actual = prepare_image(data, region=(2, 1, 6, 4))
                self.assertEqual(actual.tobytes(), expected.tobytes())
        first = Image.new('RGB', (8, 5), 'red')
        second = Image.new('RGB', (8, 5), 'blue')
        data = encode(first, 'GIF', save_all=True, append_images=[second])
        metadata, actual = prepare_image(data, region=(2, 1, 6, 4))
        self.assertEqual(actual.getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(metadata['preprocessing']['frame'], 0)

    def test_whole_image_behavior_and_full_size_region_measurements(self):
        data = encode(patterned_image())
        default_metadata, default_image = prepare_image(data)
        explicit_metadata, explicit_image = prepare_image(data, region=None)
        self.assertEqual(default_metadata, explicit_metadata)
        self.assertEqual(default_image.tobytes(), explicit_image.tobytes())
        self.assertNotIn('region', default_metadata['preprocessing'])
        self.assertEqual(default_metadata['preprocessing']['version'], 3)
        full = analyze(AnalysisRequest(data, task='inspect'))
        region = analyze(AnalysisRequest(data, task='inspect', region=(0, 0, 7, 5)))
        self.assertEqual(full['measurements'], region['measurements'])

    def test_limits_and_worker_failures_do_not_fall_back(self):
        data = encode(patterned_image())
        for effect, code in ((subprocess.TimeoutExpired('worker', 30), 'decode_timeout'),
                             (subprocess.CompletedProcess([], -9, b'', b''), 'decode_resource_limit')):
            with patch('imagescope.images.subprocess.run') as run:
                if isinstance(effect, Exception):
                    run.side_effect = effect
                else:
                    run.return_value = effect
                result = analyze(AnalysisRequest(data, task='inspect', region=(0, 0, 1, 1)))
                self.assertEqual(result['error']['code'], code)
                self.assertIsNone(result['measurements'])
                run.assert_called_once()
        with patch('imagescope.images.MAX_SOURCE_PIXELS', 10):
            result = analyze(AnalysisRequest(data, task='inspect', region=(0, 0, 1, 1)))
            self.assertEqual(result['error']['code'], 'image_too_large')

    def test_cli_json_events_stdin_source_immutability_and_human_output(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            path = Path(directory) / 'source.png'
            data = encode(patterned_image())
            path.write_bytes(data)
            before = path.stat().st_mtime_ns
            request = AnalysisRequest(path, task='inspect', region=(1, 1, 6, 4))
            expected = analyze(request)
            command = [sys.executable, '-m', 'imagescope', 'inspect', str(path), '--region', '1', '1', '6', '4']
            process = subprocess.run(command + ['--json'], capture_output=True, text=True, timeout=30)
            self.assertEqual(process.returncode, 0, process.stderr)
            actual = json.loads(process.stdout)
            actual.pop('elapsed_seconds')
            expected.pop('elapsed_seconds')
            self.assertEqual(actual, expected)
            events = subprocess.run(command + ['--events=jsonl'], capture_output=True, text=True, timeout=30)
            self.assertEqual(events.returncode, 0, events.stderr)
            records = [json.loads(line) for line in events.stdout.splitlines()]
            self.assertEqual(sum(record['type'] == 'result' for record in records), 1)
            self.assertEqual(records[-1]['result']['measurements'], expected['measurements'])
            stdin = subprocess.run([sys.executable, '-m', 'imagescope', 'inspect', '--stdin',
                                    '--region', '1', '1', '6', '4', '--json'],
                                   input=data, capture_output=True, timeout=30)
            self.assertEqual(stdin.returncode, 0, stdin.stderr)
            self.assertEqual(json.loads(stdin.stdout)['measurements'], expected['measurements'])
            bad = subprocess.run(command[:-4] + ['0', '0', '100', '100', '--json'],
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(bad.returncode, 2)
            self.assertEqual(json.loads(bad.stdout)['error']['code'], 'invalid_request')
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual(path.stat().st_mtime_ns, before)
            text = io.StringIO()
            show_result({**expected, 'elapsed_seconds': 0}, stream=text)
            self.assertIn('Region:', text.getvalue())
            self.assertIn('local to the working crop', text.getvalue())


if __name__ == '__main__':
    unittest.main()
