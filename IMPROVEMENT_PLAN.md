# Improvement plan

## North star

Do one thing and do it well: local image analysis using AI and deterministic measurements.

Wallpaper is one applied profile and use case, not the product boundary.

## Versioning and release policy

The release target remains `0.1.0`. The passes below are a prioritized improvement
backlog, not an automatic set of release blockers. Choose the final first-release
scope explicitly; completing a pass does not require a package-version bump or
publication.

Use Python-compatible prerelease versions only when distributing test builds:

- `0.1.0a1`, `0.1.0a2`, etc. for implementation snapshots.
- `0.1.0rc1`, `0.1.0rc2`, etc. once scope is complete and release testing begins.
- `0.1.0` for the first public release.

Git tags may use the corresponding `v` prefix. This plan does not authorize
publishing, tagging, or changing the package version immediately.

Track internal contracts separately from the package version:

- Profile versions: bump when a prompt, schema, or interpretation changes.
- Measurements version: bump when calculation semantics change.
- Protocol/schema versions: bump for incompatible contract changes, not ordinary
  fixes or compatible new options.

Nothing has shipped yet. Initial contracts may therefore be deliberately revised
before release rather than preserving accidental behavior indefinitely. Where
later sections call for compatibility, assess actual consumers and documented
behavior; do not build compatibility machinery solely for unreleased accidents.
Document deliberate contract revisions and update tests and version declarations
consistently. If revising the initial contract in place rather than incrementing
its version, explicitly record that pre-release decision.

## Pass 1: Correctness and simplicity

### Scope

Tighten the existing image-analysis behavior: correct operation ordering, useful
success criteria, a clearer CLI, and direct tests of pixel measurements. No new
capabilities or subsystems. This document is a plan, not an implementation.

## 1. Prepare the image before checking the model

Files: `imagescope/api.py`, `tests/test_analyzer_core.py`, and affected CLI tests.

- Keep request validation first.
- Decode and validate image input before contacting Ollama.
- Compute requested measurements before model checks or inference.
- Preserve measurements and input metadata when model checks or inference fail;
  keep the result status as error and retain the backend failure code.
- Update progress-order expectations and any documentation that specifies them.
- Preserve whole-request timeout behavior; do not accidentally give model work a
  fresh full timeout after preprocessing.

Acceptance:

- Invalid image input fails without contacting the backend.
- `describe --measurements` retains measurements on unavailable-backend,
  missing-model, and generation failures.
- Successful describe results retain their existing shape and provenance.
- `inspect` never contacts the backend.

## 2. Reject blank captions

Files: `imagescope/profiles/wallpaper.py`, `imagescope/backends/ollama.py` if
needed, and focused validation/backend tests.

- Reject captions that are empty after whitespace normalization, including
  whitespace-only Unicode input.
- Ensure standalone description validation and the inference path agree.
- Report the existing `invalid_response` error rather than an empty successful
  description.
- Continue allowing empty optional label arrays; do not invent replacement text.
- Keep the prompt unchanged in this pass. If schema or prompt changes become
  necessary, update the profile version deliberately.

Acceptance:

- Empty and whitespace-only captions fail through validation and the backend.
- Normal captions still pass and retain existing trimming behavior.
- Valid descriptions with empty optional label arrays still pass.

## 3. Clarify command-specific CLI options

Files: `imagescope/cli.py`, CLI tests, `README.md`, and protocol documentation if
its command contract is affected.

- Inventory which existing flags actually affect `inspect` versus `describe`.
- Keep input, output, timeout, and protocol controls shared.
- Present inference-only flags on `describe`, not in `inspect --help`; remove
  redundant `inspect --measurements` from the visible interface.
- Check documented usage and repository consumers before removing accepted
  flags. Preserve hidden compatibility aliases where removal would break the
  existing contract, and document any deliberate breaking change.
- Keep explicit `inspect` and `describe` commands; add no implicit default.

Acceptance:

- Each command's help describes relevant options only.
- Tests cover shared flags, describe-only flags, and the chosen compatibility
  behavior for old inspect invocations.
- Human, JSON, and JSONL output contracts remain unchanged.

## 4. Test pixel measurements directly

Files: a focused `tests/test_measurements.py`; `imagescope/measurements.py` only
if the tests expose a demonstrated defect.

