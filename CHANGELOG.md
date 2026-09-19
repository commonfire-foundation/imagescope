# Changelog

## 0.1.0 — Unreleased

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

Existing Image Lab installations are not automatically migrated.
