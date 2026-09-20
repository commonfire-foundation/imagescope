"""Fixed-resolution intensity comparisons; not image-quality judgments."""
import numpy as np
from PIL import Image

PHASH_ALGORITHM = 'dct-ii-32-low8-ac-median-v1'

# Orthonormal DCT-II basis; avoids a new SciPy dependency for a 32×32 transform.
_DCT_BASIS = np.sqrt(2 / 32) * np.cos(np.pi * np.arange(32)[:, None] * (np.arange(32) + .5) / 32)
_DCT_BASIS[0] /= np.sqrt(2)


def structure_measurements(image):
    """Input is the white-composited RGB working image; never mutated."""
    gray = image.convert('L')
    intensity = np.asarray(gray.resize((192, 192), Image.Resampling.BICUBIC), dtype=float) / 255
    detail = {'intensity_std_3x3': [
        [round(float(cell.std()), 6) for cell in np.array_split(row, 3, axis=1)]
        for row in np.array_split(intensity, 3, axis=0)]}
    symmetry = {
        'left_right': round(float(1 - np.abs(intensity - intensity[:, ::-1]).mean()), 6),
        'top_bottom': round(float(1 - np.abs(intensity - intensity[::-1, :]).mean()), 6),
    }
    small = np.asarray(gray.resize((32, 32), Image.Resampling.LANCZOS), dtype=float) / 255
    coefficients = np.round((_DCT_BASIS @ small @ _DCT_BASIS.T)[:8, :8], 12).ravel()
    bits = coefficients > np.median(coefficients[1:])
    bits[0] = False
    phash = {'algorithm': PHASH_ALGORITHM,
             'hash': f"{int(''.join('1' if bit else '0' for bit in bits), 2):016x}"}
    return detail, symmetry, phash
