# Imagescope 0.1.0rc1

Release candidate for the first standalone Imagescope release.
Local image understanding and measurement tools for applications, scripts, and people.

Git tag: `v0.1.0rc1`. This is a GitHub **pre-release**, not stable 0.1.0.

Canonical repository:
https://github.com/commonfire-org/imagescope

RC1 downloads:
https://github.com/commonfire-org/imagescope/releases/tag/v0.1.0rc1

## Included

- Stateless Linux CLI and Python API with human, JSON, and JSONL output.
- Local palette, luminance/color distributions, transparency, regional colors,
  intensity variation, mirror similarity, and perceptual hashes without AI.
- General and wallpaper description profiles using an explicitly installed
  Ollama `qwen3-vl:4b` model; no automatic downloads or remote fallback.
- Bounded image decoding, strict response validation, and partial measurements
  retained when inference fails.

See `CHANGELOG.md` and `PROTOCOL.md` for details and migration requirements.

## Install and verify

Requires Linux and Python 3.11 or later. From a directory containing the RC1
artifacts, verify checksums and install the wheel in a virtual environment:

```sh
sha256sum -c SHA256SUMS
python3 -m venv .venv
.venv/bin/python -m pip install ./imagescope-0.1.0rc1-py3-none-any.whl
.venv/bin/imagescope --version
.venv/bin/imagescope info --json
.venv/bin/imagescope inspect image.png --palette-size 16 --json
```

The version command should report `0.1.0rc1`. Pip may download Pillow and NumPy;
these instructions are not an offline dependency bundle. The source archive is
an alternative to the wheel:

```sh
.venv/bin/python -m pip install ./imagescope-0.1.0rc1.tar.gz
```

For descriptions, install/start Ollama separately. The following pull is an
explicit approximately 3.3 GB model download, not part of package installation:

```sh
ollama pull qwen3-vl:4b
.venv/bin/imagescope doctor
.venv/bin/imagescope describe image.png --profile general --json
```

## Limitations

- Model predictions can be wrong even when they pass schema validation. Text
  presence is not OCR, and measurements are not beauty or suitability scores.
- No minimum RAM/VRAM specification is established. Small local Qwen CPU checks
  took 14–37 seconds per request; earlier GPU smoke checks took about 6–14 seconds.
  These are different smoke runs, not a controlled CPU/GPU benchmark. See README.
- Gemma was an unsuccessful compatibility experiment, not supported integration.
  Qwen remains the default; arbitrary `--model` values are not guaranteed to work.
- Internal Python APIs remain unstable. Custom backends must accept the selected
  `profile` keyword; consumers must distinguish measurements from predictions.
- Linux only; no GUI, catalog, automatic model management, or cloud fallback.

## Verification and publication gates

The exact RC1 package must pass the Python 3.11–3.14 suite, wheel/source builds,
installed-package smoke tests, and archive metadata/license checks. Results and
remaining gates are recorded in `RELEASE_PLAN.md`.

Publication is gated on hosted CI and final artifact verification. The owner's
actual-terminal visual check remains pending for stable 0.1.0; automated PTY
checks cover animation, cleanup, cancellation, and narrow-terminal behavior.
This remaining manual check is disclosed rather than claimed complete for RC1.

Report issues in the canonical repository. Include `imagescope --version`,
Python/Ollama versions, the command, and sanitized output. Do not upload private
images or sensitive paths without reviewing them. The MIT license and OldJobobo
attribution are retained.
