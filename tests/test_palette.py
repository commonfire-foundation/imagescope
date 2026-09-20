import colorsys
import io
import unittest

import numpy as np
from PIL import Image

from imagescope import AnalysisRequest, analyze
from imagescope.images import prepare_image, white_composite
from imagescope.measurements import extract_palette, measure


class PaletteTests(unittest.TestCase):
    def encoded(self, image):
        data = io.BytesIO()
        image.save(data, 'PNG')
        return data.getvalue()

    def test_sizes_limited_colors_and_no_padding(self):
        pixels = np.array([[(i * 4, i * 4, i * 4) for i in range(64)]], dtype=np.uint8)
        for mode in ('RGB', 'RGBA'):
            image = Image.fromarray(pixels).convert(mode)
            if mode == 'RGBA':
                image.putalpha(128)
            for size in (1, 5, 6, 8, 10, 16, 24, 32, 48, 64):
                with self.subTest(mode=mode, size=size):
                    palette = extract_palette(image, size)
                    self.assertEqual(len(palette), size)
                    self.assertAlmostEqual(sum(p['fraction'] for p in palette), 1, delta=size * .00005 + 1e-12)
                    solid = extract_palette(Image.new(mode, (8, 8), 'red'), size)
                    self.assertEqual(len(solid), 1)
                    self.assertEqual(solid[0]['hex'], '#ff0000')
                    self.assertEqual(solid[0]['fraction'], 1)

    def test_opacity_weighting_and_hidden_rgb(self):
        for hidden in ((255, 255, 0, 0), (0, 255, 255, 0)):
            image = Image.new('RGBA', (4, 1))
            image.putdata([(255, 0, 0, 255), (0, 0, 255, 128), hidden, hidden])
            palette = {p['hex']: p['fraction'] for p in extract_palette(image)}
            self.assertEqual(set(palette), {'#ff0000', '#0000ff'})
            self.assertAlmostEqual(palette['#ff0000'], 255/383, delta=.00005)
            self.assertAlmostEqual(palette['#0000ff'], 128/383, delta=.00005)
        # With one representative, alpha weights affect the color as well as shares.
        self.assertEqual(extract_palette(image, 1)[0]['rgb'], [170, 0, 85])

    def test_fully_transparent_has_no_palette_but_white_other_measurements(self):
        image = Image.new('RGBA', (19, 11), (17, 88, 201, 0))
        result = measure(image)
        self.assertEqual(result['palette'], [])
        self.assertAlmostEqual(result['mean_luminance'], 1, delta=1e-12)
        self.assertEqual(result['dhash64'], '0000000000000000')

    def test_alpha_resize_does_not_bleed_hidden_color(self):
        results = []
        for hidden in ((0, 255, 0, 0), (0, 0, 255, 0)):
            image = Image.new('RGBA', (2050, 32), hidden)
            image.paste((255, 0, 0, 255), (0, 0, 1025, 32))
            _, working = prepare_image(self.encoded(image))
            self.assertEqual(working.mode, 'RGBA')
            self.assertLessEqual(max(working.size), 2048)
            palette = extract_palette(working, 24)
            self.assertEqual(palette, [{'hex': '#ff0000', 'rgb': [255, 0, 0],
                                        'hsl': [0.0, 100.0, 50.0], 'fraction': 1.0}])
            results.append(palette)
        self.assertEqual(*results)

    def test_indexed_and_grayscale_alpha_survive_decode(self):
        indexed = Image.new('P', (2050, 4), 0)
        indexed.putpalette([255, 0, 0, 0, 255, 0] + [0] * 762)
        indexed.paste(1, (1025, 0, 2050, 4))
        indexed.info['transparency'] = 1
        _, working = prepare_image(self.encoded(indexed))
        self.assertEqual(working.mode, 'RGBA')
        self.assertEqual(extract_palette(working)[0]['hex'], '#ff0000')
        gray = Image.new('LA', (4, 2), (80, 128))
        _, working = prepare_image(self.encoded(gray))
        self.assertEqual(working.getpixel((0, 0)), (80, 80, 80, 128))
        self.assertEqual(extract_palette(working)[0]['rgb'], [80, 80, 80])

    def test_representations_agree(self):
        for color in ((0, 0, 0), (255, 255, 255), (128, 128, 128),
                      (255, 0, 0), (0, 255, 0), (0, 0, 255), (31, 119, 213)):
            entry = extract_palette(Image.new('RGB', (1, 1), color))[0]
            self.assertEqual(entry['hex'], '#' + ''.join(f'{v:02x}' for v in color))
            self.assertEqual(entry['rgb'], list(color))
            h, s, light = entry['hsl']
            self.assertTrue(0 <= h < 360 and 0 <= s <= 100 and 0 <= light <= 100)
            reconstructed = colorsys.hls_to_rgb(h / 360, light / 100, s / 100)
            for actual, expected in zip(reconstructed, color):
                self.assertAlmostEqual(actual * 255, expected, delta=.05)
        self.assertEqual(extract_palette(Image.new('RGB', (1, 1), 'gray'))[0]['hsl'][0], 0)

    def test_opaque_default_matches_version_2_quantization(self):
        rng = np.random.default_rng(42)
        image = Image.fromarray(rng.integers(0, 256, (270, 310, 3), dtype=np.uint8))
        thumb = image.copy()
        thumb.thumbnail((256, 256))
        quantized = thumb.quantize(colors=6)
        colors = quantized.getpalette()
        expected = [{'hex': '#' + ''.join(f'{c:02x}' for c in colors[i*3:i*3+3]),
                     'fraction': round(n / (thumb.width * thumb.height), 4)}
                    for n, i in sorted(quantized.getcolors(), reverse=True)]
        for source in (image, image.convert('RGBA')):
            actual = extract_palette(source)
            self.assertEqual([{k: p[k] for k in ('hex', 'fraction')} for p in actual], expected)

    def test_repeatability_gradient_and_photograph_like_texture(self):
        # Seeded textured color field, not a private photograph or decoder fixture.
        rng = np.random.default_rng(7)
        gradient = np.tile(np.arange(256, dtype=np.uint8), (32, 1))
        images = [Image.fromarray(gradient).convert('RGBA'),
                  Image.fromarray(rng.integers(0, 256, (64, 80, 4), dtype=np.uint8))]
        images[0].putalpha(128)
        for image in images:
            before = image.tobytes()
            for size in (5, 8, 10, 16, 24, 32, 48, 64):
                result = extract_palette(image, size)
                self.assertEqual(result, extract_palette(image, size))
                self.assertTrue(1 <= len(result) <= size)
                self.assertTrue(all(0 <= p['fraction'] <= 1 for p in result))
            self.assertEqual(image.tobytes(), before)

    def test_size_validation_before_decode(self):
        for size in (0, 65, -1, True, 6.0, '6'):
            result = analyze(AnalysisRequest(b'bad image', palette_size=size, task='inspect'))
            self.assertEqual(result['error']['code'], 'invalid_request')
            with self.assertRaises(ValueError):
                extract_palette(Image.new('RGB', (1, 1)), size)

    def test_inference_receives_white_composite_and_failure_keeps_palette(self):
        image = Image.new('RGBA', (8, 4), (255, 0, 0, 128))
        from imagescope import AnalyzerError
        class Backend:
            def check_model(self, model):
                return {'name': model}, {}
            def describe(inner, preview, *args, profile):
                self.assertEqual(preview.mode, 'RGB')
                self.assertEqual(preview.getpixel((0, 0)), (255, 127, 127))
                raise AnalyzerError('invalid_response', 'failed')
        result = analyze(AnalysisRequest(self.encoded(image), measurements=True, palette_size=10), backend=Backend())
        self.assertEqual(result['error']['code'], 'invalid_response')
        self.assertEqual(result['measurements']['palette'][0]['hex'], '#ff0000')
        self.assertEqual(result['provenance']['measurements_version'], 6)
        self.assertEqual(result['provenance']['measurement_settings'], {'palette_size': 10})
        self.assertEqual(white_composite(image).getpixel((0, 0)), (255, 127, 127))
