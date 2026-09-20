import copy
import io
import json
import unittest
from unittest.mock import Mock

from PIL import Image

from imagescope import AnalysisRequest, AnalyzerError, analyze
from imagescope.backends.ollama import OllamaBackend
from imagescope.contracts import validate_result
from imagescope.profiles import PROFILES, get_profile

WALLPAPER = {'caption': 'Red', 'subjects': [], 'medium': 'abstract', 'mood': [],
             'lighting': [], 'composition': [], 'tags': ['red'],
             'text_present': False, 'watermark_present': False}
GENERAL = {'summary': 'A red field.', 'subjects': [], 'text_present': False}


class ProfileTests(unittest.TestCase):
    def setUp(self):
        encoded = io.BytesIO()
        Image.new('RGB', (12, 6), 'red').save(encoded, 'PNG')
        self.source = encoded.getvalue()

    def backend(self, output, *, continuation=False):
        def transport(endpoint, payload):
            if endpoint == 'tags':
                return {'models': [{'name': 'test'}]}
            if endpoint == 'version':
                return {'version': 'test'}
            self.payload = payload
            content = json.dumps(output)
            if continuation:
                content = content[len(payload['messages'][1]['content']):]
            return {'message': {'content': content}, 'done_reason': 'stop'}
        return OllamaBackend(transport=transport)

    def test_each_profile_drives_request_validation_and_provenance(self):
        for name, output in [('wallpaper', WALLPAPER), ('general', GENERAL)]:
            for continuation in (False, True):
                with self.subTest(profile=name, continuation=continuation):
                    result = analyze(AnalysisRequest(self.source, model='test', profile=name, measurements=True),
                                     backend=self.backend(output, continuation=continuation))
                    self.assertEqual(result['status'], 'ok', result['error'])
                    validate_result(result)
                    profile = get_profile(name)
                    self.assertEqual(self.payload['format'], profile.schema)
                    self.assertEqual(self.payload['messages'][0]['content'], profile.prompt)
                    self.assertEqual(self.payload['messages'][1]['content'], profile.json_prefix)
                    self.assertEqual(result['predictions'], output)
                    for key, value in [('profile', name), ('profile_version', profile.version), ('prompt', profile.prompt)]:
                        self.assertEqual(result['provenance'][key], value)
                    self.assertEqual(result['provenance']['settings']['json_prefix'], profile.json_prefix)
                    self.assertTrue(result['measurements'])

    def test_unknown_profiles_rejected_before_input_or_backend_work(self):
        backend = Mock()
        for name in ('missing', '', None, [], 1):
            result = analyze(AnalysisRequest(b'invalid', profile=name), backend=backend)
            self.assertEqual(result['error']['code'], 'invalid_request')
        backend.check_model.assert_not_called()
        backend.describe.assert_not_called()

    def test_cross_profile_responses_fail_in_backend_and_custom_backend(self):
        for name, wrong in [('general', WALLPAPER), ('wallpaper', GENERAL)]:
            for backend in (self.backend(wrong), Mock()):
                if isinstance(backend, Mock):
                    backend.name = 'fake'
                    backend.check_model.return_value = ({'name': 'test'}, {})
                    backend.settings.return_value = {}
                    backend.describe.return_value = (wrong, {})
                result = analyze(AnalysisRequest(self.source, model='test', profile=name, measurements=True), backend=backend)
                self.assertEqual(result['error']['code'], 'invalid_response')
                self.assertIsNone(result['predictions'])
                self.assertTrue(result['measurements'])
                validate_result(result)

    def test_result_validator_rejects_unknown_mismatched_and_stale_profiles(self):
        result = analyze(AnalysisRequest(self.source, model='test', profile='general'), backend=self.backend(GENERAL))
        for change in ({'profile': 'missing'}, {'profile_version': 'general-v0'},
                       {'prompt': 'different'}, {'profile': 'wallpaper'}):
            mutated = copy.deepcopy(result)
            mutated['provenance'].update(change)
            with self.assertRaises(AnalyzerError) as caught:
                validate_result(mutated)
            self.assertEqual(caught.exception.code, 'protocol_error')
        mutated = copy.deepcopy(result)
        mutated['predictions'] = WALLPAPER
        with self.assertRaises(AnalyzerError):
            validate_result(mutated)

    def test_general_limits_normalization_and_empty_subjects(self):
        profile = get_profile('general')
        value = {**GENERAL, 'summary': '\u2003 A red field. \n', 'subjects': [' Red  square ', 'red square', '']}
        self.assertEqual(profile.clean(profile.validate(value)),
                         {**GENERAL, 'subjects': ['red square']})
        for change in ({'summary': ''}, {'summary': '\u2003\u00a0'}, {'summary': 'x' * 1001},
                       {'subjects': ['x'] * 13}, {'subjects': ['x' * 129]},
                       {'subjects': [1]}, {'text_present': 1}, {'caption': 'wrong'}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    profile.validate({**GENERAL, **change})
                result = analyze(AnalysisRequest(self.source, model='test', profile='general'),
                                 backend=self.backend({**GENERAL, **change}))
                self.assertEqual(result['error']['code'], 'invalid_response')
        self.assertEqual(profile.validate(GENERAL), GENERAL)
        self.assertEqual(set(PROFILES), {'general', 'wallpaper'})
