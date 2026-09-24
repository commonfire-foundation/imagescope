"""Deterministic, synthetic CMYK input ICC fixture; no external assets or CMM.

ICC v2.1 lut16Type (mft2), four input channels, XYZ D50 PCS, two grid points
per axis, identity input/output curves. Not a printer characterization.
See CMYK_FIXTURE.md for the model, independent oracle, and limitations.
"""
from itertools import product
import struct


def u32(value):
    return struct.pack('>I', value)


def fixed(value):
    return struct.pack('>i', round(value * 65536))


def cmyk_profile():
    # Bradford-adapted linear sRGB -> XYZ D50 matrix. The LUT itself is affine
    # in CMYK, so interior values need no nonlinear interpolation approximation.
    matrix = ((0.4360747, 0.3850649, 0.1430804),
              (0.2225045, 0.7168786, 0.0606169),
              (0.0139322, 0.0971045, 0.7141733))
    lut = bytearray(b'mft2' + b'\0' * 4 + bytes((4, 3, 2, 0)))
    for row in range(3):
        for column in range(3):
            lut.extend(fixed(int(row == column)))
    lut.extend(struct.pack('>HH', 2, 2))  # two entries per input/output curve
    lut.extend(struct.pack('>HH', 0, 65535) * 4)
    # ICC tables vary the last input channel fastest: C, M, Y, then K.
    for cyan, magenta, yellow, black in product((0, 1), repeat=4):
        rgb = (1 - (cyan + black) / 2,
               1 - (magenta + black) / 2,
               1 - (yellow + black) / 2)
        xyz = [sum(coefficient * channel for coefficient, channel in zip(row, rgb))
               for row in matrix]
        # ICC v2 XYZ PCS encodes 1.0 as 0x8000 (not 0xffff).
        lut.extend(struct.pack('>HHH', *(round(channel * 32768) for channel in xyz)))
    lut.extend(struct.pack('>HH', 0, 65535) * 3)
    description = b'Imagescope synthetic affine CMYK v1\0'
    desc = (b'desc' + b'\0' * 4 + u32(len(description)) + description
            + b'\0' * 8 + b'\0' * 70)  # empty Unicode and ScriptCode sections
    white = b'XYZ ' + b'\0' * 4 + b''.join(fixed(v) for v in (0.9642, 1, 0.8249))
    tags = [(b'desc', desc), (b'wtpt', white),
            (b'cprt', b'text' + b'\0' * 4 + b'Imagescope synthetic test fixture; MIT\0'),
            (b'A2B0', bytes(lut)), (b'A2B1', bytes(lut))]
    header = bytearray(128)
    header[8:12] = u32(0x02100000)
    header[12:24] = b'scnrCMYKXYZ '
    header[24:36] = struct.pack('>6H', 2026, 1, 1, 0, 0, 0)
    header[36:40] = b'acsp'
    header[64:68] = u32(1)  # relative colorimetric default
    header[68:80] = white[8:20]
    header[80:84] = b'imgS'
    offset = 128 + 4 + 12 * len(tags)
    table, payload = bytearray(u32(len(tags))), bytearray()
    for signature, data in tags:
        table.extend(signature + u32(offset) + u32(len(data)))
        padded = data + b'\0' * (-len(data) % 4)
        payload.extend(padded)
        offset += len(padded)
    header[:4] = u32(offset)
    return bytes(header + table + payload)
