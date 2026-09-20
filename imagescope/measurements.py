"""Deterministic pixel measurements, independent of inference."""
import colorsys

import numpy as np
from PIL import Image

from .images import white_composite
from .color_statistics import distributions, palette_distances, linear_srgb

from .structure import structure_measurements

MEASUREMENTS_VERSION = 6


def _weighted_colors(rgb, weights, size):
    """Bounded weighted median cut over at most 256×256 visible pixels."""
    colors, inverse = np.unique(rgb, axis=0, return_inverse=True)
    weights = np.bincount(inverse, weights=weights)
    colors = colors.astype(float)

    def box(indices):
        values, mass = colors[indices], weights[indices]
        mean = np.average(values, axis=0, weights=mass)
        error = ((values - mean) ** 2 * mass[:, None]).sum(axis=0)
        return indices, error

    boxes = [box(np.arange(len(colors)))]
    while len(boxes) < size:
        candidates = [(float(error.sum()), -i, i) for i, (indices, error) in enumerate(boxes)
                      if len(indices) > 1]
        if not candidates:
            break
        _, _, chosen = max(candidates)
        indices, error = boxes.pop(chosen)
        indices = indices[np.argsort(colors[indices, int(error.argmax())], kind='stable')]
        cumulative = np.cumsum(weights[indices])
        split = int(np.searchsorted(cumulative, cumulative[-1] / 2)) + 1
        split = min(len(indices) - 1, max(1, split))
        boxes.extend((box(indices[:split]), box(indices[split:])))
    merged = {}
    for indices, _ in boxes:
        color = tuple(np.rint(np.average(colors[indices], axis=0, weights=weights[indices])).astype(int))
        merged[color] = merged.get(color, 0.0) + float(weights[indices].sum())
    return merged


def _palette_thumbnail(image):
    thumb = image.convert('RGBA') if image.mode != 'RGB' else image.copy()
    opaque = thumb.mode == 'RGB' or thumb.getchannel('A').getextrema() == (255, 255)
    if opaque:
        thumb = thumb.convert('RGB')
        thumb.thumbnail((256, 256))  # Existing opaque BICUBIC convention.
    else:
        thumb.thumbnail((256, 256), Image.Resampling.LANCZOS)
    return thumb, opaque


def extract_palette(image, size=6):
    """Approximate palette shares at bounded resolution, without a background."""
    if type(size) is not int or not 1 <= size <= 64:
        raise ValueError('palette_size must be an integer from 1 to 64')
    thumb, opaque = _palette_thumbnail(image)
    if opaque:
        # Preserve opaque version-2 quantization (and its default six colors).
        quantized = thumb.convert('RGB').quantize(colors=size)
        palette = quantized.getpalette()
        colors = {tuple(palette[index * 3:index * 3 + 3]): float(count)
                  for count, index in sorted(quantized.getcolors(), reverse=True)}
    else:
        pixels = np.asarray(thumb).reshape(-1, 4)
        visible = pixels[pixels[:, 3] > 0]
        if not len(visible):
            return []
        colors = _weighted_colors(visible[:, :3], visible[:, 3].astype(float) / 255, size)
    total = sum(colors.values())
    entries = []
    for rgb, mass in sorted(colors.items(), key=lambda item: -item[1]):
        rgb = [int(channel) for channel in rgb]
        hue, lightness, saturation = colorsys.rgb_to_hls(*(channel / 255 for channel in rgb))
        entries.append({'hex': '#' + ''.join(f'{channel:02x}' for channel in rgb),
                        'rgb': rgb,
                        'hsl': [round(hue * 360, 2) % 360, round(saturation * 100, 2), round(lightness * 100, 2)],
                        'fraction': round(mass / total, 4)})
    return entries


def transparency(image):
    """Unweighted alpha shares and half-open bounds in working coordinates."""
    alpha = image.convert('RGBA').getchannel('A')
    counts = alpha.histogram()
    total = image.width * image.height
    bounds = alpha.getbbox()
    return {'width': image.width, 'height': image.height,
            'transparent_fraction': round(counts[0] / total, 6),
            'translucent_fraction': round(sum(counts[1:255]) / total, 6),
            'visible_bounds': list(bounds) if bounds else None}


def spatial_color(image):
    """Fixed 3×3 regional palettes and opacity-weighted luminance; no background."""
    def boundaries(size):
        quotient, remainder = divmod(size, 3)
        return [i * quotient + min(i, remainder) for i in range(4)]

    xs, ys = boundaries(image.width), boundaries(image.height)
    regions = []
    for row in range(3):
        for column in range(3):
            bounds = [xs[column], ys[row], xs[column + 1], ys[row + 1]]
            region = {'row': row, 'column': column, 'bounds': bounds,
                      'palette': [], 'mean_luminance': None}
            if bounds[2] > bounds[0] and bounds[3] > bounds[1]:
                crop = image.crop(bounds)
                region['palette'] = extract_palette(crop, 3)
                thumb, _ = _palette_thumbnail(crop)
                pixels = np.asarray(thumb.convert('RGBA')).reshape(-1, 4)
                visible = pixels[pixels[:, 3] > 0]
                if len(visible):
                    values = linear_srgb(visible[:, :3].astype(float) / 255) @ np.array([.2126, .7152, .0722])
                    region['mean_luminance'] = round(float(np.average(values, weights=visible[:, 3])), 6)
            regions.append(region)
    return {'rows': 3, 'columns': 3, 'width': image.width, 'height': image.height,
            'regions': regions}


def measure(image, palette_size=6):
    measurements = {'palette': extract_palette(image, palette_size)}
    thumb, _ = _palette_thumbnail(image)
    measurements['color_distribution'], measurements['luminance_distribution'] = distributions(thumb)
    measurements['palette_distances'] = palette_distances(measurements['palette'])
    measurements['transparency'] = transparency(image)
    measurements['spatial_color'] = spatial_color(image)
    image = white_composite(image)
    measurements['local_detail'], measurements['symmetry'], measurements['phash64'] = structure_measurements(image)
    thumb = image.copy()
    thumb.thumbnail((256, 256))
    rgb = np.asarray(thumb, dtype=np.float64) / 255
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    luminance = linear @ np.array([0.2126, 0.7152, 0.0722])
    measurements.update(mean_luminance=float(luminance.mean()), luminance_std=float(luminance.std()))
    gray = np.asarray(image.convert("L").resize((9, 8), Image.Resampling.LANCZOS))
    bits = gray[:, 1:] > gray[:, :-1]
    measurements["dhash64"] = f"{int(''.join('1' if bit else '0' for bit in bits.flat), 2):016x}"
    # Fixed-size edge grid makes the heuristic comparable across input dimensions.
    grid = np.asarray(image.convert("L").resize((192, 192)), dtype=float) / 255
    dy, dx = np.gradient(grid)
    edges = np.hypot(dx, dy) > 0.08
    measurements["edge_density_3x3"] = [[float(cell.mean()) for cell in np.array_split(row, 3, axis=1)]
                                       for row in np.array_split(edges, 3, axis=0)]
    return measurements
