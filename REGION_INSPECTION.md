# Region inspection — ROI version 1

Measure a proposed crop without saving an image. Region inspection is read-only,
uses the existing deterministic measurements, and never invokes a model.

```python
from pathlib import Path
from imagescope import AnalysisRequest, analyze

result = analyze(AnalysisRequest(
    Path('image.png'), task='inspect', region=(100, 50, 900, 650),
    color_policy='srgb-v1', assume_srgb=True,
))
```

```sh
imagescope inspect image.png --region 100 50 900 650 --json
```

Color-policy defaults are unchanged (`legacy-v1`); `--assume-srgb` is an explicit
choice, not required for valid profiled images. See `COLOR_POLICY.md`.

## Request coordinates

`region` is either null (whole-image behavior) or a tuple of four integers:
`(left, top, right, bottom)`. Coordinates are **pixel edges in the EXIF-oriented
original image**, not stored/unoriented pixels, preview pixels, or working pixels.
Left/top are inclusive; right/bottom are exclusive. The rectangle must satisfy:

- `0 <= left < right <= oriented_width`
- `0 <= top < bottom <= oriented_height`

Booleans, floats, lists, empty rectangles, and out-of-bounds rectangles are rejected
as `invalid_request`. No implicit clamping, padding, rounding, or normalized
coordinates. A one-pixel rectangle is valid. Region requests are supported only
for `task='inspect'`; descriptions and metadata-only inspection are unchanged.

### Mapping an editor preview

The caller owns preview mapping. Remove the displayed image's offset/letterboxing,
then map each edge using the actual displayed image width/height and the oriented
original width/height (not the requested maximum preview dimension). For a crop
that covers a dragged preview rectangle, floor the mapped left/top edges and ceil
the right/bottom edges. Validate against the original dimensions before submitting.
This rounding convention selects covered source pixels; Imagescope itself accepts
only the resulting integer rectangle. Additional editor rotation/flip transforms
must be inverted by the caller before submitting; arbitrary edited buffers and
edit state are not part of this API.

## Processing and result contract

Region inspection uses **preprocessing version 5**, ROI version 1, and existing
measurements version 6 (version 7 when opting into histograms; see `HISTOGRAMS.md`). Protocol/schema remain version 1. Whole-image requests
retain preprocessing 3 (`legacy-v1`) or 4 (`srgb-v1`) and unchanged pixel behavior.
A related correctness fix reads TIFF stored dimensions from its IFD tags: Pillow
versions that already expose oriented `.size` must not have those dimensions
swapped a second time. Metadata-v1 and analysis dimension reporting share this fix.

1. Snapshot and validate the original source with existing input/worker limits.
2. Validate the region against original oriented dimensions before color conversion
   or cropping. Obtaining EXIF metadata itself can load pixels for some formats.
3. Apply the selected color policy without reducing the image.
4. Apply EXIF orientation, crop at original pixel resolution, and only then reduce
   the crop to at most 2048 pixels on its longest side. Indexed/LA transparency is
   expanded before reduction. Decoder-native orientation handling is respected.
5. Run the existing measurement pipeline on that working crop. Palette/luminance
   statistics still use their documented bounded thumbnails; other measurements
   retain their existing sampling conventions, now relative to the crop.

Native reduced JPEG decoding is disabled for **all** region requests, including
legacy color. A tiny crop may still require a large full-source raster; this is
not a tiled decoder. Existing 1.5 GiB memory/CPU/30-second worker limits still apply.
Resource failure never falls back to cropping an already-reduced image.

`input.width`, `input.height`, aspect ratio, and SHA-256 continue to describe the
**original image**, not the crop. Successful results record
`provenance.preprocessing.region` with:

- `version: 1`, `coordinate_space: exif-oriented-original-pixel-edges`.
- `bounds`: accepted `[left, top, right, bottom]`.
- `source_size`: oriented original `[width, height]`.
- `crop_size`: original-resolution crop `[width, height]`.
- `working_size`: reduced crop `[width, height]`.
- `working_to_source`: an exact rational geometric edge mapping. For each axis,
  `source_edge = offset + working_edge * numerator / denominator`.
- `visible_bounds_are_source_bounds: false`.

`preprocessing.downsampled` compares the working dimensions to **crop dimensions**,
not original dimensions; cropping alone does not mean downsampling. Human output
identifies the region and its working dimensions to avoid confusing source and
crop measurements. Discovery advertises `region_inspection.version: 1`.

## Transparency and precision

Transparency fractions and `visible_bounds` describe the working crop. Bounds
remain half-open and **crop-working-local**. All regional grids, detail, symmetry,
and similarity outputs also describe the crop, not the source outside it.

The rational mapping maps geometric edges; it does not recover exact original
alpha support after reduction. Resampling may soften edges, spread support, or
remove small features. Do not round mapped sampled bounds and label them exact
source bounds. Without reduction, translation by left/top maps working pixel edges
to source edges exactly; no separately scanned source-alpha bounds are returned.
Fully transparent crops retain the existing null-bounds/empty-palette conventions.

This API neither exports a crop nor edits the original. Exact full-source alpha
scans and editor state are outside this slice. Optional histograms also describe
the selected crop; their sampling and endpoint contract is in `HISTOGRAMS.md`.
