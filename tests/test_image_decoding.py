import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from imagescope import AnalysisRequest, AnalyzerError, analyze
from imagescope.contracts import WORKING_IMAGE_SIZE, validate_result
from imagescope.images import prepare_image


class ImageDecodingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_118_megapixel_jpeg_uses_reduced_decode_and_original_metadata(self):
        path = self.root / 'large.jpg'
        exif = Image.Exif()
        exif[274] = 6
        with Image.new('RGB', (14500, 8156), '#408080') as original:
            original.save(path, exif=exif)
        before = (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
        pillow_limit = Image.MAX_IMAGE_PIXELS
        metadata, image = prepare_image(path)
        self.assertEqual((metadata['width'], metadata['height']), (8156, 14500))
        self.assertLessEqual(max(image.size), WORKING_IMAGE_SIZE)
        self.assertEqual(metadata['preprocessing']['decoder'], 'pillow-jpeg-reduced')
        self.assertTrue(metadata['preprocessing']['downsampled'])
        byte_metadata, byte_image = prepare_image(path.read_bytes())
        self.assertEqual(metadata, byte_metadata)
        self.assertEqual(image.tobytes(), byte_image.tobytes())
        self.assertEqual(Image.MAX_IMAGE_PIXELS, pillow_limit)
        self.assertEqual((path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()), before)

    def test_large_png_bounded_decode_and_alpha_compositing(self):
        path = self.root / 'large.png'
        with Image.new('RGBA', (6000, 5000), (255, 0, 0, 128)) as original:
            original.save(path)
        original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        result = analyze(AnalysisRequest(path, task='inspect'))
        validate_result(result)
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual((result['input']['width'], result['input']['height']), (6000, 5000))
        self.assertEqual(result['provenance']['measurements_version'], 2)
        preprocessing = result['provenance']['preprocessing']
        self.assertEqual(preprocessing['version'], 2)
        self.assertTrue(preprocessing['downsampled'])
        self.assertEqual(preprocessing['working_width'], WORKING_IMAGE_SIZE)
        metadata, preview = prepare_image(path)
        self.assertEqual(preview.getpixel((0, 0)), (255, 127, 127))
        self.assertEqual((metadata['width'], metadata['height']), (6000, 5000))
        self.assertLessEqual(max(preview.size), WORKING_IMAGE_SIZE)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), original_hash)

    def test_source_dimension_guard_remains_before_raster_decode(self):
        data = io.BytesIO()
        Image.new('RGB', (8, 8)).save(data, 'JPEG')
        encoded = bytearray(data.getvalue())
        marker = encoded.index(b'\xff\xc0')
        encoded[marker + 5:marker + 9] = struct.pack('>HH', 30000, 30000)
        with self.assertRaises(AnalyzerError) as error:
            prepare_image(bytes(encoded))
        self.assertEqual(error.exception.code, 'image_too_large')
        self.assertIn('source limit', str(error.exception))

    def test_decoder_timeout_resource_exit_and_bad_output_are_actionable(self):
        data = io.BytesIO()
        Image.new('RGB', (8, 8)).save(data, 'PNG')
        with patch('imagescope.images.subprocess.run', side_effect=subprocess.TimeoutExpired('decoder', 30)):
            with self.assertRaises(AnalyzerError) as error:
                prepare_image(data.getvalue())
            self.assertEqual(error.exception.code, 'decode_timeout')
        for code, output, expected in [(-9, b'', 'decode_resource_limit'),
                                       (1, b'', 'decode_failed'),
                                       (0, b'{"metadata": {}}', 'decode_failed')]:
            with patch('imagescope.images.subprocess.run', return_value=subprocess.CompletedProcess([], code, output, b'')):
                with self.assertRaises(AnalyzerError) as error:
                    prepare_image(data.getvalue())
                self.assertEqual(error.exception.code, expected)

    def test_child_enforces_real_memory_and_cpu_limits(self):
        script = '''
import os, resource, sys
from imagescope import decode_worker as worker
from imagescope.contracts import DECODE_MEMORY_BYTES, DECODE_TIMEOUT, MAX_SOURCE_PIXELS
sys.argv = ['decode_worker', str(MAX_SOURCE_PIXELS), str(os.getppid())]
def exhaust(data, max_pixels):
    assert resource.getrlimit(resource.RLIMIT_AS) == (DECODE_MEMORY_BYTES, DECODE_MEMORY_BYTES)
    assert resource.getrlimit(resource.RLIMIT_CPU)[1] < DECODE_TIMEOUT
    return bytearray(DECODE_MEMORY_BYTES * 2)
worker.decode = exhaust
raise SystemExit(worker.main())
'''
        result = subprocess.run([sys.executable, '-c', script], input=b'', capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 1, result.stderr)
        error = json.loads(result.stdout)['error']
        self.assertEqual(error['code'], 'decode_resource_limit')
        self.assertIn('memory budget', error['message'])

    def test_first_frame_and_small_image_behavior(self):
        path = self.root / 'frames.gif'
        with Image.new('RGB', (20, 10), 'red') as first, Image.new('RGB', (20, 10), 'blue') as second:
            first.save(path, save_all=True, append_images=[second])
        metadata, image = prepare_image(path)
        self.assertEqual(metadata['frames'], 2)
        self.assertEqual(image.size, (20, 10))
        self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))
        self.assertFalse(metadata['preprocessing']['downsampled'])


if __name__ == '__main__':
    unittest.main()
