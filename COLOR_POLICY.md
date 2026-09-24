# Explicit color policies

## Contract

Analysis requests select `color_policy`: `legacy-v1` (default) or `srgb-v1`.
`assume_srgb` defaults to false and is only valid with `srgb-v1`.
Metadata-only inspection never transforms pixels and has no color-policy option.

- **legacy-v1:** preserve preprocessing-v3 pixel behavior exactly. Embedded ICC
  bytes are identified but not parsed or transformed. RGB-like channels continue
  to be treated as encoded sRGB by measurement formulas without claiming the
  source actually is sRGB. Unknown source color space is explicitly reported.
- **srgb-v1:** use an embedded ICC profile when present, converting supported
  source modes to encoded 8-bit sRGB. PNG's valid sRGB declaration may identify
  unprofiled RGB/gray input. Otherwise require explicit `assume_srgb=True` for
  untagged RGB/gray/indexed input. Never infer sRGB from a filename, generic RGB
  mode, EXIF alone, or an invalid embedded profile. CMYK and LAB require profiles.

ICC takes precedence over PNG declarations and assumptions. Invalid, oversized,
incompatible, or unsupported profiles fail the request; there is no silent fallback.
An assumption cannot override a broken embedded profile.

## Conversion algorithm — preprocessing version 4

1. Read first-image metadata and retain the source profile's byte fingerprint.
2. Parse profiles and transform **before** any pixel reduction, orientation, or
   white compositing, inside the existing resource-limited decoder.
3. Use LittleCMS through Pillow ImageCms, relative-colorimetric intent,
   `NOOPTIMIZE` (`0x0100`; black-point compensation remains disabled), generated
   sRGB destination profile, and 8-bit RGB output. Disable transform optimization
   to avoid interpolation error from a precomputed transform CLUT. Preserve alpha
   separately without transforming opacity.
4. Expand indexed color to RGB and palette transparency to alpha before the ICC
   transform. Transform grayscale as grayscale, CMYK as CMYK, LAB as LAB. Reject
   unsupported/high-depth modes rather than silently reducing their precision.
5. Apply existing encoded-sRGB8 LANCZOS reduction (premultiplied for alpha), EXIF
   orientation, and downstream sampling/white compositing as before.

Supported modes: RGB, RGBA, P, L, LA, 1, CMYK, LAB, subject to a compatible source
profile. Untagged assumptions/PNG sRGB declarations support only RGB/gray/indexed
modes. Conversion does not claim linear-light resizing or lossless gamut mapping.

JPEG native reduced decoding is disabled for `srgb-v1`: converting after that
reduction would violate this policy. Large images may therefore hit the existing
1.5 GiB memory/CPU/30-second worker limits even when legacy analysis succeeds.
There is no fallback to a differently ordered pipeline.

## Provenance and compatibility

`provenance.preprocessing.color_management` records policy, source mode/profile
fingerprint and status, source interpretation, result status, output color space,
intent, black-point compensation, `transform_optimization` (`disabled` for an ICC
transform, null otherwise), transform ordering, Pillow and LittleCMS versions
when applicable. Outcomes distinguish `unmanaged`, `converted`, `declared_srgb`,
and `assumed_srgb`. Unknown source color space is not reported as converted.

Whole-image default/legacy preprocessing remains version 3. The whole-image opt-in
sRGB pipeline uses preprocessing version 4. Region inspection uses preprocessing
version 5 with the same explicit color policies; see `REGION_INSPECTION.md`. Existing measurement algorithms remain version 6; opt-in histograms use the
additive version 7 contract in `HISTOGRAMS.md`. Input interpretation is distinguished
by preprocessing version and color provenance.
Protocol/schema/profile versions do not change. Consumers comparing measurements
must match preprocessing/color policies as well as measurement versions/settings.
A preview must use the same policy to be a meaningful visual comparison.

Phase 2 does not add editing, export, ROI, histogram, or AI backend behavior.

## Verification status

Synthetic regression tests cover linear-RGB conversion against the sRGB transfer
function (within one 8-bit code value), sRGB identity, LAB white, alpha preservation,
palette/grayscale input, ordering, failure paths, and exact legacy pixel regression.
CMYK integration now uses a deterministic, project-authored ICC v2 input profile
and an independent analytic sRGB reference over 6,561 CMYK samples, with a maximum
allowed difference of two 8-bit code values per channel. Lossless TIFF, decoded
JPEG samples, all eight EXIF orientations, public palette/luminance measurements,
metadata, CLI parity, and source immutability are covered. This closes the synthetic
CMYK numerical gate, not real-printer/vendor-profile or editor-preview validation.
See `tests/CMYK_FIXTURE.md` for fixture construction and limits.

### Pre-release refinement

The first unshipped Phase 2 slice used flags=0. CMYK validation exposed up to nine
code values of error near black from LittleCMS's optimized transform on the fixed
test grid (Pillow 12.3.0 / LittleCMS 2.19). `NOOPTIMIZE` reduced the observed maximum
to one. The still-unreleased `srgb-v1` contract was refined in place before release;
legacy behavior, analysis versions, and metadata inspection are unchanged. Earlier
development sRGB results lacking `transform_optimization: disabled` should be
recomputed rather than compared as equivalent. The more accurate path may use
more CPU; existing worker limits remain enforced.
