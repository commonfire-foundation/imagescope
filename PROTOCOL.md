# Imagescope protocol 1

Both event envelopes and results are versioned independently. Initial versions:
`protocol_version: 1`, `schema_version: 1`. Consumers reject unsupported versions,
not guess at their meaning. Additive fields may be ignored within version 1;
required field removal or incompatible type/meaning changes require a new version.

The dedicated `metadata` command uses the separate metadata-v1 contract documented
in `METADATA.md`, not these analysis result/event envelopes. Discovery additionally
advertises `metadata_version: 1`. Existing analysis versions and semantics are
unchanged.

## Discovery and requests

`imagescope info --json` returns program/version, protocol/schema versions,
default model, and each built-in profile's version and exact prompt. It does not
contact Ollama. Consumers may snapshot those fields for queued work.

One process handles one image request. Task is `describe` or `inspect`. File input
and `--stdin` are mutually exclusive. Both commands support output controls,
`--timeout` (0 < seconds <= 3600), and protocol controls. Describe settings:
`--profile wallpaper|general` (default wallpaper), `--model`, `--endpoint`, `--preview-size`
(256/512/768/1024), `--measurements`, and `--keep-alive` (integer seconds
0..86400). The endpoint includes the Ollama API path. Nonlocal endpoint
configuration is explicit opt-in to remote use. Inspect always measures pixels
and never contacts a backend. For compatibility, inspect still accepts the
previously shared describe settings (with existing validation), but hides them
from help: they do not affect its measurements.

Process clients can pass `--protocol-version 1`, `--expect-profile-version`, and
`--expect-prompt-sha256` to reject changed task definitions before inference.
These guards use the selected profile's version and prompt, not the default's.
These snapshot guards are primarily for batch consumers. A model name is not a
content pin: the response reports the inventory's actual model identity/digest.

## Terminal result

Every terminal result has these fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer 1 |
| `status` | `ok` or `error` |
| `input` | `path` (absolute string or null for bytes); after decoding: SHA-256 of encoded bytes, oriented dimensions, aspect ratio, format, frame count, alpha presence |
| `measurements` | Object or null; palette, color/luminance distributions, transparency, regional colors, intensity variation, symmetry, dHash/DCT hashes, and legacy luminance/edge measurements |
| `predictions` | Selected profile's description object or null |
| `provenance` | Task; description results additionally record backend, model inventory entry/digest, Ollama version, profile/version/prompt, preprocessing and generation settings |
| `diagnostics` | Bounded diagnostics; backend timing and response termination details where available |
| `elapsed_seconds` | Nonnegative finite elapsed time; may be zero for preflight/client failures |
| `error` | null on success, otherwise `{ "code": "...", "message": "..." }` |

Preprocessing is versioned, and requested measurements record a measurements
version. No application/database/job IDs are part of this contract. Callers attach
their own correlation IDs to the process they launch.

Wallpaper predictions contain required fields: `caption`, `subjects`, `medium`,
`mood`, `lighting`, `composition`, `tags`, `text_present`, `watermark_present`.
Their schema and validation live in `imagescope/profiles/wallpaper.py`.
Wallpaper-v3 limits captions to 1,000 characters and individual labels to 128;
oversized predictions produce `invalid_response`, not truncated success data.
Empty or Unicode-whitespace-only captions also produce `invalid_response`;
empty label arrays remain valid. This pre-release validation correction retains
wallpaper-v3 and its unchanged prompt/schema.

Input decoding and requested measurements run before model checks or inference,
within the same request deadline. Request-field validation still runs first;
invalid image input takes precedence over backend endpoint/model errors.
Measurements/input/provenance remain populated after model-check or inference
failures. A failed request is still `status: error`: consumers must not mistake partial data for a
successful description or replace a good prior prediction with it. Diagnostics
may preserve pre-cleanup labels and at most 8192 characters of invalid final model
output. Internal model thinking text is never included.

## Built-in task profiles

The built-in registry contains `wallpaper` (wallpaper-v3, unchanged prompt/schema)
and `general` (general-v1). Select with `--profile` or Python
`AnalysisRequest(profile=...)`; omission retains wallpaper for compatibility.
Unknown names fail before decoding/inference (`invalid_request` in the API;
argument-parser error in the CLI). Inspect accepts the existing hidden profile
option for compatibility but does not apply a description profile.

