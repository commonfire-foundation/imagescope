# Imagescope

**Local image analysis using AI and deterministic measurements.**

Imagescope turns an image into structured observations: colors, transparency,
luminance, spatial patterns, similarity hashes, and optional AI descriptions.
Use it from the terminal, in shell pipelines, or as a Python library inside
another application.

Measurements work without a model. Descriptions run through local Ollama.
Measured properties and model predictions stay separate, so applications can
use either without treating a generated description as a verified fact.

## What you can do

- **Inspect image assets:** extract up to 64 colors in HEX, RGB, and HSL;
  measure transparency, visible bounds, luminance, and regional color distribution.
- **Describe visible content:** generate a summary, subject labels, and
  text-presence predictions for photographs, screenshots, illustrations, and
  other supported images.
- **Build comparison workflows:** use perceptual hashes, mirror similarity, and
  local intensity variation as inputs to your own tools—not as quality scores
  or proof that two images are identical.
- **Integrate analysis:** consume JSON, stream JSONL progress/results, pass image
  bytes through stdin, or call the Python API.

Wallpaper captions and search tags are one optional description profile.
Imagescope is not a wallpaper manager, image editor, or catalog: it analyzes
one image per request, does not modify the source, and keeps no image history.

## Quick start

After installation, measure an image without Ollama:

```sh
imagescope inspect image.png --palette-size 16
imagescope inspect image.png --json
```

With Ollama running and `qwen3-vl:4b` explicitly installed, describe its content
or combine predictions with measurements:

```sh
imagescope describe image.jpg --profile general
imagescope describe image.jpg --profile general --measurements --json
```

The examples select `general` explicitly. RC1 still defaults to the `wallpaper`
profile when `--profile` is omitted; this documentation does not change that
behavior.

## Install

Requires Linux and Python 3.11+. **Use `uv tool` for a user installation on
Omarchy**; it isolates Pillow/NumPy and exposes `imagescope` without changing
system Python or requiring sudo. This assumes `uv` is installed; check with
`uv --version`. Imagescope is not published to PyPI, so install a downloaded
release artifact rather than `uv tool install imagescope`.

Download the RC1 wheel and `SHA256SUMS` from:

https://github.com/commonfire-org/imagescope/releases/tag/v0.1.0rc1

From the download directory:

```sh
sha256sum --check --ignore-missing SHA256SUMS
uv tool install --no-python-downloads ./imagescope-0.1.0rc1-py3-none-any.whl
imagescope --version
imagescope info --json
```

Confirm the wheel is reported `OK`. The checksum file also lists the optional
source archive; `--ignore-missing` allows downloading just the wheel. Checksums
detect changed bytes, not publisher identity. Dependencies may be downloaded;
this is not an offline bundle. `--no-python-downloads` requires an existing
compatible interpreter; optionally select one with `--python /path/to/python3`.

If `imagescope` is not found, check `uv tool dir --bin` and your PATH. To opt into
uv updating your shell configuration, run `uv tool update-shell`, then open a new
terminal. Do not use sudo or overwrite an unrelated executable to resolve a
name conflict.

### Upgrade or reinstall

Download and verify the desired release wheel, then repeat installation with
`--force`. For example, reinstall RC1:

```sh
uv tool install --force --no-python-downloads ./imagescope-0.1.0rc1-py3-none-any.whl
```

For an upgrade, substitute the newly downloaded wheel's actual filename. This
explicit artifact workflow also supports rollback to a previous wheel; do not
rely on `uv tool upgrade imagescope` to discover GitHub releases.

### Uninstall

```sh
uv tool uninstall imagescope
```

This removes uv's Imagescope environment and managed command. It does not remove
Ollama, models, images, downloaded release files, shared uv caches, or PATH edits
made by `uv tool update-shell`. No catalog or persistent image history needs
cleanup. Uninstall with the same tool that installed the application.

### Alternative: pipx

If you already use pipx, it provides the same isolated-tool approach:

```sh
pipx install ./imagescope-0.1.0rc1-py3-none-any.whl
# Reinstall or replace with a newly downloaded wheel:
pipx install --force ./imagescope-0.1.0rc1-py3-none-any.whl
pipx uninstall imagescope
```

Use `pipx ensurepath` only if you want it to update shell PATH configuration,
then open a new terminal. Choose uv **or** pipx, not both for the same command.

### Development checkout

Use a project virtual environment rather than a managed tool installation:

```sh
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/imagescope --version
```

