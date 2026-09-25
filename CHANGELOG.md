# Changelog

## Unreleased

## 0.1.0rc2 — 2026-09-25

Second release candidate for 0.1.0. Git tag: `v0.1.0rc2`; distributed as a
GitHub prerelease, not stable 0.1.0.

- Add metadata-v1 inspection without pixel decoding via Python and CLI.
- Add opt-in `srgb-v1` color management with explicit conversion provenance;
  retain legacy color behavior by default.
- Add EXIF-oriented region inspection and opt-in sampled RGB/luminance histograms.
  Default measurement output remains unchanged.
- Keep internal development plans local and out of release archives.
- Update repository URLs after the move to CommonFIRE Foundation.
- Recommend `uv tool` for isolated Omarchy/user installation, with explicit
  artifact replacement, PATH guidance, and managed uninstall. Document pipx as
  an alternative and project virtual environments for development.
- Add an opt-in, repository-isolated uv install/run/replace/uninstall smoke check.
  Published RC1 artifacts and application behavior are unchanged.

## 0.1.0rc1 — 2026-09-20

First release candidate for 0.1.0. Git tag: `v0.1.0rc1`; distributed as a
GitHub pre-release, not stable 0.1.0.

- Extract the stateless analyzer from Image Lab as Imagescope.
- Rename the Python package and CLI to `imagescope`.
- Retain protocol/schema version 1, wallpaper description, bounded decoding,
  pixel measurements, and explicit Ollama integration.
- Separate backend tests from desktop catalog and legacy adapter tests.
- Add standalone packaging, Linux CI, and development documentation.
- Add compact human-readable results and a responsive terminal spinner with
  elapsed time; preserve plain redirected progress and JSON/JSONL output.

- Bound captions, labels, and serialized result records; report oversized data as
  structured failures rather than truncating it. The wallpaper profile is now v3;
  consumers pinning v2 or its prompt hash must refresh their task snapshots.
- Report malformed endpoint URLs/ports as `invalid_request`, including in doctor.
- Include the MIT license with OldJobobo attribution in release archives.

### Image profiles and measurements

- Add the built-in `general-v1` description profile: summary, subjects, and text
  presence, alongside the default `wallpaper-v3` profile.
- Add configurable palettes of 1–64 colors (default six), with HEX, RGB, HSL,
  and approximate proportions. Preserve alpha during decoding; ignore invisible
  pixels and weight partial transparency without an assumed background.
- Add opacity-weighted color/luminance distributions, CIELAB ΔE76 palette
  distances, transparency bounds/shares, and regional palettes/luminance.
- Add regional intensity variation, mirror similarity, and an identified DCT
  perceptual hash alongside the existing dHash and edge-density measurements.
- Prepare input and requested measurements before contacting the model; retain
  partial measurements and input metadata on inference failures.
- Reject blank captions and clarify command-specific help while retaining hidden
  compatibility options for `inspect`.

### Pre-release compatibility notes

- Preprocessing advances to version 3 and measurements to version 6. Transparent
  palette results deliberately differ from the previous white-composited palette;
  AI previews and legacy luminance/dHash/edge measurements remain white-composited.
- Protocol/schema remain version 1. Consumers must accept additive measurement
  fields and select prediction validation by profile. Previously saved results
  are not rewritten.
- Custom Python backends must accept the `profile` keyword on `describe` and
  optional `settings` methods. Result validation requires matching current
  profile identity, version, prompt, and prediction shape.
- Qwen remains the default. No new inference backend or supported Gemma adapter
  is included.

Existing Image Lab installations are not automatically migrated.
