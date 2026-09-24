"""Numerical CMYK integration tests with a project-authored ICC reference."""
import hashlib
import io
from itertools import product
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image, ImageCms

from cmyk_fixture import cmyk_profile
from imagescope import AnalysisRequest, MetadataRequest, analyze, inspect_metadata
from imagescope.contracts import validate_result
from imagescope.images import prepare_image

PROFILE_SHA256 = '2ad3f9f3d4545f324d4780761b90dc7e84f146b2b7c137651604b1bff855ff8d'
TOLERANCE = 2  # 8-bit code values per channel; see CMYK_FIXTURE.md


def reference_rgb(cmyk):
    # Independent oracle: no ImageCms, no LUT reading, no production helper.
    # CMYK fixture's affine linear-light model, followed by sRGB encoding.
    rgb = []
    for ink in cmyk[:3]:
        linear = 1 - (ink + cmyk[3]) / 510
        encoded = 12.92 * linear if linear <= 0.0031308 else 1.055 * linear ** (1 / 2.4) - 0.055
        rgb.append(round(255 * encoded))
    return tuple(rgb)


def image_bytes(image, fmt='TIFF', **options):
    output = io.BytesIO()
    image.save(output, fmt, icc_profile=cmyk_profile(), **options)
    return output.getvalue()


def sample_image():
    # 9^4 fixed samples cover corners, asymmetric interiors, and dark near-edge
    # values sensitive to LittleCMS precomputed-transform interpolation errors.
    samples = list(product((0, 1, 17, 64, 128, 192, 238, 254, 255), repeat=4))
    image = Image.new('CMYK', (81, 81))
    image.putdata(samples)
    return image, samples


