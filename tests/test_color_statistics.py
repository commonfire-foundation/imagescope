import json
import math
import unittest

import numpy as np
from PIL import Image

from imagescope.color_statistics import palette_distances
from imagescope.measurements import measure


class ColorStatisticsTests(unittest.TestCase):
    def test_solid_primary_hue_hsl_and_luminance(self):
        for rgb, hue_bin, expected_luminance in [((255, 0, 0), 0, .2126),
                                                ((0, 255, 0), 4, .7152),
                                                ((0, 0, 255), 8, .0722)]:
            with self.subTest(rgb=rgb):
                result = measure(Image.new('RGB', (1, 1), rgb))
                color = result['color_distribution']
                histogram = [0.] * 12
                histogram[hue_bin] = 1.
                self.assertEqual(color['hue_histogram'], histogram)
                self.assertEqual(color['near_neutral_fraction'], 0)
                for value in color['saturation_percentiles'].values():
                    self.assertAlmostEqual(value, 100, delta=1e-6)
                for value in color['lightness_percentiles'].values():
                    self.assertAlmostEqual(value, 50, delta=1e-6)
                for value in result['luminance_distribution']['percentiles'].values():
                    self.assertAlmostEqual(value, expected_luminance, delta=1e-6)
                self.assertEqual(result['palette_distances'], [])

    def test_hue_histogram_all_bins_and_chromatic_normalization(self):
        import colorsys
        pixels = [tuple(round(c * 255) for c in colorsys.hsv_to_rgb((15 + 30*i)/360, 1, 1))
                  for i in range(12)]
        image = Image.new('RGB', (24, 1))
        image.putdata(pixels + [(128, 128, 128)] * 12)
        distribution = measure(image)['color_distribution']
        for fraction in distribution['hue_histogram']:
            self.assertAlmostEqual(fraction, 1/12, delta=1e-6)
        self.assertEqual(distribution['near_neutral_fraction'], .5)

    def test_grayscale_and_thresholds(self):
        # Encoded levels straddling the documented linear luminance thresholds.
        for level, near_black, near_white in [(0, 1, 0), (25, 1, 0), (26, 0, 0),
                                             (128, 0, 0), (249, 0, 0), (250, 0, 1), (255, 0, 1)]:
            with self.subTest(level=level):
                result = measure(Image.new('RGB', (5, 3), (level,) * 3))
                color, lum = result['color_distribution'], result['luminance_distribution']
                self.assertIsNone(color['hue_histogram'])
                self.assertEqual(color['near_neutral_fraction'], 1)
                self.assertTrue(all(v == 0 for v in color['saturation_percentiles'].values()))
                for value in color['lightness_percentiles'].values():
                    self.assertAlmostEqual(value, level / 255 * 100, delta=1e-6)
                self.assertEqual(lum['near_black_fraction'], near_black)
                self.assertEqual(lum['near_white_fraction'], near_white)
        image = Image.new('RGB', (2, 1))
        image.putdata([(110, 100, 100), (140, 100, 100)])
        self.assertEqual(measure(image)['color_distribution']['near_neutral_fraction'], .5)
        for color in ((110, 90, 90), (165, 145, 145)):
            self.assertEqual(measure(Image.new('RGB', (1, 1), color))['color_distribution']['near_neutral_fraction'], 1)

    def test_opacity_weighted_blocks_and_inverse_cdf(self):
        image = Image.new('RGBA', (4, 1))
        image.putdata([(255, 0, 0, 255), (0, 255, 0, 128), (0, 0, 255, 0), (0, 0, 0, 255)])
        result = measure(image)
        color, lum = result['color_distribution'], result['luminance_distribution']
        self.assertAlmostEqual(color['hue_histogram'][0], 255/383, delta=1e-6)
        self.assertAlmostEqual(color['hue_histogram'][4], 128/383, delta=1e-6)
        self.assertEqual(color['hue_histogram'][8], 0)
        self.assertAlmostEqual(color['near_neutral_fraction'], 255/638, delta=1e-6)
        self.assertAlmostEqual(lum['near_black_fraction'], 255/638, delta=1e-6)
        self.assertEqual(lum['percentiles'], {'p05': 0., 'p25': 0., 'p50': .2126, 'p75': .2126, 'p95': .7152})
        self.assertEqual(color['lightness_percentiles']['p25'], 0)
        self.assertEqual(color['lightness_percentiles']['p50'], 50)
        # Hidden RGB cannot change any of the new distributions.
        image.putpixel((2, 0), (255, 255, 255, 0))
        changed = measure(image)
        self.assertEqual(color, changed['color_distribution'])
        self.assertEqual(lum, changed['luminance_distribution'])

    def test_half_black_white_and_gradient_percentiles(self):
        image = Image.new('RGBA', (2, 1))
        image.putdata([(0, 0, 0, 128), (255, 255, 255, 128)])
        lum = measure(image)['luminance_distribution']
        self.assertEqual(lum['percentiles'], {'p05': 0., 'p25': 0., 'p50': 0., 'p75': 1., 'p95': 1.})
        self.assertEqual(lum['near_black_fraction'], .5)
        self.assertEqual(lum['near_white_fraction'], .5)
        gradient = Image.fromarray(np.arange(256, dtype=np.uint8).reshape(1, 256)).convert('RGB')
        result = measure(gradient)
        for p, level in [(5, 12), (25, 63), (50, 127), (75, 191), (95, 243)]:
            c = level / 255
            expected = c/12.92 if c <= .04045 else ((c + .055)/1.055)**2.4
            self.assertAlmostEqual(result['luminance_distribution']['percentiles'][f'p{p:02d}'], expected, delta=1e-6)
            self.assertAlmostEqual(result['color_distribution']['lightness_percentiles'][f'p{p:02d}'], c * 100, delta=1e-6)

    def test_transparent_and_low_alpha_have_no_background_assumption(self):
        result = measure(Image.new('RGBA', (1, 1), (255, 0, 0, 0)))
        self.assertTrue(all(value is None for value in result['color_distribution'].values()))
        self.assertTrue(all(value is None for value in result['luminance_distribution'].values()))
        self.assertEqual(result['palette_distances'], [])
        # A barely visible red pixel still has red statistics, not white statistics.
        result = measure(Image.new('RGBA', (1, 1), (255, 0, 0, 1)))
        self.assertEqual(result['luminance_distribution']['percentiles']['p50'], .2126)
        self.assertGreater(result['mean_luminance'], .98)

    def test_lab_distances_known_values_and_relationships(self):
        colors = [{'rgb': rgb} for rgb in [(0, 0, 0), (255, 255, 255),
                                          (255, 0, 0), (254, 0, 0), (0, 255, 0), (255, 0, 0)]]
        distances = {(pair['i'], pair['j']): pair['delta_e76'] for pair in palette_distances(colors)}
        self.assertEqual(len(distances), 15)
        self.assertAlmostEqual(distances[0, 1], 100, delta=.0001)
        self.assertAlmostEqual(distances[2, 4], 170.5652, delta=.001)
        self.assertEqual(distances[2, 5], 0)
        self.assertLess(distances[2, 3], 1)
        self.assertGreater(distances[2, 4], distances[2, 3])
        self.assertTrue(all(math.isfinite(v) and v >= 0 for v in distances.values()))
        self.assertEqual(palette_distances([]), [])

    def test_repeatability_finite_values_immutability_and_bounded_pairs(self):
        rng = np.random.default_rng(42)
        image = Image.fromarray(rng.integers(0, 256, (260, 280, 4), dtype=np.uint8))
        before = image.tobytes()
        first = measure(image, 24)
        self.assertEqual(first, measure(image, 24))
        self.assertEqual(image.tobytes(), before)
        self.assertEqual(len(first['palette_distances']), len(first['palette']) * (len(first['palette'])-1)//2)
        self.assertLessEqual(len(first['palette_distances']), 276)
        self.assertLess(len(json.dumps(first, allow_nan=False)), 40000)
        def finite(value):
            if isinstance(value, dict):
                for v in value.values(): finite(v)
            elif isinstance(value, list):
                for v in value: finite(v)
            elif isinstance(value, float):
                self.assertTrue(math.isfinite(value))
        finite(first)
