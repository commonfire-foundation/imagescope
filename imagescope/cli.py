"""Unix CLI: image in, structured observation out. No persistent state."""
import argparse
import json
from pathlib import Path
import signal
import sys
import threading

from . import __version__
from .backends.ollama import OllamaBackend
from .contracts import (AnalysisRequest, AnalyzerError, DEFAULT_ENDPOINT, DEFAULT_MODEL,
                        MAX_INPUT_BYTES, PROTOCOL_VERSION, SCHEMA_VERSION, empty_result,
                        bounded_json, bounded_result)
from .profiles import PROFILES, get_profile
from .presentation import Progress, show_doctor, show_error, show_result


def info():
    return {'name': 'imagescope', 'version': __version__, 'protocol_version': PROTOCOL_VERSION,
            'schema_version': SCHEMA_VERSION, 'metadata_version': 1, 'default_model': DEFAULT_MODEL,
            'histograms': {'version': 1, 'measurements_version': 7, 'opt_in': True, 'bins': 256},
            'color_policies': ['legacy-v1', 'srgb-v1'], 'default_color_policy': 'legacy-v1',
            'region_inspection': {'version': 1, 'tasks': ['inspect'],
                                  'coordinate_space': 'exif-oriented-original-pixel-edges'},
            'profiles': {name: {'version': profile.version, 'prompt': profile.prompt}
                         for name, profile in PROFILES.items()}}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only local image analysis. Never downloads models.')
    parser.add_argument('--version', action='version', version=__version__)
    sub = parser.add_subparsers(dest='command', required=True)
    metadata = sub.add_parser('info', help='Describe supported protocol and task versions')
    metadata.add_argument('--json', action='store_true')
    headers = sub.add_parser('metadata', help='Read image metadata without decoding pixels')
    headers.add_argument('image', type=Path)
    headers.add_argument('--json', action='store_true', help='One metadata-v1 JSON result on stdout')
    headers.add_argument('--timeout', type=float, default=10, help='Metadata inspection budget in seconds (maximum 30)')
    doctor = sub.add_parser('doctor', help='Check Ollama inventory and loaded-model residency')
    doctor.add_argument('--endpoint', default=DEFAULT_ENDPOINT, help='Explicit nonlocal URL opts into sending requests there')
    doctor.add_argument('--timeout', type=float, default=10)
    doctor.add_argument('--json', action='store_true')
    for command in ('inspect', 'describe'):
        p = sub.add_parser(command, help='Pixel measurements only' if command == 'inspect' else 'Generate a semantic description')
        p.add_argument('image', nargs='?', type=Path)
        p.add_argument('--stdin', action='store_true', help='Read one encoded image from stdin (64 MiB maximum)')
        if command == 'inspect':
            p.add_argument('--region', type=int, nargs=4, metavar=('LEFT', 'TOP', 'RIGHT', 'BOTTOM'),
                           help='Measure a half-open crop in EXIF-oriented original-pixel coordinates')
        # Preserve previously documented inspect flags as hidden compatibility options.
        def inference_help(text):
            return text if command == 'describe' else argparse.SUPPRESS
        p.add_argument('--profile', choices=list(PROFILES), default='wallpaper', help=inference_help('Description profile'))
        p.add_argument('--model', default=DEFAULT_MODEL, help=inference_help('Installed Ollama model'))
        p.add_argument('--endpoint', default=DEFAULT_ENDPOINT, help=inference_help('Explicit nonlocal URL opts into sending images there'))
        p.add_argument('--preview-size', type=int, choices=[256,512,768,1024], default=768, help=inference_help('Maximum AI preview dimension'))
        p.add_argument('--measurements', action='store_true', help=inference_help('Also compute pixel measurements during description'))
        p.add_argument('--palette-size', type=int, default=6, metavar='N', help='Maximum extracted colors (1–64; default: 6)' + ('; requires --measurements' if command == 'describe' else ''))
        p.add_argument('--histograms', action='store_true',
                       help='Include sampled RGB/luminance histograms' +
                       ('; requires --measurements' if command == 'describe' else ''))
        p.add_argument('--color-policy', choices=['legacy-v1', 'srgb-v1'], default='legacy-v1',
                       help='Color handling: legacy samples (default) or explicit sRGB conversion')
        p.add_argument('--assume-srgb', action='store_true',
                       help='With srgb-v1, explicitly interpret untagged RGB/gray input as sRGB')
        p.add_argument('--timeout', type=float, default=300, help='Whole-request deadline in seconds, including stdin (Linux)')
        p.add_argument('--keep-alive', type=int, default=300, help=inference_help('Ollama model residency in seconds; 0 requests immediate unload'))
        output = p.add_mutually_exclusive_group()
        output.add_argument('--json', action='store_true', help='One terminal JSON result on stdout')
        output.add_argument('--events', choices=['jsonl'], help='Versioned hello/progress/result records on stdout')
        p.add_argument('--protocol-version', type=int, default=PROTOCOL_VERSION)
        p.add_argument('--expect-profile-version', help=argparse.SUPPRESS)
        p.add_argument('--expect-prompt-sha256', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.command == 'info':
        print(json.dumps(info()) if args.json else f'imagescope {__version__} · protocol 1 · ' +
              ' · '.join(f'{name} {profile.version}' for name, profile in PROFILES.items()))
        return 0
    if args.command == 'metadata':
        from .metadata import MetadataRequest, inspect_metadata
        result = inspect_metadata(MetadataRequest(args.image, timeout=args.timeout))
        if args.json:
            print(bounded_json(result))
        elif result['status'] == 'ok':
            data = result['metadata']
            stored, oriented = data['stored_size'], data['oriented_size']
            print(f"{data['format']} · {data['mode']} · {stored['width']}×{stored['height']} stored · "
                  f"{oriented['width']}×{oriented['height']} oriented")
            print(f"ICC: {data['icc']['status']} · color conversion: none")
            for warning in result['warnings']:
                print(f"Warning [{warning['code']}]: {warning['message']}", file=sys.stderr)
        else:
            show_error(result['error']['code'], result['error']['message'])
        return 0 if result['status'] == 'ok' else (2 if result['error']['code'] == 'invalid_request' else 1)
    if args.command == 'doctor':
        try:
            AnalysisRequest(b'', timeout=args.timeout).validate()
            backend = OllamaBackend(args.endpoint, args.timeout)
            result = {'status': 'ok', 'endpoint': args.endpoint, 'version': backend.request('version'),
                      'installed': backend.request('tags'), 'loaded': backend.request('ps'),
                      'note': 'Loaded-model size_vram reports GPU residency, not a measured inference-speed benchmark.'}
            encoded = bounded_json(result)
            if args.json:
                print(encoded)
            else:
                show_doctor(result)
            return 0
        except AnalyzerError as exc:
            if args.json:
                print(json.dumps({'status':'error','error':{'code':exc.code,'message':str(exc)}}))
            else:
                show_error(exc.code, str(exc))
            return 2 if exc.code == 'invalid_request' else 1

    def emit(kind, **fields):
        print(bounded_json({'protocol_version': PROTOCOL_VERSION, 'type': kind, **fields}), flush=True)

    display = Progress(enabled=not (args.json or args.events))

    def progress(stage, label):
        if args.events:
            emit('progress', stage=stage, label=label)
        elif not args.json:
            display.update(label)

    request = AnalysisRequest(args.image if args.image is not None else b'', task=args.command,
        profile=args.profile, model=args.model, endpoint=args.endpoint, preview_size=args.preview_size,
        measurements=args.measurements, timeout=args.timeout, keep_alive=args.keep_alive,
        palette_size=args.palette_size, color_policy=args.color_policy, assume_srgb=args.assume_srgb,
        region=tuple(args.region) if getattr(args, 'region', None) is not None else None,
        histograms=args.histograms)
    result = empty_result(request)
    handlers = {}
    previous_alarm = None
    code = 1
    try:
        if args.events:
            emit('hello', schema_version=SCHEMA_VERSION)
        request.validate()
        if (args.image is None) == (not args.stdin):
            raise AnalyzerError('invalid_request', 'Provide exactly one image path or --stdin')
        if args.protocol_version != PROTOCOL_VERSION:
            raise AnalyzerError('incompatible_protocol', 'This analyzer supports protocol version 1')
        import hashlib
        profile = get_profile(args.profile)
        if ((args.expect_profile_version and args.expect_profile_version != profile.version)
                or (args.expect_prompt_sha256 and args.expect_prompt_sha256 != hashlib.sha256(profile.prompt.encode()).hexdigest())):
            raise AnalyzerError('analyzer_changed', 'Analyzer changed since queuing; retry with the current model/prompt')
        if threading.current_thread() is threading.main_thread():
            def cancel(signum, frame):
                raise KeyboardInterrupt
            def timed_out(signum, frame):
                raise AnalyzerError('timeout', 'Analyzer request timed out')
            for sig, handler in ((signal.SIGTERM, cancel), (signal.SIGINT, cancel), (signal.SIGALRM, timed_out)):
                handlers[sig] = signal.signal(sig, handler)
            previous_alarm = signal.setitimer(signal.ITIMER_REAL, args.timeout)
        if args.stdin:
            display.update('Reading image from stdin')
            data = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
            if len(data) > MAX_INPUT_BYTES:
                raise AnalyzerError('input_too_large', 'Image exceeds the 64 MiB input limit')
            from dataclasses import replace
            request = replace(request, source=data)
        from .api import analyze
        result = analyze(request, on_progress=progress)
        code = 0 if result['status'] == 'ok' else (2 if result['error']['code'] == 'invalid_request' else 1)
    except AnalyzerError as exc:
        result['status'] = 'error'
        result['error'] = {'code': exc.code, 'message': str(exc)}
        code = 2 if exc.code in ('invalid_request', 'incompatible_protocol') else 1
    except KeyboardInterrupt:
        result['status'] = 'error'
        result['error'] = {'code': 'cancelled', 'message': 'Client cancelled; Ollama may still finish an already submitted request'}
        code = 130
    except (OSError, ValueError) as exc:
        result['status'] = 'error'
        result['error'] = {'code': 'invalid_input', 'message': str(exc)}
    finally:
        if previous_alarm is not None:
            signal.setitimer(signal.ITIMER_REAL, 0)
        display.stop()
        if previous_alarm is not None:
            signal.setitimer(signal.ITIMER_REAL, *previous_alarm)
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
    result = bounded_result(result)
    if result['error'] and result['error']['code'] in ('output_too_large', 'invalid_response'):
        code = 1
    if args.events:
        emit('result', result=result)
    elif args.json:
        print(bounded_json(result), flush=True)
    elif result['status'] == 'ok':
        show_result(result)
    else:
        show_error(result['error']['code'], result['error']['message'])
    return code
