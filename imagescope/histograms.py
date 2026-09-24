"""Version-1 opacity-weighted histograms over an existing bounded thumbnail."""
import numpy as np

from .color_statistics import linear_srgb

HISTOGRAM_VERSION = 1
HISTOGRAM_MEASUREMENTS_VERSION = 7


def histogram_statistics(thumb, *, working_size, opaque):
    """Integer alpha mass, linear-luminance bins, and sampled endpoint shares."""
    if max(thumb.size) > 256:
        raise ValueError('Histogram thumbnail must be at most 256 pixels per side')
    pixels = np.asarray(thumb.convert('RGBA')).reshape(-1, 4)
    rgb = pixels[:, :3]
    alpha = pixels[:, 3].astype(np.int64)
    total = int(alpha.sum())

    def counts(indices):
        # At most 65536 * 255 units: float64 bincount sums integer weights exactly.
        return np.bincount(indices, weights=alpha, minlength=256).astype(np.int64).tolist()

    def fraction(mask):
        return round(int(alpha[mask].sum()) / total, 6) if total else None

    channels = ('red', 'green', 'blue')
    rgb_counts = {name: counts(rgb[:, index]) for index, name in enumerate(channels)}
    luminance = linear_srgb(rgb.astype(np.float64) / 255) @ np.array([.2126, .7152, .0722])
    bins = np.clip(np.floor(luminance * 256), 0, 255).astype(np.int64)
    return {
        'version': HISTOGRAM_VERSION, 'bins': 256, 'weight_unit': 'alpha8',
        'rgb_domain': 'encoded-rgb8', 'luminance_domain': 'linear-srgb',
        'sampling': {'working_size': list(working_size), 'sample_size': list(thumb.size),
                     'max_side': 256, 'downsampled': thumb.size != tuple(working_size),
                     'resampling': 'pillow-bicubic' if opaque else 'pillow-premultiplied-srgb8-lanczos'},
        'total_weight': total, 'visible_pixels': int(np.count_nonzero(alpha)),
        'rgb': rgb_counts, 'luminance': counts(bins),
        'endpoint_occupancy': {
            'rgb': {name: {'zero_fraction': fraction(rgb[:, index] == 0),
                           'max_fraction': fraction(rgb[:, index] == 255)}
                    for index, name in enumerate(channels)},
            'all_channels_zero_fraction': fraction(np.all(rgb == 0, axis=1)),
            'all_channels_max_fraction': fraction(np.all(rgb == 255, axis=1)),
            'any_channel_zero_fraction': fraction(np.any(rgb == 0, axis=1)),
            'any_channel_max_fraction': fraction(np.any(rgb == 255, axis=1))},
    }
