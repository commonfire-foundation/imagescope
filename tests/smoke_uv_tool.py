"""Opt-in uv lifecycle check; all tool/cache/temp writes stay under repo .tmp.

Usage: python tests/smoke_uv_tool.py path/to/imagescope.whl
Requires uv and network access (or cached dependencies), but no Ollama.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheel', type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve(strict=True)
    if wheel.suffix != '.whl':
        parser.error('supply a built wheel')
    uv = shutil.which('uv')
    if uv is None:
        parser.error('uv must already be installed')
    root = Path(__file__).resolve().parents[1]
    temporary = root / '.tmp'
    temporary.mkdir(exist_ok=True)
    if not temporary.resolve().is_relative_to(root):
        parser.error('repository .tmp must not resolve outside the checkout')
    scratch = Path(tempfile.mkdtemp(prefix='uv-tool-smoke-', dir=temporary))
    for name in ('bin', 'tools', 'cache', 'python', 'tmp', 'work'):
        (scratch / name).mkdir()
    env = {**os.environ,
           'UV_TOOL_DIR': str(scratch / 'tools'),
           'UV_TOOL_BIN_DIR': str(scratch / 'bin'),
           'UV_CACHE_DIR': str(scratch / 'cache'),
           'UV_PYTHON_INSTALL_DIR': str(scratch / 'python'),
           'UV_PYTHON_DOWNLOADS': 'never',
           'TMPDIR': str(scratch / 'tmp'),
           'PATH': str(scratch / 'bin') + os.pathsep + os.environ.get('PATH', '')}
    sentinel = scratch / 'work' / 'keep.txt'
    sentinel.write_text('user content must survive uninstall\n')

    def run(*command):
        result = subprocess.run(command, cwd=scratch / 'work', env=env,
                                text=True, capture_output=True, timeout=300)
        with (scratch / 'commands.log').open('a') as log:
            log.write(f'{command!r}\n{result.stdout}{result.stderr}\n')
        result.check_returncode()
        return result.stdout.strip()

    print(f'Isolated lifecycle evidence: {scratch}', flush=True)
    install = (uv, '--no-config', 'tool', 'install', '--no-python-downloads',
               '--python', sys.executable, str(wheel))
    run(*install)
    executable = scratch / 'bin' / 'imagescope'
    assert executable.exists(), 'managed command was not installed'
    first_version = run('imagescope', '--version')
    assert json.loads(run('imagescope', 'info', '--json'))['version'] == first_version
    tool_python = scratch / 'tools' / 'imagescope' / 'bin' / 'python'
    run(str(tool_python), str(root / 'tests' / 'smoke_installed.py'))
    image = scratch / 'work' / 'smoke.png'
    original_image = image.read_bytes()
    run(*install, '--force')
    assert run('imagescope', '--version') == first_version
    inspected = json.loads(run('imagescope', 'inspect', str(image), '--json'))
    assert inspected['status'] == 'ok'
    assert inspected['measurements']['palette'] == []
    run(uv, '--no-config', 'tool', 'uninstall', 'imagescope')
    assert not os.path.lexists(executable), 'managed command survived uninstall'
    assert not (scratch / 'tools' / 'imagescope').exists(), 'tool environment survived uninstall'
    assert image.read_bytes() == original_image
    assert sentinel.read_text() == 'user content must survive uninstall\n'
    print(f'Imagescope {first_version}: uv install, CLI, replacement, and uninstall passed')


if __name__ == '__main__':
    main()