General predictions have exactly these required fields:

| Field | Contract |
| --- | --- |
| `summary` | Nonblank string, at most 1,000 characters; prompt asks for 1–3 factual sentences |
| `subjects` | Array of at most 12 strings, each at most 128 characters; may be empty |
| `text_present` | Boolean; presence detection, not transcription |

General cleanup trims summary ends, normalizes subject whitespace/case, removes
empty/duplicate labels, and invents no content. Unknown fields, invalid types,
blank summaries (including Unicode whitespace), or oversized text are rejected.

The profile owns its prompt, schema, validation, normalization, and presentation
fields. Ollama requests use its schema and prompt, plus a JSON continuation prefix
for that profile's summary field. Both full JSON objects and continuations are
accepted. Responses with another profile's fields return `invalid_response`,
including responses from custom Python backends. Partial measurements survive.

Successful descriptions identify `provenance.profile`, `profile_version`, and
`prompt`. `validate_result` selects validation by that identity and rejects unknown
profiles, mismatched versions/prompts, and predictions with another profile's
shape as `protocol_error`. Consumers of saved older profiles must retain the
matching validator rather than treating a different version as current.

Pre-release Python backend contract revision: `describe(image, model,
preview_size, *, profile)` receives the selected built-in name. Optional
`settings(preview_size, *, profile)` also receives it. Custom backends must accept
that keyword; no silent fallback to wallpaper-only methods is attempted. Ollama's
standalone helpers still default to wallpaper. Package 0.1.0 and protocol/schema 1
remain unchanged: existing wallpaper payloads retain their shape; the new profile
is explicitly selected. Preprocessing remains version 3; current measurements are version 6 (see below).

## Explicit color policies

Analysis requests additionally accept `color_policy` (`legacy-v1`, default, or
`srgb-v1`) and `assume_srgb` (boolean, default false; requires `srgb-v1`). The CLI
exposes `--color-policy` and `--assume-srgb` on inspect/describe. Discovery lists
`color_policies` and `default_color_policy`. Metadata-only requests are unchanged.

`COLOR_POLICY.md` specifies the versioned algorithm. Default preprocessing remains
version 3 with unchanged pixels; opt-in sRGB conversion uses preprocessing version
4, before reduction/orientation/compositing. Both retain measurement algorithms
version 6. Color provenance is additive under schema/protocol 1 and lives in
`provenance.preprocessing.color_management`. On color failure, the requested
policy remains in provenance and available source details are in
`diagnostics.color_management`; no model is contacted.

Structured color failures include `unknown_color_space`, `unsupported_color_mode`,
`color_management_unavailable`, `invalid_color_profile`, `color_profile_too_large`,
and `color_conversion_failed`. Existing decoding resource errors still apply.
An explicit assumption never overrides an invalid embedded profile. Human output
also identifies unmanaged, converted, declared, or explicitly assumed colors.

The historical measurement sections below describe the default **legacy-v1**
input preparation. Their statements that ICC is not transformed do not apply to
`srgb-v1`. Sampling/formulas remain the same; compare results only with matching
color policy, preprocessing version, and measurement settings.

## Region inspection (ROI version 1)

Inspect requests optionally accept `region=(left, top, right, bottom)`; the CLI
uses `--region LEFT TOP RIGHT BOTTOM`. Coordinates are half-open integer pixel
edges in the EXIF-oriented original. Invalid shapes, empty rectangles, out-of-bounds
regions, and use with describe are rejected as `invalid_request`.

Region requests use preprocessing version 5, existing measurements version 6,
and schema/protocol 1. They apply color handling, orientation, and cropping before
working-image reduction; native reduced JPEG decoding is disabled. Source identity
and input dimensions remain original-image metadata. All measurements describe the
crop. Provenance records ROI version 1, original bounds, source/crop/working sizes,
and rational working-to-source edge mapping. `downsampled` refers to reduction of
the crop, not simply selecting a smaller area. Discovery advertises
`region_inspection` with version, supported tasks, and coordinate space.

