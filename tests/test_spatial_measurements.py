import io
import json
import unittest

import numpy as np
from PIL import Image

from imagescope.images import prepare_image
from imagescope.measurements import measure, spatial_color, transparency


class SpatialMeasurementTests(unittest.TestCase):
    def test_transparency_counts_and_bounds_ignore_hidden_rgb(self):
        image = Image.new('RGBA', (4, 3), (0, 255, 0, 0))
        image.putpixel((1, 1), (255, 0, 0, 128))
        image.putpixel((2, 1), (0, 0, 255, 255))
        result = transparency(image)
        self.assertEqual(result['visible_bounds'], [1, 1, 3, 2])
        self.assertEqual((result['width'], result['height']), (4, 3))
        self.assertAlmostEqual(result['transparent_fraction'], 10/12, delta=1e-6)
        self.assertAlmostEqual(result['translucent_fraction'], 1/12, delta=1e-6)
        image.putpixel((0, 0), (255, 255, 255, 0))
        self.assertEqual(result, transparency(image))
        image.putpixel((3, 2), (255, 0, 0, 1))
        self.assertEqual(transparency(image)['visible_bounds'], [1, 1, 4, 3])

    def test_uniform_opaque_translucent_and_invisible(self):
        for alpha in (0, 1, 128, 254, 255):
            with self.subTest(alpha=alpha):
                image = Image.new('RGBA', (6, 6), (255, 0, 0, alpha))
                result = measure(image)
                self.assertEqual(result['transparency']['transparent_fraction'], int(alpha == 0))
                self.assertEqual(result['transparency']['translucent_fraction'], int(0 < alpha < 255))
                self.assertEqual(result['transparency']['visible_bounds'], [0, 0, 6, 6] if alpha else None)
                for region in result['spatial_color']['regions']:
                    if alpha:
                        self.assertEqual(region['palette'][0]['hex'], '#ff0000')
                        self.assertEqual(region['palette'][0]['fraction'], 1)
                        self.assertAlmostEqual(region['mean_luminance'], .2126, delta=1e-6)
                    else:
                        self.assertEqual(region['palette'], [])
                        self.assertIsNone(region['mean_luminance'])
        rgb = transparency(Image.new('RGB', (4, 2), 'black'))
        self.assertEqual(rgb['visible_bounds'], [0, 0, 4, 2])
        self.assertEqual(rgb['transparent_fraction'], 0)
        self.assertEqual(rgb['translucent_fraction'], 0)

    def test_nine_color_blocks_map_to_expected_regions(self):
        colors = ['#ff0000', '#00ff00', '#0000ff', '#ffffff', '#000000', '#808080',
                  '#ffff00', '#00ffff', '#ff00ff']
        luminances = [.2126, .7152, .0722, 1, 0, .2158605, .9278, .7874, .2848]
        image = Image.new('RGB', (9, 6))
        for index, color in enumerate(colors):
            row, column = divmod(index, 3)
            image.paste(color, (column * 3, row * 2, (column + 1) * 3, (row + 1) * 2))
        grid = spatial_color(image)
        self.assertEqual((grid['rows'], grid['columns'], grid['width'], grid['height']), (3, 3, 9, 6))
        for index, region in enumerate(grid['regions']):
            row, column = divmod(index, 3)
            self.assertEqual((region['row'], region['column']), (row, column))
            self.assertEqual(region['bounds'], [column*3, row*2, (column+1)*3, (row+1)*2])
            self.assertEqual(region['palette'][0]['hex'], colors[index])
            self.assertAlmostEqual(region['mean_luminance'], luminances[index], delta=1e-6)

    def test_region_opacity_weighting_and_independent_palette_limit(self):
        image = Image.new('RGBA', (9, 3), (0, 255, 0, 0))
        image.putpixel((0, 0), (255, 0, 0, 255))
        image.putpixel((1, 0), (0, 0, 255, 128))
        result = measure(image, palette_size=1)
        self.assertEqual(len(result['palette']), 1)
        region = result['spatial_color']['regions'][0]
        colors = {p['hex']: p['fraction'] for p in region['palette']}
        self.assertEqual(set(colors), {'#ff0000', '#0000ff'})
        self.assertAlmostEqual(colors['#ff0000'], 255/383, delta=.00005)
        self.assertAlmostEqual(colors['#0000ff'], 128/383, delta=.00005)
        self.assertAlmostEqual(region['mean_luminance'], (.2126*255 + .0722*128)/383, delta=1e-6)
        self.assertTrue(all(r['mean_luminance'] is None for r in result['spatial_color']['regions'][1:]))

    def test_tiny_and_uneven_grid_exactly_partitions_pixels(self):
        for size in ((1, 1), (2, 1), (1, 2), (2, 2), (5, 7)):
            with self.subTest(size=size):
                regions = spatial_color(Image.new('RGB', size, 'white'))['regions']
                self.assertEqual(len(regions), 9)
                coverage = np.zeros((size[1], size[0]), dtype=int)
                for region in regions:
                    x0, y0, x1, y1 = region['bounds']
                    coverage[y0:y1, x0:x1] += 1
                    if x0 == x1 or y0 == y1:
                        self.assertEqual(region['palette'], [])
                        self.assertIsNone(region['mean_luminance'])
                    else:
                        self.assertEqual(region['mean_luminance'], 1)
                self.assertTrue(np.all(coverage == 1))
        self.assertEqual(spatial_color(Image.new('RGB', (5, 7)))['regions'][0]['bounds'], [0, 0, 2, 3])

    def test_crop_before_resize_prevents_cross_region_bleed(self):
        image = Image.new('RGB', (1800, 300), 'red')
        image.paste('blue', (600, 0, 1200, 300))
        image.paste('lime', (1200, 0, 1800, 300))
        regions = spatial_color(image)['regions']
        for region in regions:
            self.assertEqual(len(region['palette']), 1)
            self.assertEqual(region['palette'][0]['hex'], ['#ff0000', '#0000ff', '#00ff00'][region['column']])

    def test_oriented_bounds_and_indexed_transparency(self):
        image = Image.new('RGBA', (4, 2), (0, 0, 0, 0))
        image.putpixel((0, 0), (255, 0, 0, 128))
        exif = Image.Exif(); exif[274] = 6
        data = io.BytesIO(); image.save(data, 'PNG', exif=exif)
        _, working = prepare_image(data.getvalue())
        self.assertEqual(working.size, (2, 4))
        self.assertEqual(transparency(working)['visible_bounds'], [1, 0, 2, 1])
        indexed = Image.new('P', (4, 2), 0)
        indexed.putpalette([255, 0, 0, 0, 255, 0] + [0]*762)
        indexed.info['transparency'] = 0
        indexed.putpixel((2, 1), 1)
        data = io.BytesIO(); indexed.save(data, 'PNG')
        _, working = prepare_image(data.getvalue())
        self.assertEqual(transparency(working)['visible_bounds'], [2, 1, 3, 2])

    def test_repeatability_finite_bounded_output_and_input_immutability(self):
        rng = np.random.default_rng(42)
        image = Image.fromarray(rng.integers(0, 256, (60, 90, 4), dtype=np.uint8))
        image.info['test'] = 'unchanged'
        before = (image.mode, image.size, image.tobytes(), dict(image.info))
        first = measure(image, 24)
        self.assertEqual(first, measure(image, 24))
        self.assertEqual(before, (image.mode, image.size, image.tobytes(), image.info))
        self.assertLess(len(json.dumps(first, allow_nan=False)), 50000)
        self.assertLessEqual(sum(len(r['palette']) for r in first['spatial_color']['regions']), 27)
        for region in first['spatial_color']['regions']:
            self.assertTrue(0 <= region['mean_luminance'] <= 1)
