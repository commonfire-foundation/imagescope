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

Requires Linux, Python 3.11 or later, and an installed `uv`. Recommended on
Omarchy: use uv's isolated tool environment, not system Python. From a directory
containing the downloaded RC1 wheel and `SHA256SUMS`:

```sh
sha256sum --check --ignore-missing SHA256SUMS
uv tool install --no-python-downloads ./imagescope-0.1.0rc1-py3-none-any.whl
imagescope --version
imagescope info --json
imagescope inspect image.png --palette-size 16 --json
```

Confirm the wheel checksum is `OK`; the version should report `0.1.0rc1`.
Dependencies may be downloaded, but the command requires an existing compatible
Python instead of downloading one. If the command is not on PATH, inspect
`uv tool dir --bin`; `uv tool update-shell` is an explicit opt-in to editing
shell configuration, followed by opening a new terminal.

To reinstall or change versions, verify the desired wheel and use
`uv tool install --force --no-python-downloads ./<actual-wheel-filename>`.
To remove the managed environment and command:

```sh
uv tool uninstall imagescope
```

Uninstall leaves Ollama, models, images, downloaded archives, shared uv caches,
and any shell PATH edits intact. README includes pipx alternatives and a
checkout-venv workflow. This documentation update also works with the existing
RC1 artifacts; it does not replace the already published release assets.

For descriptions, install/start Ollama separately. The following pull is an
explicit approximately 3.3 GB model download, not part of package installation:

```sh
ollama pull qwen3-vl:4b
imagescope doctor
imagescope describe image.png --profile general --json
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

## Verification and follow-up

RC1 is published as a GitHub prerelease. Before using the release artifacts,
verify their published checksums. The owner's actual-terminal visual check
remains pending for stable 0.1.0; automated PTY checks cover animation, cleanup,
cancellation, and narrow-terminal behavior. This remaining manual check is
disclosed rather than claimed complete for RC1.

Report issues in the canonical repository. Include `imagescope --version`,
Python/Ollama versions, the command, and sanitized output. Do not upload private
images or sensitive paths without reviewing them. The MIT license and OldJobobo
attribution are retained.