Remove only that project-owned `.venv` when it is no longer needed; do not delete
a shared environment. See `CONTRIBUTING.md` for tests and builds.

Image descriptions additionally require a running Ollama instance and an explicitly
installed `qwen3-vl:4b` model. `inspect` works without Ollama. Installation of this
Python package does not install or download models. Use `imagescope doctor`
to inspect the existing runtime before opting into any model download yourself.

## Command-line workflows

Use JSONL for progress and a terminal result, inspect the available profiles,
or check your Ollama runtime:

```sh
imagescope describe image.jpg --profile general --measurements --events=jsonl
imagescope info --json
imagescope doctor --json
```

For wallpaper-oriented captions and search labels, select that profile:

```sh
imagescope describe image.jpg --profile wallpaper --json
```

Read encoded image bytes from stdin, without creating an image file:

```sh
grim -g "$(slurp)" - | imagescope describe --stdin --profile general --json
```

Only invoke a screenshot pipeline when the screen content is intended for analysis.
Use a wrapper to handle region-selection cancellation and clipboard/notification
policy; the analyzer itself neither captures the screen nor changes the clipboard.

Without output flags, the command prints a compact summary to stdout: dimensions,
a description and profile-specific labels, and measurement summaries when
measurements are requested. Output wraps to the terminal width. Progress and
errors go to stderr. Interactive terminals show an animated spinner with the
current stage and elapsed time, including while waiting for stdin or the model.
The spinner clears on completion, failure, timeout, or cooperative cancellation.
Redirected stderr and `TERM=dumb` use plain stage lines instead. No ANSI color or
cursor-hiding sequences are used.

`doctor` also prints a human-readable runtime/model summary by default.
`--json` emits one terminal object. `--events=jsonl` emits hello, progress, and
exactly one terminal result on stdout. Neither machine-output mode uses a spinner.
Logs are never mixed into machine-output stdout. See `PROTOCOL.md` for the
version-1 contract.

In a source checkout, replace `imagescope` with `python -m imagescope`.
Paths beginning with `-` can be supplied after `--`.

## Analysis modes

| Mode | Output | Model required? |
| --- | --- | --- |
| `inspect` | Image metadata and deterministic pixel measurements | No |
| `describe --profile general` | Visible-content summary, subjects, and text presence | Yes |
| `describe --profile wallpaper` | Caption and search-oriented style/content labels | Yes |
| `describe --profile general --measurements` | General description plus separate measurements | Yes |

`wallpaper` remains the default description profile in RC1. Select `general`
for the general-purpose description shape; measurements are independent of the
selected profile.

Both commands share input, output, timeout, palette-size, and protocol controls. Only
`describe --help` lists inference options: `--profile`, `--model`, `--endpoint`,
`--preview-size`, `--keep-alive`, and `--measurements`. Inspect always measures;
old invocations with these flags remain accepted and validated as hidden
compatibility options, without affecting the measurements.

Images are decoded and requested measurements computed before contacting Ollama.
If model checks or generation fail, JSON/JSONL results retain that partial data
and input metadata with `status: error`; human mode still reports the error.

Profiles are built in, selected explicitly with `--profile`; no plugins are loaded.
`imagescope info --json` lists each profile's version and exact prompt. The Python
API accepts `AnalysisRequest(path, profile='general')`. Both profiles share input
preparation, optional measurements, model transport, deadlines, and error handling.
`inspect` remains independent of profiles and never contacts a model.

```sh
imagescope describe image.jpg --profile general --json
imagescope describe image.png --profile general --measurements --palette-size 8
```

General-v1 predictions contain `summary` (one to three factual sentences),
`subjects` (up to 12 concise labels), and `text_present` (boolean, not OCR).
Summary text must be nonblank and at most 1,000 characters; labels are limited to
128 characters each. Empty subject arrays are valid. Results identify the selected
profile/version/prompt, and predictions are validated against the selected
profile's schema. These are model observations, not verified facts.

The wallpaper-v3 profile preserves conservative label cleanup, the 768px preview
default, white transparency background, and Qwen JSON-continuation handling.
Version 3 adds enforced length limits: 1,000 characters per caption and 128 per
label. Oversized predictions are rejected rather than silently truncated.
Only the first frame/page is analyzed. EXIF orientation is applied. Predictions
are not human-confirmed facts; no calibrated confidence score is supplied.
Text detection is not OCR. Native image metadata is not rewritten.