See `REGION_INSPECTION.md` for the complete mapping, sampling, memory-limit, and
preview-rounding contract. Working transparency bounds are not exact source-alpha
bounds. Existing whole-image requests retain their pixel behavior and preprocessing
versions. TIFF dimension reporting is corrected to use stored IFD dimensions before
EXIF orientation, avoiding double-swapping on newer Pillow versions.

## Optional histograms (measurements version 7)

`AnalysisRequest.histograms` is a boolean, default false; CLI `--histograms` opts
in. Inspect already measures; describe additionally requires `measurements=True`
or `--measurements`. Without opt-in, results retain measurements version 6, all
existing values, and their existing shape/settings. With opt-in, measurement
provenance records version 7 and `measurement_settings.histograms: true`.

`measurements.histograms` (version 1) adds 256-bin integer-alpha-weighted RGB and
linear-sRGB luminance arrays, total opacity mass, visible sampled pixels, sampling
provenance, and exact sampled endpoint fractions. The existing palette/distribution
thumbnail bounds sampling at 256×256. Existing measurement algorithms are unchanged.
Histogram counts sum to total alpha mass, not pixel count; fully invisible samples
produce zero arrays and null endpoint fractions. Endpoint occupancy is not proof
of clipping. The complete contract and comparison rules are in `HISTOGRAMS.md`.

Discovery advertises `histograms` with version, measurement version, opt-in status,
and bin count. ROI and explicit color policies compose with histograms; analysis
schema/protocol and preprocessing versions are unchanged. JSONL failure results
retain completed histograms if a subsequent inference step fails.

## Palette extraction (measurements version 3)

`--palette-size N` / Python `AnalysisRequest(palette_size=N)` accepts integers
1–64 on inspect and describe; default 6. Describe still requires
`--measurements` to compute any measurements. Each palette entry retains `hex`
and `fraction` and adds `rgb` and `hsl` arrays. All three representations are
always present in machine results; human output uses HEX.

- RGB is encoded sRGB, integer channels 0–255; HEX is its lowercase `#rrggbb`
  representation. Embedded ICC profiles are not transformed.
- HSL is derived from that same rounded RGB: hue in degrees [0, 360), saturation
  and lightness in percent [0, 100], rounded to two decimals. Neutral hue is 0.
- Fractions are opacity-weighted shares rounded to four decimals, so their sum
  may differ slightly from 1. Fully transparent input returns `palette: []`.
- Fully transparent pixels (including hidden RGB) do not contribute. Partial
  pixels contribute alpha/255, normalized by total contributing opacity rather
  than canvas area. Extracted colors have no assumed background.
- The first frame is EXIF-oriented and bounded to 2048 pixels on its longest
  side. Alpha-bearing sources convert to RGBA **before** resizing, including
  palette-indexed images. Pillow LANCZOS resizing uses premultiplied, encoded
  sRGB channels and alpha, with 8-bit intermediate precision and unpremultiplying
  afterward. This is not linear-light resizing; very low alpha may incur rounding.
  The palette working image is then bounded to 256×256 with the same convention.
- Opaque RGB inputs retain Pillow's existing BICUBIC palette thumbnail and
  six-color median-cut behavior by default. For nonopaque input, unique visible RGB colors are weighted by summed
  opacity. If necessary, weighted median cut splits the box with largest weighted
  squared RGB error along its highest-variance channel at cumulative half-weight.
  Representatives are weighted means, rounded to nearest integer (ties to even).
  Duplicate representatives are merged. No colors are added to fill a request;
  output contains at most N colors. Quantization may collapse colors and return
  fewer than N even when more source RGB values exist. Fractions and colors are approximations at
  the working resolution, not exact full-resolution counts; ordering is not a
  semantic contract.

The AI preview remains white-composited RGB. Legacy luminance mean/spread,
dHash, and edge density also use white-composited pixels, not the
background-independent palette pixels.
Preprocessing version 3 records this distinction and alpha resizing convention;
measurement provenance records the requested palette size. Transparency metrics
are specified below under measurements version 5. This deliberately changes transparent-image measurement
semantics from version 2; opaque default behavior is retained. The RGB/HSL fields
and palette-size option are additive under protocol/schema 1. Package 0.1.0 and
the wallpaper prompt/profile remain unchanged.

## Distributions and palette relationships (measurements version 4)

