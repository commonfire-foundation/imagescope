"""Versioned color handling inside the resource-limited decoding worker."""
import hashlib
import io
from typing import Any, NoReturn

from PIL import Image, __version__ as PILLOW_VERSION

from .contracts import AnalyzerError

COLOR_POLICIES = ('legacy-v1', 'srgb-v1')
MAX_COLOR_PROFILE_BYTES = 1024 * 1024
RGB_LIKE_MODES = ('RGB', 'RGBA', 'P', 'L', 'LA', '1')


def validate_color_policy(policy, assume_srgb):
    if policy not in COLOR_POLICIES:
        raise AnalyzerError('invalid_request', 'color_policy must be legacy-v1 or srgb-v1')
    if type(assume_srgb) is not bool or (assume_srgb and policy != 'srgb-v1'):
        raise AnalyzerError('invalid_request', 'assume_srgb must be boolean and requires srgb-v1')


def apply_color_policy(image, policy='legacy-v1', assume_srgb=False):
    """Return source or converted image plus explicit, bounded color provenance."""
    validate_color_policy(policy, assume_srgb)
    raw = image.info.get('icc_profile')
    declared_srgb = type(image.info.get('srgb')) is int and image.info['srgb'] in range(4)
    record = {'policy': policy, 'assume_srgb': assume_srgb,
              'source_mode': image.mode,
              'source_profile': {'status': 'present_unparsed' if raw is not None else 'absent',
                                 'sha256': hashlib.sha256(raw).hexdigest() if raw is not None else None,
                                 'size_bytes': len(raw) if raw is not None else 0,
                                 'description': None, 'color_space': None},
              'source_interpretation': 'unknown', 'status': 'unmanaged',
              'output_color_space': None, 'rendering_intent': None,
              'black_point_compensation': False, 'transform_optimization': None, 'order': None,
              'pillow_version': PILLOW_VERSION, 'littlecms_version': None}
    if declared_srgb and raw is None and image.mode in RGB_LIKE_MODES:
        record['source_interpretation'] = 'declared_srgb'
    if policy == 'legacy-v1':
        return image, record

    record.update(status='failed', rendering_intent='relative-colorimetric',
                  order='color-before-reduction-orientation-compositing')

    def fail(code, message) -> NoReturn:
        raise AnalyzerError(code, message, {'color_management': record})

    if image.mode not in (*RGB_LIKE_MODES, 'CMYK', 'LAB'):
        fail('unsupported_color_mode', f'srgb-v1 does not support source mode {image.mode}')
    if raw is not None:
        if len(raw) > MAX_COLOR_PROFILE_BYTES:
            record['source_profile']['status'] = 'oversized'
            fail('color_profile_too_large', 'Embedded ICC profile exceeds the 1 MiB conversion limit')
        try:
            from PIL import ImageCms
        except ImportError:
            fail('color_management_unavailable', 'Pillow ImageCms/LittleCMS is required for ICC conversion')
        record['littlecms_version'] = ImageCms.core.littlecms_version
        try:
            source = ImageCms.ImageCmsProfile(io.BytesIO(raw))
            record['source_profile'].update(status='valid',
                description=ImageCms.getProfileDescription(source).strip()[:512],
                color_space=raw[16:20].decode('ascii').strip())
            record['source_interpretation'] = 'embedded_icc'
        except (OSError, ValueError, TypeError, ImageCms.PyCMSError):
            record['source_profile']['status'] = 'invalid'
            fail('invalid_color_profile', 'Cannot parse embedded ICC profile; no sRGB fallback was applied')
        # Keep grayscale/CMYK/LAB in their profile's native channel layout.
        source_mode = {'RGBA': 'RGB', 'P': 'RGB', 'LA': 'L', '1': 'L'}.get(image.mode, image.mode)
        color = image.convert(source_mode) if image.mode != source_mode else image
        try:
            target = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB'))
            # Avoid LittleCMS's precomputed transform CLUT: its interpolation
            # can shift dark CMYK colors by several 8-bit code values. 0x0100
            # is cmsFLAGS_NOOPTIMIZE; Pillow 10.0 uses integers, newer versions
            # expose the Flags enum. Black-point compensation stays disabled.
            flags: Any = getattr(ImageCms, 'Flags', int)(0x0100)
            record['transform_optimization'] = 'disabled'
            converted = ImageCms.profileToProfile(color, source, target,
                renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC, outputMode='RGB',
                inPlace=False, flags=flags)
        except (OSError, ValueError, TypeError, ImageCms.PyCMSError):
            fail('color_conversion_failed', 'ICC profile is incompatible with the source mode or sRGB conversion')
        if converted is None:
            fail('color_conversion_failed', 'ICC conversion did not return an image')
        record['status'] = 'converted'
    else:
        if image.mode not in RGB_LIKE_MODES:
            fail('unknown_color_space', f'{image.mode} input requires a compatible embedded ICC profile')
        if not declared_srgb and not assume_srgb:
            fail('unknown_color_space', 'Untagged image: explicitly enable assume_srgb to interpret RGB/gray samples as sRGB')
        converted = image.convert('RGB')
        record['source_interpretation'] = 'declared_srgb' if declared_srgb else 'assumed_srgb'
        record['status'] = record['source_interpretation']
        # No CMS transform occurred for an existing/assumed sRGB interpretation.
        record['rendering_intent'] = None

    if 'A' in image.getbands() or 'transparency' in image.info:
        converted.putalpha(image.convert('RGBA').getchannel('A'))
    # Preserve EXIF for the later orientation step, but never attach the old ICC
    # to newly interpreted pixels. The internal working PNG is not an export.
    converted.info = {key: value for key, value in image.info.items()
                      if key not in ('icc_profile', 'transparency', 'srgb')}
    orientation = image.getexif().get(274)
    if orientation is not None:
        exif = Image.Exif()
        exif[274] = orientation
        converted.info['exif'] = exif.tobytes()
    record['output_color_space'] = 'srgb'
    return converted, record
