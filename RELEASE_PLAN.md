# Imagescope 0.1.0 release plan

## Target

A small, dependable Linux CLI and Python library for local image measurements
and Ollama-backed wallpaper descriptions. Ship as an initial development release,
not a promise of universally accurate image recognition or a stable internal API.

This checklist is the remaining work, not authorization to publish. Keep changes
focused; check items off only when verified.

## Already in place

- MIT license, credited to OldJobobo, with package license metadata.
- Local Git repository and initial commit; release-candidate changes are recorded
  in the local commits accompanying this checklist.
- Documented CLI/JSON protocol, Python entry points, and privacy/resource limits.
- Human-readable summaries and a responsive braille spinner.
- Linux CI definition for Python 3.11–3.14 and installed-package smoke checks.
- Prior local verification: 26 tests passed before the final spinner tweaks;
  14 presentation/CLI tests passed afterward. Wheel/source builds were verified.
  These are useful baselines, not verification of the final release artifacts.

## 1. Close the two known correctness gaps

- [x] Bound model text and terminal output.
  - Start with generous limits: 1,000 characters per caption and 128 per label.
    Preserve existing array-count limits; reject oversized predictions rather
    than silently truncating them into apparently valid results.
  - Guard serialized result/event size in UTF-8 bytes, including provenance and
    diagnostics. Reuse the existing 1 MiB event budget. On overflow, emit a small
    structured failure and exit nonzero, not a truncated or oversized JSON line.
  - Keep normal JSON/JSONL shapes and event ordering unchanged. If the embedded
    prompt/schema changes, update the profile version intentionally.
- [x] Make malformed endpoints produce `invalid_request`, not a traceback.
  - Cover URL parsing and invalid ports in `doctor` and `describe`.
  - Preserve rejection of redirects and endpoints containing credentials.
- [x] Add focused regression tests for those cases, oversized HTTP replies,
  and redirect rejection. Use the existing fake server and unittest harness.

**Done when:** reproductions fail cleanly in human and machine modes, ordinary
requests still work, and the full test suite passes. No transport rewrite needed.

## 2. Check actual use

- [x] Run real Ollama descriptions on a small set: a photo, an illustration,
  an image with visible text, and a transparent PNG. Include one stdin request
  and one `--measurements` request.
- [x] Confirm useful captions/tags, valid structured output, and no routine
  token-budget failures. Note obvious limitations rather than tuning endlessly.
- [ ] Check the spinner in the actual terminal, including Ctrl-C and a narrow
  window. Confirm redirected output has no animation and JSON remains clean.
  Automated PTY tests pass for animation, success/failure cleanup, timeout,
  SIGTERM, and SIGINT at 32 columns; the owner's visual terminal check remains.
- [x] Add a short README note with the tested Ollama version, model, hardware,
  approximate observed latency, and one representative human-output example.
  Do not commit private image content or paths.

**Done when:** the documented first-run workflow works on real images. This is
smoke testing, not a benchmark suite or a claim of calibrated accuracy.

## 3. Prepare and verify the release candidate

- [ ] Choose the public repository location and initial distribution channel.
  A GitHub release with installable archives is sufficient for 0.1.0; PyPI is
  optional. Check package-name availability before claiming or publishing there.
- [x] Add Linux/development-status metadata and clarify that the desktop consumer
  mentioned in `PROTOCOL.md` is external, not included in this package.
- [ ] Add repository/issues URLs once the destination is known.
- [x] Review the diff, preserve the OldJobobo license credit, and commit the
  intended source, tests, and docs. Exclude environments and build artifacts.
- [x] Run the full suite on Linux/Python 3.11–3.14: the same matrix passed locally
  in isolated environments. Hosted CI still requires a public repository.
- [x] Build fresh wheel/source archives and run installed-package smoke checks
  for both away from the source package. Check version, entry point, MIT license,
  and inclusion of the presentation/decoder modules.

**Done when:** the exact release candidate passes the matrix and both installed
artifact checks. Record the tested commit and a concise result below.

## 4. Release deliberately

- [ ] Finalize the 0.1.0 changelog and installation instructions for the chosen
  channel. Keep Linux-only support and Ollama/model prerequisites prominent.
- [ ] With explicit owner approval, push, tag `v0.1.0`, and publish the tested
  artifacts. Publish to PyPI only if separately chosen and authorized.
- [ ] Verify a clean installation using the published instructions/artifact.

## Not required for 0.1.0

No new backends, plugin system, batch scheduler, GUI, automatic model downloads,
Windows/macOS support, benchmark infrastructure, or automated publishing pipeline.
Do not redesign the protocol or expand scope to solve hypothetical future needs.

## Final verification record

Local verification (2026-09-18):

- 32 tests passed on each of Python 3.11.15, 3.12.13, 3.13.12, and 3.14.7.
- Each version built both archives and passed fresh wheel and source-archive
  installation smoke tests outside the source package. License attribution,
  package version, presentation module, and decoder inclusion were checked.
- Local evidence: `.tmp/matrix-*/` holds tests, build, and install logs/artifacts.
  These are ignored local outputs, not durable hosted CI records.
- Live checks: Ollama 0.20.6, qwen3-vl:4b Q4_K_M (digest prefix 1343d82ebee3),
  Ryzen 5 5600G / Radeon RX 6600-family GPU, with 100% GPU residency reported.
  Four cases passed in 5.77–13.97 seconds; a repeat simple image took 4.1 seconds.
- Known model limitations: medium misclassification, inaccurate composition
  labels, and generic/inferred tags. README documents these; no accuracy promise.
- PyPI lookup returned 404 for `imagescope`; this is not a reservation or a
  guarantee of registration eligibility.
- Still pending: owner visual terminal check, repository/channel choice, public
  URLs, hosted CI, final release date/instructions, and explicit publication
  approval. No remote, push, tag, or registry publication was performed.