Supported formats: JPEG, PNG, WebP, BMP, TIFF, GIF. Large originals are analyzed
through a working image no larger than 2048px on its longest side; the model
preview is then reduced to the requested size (768px by default). JPEG decoding
uses native reduced-resolution loading before allocating the raster. Other
formats may require a full raster internally, but decoding happens in a separate
process with a 1.5 GiB address-space budget, a CPU budget below 30 seconds, and a
30-second wall-clock limit. Alpha-bearing images convert to RGBA before reduction
so indexed transparency and hidden RGB are handled correctly; those copies remain
inside the decoder's resource budget. EXIF orientation follows reduction.

Original oriented dimensions and SHA-256 always describe the original input,
not the working preview. Preprocessing version 3 records working dimensions,
decoder strategy, downsampling, and alpha handling. Measurements version 6 adds
regional intensity variation, mirror similarity, and a DCT perceptual hash to
version 5's transparency/spatial colors and version 4's color/luminance statistics. Legacy luminance mean/spread,
dHash, and edge density still use a white composite. Existing saved results are
not rewritten.

### Extracted colors

```sh
imagescope inspect image.png --palette-size 64 --json
imagescope describe image.png --measurements --palette-size 8 --events=jsonl
```

`--palette-size` accepts 1–64, including 16, 24, 32, 48, and 64; the default remains
six. It is a maximum, not a padding target: limited-color images return only
available quantized colors. Palette extraction is bounded to a 256×256 thumbnail
and returns approximate proportions. Describe still needs `--measurements`.

Each machine-output entry contains lowercase `hex`, integer `rgb` channels
0–255, `hsl` as hue degrees [0, 360), saturation/lightness percentages [0, 100]
rounded to two decimals, and `fraction` rounded to four decimals. Neutral hue is
0. Representations describe the same quantized RGB color. Human output displays
HEX; JSON/JSONL always include all three representations.

Fully transparent pixels and their hidden RGB values are ignored; partially
transparent pixels are weighted by opacity. Proportions use total visible opacity,
not canvas area. Fully transparent input has an empty palette. The AI still sees
a white-composited preview: extracted palette colors have **no assumed background**
and are not necessarily colors in that preview. Alpha-aware resizing uses
premultiplied encoded sRGB with 8-bit precision, not linear-light color mixing.
Opaque default extraction keeps the existing behavior. See `PROTOCOL.md` for
quantization, rounding, and resizing details. No semantic theme roles or generated
Base16/Base24 schemes are implied by extracting 16 or 24 colors.

### Color and luminance distributions

Inspect and `describe --measurements` also emit:

- `color_distribution`: a 12-bin hue histogram, HSL saturation/lightness
  percentiles, and near-neutral opacity share (saturation <= 10%).
- `luminance_distribution`: linear-sRGB luminance percentiles and near-black
  (<= 0.01) / near-white (>= 0.95) opacity shares.
- `palette_distances`: all unordered palette pairs with CIELAB D65 ΔE76 distances.
  These compare the emitted palette colors, not semantic theme roles.

Distributions use at most 256×256 pixels, ignore hidden transparent RGB, and
weight partial opacity without assuming a background. Percentiles are p05, p25,
p50, p75, p95 using the inverse weighted empirical CDF (no interpolation).
Fractions round to six decimals. Hue bins cover 30 degrees each and exclude
near-neutral pixels; without chromatic pixels the histogram is null. Fully
transparent images have null distribution members and no palette pairs.

Human output summarizes visible luminance, neutral/black/white shares, and the
minimum palette distance; JSON/JSONL contain the complete statistics. The legacy
`mean_luminance` can differ because it measures the **white composite**. These
statistics are not beauty, image-quality, or suitability scores. `PROTOCOL.md`
specifies units, rounding, color conversions, and thresholds.

### Transparency and regional colors

`transparency` reports the fraction of fully transparent and partially transparent
pixels, plus visible-content bounds before white compositing. Counts are unweighted
canvas shares; human output shows percentages. Bounds are half-open
`[left, top, right, bottom]` in the **oriented working image**, whose dimensions
are included. They are not full-source coordinates. Fully transparent input has
null bounds; even alpha 1 counts as visible. Downsampling can change these counts
and soften or remove tiny features.

`spatial_color` divides that working image into a fixed 3×3 grid, in row-major
order. Each region contains coordinates, up to three dominant colors with local
opacity-weighted fractions, and alpha-weighted linear-sRGB mean luminance.
Cropping happens before regional thumbnail reduction (at most 256×256), avoiding
cross-region color mixing. The three-color regional maximum is independent of
`--palette-size`. Transparent or zero-area cells have no colors and null luminance;
tiny images have trailing empty cells rather than invented pixels.

