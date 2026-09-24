import builtins
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageCms, ImageOps, PngImagePlugin

from imagescope import AnalysisRequest, AnalyzerError, analyze
from imagescope.color_management import apply_color_policy
from imagescope.images import prepare_image


def profile_bytes():
    return ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()


def linear_rgb_profile():
    # Synthetic sRGB primaries with linear tone curves. Replace each TRC with
    # ICC parametric curve type 0, gamma 1.0; leave tag-table offsets unchanged.
    raw = bytearray(profile_bytes())
    count = int.from_bytes(raw[128:132], 'big')
    for index in range(count):
        entry = 132 + 12 * index
        if raw[entry:entry + 4] in (b'rTRC', b'gTRC', b'bTRC'):
            offset = int.from_bytes(raw[entry + 4:entry + 8], 'big')
            raw[entry + 8:entry + 12] = (16).to_bytes(4, 'big')
            raw[offset:offset + 16] = b'para' + b'\0' * 8 + struct.pack('>i', 65536)
    return bytes(raw)


def encode(image, fmt='PNG', **options):
    output = io.BytesIO()
    image.save(output, fmt, **options)
    return output.getvalue()


class ColorManagementTests(unittest.TestCase):
    def test_linear_profile_converts_to_expected_encoded_srgb(self):
        raw = linear_rgb_profile()
        data = encode(Image.new('RGB', (8, 4), (128, 128, 128)), icc_profile=raw)
        metadata, converted = prepare_image(data, color_policy='srgb-v1')
        # Independent sRGB transfer function, not another call to our converter.
        expected = round(255 * (1.055 * (128 / 255) ** (1 / 2.4) - 0.055))
        for channel in converted.getpixel((0, 0)):
            self.assertLessEqual(abs(channel - expected), 1)
        record = metadata['preprocessing']['color_management']
        self.assertEqual(record['status'], 'converted')
        self.assertEqual(record['source_profile']['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(record['rendering_intent'], 'relative-colorimetric')
        self.assertFalse(record['black_point_compensation'])
        self.assertTrue(record['littlecms_version'])
        self.assertEqual(metadata['preprocessing']['version'], 4)
        _, legacy = prepare_image(data)
        self.assertEqual(legacy.getpixel((0, 0)), (128, 128, 128))

    def test_srgb_profile_identity_and_alpha_preserved(self):
        image = Image.new('RGBA', (4, 1))
        image.putdata([(32, 64, 128, 0), (100, 200, 50, 64), (255, 0, 0, 128), (30, 90, 60, 255)])
        data = encode(image, icc_profile=profile_bytes())
        _, converted = prepare_image(data, color_policy='srgb-v1')
        self.assertEqual(converted.tobytes(), image.tobytes())

    def test_palette_and_grayscale_alpha(self):
        indexed = Image.new('P', (2, 1))
        indexed.putpalette([128, 128, 128, 40, 80, 120] + [0] * 762)
        indexed.putdata([0, 1])
        data = encode(indexed, transparency=bytes([0, 128]), icc_profile=linear_rgb_profile())
        _, result = prepare_image(data, color_policy='srgb-v1')
        self.assertEqual(result.getchannel('A').tobytes(), bytes([0, 128]))
        self.assertGreater(result.getpixel((0, 0))[0], 180)
        gray = Image.new('LA', (2, 1), (128, 42))
        _, result = prepare_image(encode(gray), color_policy='srgb-v1', assume_srgb=True)
        self.assertEqual(result.getpixel((0, 0)), (128, 128, 128, 42))

    def test_unknown_declared_and_assumed_are_distinct(self):
        data = encode(Image.new('RGB', (3, 2), 'red'))
        failed = analyze(AnalysisRequest(data, task='inspect', color_policy='srgb-v1'))
        self.assertEqual(failed['error']['code'], 'unknown_color_space')
        self.assertEqual(failed['diagnostics']['color_management']['source_interpretation'], 'unknown')
        assumed = analyze(AnalysisRequest(data, task='inspect', color_policy='srgb-v1', assume_srgb=True))
        self.assertEqual(assumed['status'], 'ok', assumed)
        self.assertEqual(assumed['provenance']['preprocessing']['color_management']['status'], 'assumed_srgb')
        pnginfo = PngImagePlugin.PngInfo()
        pnginfo.add(b'sRGB', b'\0')
        declared = encode(Image.new('RGB', (3, 2), 'red'), pnginfo=pnginfo)
        metadata, _ = prepare_image(declared, color_policy='srgb-v1')
        self.assertEqual(metadata['preprocessing']['color_management']['status'], 'declared_srgb')
        self.assertIsNone(metadata['preprocessing']['color_management']['littlecms_version'])

    def test_invalid_profiles_never_fall_back_and_legacy_does_not_parse(self):
        for raw, code in ((b'broken', 'invalid_color_profile'),
                          (b'x' * (1024 * 1024 + 1), 'color_profile_too_large')):
            data = encode(Image.new('RGB', (3, 2), 'red'), 'JPEG', icc_profile=raw)
            result = analyze(AnalysisRequest(data, task='inspect', color_policy='srgb-v1', assume_srgb=True))
            self.assertEqual(result['error']['code'], code, result)
            with Image.open(io.BytesIO(data)) as source:
                legacy_image, record = apply_color_policy(source)
                self.assertIs(legacy_image, source)
                self.assertEqual(record['status'], 'unmanaged')
            if len(raw) < 1024:
                legacy = analyze(AnalysisRequest(data, task='inspect'))
                self.assertEqual(legacy['status'], 'ok', legacy)
            # Huge ICC payloads can still hit the pre-existing legacy PNG-preview
            # decompression guard; this policy does not change that behavior.

    def test_cms_unavailable_is_structured_and_legacy_still_works(self):
        image = Image.new('RGB', (2, 2))
        image.info['icc_profile'] = profile_bytes()
        importer = builtins.__import__
        def without_cms(name, globals=None, locals=None, fromlist=(), level=0):
            if name == 'PIL' and 'ImageCms' in fromlist:
                raise ImportError('unavailable')
            return importer(name, globals, locals, fromlist, level)
        with patch('builtins.__import__', side_effect=without_cms):
            with self.assertRaises(AnalyzerError) as error:
                apply_color_policy(image, 'srgb-v1')
            self.assertEqual(error.exception.code, 'color_management_unavailable')
            self.assertIs(apply_color_policy(image)[0], image)

    def test_cmyk_is_not_converted_to_rgb_before_cms(self):
        image = Image.new('CMYK', (2, 2), (10, 20, 30, 40))
        image.info['icc_profile'] = profile_bytes()
        # An RGB profile is genuinely incompatible with CMYK.
        with self.assertRaises(AnalyzerError) as error:
            apply_color_policy(image, 'srgb-v1')
        self.assertEqual(error.exception.code, 'color_conversion_failed')
        # Routing test only: this does not establish CMYK numerical accuracy.
        with patch('PIL.ImageCms.profileToProfile', return_value=Image.new('RGB', (2, 2))) as transform:
            apply_color_policy(image, 'srgb-v1')
            self.assertEqual(transform.call_args.args[0].mode, 'CMYK')
        image.info.clear()
        with self.assertRaises(AnalyzerError) as error:
            apply_color_policy(image, 'srgb-v1', assume_srgb=True)
        self.assertEqual(error.exception.code, 'unknown_color_space')

    def test_lab_profile_and_high_depth_rejection(self):
        lab = Image.new('LAB', (2, 2), (255, 128, 128))
        lab.info['icc_profile'] = ImageCms.ImageCmsProfile(ImageCms.createProfile('LAB')).tobytes()
        converted, record = apply_color_policy(lab, 'srgb-v1')
        self.assertEqual(record['status'], 'converted')
        self.assertTrue(all(channel >= 254 for channel in converted.getpixel((0, 0))))
        with self.assertRaises(AnalyzerError) as error:
            apply_color_policy(Image.new('I;16', (2, 2)), 'srgb-v1', assume_srgb=True)
        self.assertEqual(error.exception.code, 'unsupported_color_mode')

    def test_conversion_precedes_reduction_and_orientation(self):
        exif = Image.Exif()
        exif[274] = 6
        for fmt in ('JPEG', 'TIFF'):
            data = encode(Image.new('RGB', (5000, 20), (128, 128, 128)), fmt,
                          icc_profile=linear_rgb_profile(), exif=exif)
            metadata, image = prepare_image(data, color_policy='srgb-v1')
            self.assertEqual(image.size, (8, 2048))
            self.assertEqual(metadata['preprocessing']['decoder'], 'pillow-bounded')
            self.assertGreater(image.getpixel((0, 0))[0], 180)
        source = Image.new('RGB', (5000, 20))
        source.info['icc_profile'] = profile_bytes()
        original = ImageCms.profileToProfile
        with patch('PIL.ImageCms.profileToProfile', wraps=original) as transform:
            apply_color_policy(source, 'srgb-v1')
            self.assertEqual(transform.call_args.args[0].size, (5000, 20))

    def test_legacy_pixels_match_previous_pipeline(self):
        for mode, color, fmt in (('RGB', (70, 90, 120), 'JPEG'),
                                 ('RGBA', (70, 90, 120, 128), 'PNG'),
                                 ('CMYK', (10, 20, 30, 40), 'JPEG')):
            data = encode(Image.new(mode, (5000, 20), color), fmt)
            with Image.open(io.BytesIO(data)) as old:
                scale = min(1, 2048 / max(old.size))
                old.draft('RGB', (max(1, int(old.width * scale)), max(1, int(old.height * scale))))
                working = old.convert('RGBA') if 'A' in old.getbands() else old
                working.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
                expected = ImageOps.exif_transpose(working).convert('RGBA' if mode == 'RGBA' else 'RGB')
            metadata, actual = prepare_image(data)
            self.assertEqual(actual.tobytes(), expected.tobytes())
            self.assertEqual(metadata['preprocessing']['version'], 3)

    def test_profile_precedes_png_declaration_and_explicit_assumption(self):
        source = Image.new('RGB', (3, 2), (128, 128, 128))
        source.info.update(srgb=0, icc_profile=linear_rgb_profile())
        image, record = apply_color_policy(source, 'srgb-v1', assume_srgb=True)
        self.assertEqual(record['status'], 'converted')
        self.assertGreater(image.getpixel((0, 0))[0], 180)

    def test_descriptions_and_human_output_use_color_policy(self):
        data = encode(Image.new('RGB', (3, 2), (128, 128, 128)), icc_profile=linear_rgb_profile())
        backend = Mock()
        backend.name = 'test'
        backend.check_model.return_value = ({'name': 'test'}, {'version': 'test'})
        backend.settings.return_value = {}
        backend.describe.return_value = ({'summary': 'Gray rectangle.', 'subjects': [], 'text_present': False}, {})
        result = analyze(AnalysisRequest(data, profile='general', color_policy='srgb-v1'), backend=backend)
        self.assertEqual(result['status'], 'ok', result)
        self.assertGreater(backend.describe.call_args.args[0].getpixel((0, 0))[0], 180)
        from imagescope.presentation import show_result
        output = io.StringIO()
        show_result(result, stream=output)
        self.assertIn('converted to sRGB', output.getvalue())

    def test_failure_prevents_inference_and_validates_options(self):
        backend = Mock()
        result = analyze(AnalysisRequest(encode(Image.new('RGB', (2, 2))), color_policy='srgb-v1'), backend=backend)
        self.assertEqual(result['error']['code'], 'unknown_color_space')
        backend.check_model.assert_not_called()
        for options in ({'color_policy': 'bad'}, {'assume_srgb': True},
                        {'color_policy': 'srgb-v1', 'assume_srgb': 1}):
            result = analyze(AnalysisRequest(b'', task='inspect', **options))
            self.assertEqual(result['error']['code'], 'invalid_request')

    def test_cli_and_api_parity(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            path = Path(directory) / 'linear.png'
            data = encode(Image.new('RGB', (8, 4), (128, 128, 128)), icc_profile=linear_rgb_profile())
            path.write_bytes(data)
            command = [sys.executable, '-m', 'imagescope', 'inspect', str(path), '--json', '--color-policy', 'srgb-v1']
            process = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            cli = json.loads(process.stdout)
            api = analyze(AnalysisRequest(path, task='inspect', color_policy='srgb-v1'))
            cli.pop('elapsed_seconds')
            api.pop('elapsed_seconds')
            self.assertEqual(cli, api)
            self.assertEqual(api['provenance']['measurements_version'], 6)
            self.assertEqual(path.read_bytes(), data)
            discovery = subprocess.run([sys.executable, '-m', 'imagescope', 'info', '--json'], capture_output=True, text=True)
            self.assertEqual(json.loads(discovery.stdout)['color_policies'], ['legacy-v1', 'srgb-v1'])


if __name__ == '__main__':
    unittest.main()
