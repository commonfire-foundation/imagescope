import json
import unittest

import numpy as np
from PIL import Image

from imagescope.measurements import measure
from imagescope.structure import PHASH_ALGORITHM, structure_measurements


class StructureTests(unittest.TestCase):
    def test_uniform_and_tiny_images(self):
        for size in ((1, 1), (1, 7), (9, 1), (192, 192)):
            for value in (0, 64, 128, 255):
                with self.subTest(size=size, value=value):
                    detail, symmetry, phash = structure_measurements(Image.new('RGB', size, (value,) * 3))
                    self.assertEqual(detail['intensity_std_3x3'], [[0.] * 3] * 3)
                    self.assertEqual(symmetry, {'left_right': 1., 'top_bottom': 1.})
                    self.assertEqual(phash, {'algorithm': PHASH_ALGORITHM, 'hash': '0000000000000000'})

    def test_known_boundary_local_variation(self):
        image = Image.new('RGB', (192, 192), 'black')
        image.paste('white', (96, 0, 192, 192))
        detail, symmetry, _ = structure_measurements(image)
        for row in detail['intensity_std_3x3']:
            self.assertEqual(row[0], 0)
            self.assertAlmostEqual(row[1], .5, delta=1e-6)
            self.assertEqual(row[2], 0)
        self.assertEqual(symmetry, {'left_right': 0., 'top_bottom': 1.})
        _, rotated, _ = structure_measurements(image.transpose(Image.Transpose.ROTATE_90))
        self.assertEqual(rotated, {'left_right': 1., 'top_bottom': 0.})

    def test_localized_texture_and_smooth_gradient(self):
        pixels = np.zeros((192, 192), dtype=np.uint8)
        pixels[:64, :64] = np.indices((64, 64)).sum(axis=0) % 2 * 255
        detail, _, _ = structure_measurements(Image.fromarray(pixels).convert('RGB'))
        self.assertEqual(detail['intensity_std_3x3'][0][0], .5)
        self.assertEqual(sum(map(sum, detail['intensity_std_3x3'])), .5)
        ramp = np.tile(np.arange(192, dtype=np.uint8), (192, 1))
        detail, symmetry, _ = structure_measurements(Image.fromarray(ramp).convert('RGB'))
        expected = np.std(np.arange(64) / 255)
        for row in detail['intensity_std_3x3']:
            for value in row:
                self.assertAlmostEqual(value, expected, delta=1e-6)
        self.assertEqual(symmetry['top_bottom'], 1)
        self.assertAlmostEqual(symmetry['left_right'], 1 - 96/255, delta=1e-6)

    def test_bilateral_pattern_and_asymmetric_change(self):
        image = Image.new('RGB', (192, 192), 'black')
        image.paste('white', (64, 32, 128, 160))
        _, symmetry, _ = structure_measurements(image)
        self.assertEqual(symmetry, {'left_right': 1., 'top_bottom': 1.})
        image.paste('white', (0, 0, 32, 32))
        _, changed, _ = structure_measurements(image)
        for value in changed.values():
            self.assertAlmostEqual(value, 1 - 2*(32*32)/(192*192), delta=1e-6)

    def test_hash_independent_scalar_dct_reference(self):
        # Deliberately independent scalar summation, not the vectorized basis path.
        import math
        pixels = np.random.default_rng(42).integers(0, 256, (32, 32), dtype=np.uint8)
        _, _, actual = structure_measurements(Image.fromarray(pixels).convert('RGB'))
        coefficients = []
        for u in range(8):
            for v in range(8):
                factor = (math.sqrt(1/32) if u == 0 else math.sqrt(2/32)) * (math.sqrt(1/32) if v == 0 else math.sqrt(2/32))
                value = sum(float(pixels[y, x])/255 * math.cos(math.pi*(y+.5)*u/32)
                            * math.cos(math.pi*(x+.5)*v/32) for y in range(32) for x in range(32))
                coefficients.append(round(value * factor, 12))
        threshold = sorted(coefficients[1:])[31]
        bits = [False] + [value > threshold for value in coefficients[1:]]
        expected = f"{int(''.join('1' if b else '0' for b in bits), 2):016x}"
        self.assertEqual(actual['hash'], expected)
        self.assertRegex(actual['hash'], r'^[0-9a-f]{16}$')
        self.assertEqual(actual['algorithm'], PHASH_ALGORITHM)
        self.assertLess(int(actual['hash'], 16), 2**63)

    def test_hash_contrast_and_resize_relationships(self):
        pixels = np.zeros((32, 32), dtype=np.uint8)
        pixels[5:22, 3:14] = 200
        pixels[24:28, 20:30] = 80
        image = Image.fromarray(pixels).convert('RGB')
        original = structure_measurements(image)[2]['hash']
        contrast = structure_measurements(Image.fromarray(pixels//2).convert('RGB'))[2]['hash']
        self.assertEqual(original, contrast)
        enlarged = image.resize((256, 256), Image.Resampling.NEAREST)
        larger_hash = structure_measurements(enlarged)[2]['hash']
        self.assertLessEqual((int(original, 16) ^ int(larger_hash, 16)).bit_count(), 8)
        opposing = structure_measurements(Image.fromarray(255-pixels).convert('RGB'))[2]['hash']
        self.assertGreater((int(original, 16) ^ int(opposing, 16)).bit_count(), 40)

    def test_hidden_and_partial_alpha_use_white_composite(self):
        result = measure(Image.new('RGBA', (7, 5), (255, 0, 0, 0)))
        self.assertEqual(result['symmetry'], {'left_right': 1., 'top_bottom': 1.})
        self.assertEqual(result['local_detail']['intensity_std_3x3'], [[0.] * 3] * 3)
        self.assertEqual(result['phash64']['hash'], '0000000000000000')
        image = Image.new('RGBA', (192, 192), (0, 255, 0, 0))
        image.paste((0, 0, 0, 128), (0, 0, 96, 192))
        a = measure(image)
        image.paste((255, 0, 0, 0), (96, 0, 192, 192))
        b = measure(image)
        for key in ('symmetry', 'local_detail', 'phash64'):
            self.assertEqual(a[key], b[key])
        self.assertAlmostEqual(a['symmetry']['left_right'], 1-128/255, delta=1e-6)

    def test_repeatability_immutability_and_finite_ranges(self):
        image = Image.fromarray(np.random.default_rng(7).integers(0, 256, (80, 120, 3), dtype=np.uint8))
        before = (image.size, image.mode, image.tobytes())
        a = structure_measurements(image)
        self.assertEqual(a, structure_measurements(image))
        self.assertEqual(before, (image.size, image.mode, image.tobytes()))
        self.assertTrue(all(0 <= v <= .5 for row in a[0]['intensity_std_3x3'] for v in row))
        self.assertTrue(all(0 <= v <= 1 for v in a[1].values()))
        self.assertLess(len(json.dumps(a, allow_nan=False)), 512)
