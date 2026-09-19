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

    def server(self, missing=False, malformed=False, delay=0):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                body = {'models': [] if missing else [{'name':DEFAULT_MODEL,'digest':'test'}]} if self.path.endswith('tags') else {'version':'test'}
                self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(body).encode())
            def do_POST(self):
                if delay:
                    import time
                    time.sleep(delay)
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

    def test_human_output_and_doctor(self):
        p = self.run_cli('describe', self.path, '--endpoint', self.server(), '--measurements')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(b'Tags: red', p.stdout)
        self.assertIn(b'Measurements', p.stdout)
        self.assertIn(b'Done in', p.stdout)
        self.assertNotIn(b'\r', p.stderr)
        self.assertNotIn(b'\x1b', p.stdout + p.stderr)
        doctor = self.run_cli('doctor', '--endpoint', self.server())
        self.assertEqual(doctor.returncode, 0, doctor.stderr)
        self.assertIn(b'Ollama', doctor.stdout)
        self.assertIn(b'Installed:', doctor.stdout)
        failed = self.run_cli('describe', self.path, '--endpoint', self.server(missing=True))
        self.assertEqual(failed.returncode, 1)
        self.assertEqual(failed.stdout, b'')
        self.assertIn(b'model_missing', failed.stderr)

    def test_real_terminal_spinner_and_cleanup(self):
        import os
        import pty
        import select
        import time
        # Exercise blocking HTTP, failure, timeout, SIGTERM, and narrow-terminal Ctrl-C.
        for mode in ('success', 'failure', 'timeout', 'cancel', 'interrupt'):
            with self.subTest(mode=mode):
                master, slave = pty.openpty()
                import fcntl
                import struct
                import termios
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 32 if mode == 'interrupt' else 80, 0, 0))
                args = (['describe', str(self.path), '--endpoint', self.server(delay=0.7, malformed=mode == 'failure')]
                        if mode in ('success', 'failure') else
                        ['inspect', '--stdin', '--timeout', '0.7' if mode == 'timeout' else '10'])
                p = subprocess.Popen([sys.executable, '-m', 'imagescope', *args], cwd=ROOT,
                                     env={**os.environ, 'TERM': 'xterm'}, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=slave)
                try:
                    output = b''
                    cancelled = False
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        if select.select([master], [], [], 0.1)[0]:
                            output += os.read(master, 65536)
                        if mode in ('cancel', 'interrupt') and not cancelled and output.count(b'Reading image from stdin') >= 3 and p.poll() is None:
                            import signal
                            p.send_signal(signal.SIGINT if mode == 'interrupt' else signal.SIGTERM)
                            cancelled = True
                        if p.poll() is not None:
                            while select.select([master], [], [], 0)[0]:
                                output += os.read(master, 65536)
                            break
                    else:
                        self.fail('Terminal request did not finish')
                    expected = {'success': 0, 'failure': 1, 'timeout': 1, 'cancel': 130, 'interrupt': 130}[mode]
                    self.assertEqual(p.returncode, expected, output)
                    label = b'Generating image description' if mode in ('success', 'failure') else b'Reading image from stdin'
                    self.assertGreaterEqual(output.count(label), 3, output)
                    stdout = p.stdout.read()
                    if mode == 'success':
                        self.assertIn(b'Tags: red', stdout)
                        self.assertTrue(output.endswith(b'\r' + b' ' * 79 + b'\r'), output)
                    else:
                        self.assertEqual(stdout, b'')
                        self.assertIn({'failure': b'invalid_response', 'timeout': b'timeout', 'cancel': b'cancelled', 'interrupt': b'cancelled'}[mode], output)
                        self.assertNotIn(label, output.split(b'Error')[-1] if mode not in ('cancel', 'interrupt') else output.split(b'Cancelled')[-1])
                finally:
                    if p.poll() is None:
                        p.kill()
                    p.wait()
                    p.stdin.close()
                    p.stdout.close()
                    os.close(master)
                    os.close(slave)

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
