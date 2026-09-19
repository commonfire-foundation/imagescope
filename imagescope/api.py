"""One analysis operation shared by every frontend."""
import time
from typing import Protocol

from .contracts import AnalysisRequest, AnalyzerError, empty_result
from .images import prepare_image
from .measurements import measure
from .profiles.wallpaper import PROMPT_VERSION, VISION_PROMPT


class Backend(Protocol):
    def check_model(self, model): ...
    def describe(self, image, model, preview_size): ...


def analyze(request: AnalysisRequest, *, backend: Backend | None = None, on_progress=None):
    """Return a v1 result, including partial measurements on inference failure.

    Progress callbacks receive (stage, label); they do not own result persistence.
    Expected input/backend errors become structured results. No retries/downloads.
    """
    started = time.monotonic()
    result = empty_result(request)

    def progress(stage, label):
        if time.monotonic() - started > request.timeout:
            raise AnalyzerError('timeout', 'Analyzer request timed out')
        if on_progress:
            on_progress(stage, label)

    try:
        request.validate()
        result['provenance']['preprocessing'] = {'version': 2, 'orientation': 'exif',
                                                'alpha_background': '#ffffff', 'frame': 0}
        if request.task == 'describe':
            progress('checking', 'Checking local model')
            if backend is None:
                from .backends.ollama import OllamaBackend
                backend = OllamaBackend(request.endpoint, request.timeout, request.keep_alive)
            identity, version = backend.check_model(request.model)
            result['provenance'].update(backend=getattr(backend, 'name', type(backend).__name__), model=identity, ollama_version=version,
                profile=request.profile, profile_version=PROMPT_VERSION, prompt=VISION_PROMPT,
                preprocessing={'version': 2, 'orientation': 'exif', 'alpha_background': '#ffffff',
                               'frame': 0, 'preview_format': 'jpeg', 'jpeg_quality': 90},
                settings=backend.settings(request.preview_size) if hasattr(backend, 'settings')
                         else {'preview_size': request.preview_size})
        progress('preparing', 'Preparing image')
        metadata, image = prepare_image(request.source)
        result['provenance']['preprocessing'].update(metadata.pop('preprocessing'))
        result['input'].update(metadata)
        if request.measurements or request.task == 'inspect':
            result['measurements'] = measure(image)
            result['provenance']['measurements_version'] = 2
        if request.task == 'describe':
            progress('generating', 'Generating image description')
            result['predictions'], result['diagnostics'] = backend.describe(image, request.model, request.preview_size)
        if time.monotonic() - started > request.timeout:
            raise AnalyzerError('timeout', 'Analyzer request timed out')
        result.update(status='ok', error=None)
    except AnalyzerError as exc:
        result['error'] = {'code': exc.code, 'message': str(exc)}
        result['diagnostics'].update(exc.details)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result['error'] = {'code': 'analysis_failed', 'message': str(exc)}
    result['elapsed_seconds'] = round(time.monotonic() - started, 3)
    return result
