"""Run with an installed distribution from outside the source directory."""
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys

import imagescope
from PIL import Image


def main():
    executable = Path(sys.executable).parent / 'imagescope'
    version = importlib.metadata.version('imagescope')
    assert version == imagescope.__version__
    assert 'site-packages' in str(Path(imagescope.__file__).resolve())
    info = subprocess.run([str(executable), 'info', '--json'], check=True,
                          capture_output=True, text=True)
    assert json.loads(info.stdout)['name'] == 'imagescope'
    path = Path('smoke.png')
    Image.new('RGB', (32, 16), 'red').save(path)
    result = subprocess.run([str(executable), 'inspect', str(path), '--json'],
                            check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    assert payload['status'] == 'ok', payload
    assert payload['input']['width'] == 32
    assert payload['input']['height'] == 16
    assert payload['predictions'] is None
    print(f'Installed Imagescope {version}: discovery and decoding passed')


if __name__ == '__main__':
    main()