class CmykIntegrationTests(unittest.TestCase):
    def assert_rgb_close(self, actual, expected):
        self.assertEqual(len(actual), 3)
        for index, (value, target) in enumerate(zip(actual, expected)):
            self.assertLessEqual(abs(value - target), TOLERANCE,
                                 f'channel {index}: {actual} != {expected}')

    def test_fixture_is_deterministic_and_accepted_as_cmyk_input_profile(self):
        raw = cmyk_profile()
        self.assertEqual(len(raw), 740)
        self.assertEqual(raw, cmyk_profile())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), PROFILE_SHA256)
        self.assertEqual(raw[12:24], b'scnrCMYKXYZ ')
        profile = ImageCms.ImageCmsProfile(io.BytesIO(raw))
        self.assertEqual(ImageCms.getProfileDescription(profile).strip(),
                         'Imagescope synthetic affine CMYK v1')
        # Building a real transform ensures the profile is usable, not merely
        # syntactically parseable. Numerical tests below exercise that transform.
        transform = ImageCms.buildTransform(profile, ImageCms.createProfile('sRGB'),
                                           'CMYK', 'RGB', ImageCms.Intent.RELATIVE_COLORIMETRIC)
        self.assertIsNotNone(transform)

    def test_lossless_tiff_through_isolated_decoder_matches_reference(self):
        image, samples = sample_image()
        encoded = image_bytes(image)
        metadata, actual = prepare_image(encoded, color_policy='srgb-v1')
        self.assertEqual(actual.size, image.size)
        self.assertEqual(actual.mode, 'RGB')
        for index, sample in enumerate(samples):
            with self.subTest(sample=sample):
                self.assert_rgb_close(actual.getpixel((index % image.width, index // image.width)),
                                      reference_rgb(sample))
        record = metadata['preprocessing']['color_management']
        self.assertEqual(record['source_mode'], 'CMYK')
        self.assertEqual(record['source_profile']['color_space'], 'CMYK')
        self.assertEqual(record['source_profile']['sha256'], PROFILE_SHA256)
        self.assertEqual(record['source_profile']['status'], 'valid')
        self.assertEqual(record['status'], 'converted')
        self.assertEqual(record['transform_optimization'], 'disabled')
        self.assertEqual(record['output_color_space'], 'srgb')
        # Negative control: dropping the ICC transform must not pass this test.
        _, legacy = prepare_image(encoded)
        max_difference = max(abs(a - b) for a, b in zip(actual.tobytes(), legacy.tobytes()))
        self.assertGreater(max_difference, 100)

    def test_jpeg_compares_against_decoded_cmyk_not_precompression_samples(self):
        image, _ = sample_image()
        encoded = image_bytes(image, 'JPEG', quality=95)
        with Image.open(io.BytesIO(encoded)) as source:
            self.assertEqual(source.mode, 'CMYK')
            samples = [source.getpixel((x, y)) for y in range(source.height)
                       for x in range(source.width)]
        _, actual = prepare_image(encoded, color_policy='srgb-v1')
        for index, sample in enumerate(samples):
            with self.subTest(sample=sample):
                self.assert_rgb_close(actual.getpixel((index % image.width, index // image.width)),
                                      reference_rgb(sample))

    def test_exif_orientation_preserves_cmyk_color_and_sample_placement(self):
        samples = [(0, 0, 0, 0), (255, 0, 0, 0), (0, 255, 0, 0),
                   (0, 0, 255, 0), (13, 91, 205, 49), (255, 255, 255, 255)]
        transforms = {2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180,
                      4: Image.Transpose.FLIP_TOP_BOTTOM, 5: Image.Transpose.TRANSPOSE,
                      6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE,
                      8: Image.Transpose.ROTATE_90}
        image = Image.new('CMYK', (3, 2))
        image.putdata(samples)
        expected_source = Image.new('RGB', image.size)
        expected_source.putdata([reference_rgb(sample) for sample in samples])
        for orientation in range(1, 9):
            with self.subTest(orientation=orientation):
                exif = Image.Exif()
                exif[274] = orientation
                _, actual = prepare_image(image_bytes(image, exif=exif), color_policy='srgb-v1')
                expected = (expected_source.transpose(transforms[orientation])
                            if orientation != 1 else expected_source)
                self.assertEqual(actual.size, expected.size)
                for y in range(expected.height):
                    for x in range(expected.width):
                        self.assert_rgb_close(actual.getpixel((x, y)), expected.getpixel((x, y)))

    def test_public_measurements_use_profile_and_match_reference_luminance(self):
        for sample in ((0, 0, 0, 128), (31, 119, 201, 53), (255, 255, 255, 255)):
            with self.subTest(sample=sample):
                encoded = image_bytes(Image.new('CMYK', (16, 12), sample))
                result = analyze(AnalysisRequest(encoded, task='inspect', color_policy='srgb-v1'))
                self.assertEqual(result['status'], 'ok', result)
                validate_result(result)
                palette = result['measurements']['palette']
                self.assertEqual(len(palette), 1)
                expected = reference_rgb(sample)
                self.assert_rgb_close(palette[0]['rgb'], expected)
                self.assertEqual(palette[0]['fraction'], 1)
                def luminance(rgb):
                    linear = [v / 255 / 12.92 if v / 255 <= 0.04045
                              else ((v / 255 + 0.055) / 1.055) ** 2.4 for v in rgb]
                    return sum(a * b for a, b in zip(linear, (0.2126, 0.7152, 0.0722)))
                low = luminance([max(0, v - TOLERANCE) for v in expected]) - 0.000001
                high = luminance([min(255, v + TOLERANCE) for v in expected]) + 0.000001
                values = result['measurements']['luminance_distribution']['percentiles'].values()
                self.assertTrue(all(low <= value <= high for value in values))
                self.assertEqual(result['provenance']['preprocessing']['version'], 4)
                self.assertEqual(result['provenance']['measurements_version'], 6)

    def test_metadata_cli_parity_and_source_immutability(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            path = Path(directory) / 'cmyk.tif'
            encoded = image_bytes(Image.new('CMYK', (16, 12), (31, 119, 201, 53)))
            path.write_bytes(encoded)
            before = path.stat().st_mtime_ns
            metadata = inspect_metadata(MetadataRequest(path))
            self.assertEqual(metadata['status'], 'ok', metadata)
            self.assertEqual(metadata['metadata']['mode'], 'CMYK')
            self.assertEqual(metadata['metadata']['icc']['color_space'], 'CMYK')
            self.assertEqual(metadata['metadata']['icc']['sha256'], PROFILE_SHA256)
            api = analyze(AnalysisRequest(path, task='inspect', color_policy='srgb-v1'))
            process = subprocess.run([sys.executable, '-m', 'imagescope', 'inspect', str(path),
                                      '--color-policy', 'srgb-v1', '--json'],
                                     capture_output=True, text=True, timeout=30)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(process.stderr, '')
            cli = json.loads(process.stdout)
            cli.pop('elapsed_seconds')
            api.pop('elapsed_seconds')
            self.assertEqual(cli, api)
            self.assertEqual(path.read_bytes(), encoded)
            self.assertEqual(path.stat().st_mtime_ns, before)


if __name__ == '__main__':
    unittest.main()