- Generate tiny synthetic fixtures in tests rather than adding private images.
- Cover black/white and solid-color luminance, including zero spread for uniform
  images, with explicit numerical tolerances.
- Cover color-block palette colors and proportions; allow documented rounding.
- Cover perceptual-hash format and expected behavior on uniform and opposing
  gradient images.
- Cover edge-grid dimensions, finite values in [0, 1], uniform-image zero edges,
  and a strong synthetic boundary in the expected grid region.
- Verify repeatability and that measurement does not mutate the input image.
- Avoid locking tests to incidental palette ordering or unnecessary decoder
  implementation details.

Acceptance:

- Each emitted measurement has direct behavioral coverage.
- Tests are deterministic, local, and require no Ollama service.
- Any algorithm correction is documented and assessed for measurement-version
  implications; do not silently change measurement semantics.

## Verification and completion

- Run focused tests after each change, then the complete unittest suite.
- Run the existing installed-package smoke check using the documented workflow.
- Exercise help and representative inspect/describe paths in human, JSON, and
  JSONL modes. Use the fake backend/server for reproducible failure cases.
- Verify timeout/cancellation and progress tests after changing operation order.
- Review the final diff for unintended protocol, profile, or measurement changes.
- Record actual commands/results and any unresolved compatibility decisions.

## Pass 1 completion record

Implemented and verified locally on Python 3.14.7:

- Preprocessing/measurements precede model checks; partial results survive model
  inventory and inference failures. Ollama receives only the remaining request
  budget. Progress is now preparing → checking → generating.
- Blank captions, including Unicode whitespace, fail validation and inference
  with `invalid_response`; optional arrays and caption trimming are unchanged.
- Inspect help hides inference-only options and redundant `--measurements`.
  Repository usage and the previously shared protocol flags were reviewed;
  hidden aliases retain accepted syntax/validation for existing consumers.
  No compatibility decision remains unresolved for this pass.
- Added direct synthetic coverage of every measurement, repeatability, and input
  immutability. No measurement algorithm changes were necessary.
- Pre-release contract decision: retain protocol/schema 1, wallpaper-v3,
  measurements 2, and package 0.1.0. Prompt/schema text and output shapes are
  unchanged. Blank-caption rejection corrects validation in place. Input errors
  now precede backend endpoint/model errors, so the malformed-endpoint CLI test
  now supplies valid image bytes rather than a missing file.

Verification commands/results:

- `.venv/bin/python -m unittest discover -s tests -p 'test_analyzer*.py' -v`
  — 17 passed after operation-order changes, including timeout/cancellation.
- `.venv/bin/python -m unittest discover -s tests -p test_wallpaper.py -v`
  — 2 passed.
- `.venv/bin/python -m unittest discover -s tests -p test_analyzer_cli.py -v`
  — 10 passed, including help, compatibility, human/JSON/JSONL paths and fake
  HTTP backend failures.
- `.venv/bin/python -m unittest discover -s tests -p test_measurements.py -v`
  — 6 passed.
- `.venv/bin/python -m unittest discover -s tests -v` — final run: 45 passed.
- `.venv/bin/python -m build --outdir .tmp/pass1/dist` — wheel and source archive
  built successfully. Followed `.github/workflows/ci.yml` smoke workflow using
  separate `.tmp/pass1/{wheel,sdist}-env` virtual environments, pip-installed each
  archive, then ran `tests/smoke_installed.py` from separate smoke directories
  outside the source package. Both passed. Temporary/cache directories stayed
  inside the repository. Relative interpreter paths emitted harmless Python
  prefix warnings; absolute-path reruns passed without those warnings.
- `git diff --check` — clean; reviewed source/protocol diff for unintended changes.

Ignored evidence/artifacts: `.tmp/pass1/`. No live-model evaluation, multi-Python
matrix rerun, version bump, commit, tag, or publication was performed in this pass.

## Follow-up passes

These are separate passes, not additional completion requirements for pass 1.

### Pass 2: Configurable color extraction

Build on the existing palette extraction before expanding task profiles.

Alpha handling (agreed):

- Preserve alpha through preprocessing for palette extraction, separately from
  the white-composited AI preview.
- Ignore fully transparent pixels, including their hidden RGB values.
- Weight partially transparent pixels by opacity during palette extraction and
  proportion calculations. Normalize proportions by total contributing opacity,
  not total canvas pixels.
