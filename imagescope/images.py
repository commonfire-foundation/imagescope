"""Read-only input snapshots and bounded, isolated working-image decoding."""
import base64
import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image

from .contracts import (AnalyzerError, MAX_INPUT_BYTES, MAX_SOURCE_PIXELS,
                        DECODE_TIMEOUT, MAX_DECODE_OUTPUT_BYTES, WORKING_IMAGE_SIZE,
                        strict_json_loads)

EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff', '.gif'}


def prepare_image(source):
    try:
        if isinstance(source, Path):
            before = source.stat()
            if not source.is_file():
                raise AnalyzerError('invalid_input', 'Input must be a regular image file')
            if before.st_size > MAX_INPUT_BYTES:
                raise AnalyzerError('input_too_large', 'Image exceeds the 64 MiB input limit')
            with source.open('rb') as stream:
                data = stream.read(MAX_INPUT_BYTES + 1)
            after = source.stat()
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
                raise AnalyzerError('source_changed', 'Image changed while being read')
        else:
            data = source
        if len(data) > MAX_INPUT_BYTES:
            raise AnalyzerError('input_too_large', 'Image exceeds the 64 MiB input limit')
        try:
            process = subprocess.run(
                [sys.executable, '-m', 'imagescope.decode_worker', str(MAX_SOURCE_PIXELS), str(os.getpid())],
                input=data, capture_output=True, timeout=DECODE_TIMEOUT)
        except subprocess.TimeoutExpired as exc:
            raise AnalyzerError('decode_timeout', f'Image decoding exceeded {DECODE_TIMEOUT} seconds') from exc
        if len(process.stdout) > MAX_DECODE_OUTPUT_BYTES:
            raise AnalyzerError('decode_resource_limit', 'Decoder output exceeds the preview budget')
        if process.returncode < 0:
            raise AnalyzerError('decode_resource_limit', 'Decoder stopped at its resource limit or crashed; original image is unchanged')
        try:
            result = strict_json_loads(process.stdout)
            if 'error' in result:
                raise AnalyzerError(result['error']['code'], result['error']['message'])
            if process.returncode:
                raise ValueError('Decoder failed')
            metadata = result['metadata']
            with Image.open(io.BytesIO(base64.b64decode(result['image'], validate=True))) as preview:
                if max(preview.size) > WORKING_IMAGE_SIZE:
                    raise ValueError('Decoder returned an oversized preview')
                image = preview.convert('RGB')
        except (ValueError, KeyError, TypeError) as exc:
            raise AnalyzerError('decode_failed', 'Image decoder returned an invalid preview') from exc
        metadata['sha256'] = hashlib.sha256(data).hexdigest()
        return metadata, image
    except (OSError, ValueError) as exc:
        raise AnalyzerError('invalid_input', f'Cannot read image: {exc}') from exc