All requested measurements now include `color_distribution`,
`luminance_distribution`, and `palette_distances`. These are measured statistics,
not quality, aesthetic, or suitability scores. They run by default in inspect
and in describe with `--measurements`; there are no additional selection flags.
Package/protocol/schema/profile versions and preprocessing version 3 are unchanged.
Existing palette, mean/spread, hash, and edge calculations are unchanged.

Distributions use the oriented, bounded RGB/RGBA working image, downsampled to
at most 256×256 with the palette's conventions: BICUBIC for opaque images,
premultiplied encoded-sRGB8 LANCZOS for nonopaque images. Embedded ICC profiles
are not transformed. Unlike legacy white-composited mean/spread, these new
statistics have **no assumed background**: zero-alpha pixels are ignored and
partial pixels contribute alpha/255. Shares normalize by total contributing
opacity; this is an approximation at working resolution, not source pixel counts.

`color_distribution` contains:

- `hue_histogram`: 12 fractions for [0,30), [30,60), …, [330,360) degrees.
  HSL hue is derived from encoded sRGB. Pixels with saturation <= 10% are
  near-neutral and excluded; fractions normalize by chromatic opacity only.
  No chromatic pixels means null, not an invented hue. Fractions round to six
  decimals and may not sum to exactly 1 after rounding.
- `saturation_percentiles` and `lightness_percentiles`: HSL values in [0,100],
  including neutrals (achromatic saturation is 0). Keys are `p05`, `p25`, `p50`,
  `p75`, `p95`, rounded to six decimals.
- `near_neutral_fraction`: opacity share with HSL saturation <= 10%, rounded
  to six decimals. This is a saturation threshold, not a semantic judgment.

`luminance_distribution` contains:

- `percentiles`: same keys, in [0,1]. Decode sRGB channels c in [0,1] to linear
  light: c/12.92 for c <= 0.04045, otherwise ((c+0.055)/1.055)^2.4; luminance
  is 0.2126 R + 0.7152 G + 0.0722 B.
- `near_black_fraction`: share with linear luminance <= 0.01.
- `near_white_fraction`: share with linear luminance >= 0.95.
  These fractions and percentiles round to six decimals.

Percentiles use the inverse weighted empirical CDF: the first sorted observed
value whose cumulative opacity is >= p/100 of total opacity, without interpolation.
A uniform image therefore has identical percentiles. A fully transparent image
has null for every distribution member (including percentile objects and shares).
All available outputs are finite; no NaN/infinity sentinels are used.

`palette_distances` is an array of `{i, j, delta_e76}` for each unordered pair
of indices into the emitted palette (i < j). Empty or single-color palettes have
no pairs. Convert the palette's rounded encoded sRGB to linear RGB, then XYZ:
X = .4124564 R + .3575761 G + .1804375 B;
Y = .2126729 R + .7151522 G + .0721750 B;
Z = .0193339 R + .1191920 G + .9503041 B.
Convert to CIELAB with reference white [0.95047, 1, 1.08883]. Use
f(t) = cube-root(t) above (6/29)^3, otherwise t/(3*(6/29)^2)+4/29,
applied to XYZ divided by reference white. L* = 116 f(Y)-16,
a* = 500 (f(X)-f(Y)), b* = 200 (f(Y)-f(Z)). Distance is Euclidean ΔE76 in Lab, nonnegative and rounded to four decimals.
It is an approximate perceptual distance, not ΔE2000 or a semantic distinction;
no similar/distinct cutoff is asserted. At most 64 colors produce 2,016 pairs.

The 256×256 statistics and 2,016-pair cap bound computation/output. Human summaries
show luminance p05/p50/p95, neutral/near-black/near-white shares, and the minimum
pair distance when available; full histograms, HSL percentiles, and all pairs are
available in JSON/JSONL. Empty distributions explicitly report no visible pixels.
This additive output is deliberately recorded as measurements version 4.

## Transparency and spatial colors (measurements version 5)

Two additive measurements run with inspect and `describe --measurements`.
They use the first, EXIF-oriented RGB/RGBA working image, at most 2048 pixels on
its longest side, **before white compositing**. These are working-image statistics,
not exact full-source counts or source-coordinate bounds: alpha-aware reduction
can soften boundaries, remove tiny features, and change transparency shares.
Existing preprocessing version 3 and prior measurement calculations are unchanged.