- Return an empty palette for a fully transparent image; do not fabricate white.
- Keep the white-background preview for AI descriptions.
- Measure transparency separately before compositing when implementing pass 4b.
- Document that extracted colors have no assumed background, while the AI sees
  a white-composited preview. Do not describe these as identical representations.
- Before implementation, specify working color-space and alpha-aware resizing
  conventions so hidden RGB cannot bleed into the extracted palette.
- Treat this as a deliberate measurement-semantics change, with corresponding
  version/provenance updates rather than claiming unchanged transparent output.

Extraction options:

- Add `--palette-size`, supporting counts such as 5, 8, 10, 16, and 24.
- Preserve the current six-color default for compatibility.
- Offer HEX, RGB, and HSL representations with documented ranges and rounding.
- Retain approximate color proportions.
- Define behavior when an image has fewer distinct colors than requested;
  do not manufacture extracted colors to fill the requested count.
- Test solid colors, limited-color artwork, gradients, and photographs. Use
  synthetic or appropriately licensed fixtures, not private image content.
- Keep machine-output changes deliberate and documented; assess schema and
  measurement-version implications before changing existing output.

Acceptance:

- The default palette size remains six; opaque-image behavior remains compatible
  unless an explicitly documented algorithm correction is required.
- Hidden RGB in fully transparent pixels cannot affect extraction. Tests verify
  opacity-weighted proportions and empty palettes for fully transparent input.
- The AI preview retains its white background.
- Requested palette sizes are validated and honored up to available colors.
- Color representations agree within documented conversion tolerances.
- Palette proportions and repeatability are tested across the fixture set.

#### Pass 2 completion record

Implemented and verified locally on Python 3.14.7:

- Shared CLI `--palette-size N` and Python `palette_size=N` accept integers 1–24,
  default 6. Describe still requires `--measurements`. Each palette entry always
  includes HEX, RGB, HSL, and fraction in machine output; human output stays HEX.
- Alpha is preserved through bounded decoding and palette resizing, including
  indexed/LA transparency. Fully transparent RGB is ignored, partial pixels are
  opacity-weighted, and fully transparent input returns an empty palette. Human
  output explicitly reports no visible pixels rather than an empty color line.
- AI input and non-palette measurements remain white-composited. Palette colors
  have no assumed background. Working color-space, premultiplied resizing,
  quantization, precision, representation ranges, and rounding are specified in
  `PROTOCOL.md`; no transparency metrics or theme scheme generation were added.
- Preprocessing and measurements advance to version 3. Protocol/schema 1,
  wallpaper-v3, prompt text, and package 0.1.0 remain unchanged. Palette fields
  and request options are additive. Opaque default extraction is checked against
  the previous Pillow/BICUBIC six-color path. The private `prepare_image` helper
  now returns RGB/RGBA rather than always composited RGB; API/backend callers
  are updated accordingly.
- Palette size is an upper bound, not padding: quantization can collapse colors
  even when the source has more distinct RGB values. This preserves opaque
  extraction behavior and is documented explicitly. No unresolved decisions.

Verification commands/results:

- `.venv/bin/python -m unittest discover -s tests -p test_palette.py -v`
  — 10 passed: sizes, solids/limited colors, gradients, seeded textured imagery,
  opacity shares, hidden RGB, empty palettes, indexed/LA decoding, round trips,
  repeatability, immutability, validation, AI compositing, and failure retention.
- `.venv/bin/python -m unittest discover -s tests -p test_image_decoding.py -v`
  — 6 passed, including 118MP JPEG and 30MP transparent PNG resource checks.
- `.venv/bin/python -m unittest discover -s tests -p test_measurements.py -v`
  — 6 passed.
- `.venv/bin/python -m unittest discover -s tests -p 'test_analyzer*.py' -v`
  — 21 passed, including all requested example sizes in both commands,
  human/JSON/JSONL output, fake backend failures, timeout, and cancellation.
- `.venv/bin/python -m unittest discover -s tests -v` — 57 passed.
- `.venv/bin/python -m build --outdir .tmp/pass2/dist` plus the CI installed-package
  workflow in separate `.tmp/pass2/{wheel,sdist}-env` environments — both archives
  built and both smoke checks passed. Smoke checks now include RGB output and
  fully transparent extraction with `--palette-size 24`.
