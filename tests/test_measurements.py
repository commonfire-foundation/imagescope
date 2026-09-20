"""Behavioral checks using synthetic RGB pixels; no models or private fixtures."""
import math
import unittest

import numpy as np
from PIL import Image

from imagescope.measurements import measure


class MeasurementTests(unittest.TestCase):
    def test_uniform_luminance_and_zero_spread(self):
        # Linear sRGB luminance, including a midtone to exercise gamma decoding.
        cases = [((0, 0, 0), 0), ((255, 255, 255), 1),
                 ((255, 0, 0), .2126), ((0, 255, 0), .7152),
                 ((0, 0, 255), .0722), ((128, 128, 128), .2158605001)]
        for color, expected in cases:
            for size in ((1, 1), (17, 11)):
                with self.subTest(color=color, size=size):
                    result = measure(Image.new('RGB', size, color))
                    self.assertAlmostEqual(result['mean_luminance'], expected, delta=1e-9)
                    self.assertAlmostEqual(result['luminance_std'], 0, delta=1e-12)
                    self.assertEqual(result['dhash64'], '0000000000000000')
                    self.assertEqual(result['edge_density_3x3'], [[0.0] * 3] * 3)

    def test_color_block_palette_and_proportions(self):
        image = Image.new('RGB', (12, 6), 'red')
        image.paste('green', (6, 0, 10, 6))
        image.paste('blue', (10, 0, 12, 6))
        palette = {entry['hex']: entry['fraction'] for entry in measure(image)['palette']}
        self.assertEqual(set(palette), {'#ff0000', '#008000', '#0000ff'})
        for color, expected in [('#ff0000', 1/2), ('#008000', 1/3), ('#0000ff', 1/6)]:
            # Fractions are rounded to four decimal places.
            self.assertAlmostEqual(palette[color], expected, delta=.00005)
        self.assertAlmostEqual(sum(palette.values()), 1, delta=.00015)

    def test_black_white_spread(self):
        image = Image.new('RGB', (12, 8), 'black')
        image.paste('white', (6, 0, 12, 8))
        result = measure(image)
        self.assertAlmostEqual(result['mean_luminance'], .5, delta=1e-12)
        self.assertAlmostEqual(result['luminance_std'], .5, delta=1e-12)

    def test_difference_hash_opposing_gradients(self):
        ramp = np.tile(np.arange(64, dtype=np.uint8) * 4, (32, 1))
        forward = measure(Image.fromarray(ramp).convert('RGB'))['dhash64']
        backward = measure(Image.fromarray(ramp[:, ::-1]).convert('RGB'))['dhash64']
        for value in (forward, backward):
            self.assertRegex(value, r'^[0-9a-f]{16}$')
        self.assertEqual(forward, 'ffffffffffffffff')
        self.assertEqual(backward, '0000000000000000')
        self.assertEqual((int(forward, 16) ^ int(backward, 16)).bit_count(), 64)

    def test_edge_grid_localizes_boundary(self):
        image = Image.new('RGB', (192, 192), 'black')
        image.paste('white', (96, 0, 192, 192))
        grid = measure(image)['edge_density_3x3']
        self.assertEqual(len(grid), 3)
        for row in grid:
            self.assertEqual(len(row), 3)
            for value in row:
                self.assertTrue(math.isfinite(value))
                self.assertGreaterEqual(value, 0)
                self.assertLessEqual(value, 1)
            self.assertEqual(row[0], 0)
            self.assertGreater(row[1], .02)
            self.assertEqual(row[2], 0)

    def test_repeatable_and_input_unchanged(self):
        image = Image.new('RGB', (321, 271), '#abc123')
        image.paste('#123abc', (80, 10, 200, 250))
        image.info['fixture'] = 'preserved'
        before = (image.mode, image.size, image.tobytes(), dict(image.info))
        first = measure(image)
        self.assertEqual(first, measure(image))
        self.assertEqual((image.mode, image.size, image.tobytes(), image.info), before)
        self.assertEqual(set(first), {'mean_luminance', 'luminance_std', 'palette',
                                      'dhash64', 'edge_density_3x3', 'color_distribution',
                                      'luminance_distribution', 'palette_distances',
                                      'transparency', 'spatial_color', 'local_detail',
                                      'symmetry', 'phash64'})
