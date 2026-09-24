# Synthetic CMYK ICC reference fixture

`cmyk_fixture.py` constructs a deterministic 740-byte ICC v2.1 input profile using
only Python's standard library. It is project-authored, covered by the repository's
MIT license, and contains no downloaded printer profiles or personal images.
No profile file, native compiler, system ICC installation, or network is required.

SHA-256:
`2ad3f9f3d4545f324d4780761b90dc7e84f146b2b7c137651604b1bff855ff8d`

## Definition

This is deliberately **not a physical press characterization**. Its four normalized
CMYK inputs define a simple affine linear-sRGB model:

- `R_linear = 1 - (C + K) / 2`
- `G_linear = 1 - (M + K) / 2`
- `B_linear = 1 - (Y + K) / 2`

Black ink alone at maximum therefore produces linear gray 0.5; all four inks at
maximum produce zero. This unusual response is intentional: ordinary unmanaged
Pillow CMYK-to-RGB conversion must not accidentally pass the numerical tests.

The profile maps CMYK into XYZ D50 PCS using a Bradford-adapted sRGB matrix and
an ICC `lut16Type` (`mft2`) with identity input/output curves and a 2×2×2×2 CLUT.
Because the mapping is affine, interior interpolation has no nonlinear model error.
PCS XYZ uses the ICC v2 scaling where 1.0 is encoded as 0x8000. Both A2B0 and A2B1
are supplied, with identical data, plus white-point, description, and copyright
tags. The profile timestamp is fixed, so rebuilding it yields identical bytes.

## Independent numerical reference

Tests calculate expected RGB directly from the three equations above and the
standard sRGB encoding function:

- `12.92 * linear` for `linear <= 0.0031308`
- `1.055 * linear ** (1 / 2.4) - 0.055` otherwise

Round to 8-bit channel values. This oracle does not call ImageCms, Imagescope's
conversion helper, or read the profile's CLUT/matrix. A tolerance of **2 code values
per channel** covers profile fixed-point quantization, D50 matrix rounding, and
LittleCMS/Pillow implementation differences. It is not a perceptual quality score.

Tests include all 6,561 combinations of CMYK channel values
`0, 1, 17, 64, 128, 192, 238, 254, 255`, covering corners, asymmetric interiors,
and near-black edges. Lossless TIFF
exercises exact sample inputs; JPEG tests calculate references from the decoded
CMYK samples to separate JPEG loss from color-conversion error. Public API tests
use uniform patches so palette/luminance expectations are not affected by regional
resampling. Metadata/profile identity, source immutability, EXIF orientation, and
CLI parity are checked separately.

This closes the synthetic CMYK numerical integration gate. It does not establish
accuracy for every vendor ICC profile, real printer/paper combination, rendering
intent, or operating-system color-managed preview. Those require separate fixtures
and/or integration testing when the consuming editor is available.

## Transform optimization regression

On Pillow 12.3.0 / LittleCMS 2.19, flags=0 produces up to nine code values of error
against this oracle on the fixed grid; for example CMYK `(255,255,254,254)` yields
`(3,3,4)` instead of reference `(6,6,13)`. `NOOPTIMIZE` reduces the observed grid
maximum to one code value. The isolated decoder tests therefore exercise the
non-optimized transform with the two-code-value acceptance bound. This also guards
against accidentally re-enabling the lower-fidelity optimized transform.