- Synthetic 3840×2160 random RGBA PNG (33.2 MB encoded), 24-color inspect:
  succeeded in 0.914 seconds, working image 2048×1152, parent peak RSS about
  158 MiB including fixture creation. This is a local resource sanity check,
  not a portable benchmark; decoder limits remain enforced separately.
- `git diff --check` — clean; reviewed source/docs for unintended scope changes.

Ignored evidence/artifacts: `.tmp/pass2/`. No live-model evaluation, multi-Python
matrix rerun, package-version bump, commit, tag, or publication in this pass.

### Pass 3: Task profiles

- Separate profile-specific prompts, schemas, validation, and versions from the
  shared analysis pipeline, including backend requests and result validation.
- Preserve the existing wallpaper profile and its behavior.
- Add one general image-description profile to verify the separation.
- Keep profiles built-in and explicitly selected; no plugin framework.
- Test profile selection, output validation, and provenance, including rejection
  of unknown profiles and mismatched profile output.

Acceptance:

- Wallpaper behavior remains compatible.
- Both profiles work through the shared pipeline without wallpaper-specific
  assumptions leaking into general analysis.
- Results identify the selected profile and its version.

#### Pass 3 completion record

Implemented and verified locally on Python 3.14.7:

- Added an explicit built-in profile registry containing wallpaper-v3 and
  general-v1. Each profile supplies prompt/schema, validation/cleanup, JSON
  continuation prefix, and human presentation fields. No plugins or dynamic
  registration/loading were introduced.
- General-v1 describes visible content with `summary`, `subjects`, and
  `text_present`; it does not impose wallpaper tags, mood, medium, composition,
  or watermark fields. Field limits and normalization are documented.
- API, Ollama requests, response validation, result validation, CLI discovery,
  snapshot guards, and human output use the selected profile. Unknown profiles
  and cross-profile output are rejected. API validation also covers custom
  backends, preserving measurements on invalid responses.
- Wallpaper remains the default with unchanged prompt/schema and ordinary
  output. Package 0.1.0, protocol/schema 1, and preprocessing/measurements 3 are
  unchanged; the new profile starts at general-v1.
- Deliberate pre-release Python backend revision: `describe` and optional
  `settings` receive keyword `profile` naming the selected built-in profile.
  Custom backends must accept it; no wallpaper-only fallback. Standalone Ollama
  helpers retain the wallpaper default. Result validation now requires the
  selected profile's current identity/version/prompt and prediction schema.

Verification commands/results:

- `.venv/bin/python -m unittest discover -s tests -p test_profiles.py -v`
  — 5 passed, including both profiles' full-object and continuation requests,
  schemas/prompts/provenance, unknown names, cross-profile responses, custom
  backend validation, stale/mismatched result provenance, and general limits.
- `.venv/bin/python -m unittest discover -s tests -p test_analyzer_core.py -v`
  — 9 passed; existing wallpaper/API ordering and timeout checks retained.
- `.venv/bin/python -m unittest discover -s tests -p test_wallpaper.py -v`
  — 2 passed; existing wallpaper cleanup and blank-caption checks retained.
- `.venv/bin/python -m unittest discover -s tests -p test_analyzer_cli.py -v`
  — 13 passed; general discovery, profile-specific guards, human/JSON/JSONL,
  unknown names, and mismatched HTTP responses covered alongside existing tests.
- `.venv/bin/python -m unittest discover -s tests -p test_presentation.py -v`
  — 6 passed.
- `.venv/bin/python -m unittest discover -s tests -v` — 63 passed.
- `.venv/bin/python -m build --outdir .tmp/pass3/dist` plus the CI installed-package
  workflow in separate `.tmp/pass3/{wheel,sdist}-env` environments — both archives
  built and both smoke checks passed. Installed smoke now verifies discovery of
  both profiles and general analysis using a fake Ollama transport.
- `git diff --check` — clean; reviewed profile/shared-pipeline changes and verified
  no wallpaper prompt/schema changes in this pass.

Ignored evidence/artifacts: `.tmp/pass3/`. Tests require no live Ollama service.
General-v1 has not yet received live-model quality evaluation; no multi-Python
matrix rerun, commit, tag, version bump, or publication was performed.

### Pass 4: Expanded deterministic measurements

