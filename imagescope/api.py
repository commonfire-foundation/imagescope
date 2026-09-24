"""One analysis operation shared by every frontend."""
import time
from typing import Protocol

from .contracts import AnalysisRequest, AnalyzerError, empty_result, bounded_result
from .images import prepare_image, white_composite
from .measurements import measure, MEASUREMENTS_VERSION
from .profiles import get_profile


class Backend(Protocol):
    def check_model(self, model): ...
    def describe(self, image, model, preview_size, *, profile): ...


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
        profile = get_profile(request.profile)
        result['provenance']['preprocessing'] = {
            'version': 5 if request.region is not None else (3 if request.color_policy == 'legacy-v1' else 4),
            'orientation': 'exif', 'alpha_background': '#ffffff', 'frame': 0,
            'color_management': {'policy': request.color_policy, 'assume_srgb': request.assume_srgb}}
        if request.region is not None:
            result['provenance']['preprocessing']['region'] = {
                'version': 1, 'bounds': list(request.region),
                'coordinate_space': 'exif-oriented-original-pixel-edges'}
        progress('preparing', 'Preparing image region' if request.region is not None else 'Preparing image')
        metadata, image = prepare_image(request.source, color_policy=request.color_policy,
                                        assume_srgb=request.assume_srgb, region=request.region)
        result['provenance']['preprocessing'].update(metadata.pop('preprocessing'))
        result['input'].update(metadata)
        if request.measurements or request.task == 'inspect':
            result['measurements'] = measure(image, request.palette_size, histograms=request.histograms)
            result['provenance']['measurements_version'] = MEASUREMENTS_VERSION
            result['provenance']['measurement_settings'] = {'palette_size': request.palette_size}
            if request.histograms:
                from .histograms import HISTOGRAM_MEASUREMENTS_VERSION
                result['provenance']['measurements_version'] = HISTOGRAM_MEASUREMENTS_VERSION
                result['provenance']['measurement_settings']['histograms'] = True
        if request.task == 'describe':
            progress('checking', 'Checking local model')
            if backend is None:
                from .backends.ollama import OllamaBackend
                backend = OllamaBackend(request.endpoint, request.timeout - (time.monotonic() - started), request.keep_alive)
            identity, version = backend.check_model(request.model)
            result['provenance'].update(backend=getattr(backend, 'name', type(backend).__name__), model=identity, ollama_version=version,
                profile=profile.name, profile_version=profile.version, prompt=profile.prompt,
                preprocessing={**result['provenance']['preprocessing'],
                               'preview_format': 'jpeg', 'jpeg_quality': 90},
                settings=backend.settings(request.preview_size, profile=profile.name) if hasattr(backend, 'settings')
                         else {'preview_size': request.preview_size})
            progress('generating', 'Generating image description')
            predictions, diagnostics = backend.describe(
                white_composite(image), request.model, request.preview_size, profile=profile.name)
            result['diagnostics'] = diagnostics
            try:
                profile.validate(predictions)
            except (ValueError, TypeError) as exc:
                raise AnalyzerError('invalid_response', str(exc)) from exc
            result['predictions'] = profile.clean(predictions)
        if time.monotonic() - started > request.timeout:
            raise AnalyzerError('timeout', 'Analyzer request timed out')
        result.update(status='ok', error=None)
    except AnalyzerError as exc:
        result['error'] = {'code': exc.code, 'message': str(exc)}
        result['diagnostics'].update(exc.details)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result['error'] = {'code': 'analysis_failed', 'message': str(exc)}
    result['elapsed_seconds'] = round(time.monotonic() - started, 3)
    return bounded_result(result)