These fields run in inspect and `describe --measurements`, including partial
results on inference failure. Human output shows a compact regional summary;
JSON/JSONL include every region and color.

### Detail, symmetry, and perceptual similarity

Requested measurements also include:

- `local_detail.intensity_std_3x3`: regional grayscale population standard
  deviation in [0,0.5] on a 192×192 working view, rounded to six decimals.
- `symmetry.left_right` and `symmetry.top_bottom`: one minus mean absolute
  mirrored intensity difference on that view, in [0,1]. Higher means closer
  grayscale agreement, not better image quality.
- `phash64`: a 16-digit hexadecimal DCT pHash with algorithm identifier
  `dct-ii-32-low8-ac-median-v1`, alongside the unchanged `dhash64`.

These use a **white composite**, like the existing edge grid and dHash, not the
background-independent color measurements. Fully transparent images behave like
white: zero variation, perfect mirror similarity, and a zero hash. Tiny inputs
are resized to the fixed working resolutions. Color-only differences may be lost.

The pHash uses an orthonormal 32×32 DCT-II and the median of the top-left 8×8 AC
coefficients; the DC bit is forced to zero (63 data bits in a 64-bit container).
Use Hamming distance only between hashes with the same algorithm identifier.
Equal hashes do not prove identical images; all uniform intensities collide.
`PROTOCOL.md` specifies resizing, rounding, thresholds, and bit packing.

Human output shows the variation grid, mirror similarities, and identified hash;
JSON/JSONL expose the same measurements. None is a beauty, quality, focus, or
wallpaper-suitability score.

Safety ceilings remain: 64 MiB encoded input, 500 megapixels in source headers,
and bounded decoder memory/time. This does not promise every 500MP image can
fit the memory budget. Limits produce specific structured errors, not a blanket
25MP rejection. HTTP replies remain bounded to 2 MiB. Serialized results/events (including
provenance, diagnostics, and the event envelope) are bounded to 1 MiB; an oversized
result is replaced by a small `output_too_large` failure without partial data. OS-enforced decoder limits
are required; unsupported platforms return `decoder_unavailable` rather than
silently decoding without protection. Linux also ties the decoder's lifetime to
its parent, so cancellation cannot leave an orphan decoder running.

## Runtime and privacy

The default endpoint is local Ollama. An explicit `--endpoint` can opt into a
remote HTTP(S) API; doing so sends the preview image to that server. There is no
automatic remote fallback. Redirects are rejected. Input images are untrusted data,
not commands; model output is schema-validated and never executed.

`--timeout 300` sets a Linux CLI whole-request deadline, including stdin and
inference. The Python API bounds backend requests and checks between stages; it
is not a hard preemptive deadline for arbitrary caller-supplied backends.

`--keep-alive 300` asks Ollama to retain the model for five minutes. Repeated batch
requests refresh residency. `--keep-alive 0` explicitly asks Ollama to unload after
its request; use carefully if other applications share that model. This is a
request to Ollama, not a memory-reclamation guarantee.

SIGINT/SIGTERM produce a cancellation result when possible. Killing this client
or reaching a timeout does **not** guarantee Ollama stops work already submitted.
There is no silent retry. Hard kills cannot produce terminal events. Separate
clients are not globally serialized; each application owns its queue, while
Ollama manages concurrent requests. A shared scheduling broker is not included.

The tool creates no database or cache. Applications decide what to retain; results
contain source paths for file inputs and descriptive content that may be sensitive.
The model runtime can independently retain a loaded model or its own logs.

## Inference requirements and observed performance

`inspect` needs no model, GPU, or Ollama service. Descriptions require a running
Ollama instance and an explicitly installed `qwen3-vl:4b` model (roughly 3.3 GB
on disk). Model download size is **not** a RAM or VRAM requirement: runtime use
also depends on context, image processing, concurrency, and Ollama's backend.
No minimum RAM/VRAM configuration has been established. The tested machine has
32 GiB RAM and an 8 GiB Radeon RX 6600 XT; these are test hardware details, not
minimum requirements or a guarantee for other GPU/driver combinations.

CPU inference is possible but substantially slower in the small local checks
below. There is no Imagescope CPU/GPU selector; Ollama controls device placement.
`--timeout` can increase the request deadline up to 3600 seconds, but does not
solve insufficient memory or guarantee that a failed runner will recover.

