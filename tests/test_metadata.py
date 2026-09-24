import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from PIL import Image, ImageCms, ImageFile

from imagescope import MetadataRequest, inspect_metadata
from imagescope.contracts import MAX_SOURCE_PIXELS, MAX_EVENT_BYTES
from imagescope.metadata_worker import extract_metadata, MAX_EXIF_BYTES, MAX_ICC_BYTES


def encoded(fmt='PNG', mode='RGB', **kwargs):
    stream = io.BytesIO()
    Image.new(mode, (8, 12)).save(stream, format=fmt, **kwargs)
    return stream.getvalue()


class MetadataTests(unittest.TestCase):
    def test_supported_formats_do_not_decode_or_seek_frames(self):
        for fmt in ('JPEG', 'PNG', 'WEBP', 'BMP', 'TIFF', 'GIF'):
            data = encoded(fmt)
            with self.subTest(fmt=fmt), ExitStack() as stack:
                with Image.open(io.BytesIO(data)) as probe:
                    plugin = type(probe)
                for cls, method in ((Image.Image, 'load'), (ImageFile.ImageFile, 'load'),
                                    (plugin, 'load'), (Image.Image, 'convert'),
                                    (Image.Image, 'resize'), (Image.Image, 'thumbnail')):
                    stack.enter_context(patch.object(cls, method, side_effect=AssertionError('pixel access')))
                # Opening may legitimately seek frame zero; no later traversal.
                original_seek = plugin.seek
                def seek(image, frame):
                    if frame != 0:
                        raise AssertionError('frame traversal')
                    return original_seek(image, frame)
                stack.enter_context(patch.object(plugin, 'seek', seek))
                result = extract_metadata(data, MAX_SOURCE_PIXELS)
                self.assertEqual(result['metadata']['format'], fmt)
                self.assertEqual(result['metadata']['stored_size'], {'width': 8, 'height': 12})

    def test_all_orientations(self):
        for orientation in range(1, 9):
            exif = Image.Exif()
            exif[274] = orientation
            result = inspect_metadata(MetadataRequest(encoded('JPEG', exif=exif)))
            self.assertEqual(result['status'], 'ok', result)
            metadata = result['metadata']
            self.assertEqual(metadata['orientation'], orientation)
            self.assertFalse(metadata['orientation_assumed'])
            self.assertEqual(metadata['oriented_size'],
                             {'width': 12, 'height': 8} if orientation >= 5 else {'width': 8, 'height': 12})

    def test_path_bytes_parity_and_unchanged_source(self):
        data = encoded('PNG', 'RGBA')
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            path = Path(directory) / 'source.png'
            path.write_bytes(data)
            before = path.stat()
            a = inspect_metadata(MetadataRequest(path))
            b = inspect_metadata(MetadataRequest(data))
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)
        for result in (a, b):
            result.pop('elapsed_seconds')
        self.assertEqual(a, b)
        self.assertTrue(a['metadata']['has_alpha_channel'])

    def test_icc_valid_invalid_and_oversized(self):
        valid = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        for profile, status in ((valid, 'present'), (b'broken', 'invalid'),
                                (b'x' * (MAX_ICC_BYTES + 1), 'omitted')):
            # Use JPEG for the huge profile: PNG has an independent decompression limit.
            result = inspect_metadata(MetadataRequest(encoded('JPEG', icc_profile=profile)))
            self.assertEqual(result['status'], 'ok', result)
            icc = result['metadata']['icc']
            self.assertEqual(icc['status'], status)
            self.assertEqual(icc['size_bytes'], len(profile))
            self.assertEqual(len(icc['sha256']), 64)
            self.assertEqual(result['metadata']['color_conversion'], 'none')
            if status == 'present':
                self.assertEqual(icc['color_space'], 'RGB')
                self.assertIn('sRGB', icc['description'])
            else:
                self.assertTrue(result['warnings'])

    def test_exif_limits_and_invalid_orientation(self):
        exif = Image.Exif()
        exif[274] = 42
        exif[270] = 'a' * 1000
        result = inspect_metadata(MetadataRequest(encoded('JPEG', exif=exif)))
        self.assertEqual(result['status'], 'ok', result)
        self.assertIsNone(result['metadata']['orientation'])
        self.assertEqual(len(result['metadata']['exif']['tags']['270']), 512)
        self.assertEqual({w['code'] for w in result['warnings']},
                         {'invalid_metadata', 'metadata_truncated'})
        for raw, expected in ((b'bad', 'invalid'), (b'x' * (MAX_EXIF_BYTES + 1), 'omitted')):
            result = inspect_metadata(MetadataRequest(encoded('PNG', exif=raw)))
            self.assertEqual(result['status'], 'ok', result)
            self.assertEqual(result['metadata']['exif']['status'], expected)
            self.assertTrue(result['warnings'])

    def test_top_level_exif_and_output_budgets(self):
        exif = Image.Exif()
        for tag in range(50000, 50080):
            exif[tag] = 'value'
        result = inspect_metadata(MetadataRequest(encoded('PNG', exif=exif)))
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(len(result['metadata']['exif']['tags']), 64)
        self.assertIn('metadata_limit', {w['code'] for w in result['warnings']})
        self.assertLess(len(json.dumps(result, allow_nan=False).encode()), MAX_EVENT_BYTES)

    def test_png_trailing_exif_is_explicitly_unknown(self):
        exif = Image.Exif()
        exif[274] = 6
        data = encoded('PNG', exif=exif)
        position, chunks = 8, []
        while position < len(data):
            length = int.from_bytes(data[position:position + 4], 'big') + 12
            chunks.append(data[position:position + length])
            position += length
        exif_chunk = next(chunk for chunk in chunks if chunk[4:8] == b'eXIf')
        reordered = data[:8] + b''.join(chunk for chunk in chunks
                                       if chunk[4:8] not in (b'eXIf', b'IEND')) + exif_chunk + chunks[-1]
        result = inspect_metadata(MetadataRequest(reordered))
        self.assertEqual(result['status'], 'ok', result)
        self.assertEqual(result['metadata']['exif']['status'], 'unknown')
        self.assertIsNone(result['metadata']['orientation'])
        self.assertTrue(result['metadata']['orientation_assumed'])

    def test_animation_counts_do_not_require_traversal(self):
        first = Image.new('RGB', (8, 12), 'red')
        second = Image.new('RGB', (8, 12), 'blue')
        for fmt in ('GIF', 'TIFF', 'PNG', 'WEBP'):
            stream = io.BytesIO()
            first.save(stream, format=fmt, save_all=True, append_images=[second], duration=100, loop=0)
            result = inspect_metadata(MetadataRequest(stream.getvalue()))
            self.assertEqual(result['status'], 'ok', result)
            sequence = result['metadata']['sequence']
            if fmt in ('GIF', 'TIFF'):
                self.assertIsNone(sequence['count'])
                self.assertTrue(result['warnings'])
            else:
                self.assertEqual(sequence['count'], 2)
                self.assertTrue(sequence['animated'])
            if fmt == 'TIFF':
                self.assertEqual(sequence['kind'], 'pages')
                self.assertFalse(sequence['animated'])

    def test_bad_requests_inputs_and_timeout(self):
        for source, timeout, code in (('not-a-Path', 10, 'invalid_request'),
                                      (b'', 0, 'invalid_request'),
                                      (b'', float('nan'), 'invalid_request'),
                                      (b'', True, 'invalid_request'),
                                      (b'', 31, 'invalid_request'),
                                      (b'not an image', 10, 'invalid_input'),
                                      (Path('/does-not-exist-imagescope'), 10, 'invalid_input')):
            result = inspect_metadata(MetadataRequest(source, timeout=timeout))
            self.assertEqual(result['error']['code'], code, result)
        with patch('imagescope.metadata.subprocess.run', side_effect=subprocess.TimeoutExpired('worker', 1)):
            result = inspect_metadata(MetadataRequest(encoded()))
            self.assertEqual(result['error']['code'], 'metadata_timeout')
        with patch('imagescope.images.MAX_INPUT_BYTES', 8):
            result = inspect_metadata(MetadataRequest(b'x' * 9))
            self.assertEqual(result['error']['code'], 'input_too_large')

    def test_worker_failures(self):
        for returncode, output, code in ((-9, b'', 'metadata_resource_limit'),
                                         (0, b'x' * (MAX_EVENT_BYTES + 1), 'metadata_resource_limit'),
                                         (0, b'[]', 'metadata_failed'),
                                         (0, b'{}', 'metadata_failed'),
                                         (1, b'{}', 'metadata_failed'),
                                         (0, b'not json', 'metadata_failed')):
            process = subprocess.CompletedProcess([], returncode, stdout=output)
            with patch('imagescope.metadata.subprocess.run', return_value=process):
                result = inspect_metadata(MetadataRequest(encoded()))
                self.assertEqual(result['error']['code'], code, result)

    def test_cli_json_and_human(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            path = Path(directory) / 'source.png'
            path.write_bytes(encoded())
            command = [sys.executable, '-m', 'imagescope', 'metadata', str(path)]
            process = subprocess.run(command + ['--json'], capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(process.stderr, '')
            result = json.loads(process.stdout)
            api = inspect_metadata(MetadataRequest(path))
            result.pop('elapsed_seconds')
            api.pop('elapsed_seconds')
            self.assertEqual(result, api)
            human = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(human.returncode, 0)
            self.assertIn('PNG', human.stdout)
            self.assertIn('Warning', human.stderr)
            invalid = subprocess.run(command + ['--json', '--timeout', '0'], capture_output=True, text=True)
            self.assertEqual(invalid.returncode, 2)
            self.assertEqual(json.loads(invalid.stdout)['error']['code'], 'invalid_request')


if __name__ == '__main__':
    unittest.main()