Add all of the following independently of AI inference, in the priority order
below. Each subpass can be verified and completed separately.

#### 4a: Color and luminance distributions

Natural extensions of the palette work:

- **Color distribution:** hue histogram, saturation and lightness percentiles,
  and near-neutral pixel share.
- **Light/dark distribution:** luminance percentiles and near-black/near-white
  pixel percentages.
- **Palette relationships:** perceptual distances between extracted colors to
  distinguish similar shades from distinct accents.

##### Pass 4a completion record

Implemented and verified locally on Python 3.14.7:

- Added `color_distribution`: 12-bin HSL hue histogram, saturation/lightness
  percentiles, and near-neutral share. Added `luminance_distribution`: linear
  sRGB luminance percentiles and near-black/near-white shares. Added
  `palette_distances`: indexed unordered CIELAB D65 ΔE76 pairs.
- Specified algorithms, color spaces, thresholds, rounding, weighted inverse-CDF
  percentiles, and unavailable-value behavior in `PROTOCOL.md` before exposing
  the fields. New distributions are opacity-weighted with no assumed background;
  legacy white-composited measurements retain their existing calculations.
- Statistics use at most 256×256 pixels and distances at most 276 pairs. All run
  with requested measurements; local cost/output checks support this default.
  Human output is a compact summary; JSON/JSONL expose all fields.
- Fully transparent images produce null distribution members and no pairs.
  Achromatic/near-neutral images have no hue histogram rather than fabricated
  hue. Exact 10% saturation threshold ties are compared in integer RGB units.
- Measurements advance to version 4. Preprocessing 3, protocol/schema 1,
  wallpaper-v3, general-v1, and package 0.1.0 remain unchanged. This is additive
  output with explicit measurement provenance, not a reinterpretation of old
  mean/spread fields. No 4b/4c features or quality/suitability scores were added.

Verification commands/results:

- `.venv/bin/python -m unittest discover -s tests -p test_color_statistics.py -v`
  — initial 7 tests passed; an additional all-bin histogram test passed in the
  final suite. Coverage includes solids, all hue bins, gray thresholds, gradients,
  weighted blocks/percentiles, hidden RGB, low/zero alpha, tiny images, known Lab
  distances, near/far colors, finite values, repeatability, and immutability.
- `.venv/bin/python -m unittest discover -s tests -p 'test_analyzer*.py' -v`
  — 22 passed, including inspect/describe, human/JSON/JSONL, version provenance,
  pair counts, transparent output, and failure retention.
- `.venv/bin/python -m unittest discover -s tests -p test_measurements.py -v`
  — 6 passed; legacy measurement behavioral coverage retained.
- `.venv/bin/python -m unittest discover -s tests -v` — final run: 71 passed.
- `.venv/bin/python -m build --outdir .tmp/pass4a/dist` plus the existing CI
  isolated wheel/source installation workflow — both builds and both installed
  smoke checks passed, including new statistics and transparent null values.
- Synthetic 3840×2160 RGBA PNG (33.2 MB encoded), 24-color inspect: 0.974 seconds,
  276 pairs, 14,891 serialized result bytes. New statistics/pairs on the bounded
  thumbnail averaged 0.0134 seconds over 10 calls. Parent peak RSS was about
  185 MiB including fixture generation. This is a local sanity check, not a
  portable benchmark; existing large-image/resource-limit tests also pass.
- `git diff --check` — clean. Evidence/artifacts are ignored under `.tmp/pass4a/`.

No live model was required. No multi-Python matrix rerun, package-version bump,
commit, tag, or publication was performed. No unresolved 4a decisions remain.

#### 4b: Transparency and spatial color

Requires explicit preprocessing and regional-output decisions:

- **Transparency:** transparent and translucent pixel percentages, plus
  visible-content bounds, measured before compositing.
- **Spatial color distribution:** dominant colors and luminance by region.

##### Pass 4b completion record

Implemented and verified locally on Python 3.14.7:

- Added `transparency`: unweighted transparent/translucent working-pixel shares,
  working dimensions, and half-open visible bounds (alpha > 0), before white
  compositing. Fully transparent input has null bounds; hidden RGB has no effect.
- Added `spatial_color`: a fixed row-major 3×3 working-image grid with bounds,
  up to three opacity-weighted colors per region and alpha-weighted linear-sRGB
  mean luminance. Crop before regional thumbnailing to prevent cross-region
  color bleed. Regional palettes are independent of global palette-size.
