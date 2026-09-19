import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from imagescope import AnalysisRequest, AnalyzerError, analyze
from imagescope.contracts import validate_result, strict_json_loads
from imagescope.profiles.wallpaper import PROMPT_VERSION, VISION_PROMPT

VISION = {'caption': 'Red', 'subjects': [], 'medium': 'abstract', 'mood': [],
          'lighting': [], 'composition': [], 'tags': ['red'],
          'text_present': False, 'watermark_present': False}


class FakeBackend:
    def check_model(self, model):
        return {'name': model, 'digest': 'test-digest'}, {'version': 'test'}

    def describe(self, image, model, preview_size):
        return dict(VISION), {}


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'red.png'
        Image.new('RGB', (120, 60), 'red').save(self.path)

    def test_path_and_bytes_match_without_modifying_original(self):
        data = self.path.read_bytes()
        a = analyze(AnalysisRequest(self.path), backend=FakeBackend())
        b = analyze(AnalysisRequest(data), backend=FakeBackend())
        validate_result(a)
        validate_result(b)
        self.assertEqual(a['predictions'], b['predictions'])
        self.assertEqual(a['input']['sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(a['input']['sha256'], b['input']['sha256'])
        self.assertIsNone(b['input']['path'])
        self.assertIsNone(a['measurements'])
        self.assertEqual(a['provenance']['profile_version'], PROMPT_VERSION)
        self.assertEqual(a['provenance']['prompt'], VISION_PROMPT)
        self.assertEqual(self.path.read_bytes(), data)

    def test_inspect_never_connects_to_backend(self):
        with patch('imagescope.backends.ollama.OllamaBackend', side_effect=AssertionError('Network')):
            result = analyze(AnalysisRequest(self.path, task='inspect'))
        self.assertEqual(result['status'], 'ok')
        self.assertIsNone(result['predictions'])
        self.assertEqual(result['measurements']['palette'][0]['hex'], '#ff0000')
        self.assertAlmostEqual(result['measurements']['mean_luminance'], 0.2126)

    def test_partial_measurements_and_stable_error(self):
        backend = FakeBackend()
        backend.describe = lambda *args: (_ for _ in ()).throw(AnalyzerError('invalid_response', 'bad JSON', {'reason': 'length'}))
        result = analyze(AnalysisRequest(self.path, measurements=True), backend=backend)
        validate_result(result)
        self.assertEqual(result['error']['code'], 'invalid_response')
        self.assertTrue(result['measurements'])
        self.assertIsNone(result['predictions'])
        self.assertEqual(result['diagnostics']['reason'], 'length')

    def test_limits_and_invalid_input(self):
        for source, code in [(b'not an image', 'invalid_input'), (self.path.parent / 'missing.png', 'invalid_input')]:
            result = analyze(AnalysisRequest(source, task='inspect'))
            self.assertEqual(result['error']['code'], code)
        with patch('imagescope.images.MAX_INPUT_BYTES', 4):
            self.assertEqual(analyze(AnalysisRequest(self.path, task='inspect'))['error']['code'], 'input_too_large')
        with patch('imagescope.images.MAX_SOURCE_PIXELS', 10):
            self.assertEqual(analyze(AnalysisRequest(self.path, task='inspect'))['error']['code'], 'image_too_large')

    def test_untrusted_results_and_diagnostics(self):
        result = analyze(AnalysisRequest(self.path), backend=FakeBackend())
        result['diagnostics']['vision'] = {'caption': 'unvalidated replacement'}
        self.assertEqual(result['predictions'], VISION)
        validate_result(result)
        with self.assertRaises(ValueError):
            strict_json_loads('{"number":NaN}')
        result['elapsed_seconds'] = float('inf')
        with self.assertRaises(AnalyzerError):
            validate_result(result)

    def test_progress_and_invalid_request(self):
        stages = []
        result = analyze(AnalysisRequest(self.path), backend=FakeBackend(), on_progress=lambda stage,label: stages.append(stage))
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(stages, ['checking', 'preparing', 'generating'])
        for options in ({'preview_size': 5}, {'timeout': float('nan')}, {'keep_alive': -1}, {'task': 'ocr'}):
            self.assertEqual(analyze(AnalysisRequest(self.path, **options))['error']['code'], 'invalid_request')
