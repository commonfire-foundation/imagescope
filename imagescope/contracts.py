"""Public version-1 request/result contract. No GUI or persistence dependencies."""
from dataclasses import dataclass
import math
import json
from pathlib import Path

PROTOCOL_VERSION = 1
SCHEMA_VERSION = 1
DEFAULT_MODEL = 'qwen3-vl:4b'
DEFAULT_ENDPOINT = 'http://127.0.0.1:11434/api/'
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_SOURCE_PIXELS = 500_000_000
WORKING_IMAGE_SIZE = 2048
DECODE_MEMORY_BYTES = 1536 * 1024 * 1024
DECODE_TIMEOUT = 30
MAX_DECODE_OUTPUT_BYTES = 24 * 1024 * 1024
MAX_EVENT_BYTES = 1024 * 1024


class AnalyzerError(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class AnalysisRequest:
    source: Path | bytes
    task: str = 'describe'
    profile: str = 'wallpaper'
    model: str = DEFAULT_MODEL
    endpoint: str = DEFAULT_ENDPOINT
    preview_size: int = 768
    measurements: bool = False
    timeout: float = 300
    keep_alive: int = 300

    def validate(self):
        if not isinstance(self.source, (Path, bytes)):
            raise AnalyzerError('invalid_request', 'source must be a pathlib.Path or image bytes')
        if self.task not in ('inspect', 'describe') or self.profile != 'wallpaper':
            raise AnalyzerError('invalid_request', 'Supported tasks: inspect, describe; supported profile: wallpaper')
        if self.preview_size not in (256, 512, 768, 1024):
            raise AnalyzerError('invalid_request', 'preview_size must be 256, 512, 768, or 1024')
        if type(self.timeout) not in (int, float) or not math.isfinite(self.timeout) or not 0 < self.timeout <= 3600:
            raise AnalyzerError('invalid_request', 'timeout must be between 0 and 3600 seconds')
        if type(self.keep_alive) is not int or not 0 <= self.keep_alive <= 86400:
            raise AnalyzerError('invalid_request', 'keep_alive must be between 0 and 86400 seconds')
        if not isinstance(self.model, str) or not self.model.strip():
            raise AnalyzerError('invalid_request', 'model must be a nonempty name')


def empty_result(request):
    return {'schema_version': SCHEMA_VERSION, 'status': 'error',
            'input': {'path': str(request.source.resolve()) if isinstance(request.source, Path) else None},
            'measurements': None, 'predictions': None, 'provenance': {'task': request.task},
            'diagnostics': {}, 'elapsed_seconds': 0.0, 'error': None}


def strict_json_loads(data):
    def reject(value):
        raise ValueError(f'Non-finite JSON number: {value}')
    return json.loads(data, parse_constant=reject)


def bounded_json(value):
    """Serialize a complete record, including its newline, within the wire budget."""
    try:
        text = json.dumps(value, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise AnalyzerError('invalid_response', 'Result contains invalid JSON values') from exc
    if len(text.encode('utf-8')) + 1 > MAX_EVENT_BYTES:
        raise AnalyzerError('output_too_large', 'Result exceeds the 1 MiB output limit')
    return text


def bounded_result(result):
    """Reserve the event envelope even for API/JSON users; never truncate results."""
    try:
        bounded_json({'protocol_version': PROTOCOL_VERSION, 'type': 'result', 'result': result})
        return result
    except AnalyzerError as exc:
        return {'schema_version': SCHEMA_VERSION, 'status': 'error',
                'input': {'path': None}, 'measurements': None, 'predictions': None,
                'provenance': {}, 'diagnostics': {}, 'elapsed_seconds': 0.0,
                'error': {'code': exc.code, 'message': str(exc)}}


def validate_result(result):
    """Validate untrusted process output before a consumer persists it."""
    from .profiles.wallpaper import validate_description
    def invalid():
        raise AnalyzerError('protocol_error', 'Invalid analyzer result contract')
    if not isinstance(result, dict) or type(result.get('schema_version')) is not int or result['schema_version'] != SCHEMA_VERSION:
        invalid()
    if not {'input', 'measurements', 'predictions', 'provenance', 'diagnostics', 'elapsed_seconds', 'error'}.issubset(result):
        invalid()
    if result.get('status') not in ('ok', 'error'):
        invalid()
    for field in ('input', 'provenance', 'diagnostics'):
        if not isinstance(result.get(field), dict):
            invalid()
    elapsed = result.get('elapsed_seconds')
    if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
        invalid()
    if result.get('measurements') is not None and not isinstance(result['measurements'], dict):
        invalid()
    if result['status'] == 'error':
        error = result.get('error')
        if not isinstance(error, dict) or not all(isinstance(error.get(k), str) and error[k] for k in ('code', 'message')):
            invalid()
    else:
        data = result['input']
        if (not isinstance(data.get('sha256'), str) or len(data['sha256']) != 64
                or any(c not in '0123456789abcdef' for c in data['sha256'])
                or any(type(data.get(k)) is not int or data[k] < 1 for k in ('width', 'height'))):
            invalid()
        if result.get('error') is not None:
            invalid()
        if result['provenance'].get('task') == 'describe':
            try:
                validate_description(result.get('predictions'))
            except (ValueError, TypeError):
                invalid()
        elif result['provenance'].get('task') != 'inspect' or result['predictions'] is not None:
            invalid()
    return result
