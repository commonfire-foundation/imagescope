# Imagescope 0.1.0 release plan

Current candidate: **0.1.0rc1**. Intended tag: `v0.1.0rc1`; intended release
status: GitHub pre-release. Owner approval for creating the public CommonFIRE
repository and publishing RC1 has been received. Publication remains gated on
hosted CI and final artifact verification. The stable target remains 0.1.0. See `RELEASE_NOTES.md` for RC1 artifact-install
instructions and known limitations.

## Target

A small, dependable Linux CLI and Python library for local image measurements
and Ollama-backed general and wallpaper descriptions. Ship as an initial development release,
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

- [x] Confirm public destination `commonfire-org/imagescope` and GitHub Releases
  as the initial distribution channel. The public repository has been created
  on GitHub Free. PyPI is not selected or authorized.
- [x] Add Linux/development-status metadata and clarify that the desktop consumer
  mentioned in `PROTOCOL.md` is external, not included in this package.
- [x] Add the canonical CommonFIRE repository/issues URLs to package metadata.
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

- [x] Finalize the RC1 changelog and artifact installation instructions for
  GitHub Releases. Linux-only support and Ollama prerequisites remain prominent.
- [ ] With explicit owner approval, push, tag `v0.1.0rc1`, and publish the tested
  RC1 artifacts as a pre-release. Promote to `v0.1.0` only after final acceptance.
  Publish to PyPI only if separately chosen and authorized.
- [ ] Verify a clean installation using the published instructions/artifact.

## Not required for 0.1.0

No new backends, plugin system, batch scheduler, GUI, automatic model downloads,
Windows/macOS support, benchmark infrastructure, or automated publishing pipeline.
Do not redesign the protocol or expand scope to solve hypothetical future needs.

## RC1 verification

Candidate `0.1.0rc1` uses implementation baseline `a343a38` plus the local
version/metadata and release-documentation changes. No inference or measurement
algorithms changed during RC1 preparation. Final metadata now identifies the
public CommonFIRE repository; the release commit and tag identify the candidate.

- 88 tests passed on each of Python 3.11.15, 3.12.13, 3.13.12, and 3.14.7.
- Each interpreter built RC1 wheel/source archives and passed fresh installed
  smoke tests for both formats. Installed metadata and runtime versions agree.
- Evidence and the runner are under `.tmp/rc1/`; these are ignored local records.
  The final handoff directory is `.tmp/rc1/artifacts/`, containing the wheel,
  source archive, and `SHA256SUMS`. Checksums detect changes, not publisher identity.
- RC1 release notes provide artifact-based installation without inventing a
  public repository or package-index URL. Package classification is Beta;
  protocol/schema remain 1, preprocessing 3, measurements 6, wallpaper-v3,
  and general-v1 are unchanged.
- Owner approval for RC1 publication was received after local verification.
  Public repository and metadata are now configured. Hosted CI and final artifact
  checks gate publication; the actual-terminal visual check remains disclosed
  as pending for stable 0.1.0, not claimed as completed for RC1.
- Publication evidence is the tagged commit, its hosted Actions run, and the
  release assets/checksums. Do not advertise RC1 as stable 0.1.0.

## Pre-RC1 preparation verification

Verified against implementation commit `a343a38`, with the release-documentation
updates in this preparation pass. No production source changed in this pass.
Package version remains 0.1.0, unreleased.

| Python | Full suite | Wheel + source build | Installed wheel / source smoke |
| --- | --- | --- | --- |
| 3.11.15 | 88 passed | passed | both passed |
| 3.12.13 | 88 passed | passed | both passed |
| 3.13.12 | 88 passed | passed | both passed |
| 3.14.7 | 88 passed | passed | both passed |

- Fresh test and installation environments live under
  `.tmp/commonfire-prep/matrix-<version>/`. Tests use synthetic images and a fake
  local HTTP server; installed smoke checks run away from the source package.
- Reproduction: each interpreter creates a venv, installs `.[dev]`, runs
  `python -m unittest discover -s tests -v`, builds with `python -m build`, then
  installs each archive in its own venv and runs `tests/smoke_installed.py` from
  a separate working directory. The local runner is
  `.tmp/commonfire-prep/run-matrix.sh`; CI specifies the same supported matrix.
- All eight archives were inspected for the new modules, decoder/presentation
  inclusion, retained OldJobobo license attribution, and exclusion of local
  `.tmp`/`.venv` contents. All checks passed.
- Refreshed the unreleased changelog for profiles, measurements, alpha handling,
  partial failures, and custom-backend migration requirements. README now
  separates GPU smoke observations from the small CPU comparison and explicitly
  states that minimum hardware requirements have not been established.
- The earlier GPU smoke record below applies to the earlier candidate, not to
  every new feature. The current implementation's CPU comparison covered both
  profiles: Qwen produced valid JSON in all six requests and recognized main
  content, with known label errors. Gemma remains experimental and unsupported;
  its Vulkan crash and prompt-sensitive CPU results do not block the Qwen-based
  release scope. No inference accuracy guarantee is implied.
- `git remote -v` returned no remotes. No repository was created, remote added,
  history pushed, tag created, or registry publication attempted.
- Artifacts/logs are ignored local verification evidence, not hosted CI or final
  published release assets. Rebuild final artifacts after publication metadata
  and release documentation are finalized.

Remaining owner/release actions: actual-terminal visual check, confirmation and
creation of the public repository/channel, real repository/issues metadata,
channel-specific install instructions, hosted CI, and explicit publication
approval. The changelog content is refreshed but remains unreleased; no release
or readiness claim substitutes for these outstanding checks.

## Earlier candidate verification record

Local verification (2026-09-19):

- Tested implementation commit: `5876717` (the subsequent verification-record
  commit only updates this document).
- 32 tests passed on each of Python 3.11.15, 3.12.13, 3.13.12, and 3.14.7.
- Each version built both archives and passed fresh wheel and source-archive
  installation smoke tests outside the source package. License attribution,
  package version, presentation module, and decoder inclusion were checked.
- Local evidence: `.tmp/matrix-*/` holds tests, build, and install logs/artifacts.
  Final rebuilt archives are in `.tmp/release-candidate/dist/`.
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
