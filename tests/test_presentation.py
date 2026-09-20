import io
import os
import threading
import unittest
from unittest.mock import patch

from imagescope.presentation import Progress, plain, show_error, show_result


class Terminal(io.StringIO):
    def __init__(self):
        super().__init__()
        self.frames = threading.Event()
        self.count = 0

    def isatty(self):
        return True

    def flush(self):
        self.count += 1
        if self.count >= 3:
            self.frames.set()


class PresentationTests(unittest.TestCase):
    def test_spinner_moves_without_progress_callbacks_and_cleans_up(self):
        terminal = Terminal()
        with patch.dict(os.environ, {'TERM': 'xterm', 'NO_COLOR': '1'}):
            progress = Progress(terminal)
            try:
                progress.update('Generating image description')
                self.assertTrue(terminal.frames.wait(2), 'Spinner stalled during work')
            finally:
                progress.stop()
        self.assertFalse(progress.thread.is_alive())
        text = terminal.getvalue()
        for frame in '⠋⠙⠹':
            self.assertIn('\r' + frame + ' Generating image description', text)
        self.assertTrue(text.endswith('\r' + ' ' * 79 + '\r'))
        self.assertNotIn('\r\r', text, 'Do not park the block cursor over the spinner between frames')
        self.assertNotIn('\x1b', text)

    def test_redirected_and_dumb_terminals_are_static(self):
        for terminal in (io.StringIO(), Terminal()):
            with patch.dict(os.environ, {'TERM': 'dumb'}):
                progress = Progress(terminal)
                progress.update('Preparing image')
                progress.update('Generating image description')
                progress.stop()
            self.assertIsNone(progress.thread)
            self.assertEqual(terminal.getvalue(), 'Preparing image\nGenerating image description\n')

    def test_machine_mode_is_silent_even_on_terminal(self):
        terminal = Terminal()
        progress = Progress(terminal, enabled=False)
        progress.update('Reading image')
        progress.stop()
        self.assertEqual(terminal.getvalue(), '')
        self.assertIsNone(progress.thread)

    def test_spinner_adapts_to_current_terminal_width(self):
        terminal = Terminal()
        with patch.dict(os.environ, {'TERM': 'xterm'}), patch('imagescope.presentation.columns', return_value=12):
            progress = Progress(terminal)
            try:
                progress.update('Generating image description')
                self.assertTrue(terminal.frames.wait(2))
            finally:
                progress.stop()
        self.assertTrue(all(len(line) <= 12 for line in terminal.getvalue().split('\r')))

    def test_output_wraps_and_sanitizes_untrusted_content(self):
        stream = io.StringIO()
        result = {'input': {'width': 120, 'height': 60, 'format': 'PNG'},
                  'predictions': {'caption': 'A red landscape with a very long description.\x1b\n',
                                  'subjects': ['landscape'], 'medium': 'illustration', 'mood': [],
                                  'lighting': [], 'composition': [], 'tags': ['red', 'wide'],
                                  'text_present': True, 'watermark_present': False},
                  'measurements': None, 'elapsed_seconds': 1.25, 'provenance': {'profile': 'wallpaper'}}
        with patch('imagescope.presentation.columns', return_value=32):
            show_result(result, stream)
        text = stream.getvalue()
        self.assertIn('Tags: red, wide', text)
        self.assertIn('Detected: text', text)
        self.assertNotIn('\x1b', text)
        self.assertTrue(all(len(line) <= 32 for line in text.splitlines()))
        self.assertEqual(plain('bad\r\x1bname'), 'bad name')

    def test_error_keeps_code_and_actionable_message(self):
        stream = io.StringIO()
        show_error('model_missing', 'Install it explicitly with: ollama pull qwen3-vl:4b', stream)
        self.assertIn('Error · model_missing', stream.getvalue())
        self.assertIn('ollama pull qwen3-vl:4b', stream.getvalue())
