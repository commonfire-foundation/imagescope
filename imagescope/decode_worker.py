"""Private, resource-limited image decoder. No model, Qt, or database access."""
import base64
import io
import json
import sys
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from .contracts import (AnalyzerError, DECODE_MEMORY_BYTES, DECODE_TIMEOUT,
                        MAX_INPUT_BYTES, MAX_SOURCE_PIXELS, WORKING_IMAGE_SIZE,
                        MAX_DECODE_OUTPUT_BYTES, validate_region)

FORMATS = {'JPEG', 'PNG', 'WEBP', 'BMP', 'TIFF', 'GIF'}


def decode(data, max_pixels, *, color_policy='legacy-v1', assume_srgb=False, region=None):
    # This global is changed only in the isolated child, never in the UI or API
    # caller. Keep a hard source-dimension limit in addition to OS memory limits.
    Image.MAX_IMAGE_PIXELS = max_pixels
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as original:
            if original.format not in FORMATS:
                raise AnalyzerError('unsupported_image', 'Supported formats: JPEG, PNG, WebP, BMP, TIFF, GIF')
            if original.width * original.height > max_pixels:
                raise AnalyzerError('image_too_large', f'Image exceeds the {max_pixels:,}-pixel source limit')
            from .images import stored_dimensions
            width, height = stored_dimensions(original)
            orientation = original.getexif().get(274, 1)
            if orientation in (5, 6, 7, 8):
                width, height = height, width
            validate_region(region, source_size=(width, height))
            metadata = {'format': original.format, 'frames': getattr(original, 'n_frames', 1),
                        'has_alpha_channel': 'A' in original.getbands() or 'transparency' in original.info,
                        'width': width, 'height': height,
                        'aspect_ratio': round(width / height, 5)}
            from .color_management import apply_color_policy
            working, color_record = apply_color_policy(original, color_policy, assume_srgb)
            # Only legacy may shrink JPEG during decode; sRGB conversion must
            # precede all reduction and retain native source-profile channels.
            # Ask JPEG's decoder to shrink before allocating a full-size raster.
            scale = min(1, WORKING_IMAGE_SIZE / max(original.size))
            target_size = (max(1, int(original.width * scale)), max(1, int(original.height * scale)))
            original_size = original.size
            if color_policy == 'legacy-v1' and region is None:
                original.draft('RGB', target_size)
            reduced = original.size != original_size
            # Other formats may require full decoding; the child has a hard
            # address-space/CPU budget. Shrink before orientation copies.
            # Convert indexed/LA transparency before shrinking: RGBA resize uses
            # premultiplied channels, so hidden RGB cannot bleed into visible color.
            if region is not None:
                # No draft/thumbnail may run before these original-pixel edges
                # are applied. exif_transpose also handles TIFF's native loading.
                working = ImageOps.exif_transpose(working).crop(region)
            working = working.convert('RGBA') if metadata['has_alpha_channel'] else working
            working.thumbnail((WORKING_IMAGE_SIZE, WORKING_IMAGE_SIZE), Image.Resampling.LANCZOS)
            image = (working if region is not None else ImageOps.exif_transpose(working)).convert(
                'RGBA' if metadata['has_alpha_channel'] else 'RGB')
            analysis_size = (region[2] - region[0], region[3] - region[1]) if region is not None else (width, height)
            metadata['preprocessing'] = {
                'version': 5 if region is not None else (3 if color_policy == 'legacy-v1' else 4),
                'color_management': color_record,
                'orientation': 'exif', 'alpha_background': '#ffffff', 'frame': 0,
                'palette_alpha': 'opacity-weighted-no-background',
                'alpha_resize': 'pillow-premultiplied-srgb8-lanczos',
                'decoder': 'pillow-jpeg-reduced' if reduced else 'pillow-bounded',
                'working_width': image.width, 'working_height': image.height,
                'downsampled': image.size != analysis_size}
            if region is not None:
                metadata['preprocessing']['region'] = {
                    'version': 1, 'coordinate_space': 'exif-oriented-original-pixel-edges',
                    'bounds': list(region), 'source_size': [width, height],
                    'crop_size': list(analysis_size), 'working_size': list(image.size),
                    'working_to_source': {
                        'x': {'offset': region[0], 'numerator': analysis_size[0], 'denominator': image.width},
                        'y': {'offset': region[1], 'numerator': analysis_size[1], 'denominator': image.height}},
                    'visible_bounds_are_source_bounds': False}
            output = io.BytesIO()
            image.save(output, 'PNG')
            return {'metadata': metadata, 'image': base64.b64encode(output.getvalue()).decode('ascii')}


def main():
    try:
        # Fail closed where OS limits are unavailable, rather than silently
        # treating an unrestricted decode as safe.
        import resource
        if sys.platform.startswith('linux'):
            import ctypes
            import os
            import signal
            # Closing/killing the analyzer must not leave an expensive decoder
            # orphaned. Check the parent again to close the startup race.
            libc = ctypes.CDLL(None, use_errno=True)
            if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
                raise OSError(ctypes.get_errno(), 'Cannot bind decoder lifetime to parent')
            if os.getppid() != int(sys.argv[2]):
                return 1
        resource.setrlimit(resource.RLIMIT_AS, (DECODE_MEMORY_BYTES, DECODE_MEMORY_BYTES))
        resource.setrlimit(resource.RLIMIT_CPU, (DECODE_TIMEOUT - 2, DECODE_TIMEOUT - 1))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ImportError, OSError, ValueError) as exc:
        print(json.dumps({'error': {'code': 'decoder_unavailable', 'message': f'Cannot enforce decoder resource limits: {exc}'}}))
        return 1
    try:
        max_pixels = min(int(sys.argv[1]), MAX_SOURCE_PIXELS)
        if max_pixels < 1:
            raise ValueError('Invalid source pixel limit')
        data = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(data) > MAX_INPUT_BYTES:
            raise AnalyzerError('input_too_large', 'Image exceeds the 64 MiB input limit')
        if len(sys.argv) > 3 and sys.argv[3] == 'metadata':
            from .metadata_worker import extract_metadata
            result = extract_metadata(data, max_pixels)
        elif len(sys.argv) > 4:
            result = decode(data, max_pixels, color_policy=sys.argv[4],
                            assume_srgb=len(sys.argv) > 5 and sys.argv[5] == '1',
                            region=tuple(map(int, sys.argv[6].split(',')))
                            if len(sys.argv) > 6 and sys.argv[6] else None)
        else:
            result = decode(data, max_pixels)
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        result = {'error': {'code': 'image_too_large', 'message': f'Image exceeds the {max_pixels:,}-pixel source limit'}}
    except MemoryError:
        result = {'error': {'code': 'decode_resource_limit', 'message': 'Image decoding exceeded the 1.5 GiB memory budget'}}
    except AnalyzerError as exc:
        result = {'error': {'code': exc.code, 'message': str(exc), 'details': exc.details}}
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        result = {'error': {'code': 'invalid_input', 'message': f'Cannot decode image: {str(exc)[:500]}'}}
    encoded = json.dumps(result)
    if len(encoded) > MAX_DECODE_OUTPUT_BYTES:
        encoded = json.dumps({'error': {'code': 'decode_resource_limit', 'message': 'Decoded preview exceeds output budget'}})
    print(encoded)
    return 1 if 'error' in result else 0


if __name__ == '__main__':
    raise SystemExit(main())