`transparency` contains:

- `width`, `height`: working-image dimensions defining the coordinate system.
- `transparent_fraction`: count of alpha == 0 divided by working canvas pixels.
- `translucent_fraction`: count of 0 < alpha < 255 divided by working canvas pixels.
  These are unweighted pixel shares in [0,1], rounded to six decimals (human
  output uses percentages), unlike opacity-weighted palette/distribution shares.
  Opaque pixels make up the remainder. RGB input is fully opaque.
- `visible_bounds`: `[left, top, right, bottom]` enclosing all alpha > 0 pixels,
  with integer coordinates, inclusive left/top and exclusive right/bottom.
  Fully transparent input has null bounds; an opaque image has `[0,0,width,height]`.
  Hidden RGB does not affect counts or bounds.

`spatial_color` contains `rows: 3`, `columns: 3`, working `width`/`height`, and
`regions`: nine row-major entries. Each entry has zero-based `row`, `column`,
working-image `bounds` in the same half-open convention, `palette`, and
`mean_luminance`. Each axis is split into three contiguous chunks; the first
size%3 chunks receive one extra pixel. Images smaller than three pixels along an
axis have trailing zero-area regions, not upscaled invented samples.

Each nonempty region is cropped **before** thumbnail reduction, avoiding color
bleed between regions. Use the palette conventions: at most 256×256, BICUBIC for
opaque crops and premultiplied encoded-sRGB8 LANCZOS for nonopaque crops; no ICC
transform or assumed background. `palette` is at most three colors, independent
of global `--palette-size`, with the existing HEX/RGB/HSL and local opacity-share
fractions. This is regional quantization, not a ranked semantic accent selection.
`mean_luminance` is the alpha-weighted mean of linear-sRGB luminance (the same
transfer function/coefficients as version 4) over that regional thumbnail, rounded
to six decimals in [0,1]. Zero-area or fully transparent regions have an empty
palette and null mean luminance. There are no NaN/infinity values.

At most nine bounded thumbnails and 27 regional colors are emitted. Human output
summarizes transparency, visible working bounds, and a compact 3×3 grid of each
region's leading HEX color and mean luminance (`none` where unavailable).
JSON/JSONL expose all regional colors, shares, coordinates, and values.
Measurements advance to version 5; package 0.1.0, protocol/schema 1, preprocessing
3, and both task-profile versions remain unchanged. No symmetry, extra hashes,
local-detail statistics, or quality/suitability scores are introduced here.

## Detail, symmetry, and similarity (measurements version 6)

All requested measurements additionally emit `local_detail`, `symmetry`, and
`phash64`. These are deterministic intensity comparisons, not sharpness, beauty,
quality, or wallpaper-suitability judgments. Prior fields retain their algorithms.
Package 0.1.0, protocol/schema 1, preprocessing 3, and task profiles are unchanged.

These three measurements use the oriented working image **composited on white**,
then Pillow's `L` conversion (8-bit encoded-intensity grayscale, not linear-light
luminance). This matches the background convention of the existing edge grid and
dHash, not the background-independent color distributions. Hidden RGB at alpha 0
cannot affect them. Fully transparent images behave like white; uniform images
have zero local variation, perfect mirror similarity, and a zero pHash. Tiny
images are resized for these fixed-resolution comparisons, not treated as missing.

`local_detail` contains `intensity_std_3x3`: a row-major 3×3 array of population
standard deviations (ddof=0) of grayscale intensity divided by 255. Resize to
192×192 with explicit Pillow BICUBIC, then partition into nine 64×64 cells.
Values lie in [0,0.5] and round to six decimals. High variation can mean shading,
texture, or a hard boundary; it is not a measured focus/sharpness verdict. The
existing `edge_density_3x3` is unchanged and remains separately available.

`symmetry` uses the same 192×192 grayscale array and contains:

- `left_right`: 1 - mean(abs(I - horizontally flipped I)).
- `top_bottom`: 1 - mean(abs(I - vertically flipped I)).

I is grayscale intensity in [0,1]. Both scores are in [0,1], rounded to six
decimals; 1 means identical mirrored intensity and 0 means maximum disagreement.
The names describe the halves compared, not an ambiguous named axis. These are
low-resolution grayscale similarities; color-only differences and small features
may be missed. They do not establish semantic symmetry or image quality.

