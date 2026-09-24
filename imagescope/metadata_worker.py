"""Header-only metadata extraction, called inside the resource-limited worker."""
import hashlib
import io
import math
import warnings

from PIL import Image, UnidentifiedImageError

from .contracts import AnalyzerError

MAX_EXIF_BYTES = 256 * 1024
MAX_ICC_BYTES = 1024 * 1024
MAX_EXIF_FIELDS = 64
MAX_TEXT = 512


def extract_metadata(data, max_pixels):
    from .decode_worker import FORMATS

    notices = []

    def warn(code, field, message):
        if len(notices) < 32:
            notices.append({'code': code, 'field': field, 'message': message})

    def scalar(value):
        if isinstance(value, str):
            if len(value) > MAX_TEXT:
                warn('metadata_truncated', 'exif', 'EXIF text limited to 512 characters')
            return value[:MAX_TEXT]
        if value is None or type(value) in (bool, int):
            return value
        if isinstance(value, (float,)) and math.isfinite(value):
            return value
        # Rational, binary, nested and vendor-specific values are not expanded.
        warn('metadata_omitted', 'exif', 'Non-scalar EXIF values omitted')
        return None

    Image.MAX_IMAGE_PIXELS = max_pixels
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        try:
            # Never invoke unrelated format plugins: some load pixels in _open.
            image = Image.open(io.BytesIO(data), formats=sorted(FORMATS))
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
            raise AnalyzerError('invalid_input', f'Cannot read image headers: {str(exc)[:300]}') from exc
        with image:
            if image.format not in FORMATS:
                raise AnalyzerError('unsupported_image', 'Supported formats: JPEG, PNG, WebP, BMP, TIFF, GIF')
            from .images import stored_dimensions
            width, height = stored_dimensions(image)
            if width * height > max_pixels:
                raise AnalyzerError('image_too_large', f'Image exceeds the {max_pixels:,}-pixel source limit')
            exif = Image.Exif()
            exif_status = 'absent'
            raw = image.info.get('exif')
            try:
                if raw:
                    if len(raw) > MAX_EXIF_BYTES:
                        exif_status = 'omitted'
                        warn('metadata_limit', 'exif', 'EXIF exceeds the 256 KiB parsing limit')
                    else:
                        if not raw.startswith(b'Exif\x00\x00') and not raw.startswith((b'II', b'MM')):
                            raise ValueError('Invalid EXIF header')
                        exif.load(raw)
                        exif_status = 'present'
                elif image.format == 'TIFF':
                    # Base implementation reads TIFF tags, not the pixel raster.
                    exif = Image.Image.getexif(image)
                    exif_status = 'present'
                elif image.format == 'PNG':
                    # PNG.getexif() loads pixels looking for trailing eXIf chunks.
                    exif_status = 'unknown'
                    warn('metadata_not_scanned', 'exif', 'PNG chunks after image data were not scanned')
            except (OSError, ValueError, TypeError, SyntaxError, OverflowError):
                exif = Image.Exif()
                exif_status = 'invalid'
                warn('invalid_metadata', 'exif', 'Cannot parse EXIF metadata')
            orientation = exif.get(274)
            if orientation is not None and (type(orientation) is not int or orientation not in range(1, 9)):
                warn('invalid_metadata', 'orientation', 'EXIF orientation must be an integer from 1 through 8')
                orientation = None
            oriented = (height, width) if orientation in (5, 6, 7, 8) else (width, height)
            fields = {}
            for index, key in enumerate(exif):
                if index >= MAX_EXIF_FIELDS:
                    warn('metadata_limit', 'exif', 'At most 64 top-level EXIF tags are returned')
                    break
                try:
                    fields[str(key)] = scalar(exif[key])
                except (OSError, ValueError, TypeError, OverflowError):
                    warn('invalid_metadata', 'exif', 'An EXIF tag could not be read')

            raw_icc = image.info.get('icc_profile')
            icc = {'status': 'absent', 'size_bytes': 0, 'sha256': None,
                   'description': None, 'color_space': None}
            if raw_icc is not None:
                icc.update(status='present', size_bytes=len(raw_icc),
                           sha256=hashlib.sha256(raw_icc).hexdigest())
                if len(raw_icc) > MAX_ICC_BYTES:
                    icc['status'] = 'omitted'
                    warn('metadata_limit', 'icc', 'ICC exceeds the 1 MiB parsing limit')
                else:
                    try:
                        from PIL import ImageCms
                        profile = ImageCms.ImageCmsProfile(io.BytesIO(raw_icc))
                        icc.update(description=ImageCms.getProfileDescription(profile).strip()[:MAX_TEXT],
                                   color_space=raw_icc[16:20].decode('ascii').strip())
                    except ImportError:
                        icc['status'] = 'unavailable'
                        warn('metadata_unavailable', 'icc', 'ICC parser is unavailable')
                    except (OSError, ValueError, TypeError):
                        icc['status'] = 'invalid'
                        warn('invalid_metadata', 'icc', 'Cannot parse embedded ICC profile')

            # Do not access n_frames/is_animated properties: GIF/TIFF may scan
            # arbitrarily many frames. Only use counts already read at open().
            count = image.__dict__.get('n_frames')
            if image.format in ('JPEG', 'BMP'):
                count = 1
            elif image.format == 'PNG' and count is None:
                count = 1
            if type(count) is not int or count < 1:
                count = None
                warn('metadata_not_scanned', 'sequence', 'Frame/page count requires traversal and was not inspected')
            sequence = {'kind': 'pages' if image.format == 'TIFF' else 'frames',
                        'count': count,
                        'animated': (count > 1 if count is not None else None)
                        if image.format in ('GIF', 'PNG', 'WEBP') else False,
                        'loop': image.info.get('loop') if type(image.info.get('loop')) is int else None,
                        'first_frame_duration_ms': image.info.get('duration')
                        if type(image.info.get('duration')) in (int, float)
                        and math.isfinite(image.info['duration']) else None}
            metadata = {'format': image.format, 'mode': image.mode,
                        'stored_size': {'width': width, 'height': height},
                        'oriented_size': {'width': oriented[0], 'height': oriented[1]},
                        'orientation': orientation,
                        'orientation_assumed': orientation is None,
                        'has_alpha_channel': 'A' in image.getbands() or 'transparency' in image.info,
                        'exif': {'status': exif_status, 'tags': fields},
                        'icc': icc, 'sequence': sequence,
                        'color_conversion': 'none'}
        if caught:
            warn('parser_warning', 'metadata', 'Image parser reported metadata warnings; fields may be incomplete')
    return {'metadata': metadata, 'warnings': notices}