- Specified working coordinates, alpha thresholds, rounding, uneven-grid splits,
  empty tiny-image cells, regional resizing/weighting, and output limits in
  `PROTOCOL.md` before implementation. These are bounded working-image statistics,
  not exact source-resolution alpha counts/bounds; downsampling effects are
  explicitly documented in README and protocol.
- Added concise human transparency/bounds/grid output; JSON/JSONL expose complete
  regions. Transparent and zero-area regions contain an empty palette and null
  luminance. Existing measurements and white-composited AI previews are unchanged.
- Measurements advance to version 5. Preprocessing 3, protocol/schema 1, both
  profile versions, and package 0.1.0 remain unchanged. No 4c features or
  quality/suitability scores were introduced. No unresolved 4b decisions remain.

Verification commands/results:

- `.venv/bin/python -m unittest discover -s tests -p test_spatial_measurements.py -v`
  — 8 passed: alpha counts/bounds, hidden RGB, low alpha, solids, known nine-color
  layouts, regional opacity weights, grid coverage, tiny/uneven images, crop
  isolation, EXIF orientation, indexed transparency, repeatability, finite output,
  input immutability, and regional color limits.
- `.venv/bin/python -m unittest discover -s tests -p 'test_analyzer*.py' -v`
  — 22 passed: inspect/describe, human/JSON/JSONL, version provenance, bounds/grid
  fields, transparent output, and unavailable/missing/failed backend retention.
- `.venv/bin/python -m unittest discover -s tests -p test_measurements.py -v`
  — 6 passed; legacy behaviors retained.
- `.venv/bin/python -m unittest discover -s tests -v` — 79 passed, including
  large decoder fixtures and resource-limit tests. The large transparent PNG test
  explicitly checks that bounds use working dimensions rather than source size.
- `.venv/bin/python -m build --outdir .tmp/pass4b/dist` plus the existing CI
  isolated wheel/source installation workflow — both builds and both installed
  smoke checks passed, including transparency and regional output.
- Synthetic 3840×2160 RGBA input, reduced to 2048×1152: 1.743 seconds for 24-color
  inspect, 9 regions/27 regional colors, 18,455 serialized result bytes. New
  transparency/spatial work averaged 0.4383 seconds over five calls; parent peak
  RSS about 164 MiB including fixture generation. This local bounded-cost check
  supports running the fields with requested measurements; it is not a portable
  benchmark. No additional selection controls were needed.
- `git diff --check` — clean. Ignored evidence/artifacts: `.tmp/pass4b/`.

No live model, multi-Python matrix rerun, package-version bump, commit, tag, or
publication was performed.

#### 4c: Detail, symmetry, and similarity

Secondary measurements with more interpretation caveats:

- **Local detail:** regional edge strength or intensity variation, extending
  the existing edge-density grid.
- **Symmetry:** horizontal and vertical mirror-similarity scores.
- **Additional similarity hashes:** a perceptual hash alongside the existing
  difference hash, with its algorithm and parameters explicitly identified.

Implementation requirements for every subpass:

- Define algorithms, units, ranges, histogram bins, thresholds, region grids,
  percentile conventions, and rounding before exposing the new fields.
- Document color spaces, resizing, orientation, and alpha handling. Measure
  transparency before white-background compositing and define whether other
  measurements use visible pixels, alpha weighting, or a composited image.
- Handle fully transparent images, uniform images, tiny images, and undefined
  hue explicitly. Represent unavailable measurements consistently without NaN
  or infinity in machine output.
- Name actual measurements rather than inferred judgments. Edge strength is not
  an objective sharpness or quality verdict; symmetry and hashes are algorithmic
  comparisons, not semantic understanding.
- Preserve bounded resource use. Select and document working resolutions and
  assess runtime/memory cost before deciding which measurements run by default.
- Keep output readable; document any selection controls without introducing
  an unrelated configuration framework.
- Record measurement provenance and apply the internal versioning policy to
  algorithm and output-contract changes.

Acceptance:

- Every new measurement has direct synthetic-fixture tests with expected values
  or relationships and explicit numerical tolerances.