`phash64` is `{algorithm: "dct-ii-32-low8-ac-median-v1", hash: "..."}`. The hash
is exactly 16 lowercase hexadecimal characters. Algorithm:

1. Resize white-composited `L` to 32×32 using LANCZOS and divide values by 255.
2. Compute an orthonormal separable DCT-II. For N=32, basis[k,n] =
   sqrt(2/N) * cos(pi*(n+0.5)*k/N), with row k=0 scaled by 1/sqrt(2).
3. Take the top-left 8×8 coefficients, rounded to 12 decimal places to suppress
   floating-point residue. Compute the median of the 63 AC coefficients only.
4. Set each AC bit iff its coefficient is strictly greater than that median.
   Force the DC bit to zero. Pack all 64 positions in row-major order, first
   position most significant. There are 63 data bits in the 64-bit container.

Compare hashes only within the same algorithm identifier using XOR/popcount
(Hamming distance, 0–63). Zero distance is not proof of identical images; all
uniform intensities intentionally collide. No semantic similarity threshold is
asserted. This is a DCT pHash, not the existing horizontal difference hash
`dhash64`; that field remains unchanged.

Work is bounded to one 192×192 array and one 32×32 DCT, with fixed-size outputs.
Human output shows the variation grid, both mirror scores, and the hash with its
algorithm identifier. JSON/JSONL include the complete fields. These additions
advance measurements to version 6 and run with inspect or describe measurements.

The palette-size ceiling was expanded from 24 to 64 as a compatible option
extension. Measurements remain version 6: existing size choices, algorithms,
rounding, and the six-color default are unchanged. Regional palettes remain
capped at three colors each.

## Event stream

`--events=jsonl` emits UTF-8 JSON, one record per line, flushed as stages change:

```json
{"protocol_version":1,"type":"hello","schema_version":1}
{"protocol_version":1,"type":"progress","stage":"preparing","label":"Preparing image"}
{"protocol_version":1,"type":"progress","stage":"checking","label":"Checking local model"}
{"protocol_version":1,"type":"progress","stage":"generating","label":"Generating image description"}
```

The final record has `type: "result"` and a `result` field containing the complete
terminal object above. Exactly one hello and terminal result are expected, and
nothing may follow the terminal result. Inspect omits model-related progress;
failures may end at any stage. Labels are human-readable and are not stable codes.
No percentages, token-content stream, or job-control commands are implied.

The analyzer limits each serialized record to 1 MiB, including its terminating
newline and the result-event envelope. This bound also applies to API results
and plain JSON results with space reserved for that envelope. Oversized results
become a minimal `output_too_large` failure; input, partial data, and diagnostics
are discarded in that case. Doctor output is subject to the same record limit.

The external Image Lab desktop reader (not shipped in this distribution) accepts
at most 1 MiB per event and 2 MiB per request stream,
requires newline termination, and bounds captured diagnostic stderr. It fails the
job on malformed output, duplicate terminal results, missing hello/result,
incompatible versions, process crashes, or a success record with nonzero exit.
The desktop additionally verifies source path, requested model/profile/prompt,
and requested measurement presence before storage, and rechecks its own source
fingerprint before committing. Inference progress belongs to the launching job.

## Exit codes and errors

- `0`: successful request.
- `1`: input, backend, or inference failure.
- `2`: invalid invocation/request or incompatible requested protocol.
- `130`: cooperative cancellation.

Argument-parser errors print usage on stderr and may exit without a JSON result.
Hard crashes/kills may also lack a terminal record. Consumers must observe **both**
the terminal record and process exit, with their own deadline.

Initial error codes: `invalid_request`, `incompatible_protocol`, `analyzer_changed`,
`invalid_input`, `unsupported_image`, `input_too_large`, `image_too_large`,
`source_changed`, `model_missing`, `backend_unavailable`, `backend_error`,
`invalid_response`, `output_too_large`, `timeout`, `cancelled`, `analysis_failed`. New error codes may
be added; unknown codes must still be treated as failures. English messages can
change. Client-side malformed-result validation uses `protocol_error`.

The analyzer has no persistence, retry queue, hotkey, clipboard, screenshot, or
notification interface. Those policies belong to its consumers.
