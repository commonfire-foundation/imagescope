"""Human CLI presentation. Never used for machine-readable output."""
import os
import sys
import textwrap
import threading
import time
import unicodedata


def plain(value):
    """Keep filenames/model text from injecting terminal controls."""
    return ' '.join(''.join(' ' if unicodedata.category(c).startswith('C') else c
                            for c in str(value)).split())


def columns(stream):
    try:
        return max(1, os.get_terminal_size(stream.fileno()).columns - 1)
    except (AttributeError, OSError, ValueError):
        return 79


class Progress:
    """Animate independently of blocking work; degrade to one line per stage."""
    def __init__(self, stream=None, *, enabled=True):
        self.stream = sys.stderr if stream is None else stream
        self.enabled = enabled
        self.animated = enabled and self.stream.isatty() and os.environ.get('TERM') != 'dumb'
        self.label = ''
        self.started = time.monotonic()
        self.stopped = threading.Event()
        self.thread = None

    def update(self, label):
        if not self.enabled:
            return
        self.label = plain(label)
        if not self.animated:
            print(self.label, file=self.stream, flush=True)
        elif self.thread is None:
            self.started = time.monotonic()
            self.thread = threading.Thread(target=self._run, name='imagescope-progress', daemon=True)
            self.thread.start()

    def _run(self):
        frame = 0
        frames = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
        try:
            while not self.stopped.is_set():
                width = columns(self.stream)
                text = f"{frames[frame % len(frames)]} {self.label}  {time.monotonic() - self.started:.1f}s"
                # Space padding needs no color/cursor ANSI state.
                self.stream.write('\r' + text[:width].ljust(width))
                self.stream.flush()
                frame += 1
                self.stopped.wait(0.08)
        except (OSError, ValueError):
            # A disconnected terminal must not fail an otherwise valid analysis.
            pass

    def stop(self):
        self.stopped.set()
        if self.thread is not None:
            self.thread.join()
            try:
                self.stream.write('\r' + ' ' * columns(self.stream) + '\r')
                self.stream.flush()
            except (OSError, ValueError):
                pass


def paragraph(text, stream, *, indent=''):
    print(textwrap.fill(plain(text), width=columns(stream), initial_indent=indent,
                        subsequent_indent=indent), file=stream)


def show_result(result, stream=None):
    stream = sys.stdout if stream is None else stream
    data = result['input']
    prediction = result['predictions']
    paragraph(f"{data['width']} × {data['height']} · {data['format']}", stream)
    if prediction:
        print(file=stream)
        paragraph(prediction['caption'] or 'No caption returned.', stream)
        for key, label in [('subjects', 'Subjects'), ('medium', 'Medium'), ('mood', 'Mood'),
                           ('lighting', 'Lighting'), ('composition', 'Composition'), ('tags', 'Tags')]:
            value = prediction[key]
            if value:
                paragraph(f"{label}: {', '.join(value) if isinstance(value, list) else value}", stream)
        flags = [label for key, label in [('text_present', 'text'), ('watermark_present', 'watermark')]
                 if prediction[key]]
        if flags:
            paragraph('Detected: ' + ', '.join(flags), stream)
    measurements = result['measurements']
    if measurements:
        print(file=stream)
        paragraph('Measurements', stream)
        paragraph('Palette: ' + '  '.join(color['hex'] for color in measurements['palette']), stream, indent='  ')
        paragraph(f"Luminance: {measurements['mean_luminance']:.3f} · spread {measurements['luminance_std']:.3f}",
                  stream, indent='  ')
    print(file=stream)
    paragraph(f"Done in {result['elapsed_seconds']:.1f}s" + (' · model predictions, not verified facts' if prediction else ''), stream)


def show_error(code, message, stream=None):
    stream = sys.stderr if stream is None else stream
    paragraph(f"{'Cancelled' if code == 'cancelled' else 'Error'} · {code}", stream)
    paragraph(message, stream, indent='  ')


def show_doctor(result):
    paragraph(f"Ollama · {result['version'].get('version', 'version unknown')}", sys.stdout)
    paragraph(result['endpoint'], sys.stdout)
    for key, label in [('installed', 'Installed'), ('loaded', 'Loaded')]:
        models = result[key].get('models', [])
        paragraph(f"{label}: " + (', '.join(str(m.get('name', m.get('model', 'unknown'))) for m in models) or 'none'), sys.stdout)
    paragraph(result['note'], sys.stdout)
