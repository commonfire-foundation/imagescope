# Editing histograms — version 1

Histograms are opt-in, read-only measurements. They use the existing alpha-aware
palette thumbnail (at most 256×256), not the full original raster. No model or
editing/export behavior is added.

```sh
imagescope inspect image.png --histograms --json
imagescope inspect image.png --region 100 50 900 650 --histograms --json
imagescope describe image.png --profile general --measurements --histograms --json
```

```python
from imagescope import AnalysisRequest, analyze

result = analyze(AnalysisRequest(source, task='inspect', histograms=True))
```

`histograms` must be a boolean. Describe requires `measurements=True` as well;
requesting histograms without measurements is an `invalid_request`. Metadata-only
inspection has no histogram option. Existing requests with histograms disabled
retain their measurement-v6 values and shape. Requests with histograms enabled
use measurements version **7** and add `measurements.histograms` (version **1**).
No existing measurement calculation changes. Protocol/schema/preprocessing and
color-policy versions remain unchanged. Discovery advertises histogram version 1.

## Sampling and weighting

The histogram sample is the same bounded thumbnail used for color/luminance
distributions: BICUBIC for opaque input, premultiplied encoded-sRGB8 LANCZOS for
nonopaque input. No white compositing. Original/ROI working-image reduction may
already have occurred before this thumbnail. The result records working/sample
sizes, thumbnail reduction, maximum dimension, and resampling method. Full-source
reduction and ROI mapping remain in preprocessing provenance.

Each sampled pixel contributes its integer alpha value (0–255). Hidden RGB at
alpha 0 contributes zero; partial opacity contributes proportionally. RGB samples
contribute 255. `weight_unit: alpha8` identifies these units; counts are **opacity
mass, not pixel counts**. `visible_pixels` separately counts sample pixels with
alpha > 0. Each of the four count arrays sums exactly to `total_weight`. Divide
counts by `total_weight` to get normalized shares when that total is nonzero.

## Histogram shape

`measurements.histograms` contains:

- `version: 1`, `bins: 256`, `weight_unit: alpha8`.
- `rgb_domain: encoded-rgb8`; `luminance_domain: linear-srgb`.
- `sampling`: working/sample sizes, maximum side, resampling method, and whether
  thumbnail reduction occurred.
- `total_weight`, `visible_pixels`.
- `rgb`: `red`, `green`, `blue`, each an array of 256 nonnegative integer weights.
  RGB bin `i` means the exact 8-bit channel value `i`.
- `luminance`: 256 nonnegative integer weights. Linearize encoded RGB using the
  sRGB transfer function; `Y = .2126 R + .7152 G + .0722 B`. Bin `i` is
  `[i/256, (i+1)/256)`; the final bin includes 1.0. Equivalently use
  `min(255, floor(Y * 256))`. This is not Pillow's encoded `L` conversion.
- `endpoint_occupancy`, defined below.

The selected color policy applies before measurement. Under legacy-v1, the sRGB
interpretation of channel values is a measurement convention, not verification
of the source color space. See `COLOR_POLICY.md`.

## Clipping-related endpoint statistics

`endpoint_occupancy` reports **sampled endpoint occupancy, not proof of clipping**.
For each RGB channel, `zero_fraction` and `max_fraction` are opacity-weighted shares
at exactly 0 and exactly 255. Also report:

- `all_channels_zero_fraction`: sampled RGB is exactly black.
- `all_channels_max_fraction`: sampled RGB is exactly white.
- `any_channel_zero_fraction`: at least one channel is exactly 0.
- `any_channel_max_fraction`: at least one channel is exactly 255.

Shares are rounded to six decimals and lie in [0,1]. Fully transparent input has
zero weights, zero visible pixels, and null endpoint fractions (undefined), not
zero fractions suggesting there was measurable content. No NaN/infinity is emitted.
A luminance first/last-bin count is **not** an exact black/white count: those bins
include nearby intensities. Use all-channel endpoint fractions for exact sampled
black/white occupancy.

Saturated colors, intentionally black/white artwork, previous decoding, and
resampling can all produce endpoints. These measurements cannot establish sensor
clipping, recover lost detail, or measure HDR/out-of-gamut values. Small source
highlights may disappear during reduction; report this sampling limitation in UIs.

## Before/after comparisons

Normalize by each result's total opacity mass; raw counts differ with sample size
and transparency. Compare only matching histogram/measurement versions, color
policy/implementation, preprocessing, crop/coordinate scope, and sampling settings.
Changed dimensions and resampling can affect results even without tonal edits.
For an unsaved edited image, the caller can provide encoded image bytes explicitly;
Imagescope does not own edit state or infer which revision a result describes.
The caller must attach source/edit revisions and reject stale results.

Human output gives a compact histogram/endpoint summary. JSON/JSONL contain the
complete arrays and sampling information. This is not a full-resolution histogram
or an automatic recommendation to change exposure.
