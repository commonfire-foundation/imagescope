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
    discovery = json.loads(info.stdout)
    assert discovery['name'] == 'imagescope'
    assert set(discovery['profiles']) == {'wallpaper', 'general'}
    path = Path('smoke.png')
    Image.new('RGB', (32, 16), 'red').save(path)
    result = subprocess.run([str(executable), 'inspect', str(path), '--json'],
                            check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    assert payload['status'] == 'ok', payload
    assert payload['input']['width'] == 32
    assert payload['input']['height'] == 16
    assert payload['predictions'] is None
    assert payload['provenance']['measurements_version'] == 6
    assert payload['measurements']['local_detail']['intensity_std_3x3'] == [[0.] * 3] * 3
    assert payload['measurements']['symmetry'] == {'left_right': 1., 'top_bottom': 1.}
    assert payload['measurements']['phash64'] == {'algorithm': 'dct-ii-32-low8-ac-median-v1', 'hash': '0000000000000000'}
    assert payload['measurements']['transparency']['visible_bounds'] == [0, 0, 32, 16]
    assert len(payload['measurements']['spatial_color']['regions']) == 9
    assert payload['measurements']['luminance_distribution']['percentiles']['p50'] == .2126
    assert payload['measurements']['color_distribution']['hue_histogram'][0] == 1
    assert payload['measurements']['palette_distances'] == []
    assert payload['measurements']['palette'][0]['rgb'] == [255, 0, 0]
    assert discovery['region_inspection']['version'] == 1
    region = subprocess.run([str(executable), 'inspect', str(path), '--region', '4', '2', '20', '10', '--json'],
                            check=True, capture_output=True, text=True)
    cropped = json.loads(region.stdout)
    assert cropped['status'] == 'ok', cropped
    assert cropped['input']['width'] == 32
    assert cropped['provenance']['preprocessing']['version'] == 5
    assert cropped['provenance']['preprocessing']['region']['crop_size'] == [16, 8]
    assert cropped['measurements']['transparency']['visible_bounds'] == [0, 0, 16, 8]
    assert cropped['measurements']['palette'][0]['rgb'] == [255, 0, 0]
    assert discovery['histograms']['version'] == 1
    histogram_result = subprocess.run([str(executable), 'inspect', str(path), '--histograms', '--json'],
                                      check=True, capture_output=True, text=True)
    histogram_payload = json.loads(histogram_result.stdout)
    assert histogram_payload['status'] == 'ok', histogram_payload
    assert histogram_payload['provenance']['measurements_version'] == 7
    histogram = histogram_payload['measurements']['histograms']
    assert histogram['total_weight'] == 32 * 16 * 255
    assert histogram['rgb']['red'][255] == histogram['total_weight']
    assert sum(histogram['luminance']) == histogram['total_weight']
    Image.new('RGBA', (32, 16), (255, 0, 0, 0)).save(path)
    result = subprocess.run([str(executable), 'inspect', str(path), '--palette-size', '24', '--json'],
                            check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    assert payload['measurements']['palette'] == []
    assert payload['measurements']['transparency']['transparent_fraction'] == 1
    assert payload['measurements']['transparency']['visible_bounds'] is None
    assert all(r['mean_luminance'] is None for r in payload['measurements']['spatial_color']['regions'])
    assert payload['measurements']['luminance_distribution']['percentiles'] is None
    assert payload['provenance']['measurement_settings']['palette_size'] == 24
    from imagescope import AnalysisRequest, analyze
    from imagescope.backends.ollama import OllamaBackend
    from imagescope.contracts import validate_result
    from imagescope.profiles import get_profile
    general = get_profile('general')
    prediction = {'summary': 'A white field.', 'subjects': [], 'text_present': False}
    def transport(endpoint, payload):
        if endpoint == 'tags':
            return {'models': [{'name': 'test'}]}
        if endpoint == 'version':
            return {'version': 'test'}
        assert payload['format'] == general.schema
        assert payload['messages'][0]['content'] == general.prompt
        return {'message': {'content': json.dumps(prediction)}}
    result = analyze(AnalysisRequest(path, model='test', profile='general'),
                     backend=OllamaBackend(transport=transport))
    validate_result(result)
    assert result['status'] == 'ok', result['error']
    assert result['predictions'] == prediction
    print(f'Installed Imagescope {version}: discovery, decoding, all measurements, and general profile passed')


if __name__ == '__main__':
    main()
