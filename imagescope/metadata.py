"""Public, model-independent metadata inspection; never prepares a raster."""
from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import subprocess
import sys
import time

from .contracts import (AnalyzerError, DECODE_TIMEOUT, MAX_EVENT_BYTES,
                        MAX_SOURCE_PIXELS, bounded_json, strict_json_loads)
from .images import read_source

METADATA_VERSION = 1


@dataclass(frozen=True)
class MetadataRequest:
    source: Path | bytes
    timeout: float = 10

    def validate(self):
        if not isinstance(self.source, (Path, bytes)):
            raise AnalyzerError('invalid_request', 'source must be a pathlib.Path or image bytes')
        if (type(self.timeout) not in (int, float) or not math.isfinite(self.timeout)
                or not 0 < self.timeout <= DECODE_TIMEOUT):
            raise AnalyzerError('invalid_request', f'timeout must be between 0 and {DECODE_TIMEOUT} seconds')


def inspect_metadata(request: MetadataRequest):
    """Return metadata-v1, including bounded warnings, without inference or pixels.

    Input bytes are snapshotted and hashed. Timeout covers elapsed input reading
    and worker execution; ordinary file reads are not preempted by this API.
    """
    started = time.monotonic()
    result = {'metadata_version': METADATA_VERSION, 'status': 'error',
              'input': {}, 'metadata': None, 'warnings': [], 'error': None,
              'elapsed_seconds': 0.0}
    try:
        request.validate()
        data = read_source(request.source)
        result['input'] = {'sha256': hashlib.sha256(data).hexdigest(), 'size_bytes': len(data)}
        remaining = request.timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise AnalyzerError('metadata_timeout', 'Metadata inspection timed out')
        try:
            process = subprocess.run(
                [sys.executable, '-m', 'imagescope.decode_worker',
                 str(MAX_SOURCE_PIXELS), str(os.getpid()), 'metadata'],
                input=data, capture_output=True, timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            raise AnalyzerError('metadata_timeout', 'Metadata inspection timed out') from exc
        if process.returncode < 0:
            raise AnalyzerError('metadata_resource_limit', 'Metadata worker stopped at its resource limit or crashed')
        if len(process.stdout) > MAX_EVENT_BYTES:
            raise AnalyzerError('metadata_resource_limit', 'Metadata worker exceeded its output budget')
        try:
            payload = strict_json_loads(process.stdout)
            if not isinstance(payload, dict):
                raise ValueError('Expected object')
            if 'error' in payload:
                raise AnalyzerError(payload['error']['code'], payload['error']['message'])
            if (process.returncode or not isinstance(payload.get('metadata'), dict)
                    or not isinstance(payload.get('warnings'), list)):
                raise ValueError('Invalid metadata response')
        except (ValueError, KeyError, TypeError) as exc:
            raise AnalyzerError('metadata_failed', 'Metadata worker returned an invalid response') from exc
        result.update(metadata=payload['metadata'], warnings=payload['warnings'], status='ok')
        bounded_json(result)
    except AnalyzerError as exc:
        result.update(status='error', metadata=None, warnings=[],
                      error={'code': exc.code, 'message': str(exc)[:500]})
    result['elapsed_seconds'] = round(time.monotonic() - started, 3)
    return result
