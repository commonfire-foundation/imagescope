"""Bounded color statistics over the palette thumbnail; see PROTOCOL.md."""
import numpy as np

PERCENTILES = (5, 25, 50, 75, 95)


def linear_srgb(rgb):
    return np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)


def _percentiles(values, weights):
    order = np.argsort(values, kind='stable')
    cumulative = np.cumsum(weights[order])
    indices = np.searchsorted(cumulative, np.array(PERCENTILES) / 100 * cumulative[-1], side='left')
    return {f'p{p:02d}': round(float(values[order[index]]), 6)
            for p, index in zip(PERCENTILES, indices)}


def distributions(thumb):
    """Opacity-weighted statistics; input is already at most 256×256."""
    pixels = np.asarray(thumb.convert('RGBA')).reshape(-1, 4)
    pixels = pixels[pixels[:, 3] > 0]
    color = dict(hue_histogram=None, saturation_percentiles=None,
                 lightness_percentiles=None, near_neutral_fraction=None)
    luminance = dict(percentiles=None, near_black_fraction=None, near_white_fraction=None)
    if not len(pixels):
        return color, luminance
    rgb = pixels[:, :3].astype(float) / 255
    # Integer opacity units are equivalent to alpha/255 weights, with exact
    # cumulative sums at percentile boundaries (at most 65536 * 255).
    weights = pixels[:, 3].astype(float)
    total = weights.sum()
    maximum_byte = pixels[:, :3].max(axis=1).astype(int)
    minimum_byte = pixels[:, :3].min(axis=1).astype(int)
    maximum, minimum = maximum_byte / 255, minimum_byte / 255
    delta = maximum - minimum
    lightness = (maximum + minimum) / 2
    saturation = np.divide(delta, 1 - np.abs(maximum + minimum - 1),
                           out=np.zeros_like(delta), where=delta > 0)
    hue = np.zeros_like(delta)
    channel = rgb.argmax(axis=1)
    for index, (a, b, offset) in enumerate(((1, 2, 0), (2, 0, 2), (0, 1, 4))):
        mask = (channel == index) & (delta > 0)
        hue[mask] = ((rgb[mask, a] - rgb[mask, b]) / delta[mask] + offset) * 60
    hue %= 360
    # Compare the 10% threshold in integer RGB units to include exact ties.
    neutral = (maximum_byte - minimum_byte) * 10 <= 255 - np.abs(maximum_byte + minimum_byte - 255)
    if np.any(~neutral):
        histogram, _ = np.histogram(hue[~neutral], bins=np.arange(0, 361, 30), weights=weights[~neutral])
        color['hue_histogram'] = np.round(histogram / weights[~neutral].sum(), 6).tolist()
    color.update(saturation_percentiles=_percentiles(saturation * 100, weights),
                 lightness_percentiles=_percentiles(lightness * 100, weights),
                 near_neutral_fraction=round(float(weights[neutral].sum() / total), 6))
    values = linear_srgb(rgb) @ np.array([.2126, .7152, .0722])
    luminance.update(percentiles=_percentiles(values, weights),
                     near_black_fraction=round(float(weights[values <= .01].sum() / total), 6),
                     near_white_fraction=round(float(weights[values >= .95].sum() / total), 6))
    return color, luminance


def palette_distances(palette):
    """Pairwise CIELAB D65 ΔE76 for the actual emitted rounded RGB colors."""
    if len(palette) < 2:
        return []
    rgb = np.array([entry['rgb'] for entry in palette], dtype=float) / 255
    xyz = linear_srgb(rgb) @ np.array([[.4124564, .2126729, .0193339],
                                      [.3575761, .7151522, .1191920],
                                      [.1804375, .0721750, .9503041]])
    relative = xyz / np.array([.95047, 1., 1.08883])
    delta = 6 / 29
    f = np.where(relative > delta ** 3, np.cbrt(relative), relative / (3 * delta ** 2) + 4 / 29)
    lab = np.column_stack((116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])))
    return [{'i': i, 'j': j, 'delta_e76': round(float(np.linalg.norm(lab[i] - lab[j])), 4)}
            for i in range(len(palette)) for j in range(i + 1, len(palette))]
