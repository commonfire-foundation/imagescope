# Imagescope 0.1.0rc2

Second prerelease candidate for 0.1.0. This is not stable 0.1.0 and is not
published to PyPI. Linux and Python 3.11 or later are required.

## Changes since RC1

- Add a separate metadata-v1 Python API and `imagescope metadata` command for
  bounded header inspection without decoding image pixels or contacting a model.
- Add opt-in `srgb-v1` color conversion with explicit color provenance. The
  default `legacy-v1` behavior remains unchanged; untagged and invalid profiles
  are not silently treated as converted sRGB.
- Add EXIF-oriented pixel-region inspection with `inspect --region`, cropping
  before reduction and reporting coordinate and sampling provenance.
- Add opt-in 256-bin RGB and luminance histograms with alpha-weighted sampling.
  Default measurement output remains unchanged.
- Clarify managed installation and keep internal plans out of distribution
  archives. Update URLs for the CommonFIRE Foundation repository move.

New options and APIs have their own contracts in `METADATA.md`,
`COLOR_POLICY.md`, `REGION_INSPECTION.md`, and `HISTOGRAMS.md`. See
`CHANGELOG.md` and `PROTOCOL.md` for the existing analysis contract.

## Download and verify

Download the wheel and `SHA256SUMS` from the RC2 GitHub prerelease:

https://github.com/commonfire-foundation/imagescope/releases/tag/v0.1.0rc2

From the download directory, with `uv` already installed and a compatible
Python available:

```sh
sha256sum --check --ignore-missing SHA256SUMS
uv tool install --no-python-downloads ./imagescope-0.1.0rc2-py3-none-any.whl
imagescope --version
imagescope info --json
imagescope inspect image.png --json
```

To replace an existing managed installation, use `uv tool install --force
--no-python-downloads ./imagescope-0.1.0rc2-py3-none-any.whl` after verifying
the wheel. Source archives and pipx/checkout alternatives are described in
`README.md`. Ollama and its model are separately installed only for `describe`;
metadata and measurements do not require a model. Artifact checksums detect
changed bytes, not publisher identity.

## Limitations

Metadata-only parsing is bounded but filesystem stalls are not preempted.
Color conversion is not proof of editor/printer matching. Histogram bins
represent sampled pixels, not full-source counts or evidence of clipping.
Region measurements may be reduced; working-image alpha bounds are not exact
source bounds. AI descriptions can be inaccurate. Image editing, theme export,
and catalogs are consumer responsibilities. No automatic model download or
remote fallback is provided.

This prerelease does not claim the owner's actual-terminal spinner check required
for stable 0.1.0. Report issues with a sanitized command/output and version;
do not upload private images or sensitive paths without reviewing them.
