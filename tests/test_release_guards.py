import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image

from imagescope import AnalysisRequest, analyze
from imagescope.backends.ollama import OllamaBackend
from imagescope.contracts import (AnalyzerError, DEFAULT_MODEL, MAX_EVENT_BYTES,
                                 bounded_json, bounded_result, validate_result)
from imagescope.profiles.wallpaper import validate_description

ROOT = Path(__file__).resolve().parents[1]
VISION = {'caption': 'Red', 'subjects': [], 'medium': 'abstract', 'mood': [],
          'lighting': [], 'composition': [], 'tags': ['red'],
          'text_present': False, 'watermark_present': False}


@contextlib.contextmanager
def server(mode):
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            paths.append(self.path)
            if mode == 'redirect':
                self.send_response(307)
                self.send_header('Location', '/destination')
                self.end_headers()
                return
            if mode == 'oversized':
                body = b'x' * (2 * 1024 * 1024 + 1)
            elif self.path.endswith('tags'):
                model = {'name': DEFAULT_MODEL}
                if mode == 'inventory':
                    model['padding'] = 'x' * MAX_EVENT_BYTES
                body = json.dumps({'models': [model]}).encode()
            else:
                body = b'{"version":"test","models":[]}'
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            value = dict(VISION)
            if mode == 'caption':
                value['caption'] = 'x' * 1001
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({'message': {'content': json.dumps(value)}}).encode())

    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{http.server_port}/api/', paths
    finally:
        http.shutdown()
        http.server_close()
        thread.join()


class ReleaseGuardTests(unittest.TestCase):
    def test_prediction_string_limits(self):
        value = {**VISION, 'caption': 'x' * 1000, 'tags': ['x' * 128]}
        self.assertEqual(validate_description(value), value)
        for change in ({'caption': 'x' * 1001}, {'tags': ['x' * 129]}, {'subjects': ['x' * 129]}):
            with self.assertRaises(ValueError):
                validate_description({**VISION, **change})

    def test_serialized_byte_limit_includes_escaping_and_newline(self):
        bounded_json('x' * (MAX_EVENT_BYTES - 3))
        with self.assertRaises(AnalyzerError):
            bounded_json('x' * (MAX_EVENT_BYTES - 2))
        with self.assertRaises(AnalyzerError):
            bounded_json('⠋' * (MAX_EVENT_BYTES // 6 + 1))
        result = bounded_result({'diagnostics': {'oversized': 'x' * MAX_EVENT_BYTES}})
        validate_result(result)
        self.assertEqual(result['error']['code'], 'output_too_large')
        self.assertLess(len(bounded_json(result)), 1024)

    def test_api_result_bounds_include_backend_provenance(self):
        class Backend:
            def check_model(self, model):
                return {'name': model, 'padding': 'x' * MAX_EVENT_BYTES}, {}

            def describe(self, *args):
                return dict(VISION), {}

        data = io.BytesIO()
        Image.new('RGB', (8, 8), 'red').save(data, 'PNG')
        result = analyze(AnalysisRequest(data.getvalue()), backend=Backend())
        self.assertEqual(result['error']['code'], 'output_too_large')

    def test_malformed_endpoints_in_doctor_and_describe(self):
        for endpoint in ('http://[', 'http://localhost:bad', 'http://localhost:65536',
                         'http://localhost:0', 'http://user:pass@localhost', 'http://local host'):
            for command in ('doctor', 'describe'):
                for flags in ([], ['--json']):
                    args = [command] + (['missing.png'] if command == 'describe' else [])
                    p = subprocess.run([sys.executable, '-m', 'imagescope', *args,
                                        '--endpoint', endpoint, *flags], cwd=ROOT,
                                       capture_output=True, timeout=10)
                    self.assertEqual(p.returncode, 2, p.stderr)
                    self.assertNotIn(b'Traceback', p.stderr)
                    if flags:
                        self.assertEqual(json.loads(p.stdout)['error']['code'], 'invalid_request')
                    else:
                        self.assertEqual(p.stdout, b'')
                        self.assertIn(b'invalid_request', p.stderr)

    def test_redirects_and_oversized_http_responses(self):
        for mode, code in [('redirect', 'backend_error'), ('oversized', 'invalid_response')]:
            with server(mode) as (endpoint, paths):
                with self.assertRaises(AnalyzerError) as raised:
                    OllamaBackend(endpoint).request('tags')
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(paths, ['/api/tags'])

    def test_oversized_predictions_and_metadata_fail_cleanly_in_all_modes(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / 'image.png'
            Image.new('RGB', (8, 8), 'red').save(path)
            for mode, code in [('caption', 'invalid_response'), ('inventory', 'output_too_large')]:
                with server(mode) as (endpoint, _):
                    for flags in ([], ['--json'], ['--events=jsonl']):
                        p = subprocess.run([sys.executable, '-m', 'imagescope', 'describe', str(path),
                                            '--endpoint', endpoint, *flags], cwd=ROOT,
                                           capture_output=True, timeout=10)
                        self.assertEqual(p.returncode, 1, p.stderr)
                        self.assertNotIn(b'Traceback', p.stderr)
                        if not flags:
                            self.assertEqual(p.stdout, b'')
                            self.assertIn(code.encode(), p.stderr)
                            continue
                        self.assertEqual(p.stderr, b'')
                        lines = p.stdout.splitlines(keepends=True)
                        self.assertTrue(all(len(line) <= MAX_EVENT_BYTES for line in lines))
                        if flags == ['--json']:
                            result = json.loads(p.stdout)
                        else:
                            events = [json.loads(line) for line in lines]
                            self.assertEqual(events[0]['type'], 'hello')
                            self.assertEqual([e['type'] for e in events].count('result'), 1)
                            self.assertEqual(events[-1]['type'], 'result')
                            result = events[-1]['result']
                        self.assertEqual(result['error']['code'], code)
                    if mode == 'inventory':
                        p = subprocess.run([sys.executable, '-m', 'imagescope', 'doctor',
                                            '--endpoint', endpoint, '--json'], cwd=ROOT,
                                           capture_output=True, timeout=10)
                        self.assertEqual(p.returncode, 1)
                        self.assertEqual(json.loads(p.stdout)['error']['code'], 'output_too_large')