- Tests cover color blocks, grayscale, gradients, alpha patterns, known spatial
  layouts, symmetric/asymmetric patterns, and similarity-hash behavior.
- Repeatability, finite output, input immutability, and edge-case handling are
  verified; tests require no model or network.
- All new measurements work through `inspect` and requested measurements during
  `describe`, including retention when inference fails.
- Resource checks demonstrate bounded operation on representative large inputs;
  human, JSON, and JSONL output remain usable and within their size limits.
- No beauty, quality, or wallpaper-suitability scores are introduced.

##### Pass 4c completion record

Implemented and verified locally on Python 3.14.7:

- Added `local_detail.intensity_std_3x3`: population grayscale-intensity spread
  on nine 64×64 cells of a 192×192 view. The original edge-density grid is unchanged.
- Added `symmetry.left_right` / `top_bottom`: 1 minus mean absolute mirrored
  grayscale difference. Names specify which halves are compared; no quality,
  sharpness, beauty, or semantic-symmetry judgment is implied.
- Added `phash64`, with algorithm `dct-ii-32-low8-ac-median-v1`: orthonormal
  32×32 DCT-II, top-left 8×8 AC median, 12-decimal coefficient rounding, DC bit
  forced zero, row-major 16-digit hexadecimal output. Existing dHash is unchanged.
  This is a 63-data-bit hash in a 64-bit container, not a claim of interchangeability
  with other pHash implementations.
- Specified resolutions, interpolation, grayscale/white-composite alpha convention,
  numerical ranges, rounding, bit packing, and comparison caveats in `PROTOCOL.md`
  before implementation. Fully transparent images behave like white; tiny inputs
  use fixed-size resampling. Uniform images deliberately collide in pHash.
- Human output includes variation, mirrors, and the identified hash; JSON/JSONL
  expose all fields. Measurements advance to version 6; package 0.1.0,
  preprocessing 3, protocol/schema 1, and both task profiles are unchanged.
- No new dependencies, additional selection controls, or deferred theme-export
  features were introduced. No unresolved 4c decisions remain.

Verification commands/results:

- `.venv/bin/python -m unittest discover -s tests -p test_structure.py -v`
  — 8 passed: uniform/tiny inputs, exact boundary variation, localized texture,
  gradients, mirrored/asymmetric patterns, independent scalar DCT reference,
  contrast/resize/opposing-image hash relationships, hidden/partial alpha,
  repeatability, immutability, finite ranges, and bounded output.
- `.venv/bin/python -m unittest discover -s tests -p 'test_analyzer*.py' -v`
  — 22 passed: API and CLI output, inspect/describe, human/JSON/JSONL, provenance,
  and retention of new measurements on unavailable/inference failures.
- `.venv/bin/python -m unittest discover -s tests -p test_measurements.py -v`
  — 6 passed; prior palette/luminance/dHash/edge behavior retained.
- `.venv/bin/python -m unittest discover -s tests -v` — 87 passed.
- `.venv/bin/python -m build --outdir .tmp/pass4c/dist` plus the existing CI
  isolated wheel/source installation workflow — both builds and both installed
  smoke checks passed, including all new structure fields and algorithm identity.
- Synthetic 3840×2160 RGBA input, reduced to 2048×1152: 1.356 seconds for 24-color
  inspect, 18,739 serialized result bytes. New structure measurements averaged
  0.0081 seconds over 20 calls on the white-composited working image; parent peak
  RSS about 165 MiB including fixture generation. This local resource check
  supports default inclusion with requested measurements, not a portable benchmark.
- `git diff --check` — clean. Ignored evidence/artifacts: `.tmp/pass4c/`.

No live model, multi-Python matrix rerun, package-version bump, commit, tag, or
publication was performed.

### Separate decision: Base16/Base24 export

- Distinguish extracting 16 or 24 colors from generating a semantic Base16 or
  Base24 scheme with background, foreground, accent, and terminal-color roles.
- Decide whether scheme generation belongs in a separate converter consuming
  Imagescope output; this is not authorization to implement scheme generation.
- Never present adjusted or generated scheme colors as literal image
  observations.

## Deferred

Prompt/tag-count tuning and installation/distribution changes remain outside
pass 1. Evaluate prompt changes separately against a small fixed set of real
images rather than mixing them with correctness fixes. Additional profile and
color-extraction and deterministic-measurement work follows the separate passes
above.
