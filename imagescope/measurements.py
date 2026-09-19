"""Deterministic pixel measurements, independent of inference."""
import numpy as np
from PIL import Image


def measure(image):
    measurements = {}
    thumb = image.copy()
    thumb.thumbnail((256, 256))
    rgb = np.asarray(thumb, dtype=np.float64) / 255
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    luminance = linear @ np.array([0.2126, 0.7152, 0.0722])
    measurements.update(mean_luminance=float(luminance.mean()), luminance_std=float(luminance.std()))
    quantized = thumb.quantize(colors=6)
    palette = quantized.getpalette()
    counts = sorted(quantized.getcolors(), reverse=True)
    measurements["palette"] = [
        {"hex": "#" + "".join(f"{c:02x}" for c in palette[index * 3:index * 3 + 3]),
         "fraction": round(count / (thumb.width * thumb.height), 4)}
        for count, index in counts
    ]
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
