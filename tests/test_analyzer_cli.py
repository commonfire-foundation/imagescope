import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image
from imagescope.contracts import DEFAULT_MODEL

ROOT = Path(__file__).resolve().parents[1]
VISION = {'caption':'Red', 'subjects':[], 'medium':'abstract', 'mood':[], 'lighting':[],
          'composition':[], 'tags':['red'], 'text_present':False, 'watermark_present':False}


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'image.png'
        Image.new('RGB', (120, 60), 'red').save(self.path)

    def run_cli(self, *args, data=None):
        return subprocess.run([sys.executable, '-m', 'imagescope', *map(str,args)],
                              cwd=ROOT, input=data, capture_output=True, timeout=10)

    def server(self, missing=False, malformed=False):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                body = {'models': [] if missing else [{'name':DEFAULT_MODEL,'digest':'test'}]} if self.path.endswith('tags') else {'version':'test'}
                self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(body).encode())
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                body = {'message':{'content':'broken' if malformed else json.dumps(VISION)},'done_reason':'stop'}
                self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(body).encode())
        server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def close(): server.shutdown(); server.server_close(); thread.join()
        self.addCleanup(close)
        return f'http://127.0.0.1:{server.server_port}/api/'

    def test_file_stdin_and_one_json_result(self):
        a = self.run_cli('inspect', self.path, '--json')
        b = self.run_cli('inspect', '--stdin', '--json', data=self.path.read_bytes())
        self.assertEqual((a.returncode,b.returncode), (0,0))
        self.assertEqual(a.stderr, b'')
        self.assertEqual(json.loads(a.stdout)['measurements'], json.loads(b.stdout)['measurements'])
        self.assertEqual(len(a.stdout.splitlines()), 1)

    def test_events_and_real_http_transport(self):
        p = self.run_cli('describe', self.path, '--endpoint', self.server(), '--events=jsonl')
        self.assertEqual(p.returncode,0,p.stderr)
        events = [json.loads(line) for line in p.stdout.splitlines()]
        self.assertEqual([e['type'] for e in events], ['hello','progress','progress','progress','result'])
        self.assertTrue(all(e['protocol_version']==1 for e in events))
        self.assertEqual(events[-1]['result']['predictions'],VISION)

    def test_missing_model_and_invalid_response(self):
        for endpoint, code in [(self.server(missing=True),'model_missing'), (self.server(malformed=True),'invalid_response')]:
            p = self.run_cli('describe', self.path, '--endpoint', endpoint, '--json', '--measurements')
            result = json.loads(p.stdout)
            self.assertEqual(p.returncode,1)
            self.assertEqual(result['error']['code'],code)
            if code == 'invalid_response': self.assertTrue(result['measurements'])

    def test_backend_unavailable(self):
        import socket
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1', 0))
            endpoint = f'http://127.0.0.1:{reserved.getsockname()[1]}/api/'
            p = self.run_cli('describe', self.path, '--endpoint', endpoint, '--json')
        self.assertEqual(p.returncode, 1)
        self.assertEqual(json.loads(p.stdout)['error']['code'], 'backend_unavailable')

    def test_request_errors_and_incompatible_version(self):
        for args, code in [(('inspect','--json'),'invalid_request'),
                           (('inspect',str(self.path),'--json','--protocol-version','999'),'incompatible_protocol'),
                           (('inspect',str(self.path),'--json','--timeout','nan'),'invalid_request'),
                           (('inspect',str(self.path),'--json','--expect-profile-version','old'),'analyzer_changed')]:
            p = self.run_cli(*args)
            self.assertNotEqual(p.returncode,0)
            self.assertEqual(json.loads(p.stdout)['error']['code'],code)

    def test_stdin_deadline_and_cancellation(self):
        for cancel in (False,True):
            p = subprocess.Popen([sys.executable,'-m','imagescope','inspect','--stdin','--events=jsonl',
                                  '--timeout','0.2' if not cancel else '10'],cwd=ROOT,
                                 stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                self.assertEqual(json.loads(p.stdout.readline())['type'],'hello')
                if cancel:
                    # Wait for handlers: after hello, validate/install occurs before blocking read.
                    import time
                    time.sleep(0.1)
                    p.terminate()
                p.wait(timeout=5)  # Keep stdin open: timeout must work without EOF.
                records=[json.loads(line) for line in p.stdout.read().splitlines()]
                self.assertEqual(records[-1]['result']['error']['code'],'cancelled' if cancel else 'timeout')
            finally:
                if p.poll() is None: p.kill();p.wait()
                p.stdin.close();p.stdout.close();p.stderr.close()