### GPU smoke check

Earlier 0.1.0-candidate smoke tests used Ollama 0.20.6, `qwen3-vl:4b`
(Q4_K_M, digest prefix `1343d82ebee3`), a Ryzen 5 5600G, and an AMD Radeon
RX 6600-family GPU. Ollama reported 100% GPU residency. Four requests covering a
photo, illustrated wallpaper, visible text through stdin, and a transparent PNG
returned valid results with measurements in approximately 6–14 seconds each;
a repeated simple image took about 4 seconds. These are observations, not speed
guarantees or a quality benchmark.

Descriptions were broadly useful, but the model called an illustration a 3D
render and a head-and-shoulders portrait “full body.” Tags can also contain generic
or inferred terms despite the prompt. Treat medium/composition labels and text
flags as predictions, not verified facts or OCR.

### CPU comparison and optional-model caveat

A later local test used Ollama 0.20.6 on the same machine with a per-request
`num_gpu: 0` override in an experimental transport, not a shipped CLI option.
Three small images (portrait, text card, transparent circle) were each analyzed
with both profiles, using a 768px maximum preview, 4096-token context, and
1024-token output limit. Qwen returned schema-valid output in all six requests
and recognized the main content, with observed request times of 14–37 seconds.
Those transport timings include image encoding/inference and model loading where
applicable, but not the CLI's full decoding/measurement pipeline. Single runs
and a tiny fixture set do not establish typical latency or minimum hardware.

An experimental `gemma3:4b` comparison is **not supported integration**: its
Vulkan runner failed twice with `ErrorDeviceLost`. CPU requests took approximately
100–134 seconds and produced valid JSON but frequently incorrect descriptions.
A short-prompt control worked on the text card, whereas the current general
prompt did not; the underlying cause is not established. `--model` permits
experimentation with installed Ollama models, not a promise of drop-in prompt or
runtime compatibility. Qwen remains the default and the evaluated model.

### Measurement output

Current inspect output for the transparent red-circle fixture (abridged; model
predictions omitted). Unlike the older white-composited palette, extracted colors
now describe visible pixels without an assumed background:

```text
400 × 400 · PNG

Measurements
  Palette: #d22c2c #d32c2c #d12c2c #d12d2d #d42e2e #cf2c2c
  Luminance: 0.702 · spread 0.373
```

## Python API

```python
from pathlib import Path
from imagescope import AnalysisRequest, analyze

result = analyze(AnalysisRequest(
    Path('image.jpg'), profile='general', measurements=True,
))
if result['status'] == 'ok':
    print(result['predictions']['summary'])
    print(result['measurements']['palette'])
else:
    print(result['error']['code'], result['error']['message'])
```

Use `source=encoded_bytes` for in-memory input. An optional `on_progress(stage,
label)` callback receives stage transitions, not fabricated percentages. Expected
failures are structured results; callback/programmer errors are not a stable public
error taxonomy. The backend seam supports testing; Ollama is the only shipped
inference implementation. No plugin loader is provided.

## Development and builds

```sh
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m build
```

Tests use generated images and a local fake HTTP server; no Ollama instance,
model download, Qt, or desktop application is required. The large-image tests
allocate a roughly 118-megapixel source image, so allow adequate memory.

CI tests supported Python versions on Linux, builds wheel/source archives, and
checks the installed CLI from outside the source tree.

## Integration contract

Each request produces a result containing input metadata, measurements,
predictions, provenance, and status. Applications own storage, indexing, batch
scheduling, and any actions based on those results. A failed model request may
still include useful measurements; always check status before using predictions.

The supported entry points are the CLI/JSON protocol in `PROTOCOL.md` and
`imagescope.AnalysisRequest`, `imagescope.AnalyzerError`, and `imagescope.analyze`.
Internal submodules are not yet a stable public API. In particular, consumers
using decoder or validation helpers should pin an exact package version until
those interfaces are formalized. Package, protocol, profile, and measurement
versions are independent; consult `imagescope info --json` for discovery.

## Project status and licensing

Release candidate: **0.1.0rc1**, targeting 0.1.0. Treat it as
pre-release software; internal Python APIs are not stable. The canonical public
repository is:

https://github.com/commonfire-org/imagescope

No PyPI publication is implied. Licensed under the MIT License; see `LICENSE`.
See `RELEASE_NOTES.md` for RC1
installation and limitations, and `CONTRIBUTING.md` for development guidance.
