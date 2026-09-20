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

    def server(self, missing=False, malformed=False, delay=0, description=None):
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
                body = {'message':{'content':'broken' if malformed else json.dumps(VISION if description is None else description)},'done_reason':'stop'}
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

    def test_command_help_and_inspect_compatibility(self):
        inference = ['--profile', '--model', '--endpoint', '--preview-size', '--measurements', '--keep-alive']
        for command in ('inspect', 'describe'):
            help_result = self.run_cli(command, '--help')
            self.assertEqual(help_result.returncode, 0)
            text = help_result.stdout.decode()
            for flag in ('--stdin', '--json', '--events', '--timeout', '--palette-size', '--protocol-version'):
                self.assertIn(flag, text)
            for flag in inference:
                self.assertEqual(flag in text, command == 'describe', flag)
        old = self.run_cli('inspect', self.path, '--json', '--profile', 'wallpaper',
                           '--model', 'unused', '--endpoint', 'http://127.0.0.1:1/api/',
                           '--preview-size', '256', '--measurements', '--keep-alive', '0')
        plain = self.run_cli('inspect', self.path, '--json')
        self.assertEqual(old.returncode, 0, old.stderr)
        self.assertEqual(json.loads(old.stdout)['measurements'], json.loads(plain.stdout)['measurements'])
        self.assertNotEqual(self.run_cli(self.path).returncode, 0)

    def test_general_profile_discovery_guards_and_output_modes(self):
        import hashlib
        from imagescope.profiles import get_profile
        general = get_profile('general')
        output = {'summary': 'A red field.', 'subjects': [], 'text_present': False}
        endpoint = self.server(description=output)
        discovered = json.loads(self.run_cli('info', '--json').stdout)
        self.assertEqual(set(discovered['profiles']), {'wallpaper', 'general'})
        self.assertEqual(discovered['profiles']['general'], {'version': general.version, 'prompt': general.prompt})
        for flags in ([], ['--json'], ['--events=jsonl']):
            p = self.run_cli('describe', self.path, '--profile', 'general', '--endpoint', endpoint,
                             '--measurements', '--expect-profile-version', general.version,
                             '--expect-prompt-sha256', hashlib.sha256(general.prompt.encode()).hexdigest(), *flags)
            self.assertEqual(p.returncode, 0, p.stderr)
            if not flags:
                self.assertIn(b'A red field.', p.stdout)
                self.assertIn(b'Measurements', p.stdout)
                self.assertNotIn(b'Tags:', p.stdout)
            else:
                result = json.loads(p.stdout) if flags == ['--json'] else json.loads(p.stdout.splitlines()[-1])['result']
                self.assertEqual(result['predictions'], output)
                self.assertEqual(result['provenance']['profile'], 'general')
        for flag, value in [('--expect-profile-version', 'wallpaper-v3'),
                            ('--expect-prompt-sha256', hashlib.sha256(get_profile('wallpaper').prompt.encode()).hexdigest())]:
            p = self.run_cli('describe', self.path, '--profile', 'general', flag, value, '--json')
            self.assertEqual(json.loads(p.stdout)['error']['code'], 'analyzer_changed')
        unknown = self.run_cli('describe', self.path, '--profile', 'unknown', '--json')
        self.assertEqual(unknown.returncode, 2)
        self.assertEqual(unknown.stdout, b'')
        mismatch = self.run_cli('describe', self.path, '--profile', 'general', '--endpoint', self.server(), '--json')
        self.assertEqual(json.loads(mismatch.stdout)['error']['code'], 'invalid_response')

    def test_palette_sizes_and_formats_through_cli(self):
        gradient = Image.new('RGB', (64, 8))
        gradient.putdata([(x * 4, x * 4, x * 4) for _ in range(8) for x in range(64)])
        gradient.save(self.path)
        endpoint = self.server()
        for command in ('inspect', 'describe'):
            inference = ['--endpoint', endpoint, '--measurements'] if command == 'describe' else []
            for size in (5, 6, 8, 10, 16, 24, 32, 48, 64):
                output = self.run_cli(command, self.path, *inference, '--palette-size', size, '--json')
                self.assertEqual(output.returncode, 0, output.stderr)
                result = json.loads(output.stdout)
                self.assertEqual(len(result['measurements']['palette']), size)
                self.assertIsNotNone(result['measurements']['luminance_distribution']['percentiles'])
                self.assertEqual(result['measurements']['color_distribution']['near_neutral_fraction'], 1)
                self.assertEqual(len(result['measurements']['palette_distances']), size * (size - 1) // 2)
                self.assertEqual(result['provenance']['measurements_version'], 6)
                self.assertEqual(len(result['measurements']['local_detail']['intensity_std_3x3']), 3)
                self.assertEqual(result['measurements']['symmetry']['top_bottom'], 1)
                self.assertRegex(result['measurements']['phash64']['hash'], r'^[0-9a-f]{16}$')
                self.assertEqual(result['measurements']['transparency']['visible_bounds'], [0, 0, 64, 8])
                self.assertEqual(len(result['measurements']['spatial_color']['regions']), 9)
                self.assertEqual(result['provenance']['measurement_settings']['palette_size'], size)
                self.assertEqual(set(result['measurements']['palette'][0]), {'hex', 'rgb', 'hsl', 'fraction'})
            for size in (0, 65):
                output = self.run_cli(command, self.path, '--palette-size', size, '--json')
                self.assertEqual(output.returncode, 2)
                self.assertEqual(json.loads(output.stdout)['error']['code'], 'invalid_request')
        no_measurements = self.run_cli('describe', self.path, '--endpoint', endpoint, '--palette-size', 16, '--json')
        self.assertEqual(no_measurements.returncode, 0)
        self.assertIsNone(json.loads(no_measurements.stdout)['measurements'])

    def test_64_color_event_output_stays_bounded(self):
        from imagescope.contracts import MAX_EVENT_BYTES
        image = Image.new('RGBA', (64, 8))
        image.putdata([(x*4, x*4, x*4, 128) for _ in range(8) for x in range(64)])
        image.save(self.path)
        output = self.run_cli('inspect', self.path, '--palette-size', 64, '--events=jsonl')
        self.assertEqual(output.returncode, 0, output.stderr)
        lines = output.stdout.splitlines(keepends=True)
        self.assertTrue(all(len(line) <= MAX_EVENT_BYTES for line in lines))
        result = json.loads(lines[-1])['result']
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(len(result['measurements']['palette']), 64)
        self.assertEqual(len(result['measurements']['palette_distances']), 2016)

    def test_transparent_palette_in_human_and_event_output(self):
        Image.new('RGBA', (8, 8), (255, 0, 0, 0)).save(self.path)
        human = self.run_cli('inspect', self.path, '--palette-size', 24)
        self.assertEqual(human.returncode, 0, human.stderr)
        self.assertIn(b'Palette: none (no visible pixels)', human.stdout)
        self.assertIn(b'Visible-color statistics: none (no visible pixels)', human.stdout)
        for command in ('inspect', 'describe'):
            inference = ['--endpoint', self.server(missing=True), '--measurements'] if command == 'describe' else []
            output = self.run_cli(command, self.path, *inference, '--palette-size', 24, '--events=jsonl')
            self.assertEqual(output.returncode, 1 if command == 'describe' else 0)
            events = [json.loads(line) for line in output.stdout.splitlines()]
            self.assertEqual(events[0]['type'], 'hello')
            self.assertEqual(events[-1]['type'], 'result')
            result = events[-1]['result']
            self.assertEqual(result['measurements']['palette'], [])
            self.assertIsNone(result['measurements']['luminance_distribution']['percentiles'])
            self.assertIsNone(result['measurements']['color_distribution']['hue_histogram'])
            self.assertEqual(result['measurements']['palette_distances'], [])
            self.assertEqual(result['measurements']['transparency']['transparent_fraction'], 1)
            self.assertIsNone(result['measurements']['transparency']['visible_bounds'])
            self.assertTrue(all(r['mean_luminance'] is None for r in result['measurements']['spatial_color']['regions']))
            self.assertEqual(result['provenance']['measurement_settings']['palette_size'], 24)
            if command == 'describe':
                self.assertEqual(result['error']['code'], 'model_missing')

    def test_inspect_output_modes(self):
        human = self.run_cli('inspect', self.path)
        self.assertEqual(human.returncode, 0, human.stderr)
        self.assertIn(b'Measurements', human.stdout)
        self.assertIn(b'Visible luminance p05/50/95:', human.stdout)
        self.assertIn(b'Opacity shares:', human.stdout)
        self.assertIn(b'Transparency:', human.stdout)
        self.assertIn(b'Regional colors / visible luminance', human.stdout)
        self.assertIn(b'Intensity variation (3', human.stdout)
        self.assertIn(b'Mirror similarity:', human.stdout)
        self.assertIn(b'pHash:', human.stdout)
        events = self.run_cli('inspect', '--stdin', '--events=jsonl', '--timeout', '5',
                              '--protocol-version', '1', data=self.path.read_bytes())
        self.assertEqual(events.returncode, 0, events.stderr)
        records = [json.loads(line) for line in events.stdout.splitlines()]
        self.assertEqual([r['type'] for r in records], ['hello', 'progress', 'result'])
        self.assertEqual(records[1]['stage'], 'preparing')
        self.assertEqual(records[-1]['result']['status'], 'ok')

    def test_events_and_real_http_transport(self):
        p = self.run_cli('describe', self.path, '--endpoint', self.server(), '--events=jsonl')
        self.assertEqual(p.returncode,0,p.stderr)
        events = [json.loads(line) for line in p.stdout.splitlines()]
        self.assertEqual([e['type'] for e in events], ['hello','progress','progress','progress','result'])
        self.assertEqual([e['stage'] for e in events if e['type'] == 'progress'], ['preparing', 'checking', 'generating'])
        self.assertTrue(all(e['protocol_version']==1 for e in events))
        self.assertEqual(events[-1]['result']['predictions'],VISION)
        measured = self.run_cli('describe', self.path, '--endpoint', self.server(), '--measurements', '--events=jsonl')
        self.assertEqual(measured.returncode, 0)
        result = json.loads(measured.stdout.splitlines()[-1])['result']
        self.assertEqual(result['measurements']['luminance_distribution']['percentiles']['p50'], .2126)
        self.assertEqual(result['measurements']['color_distribution']['hue_histogram'][0], 1)
        self.assertEqual(result['measurements']['transparency']['transparent_fraction'], 0)
        self.assertEqual(result['measurements']['symmetry'], {'left_right': 1., 'top_bottom': 1.})
        self.assertEqual(result['measurements']['phash64']['hash'], '0000000000000000')
        self.assertEqual(result['measurements']['local_detail']['intensity_std_3x3'], [[0.] * 3] * 3)
        self.assertEqual(len(result['measurements']['spatial_color']['regions']), 9)

    def test_missing_model_and_invalid_response(self):
        for endpoint, code in [(self.server(missing=True),'model_missing'), (self.server(malformed=True),'invalid_response')]:
            p = self.run_cli('describe', self.path, '--endpoint', endpoint, '--json', '--measurements')
            result = json.loads(p.stdout)
            self.assertEqual(p.returncode,1)
            self.assertEqual(result['error']['code'],code)
            self.assertTrue(result['measurements'])
            self.assertTrue(result['input']['sha256'])

    def test_backend_unavailable(self):
        import socket
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1', 0))
            endpoint = f'http://127.0.0.1:{reserved.getsockname()[1]}/api/'
            p = self.run_cli('describe', self.path, '--endpoint', endpoint, '--json', '--measurements')
        self.assertEqual(p.returncode, 1)
        self.assertEqual(json.loads(p.stdout)['error']['code'], 'backend_unavailable')
        self.assertTrue(json.loads(p.stdout)['measurements']['luminance_distribution'])
        self.assertTrue(json.loads(p.stdout)['measurements']['color_distribution'])
        self.assertIn('palette_distances', json.loads(p.stdout)['measurements'])
        self.assertTrue(json.loads(p.stdout)['measurements']['transparency'])
        self.assertTrue(json.loads(p.stdout)['measurements']['spatial_color'])
        for field in ('local_detail', 'symmetry', 'phash64'):
            self.assertTrue(json.loads(p.stdout)['measurements'][field])

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
