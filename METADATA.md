# Metadata inspection — version 1

`inspect_metadata(MetadataRequest(source, timeout=10))` reads image metadata without
inference, pixel measurements, raster loading, preview creation, or color conversion.
`source` is a `pathlib.Path` or encoded `bytes`. The CLI accepts a file path:

```sh
imagescope metadata image.png
imagescope metadata image.png --json --timeout 10
```

This is distinct from `inspect`, which decodes a working image and measures pixels.
The metadata command does not support stdin, JSONL events, or profile/model flags.
It returns 0 on success, 2 for invalid requests, and 1 for inspection failures.
Human summaries go to stdout; human warnings/errors go to stderr. JSON mode emits
one result on stdout, with warnings and errors inside that object.

## Public API

```python
from pathlib import Path
from imagescope import MetadataRequest, inspect_metadata

result = inspect_metadata(MetadataRequest(Path('image.png')))
if result['status'] == 'ok':
    print(result['metadata']['stored_size'])
    print(result['metadata']['oriented_size'])
    print(result['warnings'])
else:
    print(result['error']['code'], result['error']['message'])
```

Metadata has its own `metadata_version: 1`; it is **not** an analysis schema-v1
result and must not be passed to `validate_result()`. `imagescope info --json`
advertises `metadata_version`. Existing protocol/schema, preprocessing, measurement,
and profile versions are unchanged. Consumers must reject unknown metadata
versions. Additive fields may be ignored; incompatible meanings require a new
metadata version.

## Result fields

- `metadata_version`: integer 1.
- `status`: `ok` or `error`. Warnings can accompany success.
- `input`: encoded `sha256` and `size_bytes` after successful input reading; empty
  on earlier failure. Hashing reads the whole encoded input, not the pixel raster.
- `metadata`: object on success, null on failure.
- `warnings`: at most 32 objects with stable `code`, `field`, and explanatory
  `message`. Consumers should branch on codes, not message text.
- `error`: null on success, otherwise `code` and `message`.
- `elapsed_seconds`: nonnegative elapsed wall time.

Metadata includes:

| Field | Meaning |
| --- | --- |
| `format`, `mode` | Pillow's detected format and original first-image color mode |
| `stored_size` | Original header width/height, before EXIF orientation |
| `oriented_size` | Width/height swapped for EXIF orientations 5–8; no pixels are transformed |
| `orientation` | EXIF tag 274, integer 1–8, or null if absent/invalid/unavailable |
| `orientation_assumed` | True when dimensions assume orientation 1 because no valid orientation was read |
| `has_alpha_channel` | Alpha channel or declared transparency; not a measurement of actual transparent pixels |
| `exif` | Status and bounded top-level tags keyed by numeric tag strings |
| `icc` | Status, embedded byte count/fingerprint, description and source color-space signature when readable |
| `sequence` | Frames versus pages, count when available without traversal, animation state, loop value, first-frame duration in milliseconds when present |
| `color_conversion` | Always `none` in this version |

A valid ICC profile does not mean the image has been converted or verified against
that profile. An absent profile does not establish sRGB. No sRGB assumption is
made here. ICC description is untrusted source text, not a canonical identity;
use the byte fingerprint to distinguish profiles.

## Partial metadata and limits

Supported formats match analysis: JPEG, PNG, WebP, BMP, TIFF, GIF. Only headers and
first-image metadata are inspected. Metadata success does **not** establish pixel
stream integrity or guarantee that a later full decode will succeed.

- Input is limited to 64 MiB and source dimensions to 500 million pixels.
- Parsing runs in the existing isolated Linux worker with 1.5 GiB address-space,
  CPU, disabled core-dump, and parent-lifetime safeguards. Metadata defaults to a
  10-second budget and accepts positive finite timeouts up to 30 seconds.
- The worker receives the remaining budget after input snapshotting/hashing.
  Ordinary filesystem reads in the Python caller are not preemptible; the timeout
  bounds worker execution, not a stalled filesystem read.
- Results fit the existing 1 MiB JSON budget. Embedded EXIF parsing is capped at
  256 KiB; ICC parsing at 1 MiB. Oversized ICC bytes are fingerprinted, not parsed.
  TIFF directory parsing is additionally bounded by the worker/input budgets.
- Return at most 64 top-level EXIF fields, with text limited to 512 characters.
  Binary, rational, nested, and vendor-specific values are represented as null
  with warnings, not recursively expanded. This is not a complete EXIF dump.
  EXIF may contain private source text; callers own display and retention policy.
- EXIF status is `present`, `absent`, `unknown`, `invalid`, or `omitted`.
  PNG chunks after image data are not scanned: EXIF may be `unknown`, and oriented
  dimensions may therefore be assumed. No call to PNG's pixel-loading `getexif()`
  is made. XMP orientation is not interpreted.
- ICC status is `present`, `absent`, `invalid`, `omitted`, or `unavailable` when the
  CMS parser cannot be imported. Malformed parser data can also produce a general
  warning or an input error; not every damaged file is recoverable.
- GIF and TIFF frame/page counts are null when traversal would be needed. GIF's
  animation state is then null, not false. TIFF pages are not called animation.
  PNG/WebP counts already supplied at open time are retained. No total sequence
  duration is calculated; duration and loop values remain source declarations.

Warning codes: `metadata_limit`, `metadata_truncated`, `metadata_omitted`,
`metadata_not_scanned`, `metadata_unavailable`, `invalid_metadata`, and
`parser_warning`. Worker/input failures are structured errors, not warnings.
Resource-limit failures can retain the existing decoder error codes because the
same sandbox enforces both operations. No original image is modified.

Metadata-only inspection remains separate from color transformation and region
inspection, documented in `COLOR_POLICY.md` and `REGION_INSPECTION.md`. Optional
histograms are documented in `HISTOGRAMS.md`. TIFF stored dimensions come from
IFD tags so newer Pillow versions' already-oriented `.size` is not swapped twice.
