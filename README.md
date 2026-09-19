# Imagescope

A stateless Linux command and Python library: image in, structured observation out.
No Qt, SQLite catalog, daemon, automatic model downloads, or persistent image history.
The wallpaper organizer is a separate consumer, not part of this distribution.

## Install

Requires Linux, Python 3.11+, Pillow, and NumPy. From this checkout, install
in a virtual environment (the package is not currently published to PyPI):

```sh
python -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/imagescope --version
```

Image descriptions additionally require a running Ollama instance and an explicitly
installed `qwen3-vl:4b` model. `inspect` works without Ollama. Installation of this
Python package does not install or download models. Use `imagescope doctor`
to inspect the existing runtime before opting into any model download yourself.

## Commands

```sh
imagescope describe image.jpg --profile wallpaper --json
imagescope inspect image.jpg --json
imagescope describe image.jpg --measurements --events=jsonl
imagescope info --json
imagescope doctor --json
```

Read encoded image bytes from stdin, without creating an image file:

```sh
grim -g "$(slurp)" - | imagescope describe --stdin --json
```

Only invoke a screenshot pipeline when the screen content is intended for analysis.
Use a wrapper to handle region-selection cancellation and clipboard/notification
policy; the analyzer itself neither captures the screen nor changes the clipboard.

Without output flags, the command prints a compact summary to stdout: dimensions,
caption and search labels for descriptions, and a palette/luminance summary when
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

## Tasks and behavior

- `describe`: the versioned `wallpaper` profile generates captions and search tags.
- `inspect`: objective dimensions, hash, luminance, palette, perceptual hash, and
  coarse edge-density measurements, with no model request.
- `describe --measurements`: both; measured properties remain distinct from predictions.

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
30-second wall-clock limit. EXIF orientation and white alpha compositing happen
after reduction, avoiding full-size intermediate copies.

Original oriented dimensions and SHA-256 always describe the original input,
not the working preview. Preprocessing version 2 records working dimensions,
decoder strategy, and whether downsampling occurred. Measurements version 2 is
computed from the bounded working image; sampled values/perceptual hashes may
differ from older results. Existing saved results are not rewritten.

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

## Tested runtime

Local 0.1.0-candidate smoke tests used Ollama 0.20.6, `qwen3-vl:4b`
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

Example human output for a simple transparent red-circle image (abridged):

```text
400 × 400 · PNG

solid red circle on plain white background
Subjects: circle
Medium: abstract
Tags: red, circle, solid, white, background, flat, minimalist, geometric

Measurements
  Palette: #ffffff #dc5a5a #da5252 #e48181 #f8e0e0 #db5757
  Luminance: 0.702 · spread 0.373

Done in 4.1s · model predictions, not verified facts
```

## Python API

```python
from pathlib import Path
from imagescope import AnalysisRequest, analyze

result = analyze(AnalysisRequest(Path('image.jpg'), measurements=True))
if result['status'] == 'ok':
    print(result['predictions']['caption'])
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

## Integration and compatibility

Imagescope was extracted from Image Lab. It is a separate distribution and does
not provide the old `image_analyzer` import or `image-analyze` command. Existing
consumers must explicitly migrate their dependency, imports, and subprocess
command. Image Lab is not modified by this extraction.

The supported entry points are the CLI/JSON protocol in `PROTOCOL.md` and
`imagescope.AnalysisRequest`, `imagescope.AnalyzerError`, and `imagescope.analyze`.
Internal submodules are not yet a stable public API. In particular, consumers
using decoder or validation helpers should pin an exact package version until
those interfaces are formalized. Package, protocol, profile, and measurement
versions are independent; consult `imagescope info --json` for discovery.

## Project status and licensing

Initial standalone development release: 0.1.0. No remote repository or package
registry publication is implied by this checkout. Licensed under the MIT License; see `LICENSE`.
See `CONTRIBUTING.md` for development guidance.
