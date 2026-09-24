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
    region = result.get('provenance', {}).get('preprocessing', {}).get('region')
    if region:
        bounds = ', '.join(map(str, region['bounds']))
        width, height = region['working_size']
        paragraph(f'Region: [{bounds}] (half-open) · {width} × {height} working pixels', stream)
        paragraph('Visible bounds are local to the working crop; ROI uses oriented source pixels.', stream)
    color = result.get('provenance', {}).get('preprocessing', {}).get('color_management')
    if color and color.get('status'):
        labels = {'converted': 'converted to sRGB', 'declared_srgb': 'source declares sRGB',
                  'assumed_srgb': 'sRGB explicitly assumed',
                  'unmanaged': 'unmanaged; source color space unknown'}
        label = labels.get(color['status'], color['status'])
        if color['status'] == 'unmanaged' and color.get('source_interpretation') == 'declared_srgb':
            label = 'unmanaged; source declares sRGB'
        paragraph(f"Color: {color['policy']} · {label}", stream)
    if prediction:
        print(file=stream)
        from .profiles import get_profile
        profile = get_profile(result['provenance']['profile'])
        paragraph(prediction[profile.summary_field], stream)
        for key, label in profile.labels:
            value = prediction[key]
            if value:
                paragraph(f"{label}: {', '.join(value) if isinstance(value, list) else value}", stream)
        flags = [label for key, label in profile.flags
                 if prediction[key]]
        if flags:
            paragraph('Detected: ' + ', '.join(flags), stream)
    measurements = result['measurements']
    if measurements:
        print(file=stream)
        paragraph('Measurements', stream)
        histograms = measurements.get('histograms')
        if histograms:
            width, height = histograms['sampling']['sample_size']
            paragraph(f'Histograms: 256 bins · {width} × {height} sample · opacity-weighted', stream, indent='  ')
            endpoints = histograms['endpoint_occupancy']
            black, white = endpoints['all_channels_zero_fraction'], endpoints['all_channels_max_fraction']
            if black is None:
                paragraph('Sampled endpoints: undefined (no visible pixels)', stream, indent='  ')
            else:
                paragraph(f'Sampled endpoints: {black:.1%} black · {white:.1%} white; not proof of clipping',
                          stream, indent='  ')
        palette = '  '.join(color['hex'] for color in measurements['palette'])
        paragraph('Palette: ' + (palette or 'none (no visible pixels)'), stream, indent='  ')
        paragraph(f"Luminance: {measurements['mean_luminance']:.3f} · spread {measurements['luminance_std']:.3f}",
                  stream, indent='  ')
        distribution = measurements.get('luminance_distribution')
        if distribution is not None:
            percentiles = distribution['percentiles']
            if percentiles is None:
                paragraph('Visible-color statistics: none (no visible pixels)', stream, indent='  ')
            else:
                paragraph('Visible luminance p05/50/95: ' + ' / '.join(
                    f'{percentiles[key]:.3f}' for key in ('p05', 'p50', 'p95')), stream, indent='  ')
                neutral = measurements['color_distribution']['near_neutral_fraction']
                paragraph(f"Opacity shares: neutral {neutral:.1%} · near-black "
                          f"{distribution['near_black_fraction']:.1%} · near-white "
                          f"{distribution['near_white_fraction']:.1%}", stream, indent='  ')
        alpha = measurements.get('transparency')
        if alpha is not None:
            paragraph(f"Transparency: {alpha['transparent_fraction']:.1%} transparent · "
                      f"{alpha['translucent_fraction']:.1%} translucent", stream, indent='  ')
            bounds = alpha['visible_bounds']
            paragraph(f"Visible bounds ({alpha['width']} × {alpha['height']} working pixels): " +
                      (str(bounds) if bounds is not None else 'none'), stream, indent='  ')
        spatial = measurements.get('spatial_color')
        if spatial is not None:
            paragraph('Regional colors / visible luminance (3×3, left to right):', stream, indent='  ')
            for row in range(3):
                entries = []
                for region in spatial['regions'][row * 3:(row + 1) * 3]:
                    entries.append(f"{region['palette'][0]['hex']} / {region['mean_luminance']:.3f}"
                                   if region['palette'] else 'none')
                paragraph(f"Row {row + 1}: " + ' | '.join(entries), stream, indent='    ')
        detail = measurements.get('local_detail')
        if detail is not None:
            paragraph('Intensity variation (3×3):', stream, indent='  ')
            for row in detail['intensity_std_3x3']:
                paragraph(' / '.join(f'{value:.3f}' for value in row), stream, indent='    ')
        symmetry = measurements.get('symmetry')
        if symmetry is not None:
            paragraph(f"Mirror similarity: left/right {symmetry['left_right']:.3f} · "
                      f"top/bottom {symmetry['top_bottom']:.3f}", stream, indent='  ')
        phash = measurements.get('phash64')
        if phash is not None:
            paragraph(f"pHash: {phash['hash']} ({phash['algorithm']})", stream, indent='  ')
        pairs = measurements.get('palette_distances', [])
        if pairs:
            paragraph(f"Minimum palette ΔE76: {min(pair['delta_e76'] for pair in pairs):.2f}", stream, indent='  ')
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
