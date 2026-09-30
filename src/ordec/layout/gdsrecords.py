# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Record-level GDS reader. A GDS file is a sequence of records, each with a
4-byte header: total record length (uint16, big endian), record type, data
type. Only what gds_in.py needs is decoded, coordinates stay integers.

scan(data) -> (units, structures)
    Walks all record headers of a GDS file (bytes-like) up to its ENDLIB
    record. units is the value of the UNITS record: (user units per database
    unit, database unit in meters). structures lists (name, start, end) per structure, where
    data[start:end] holds the records of its elements.

read_structure(data, start, end) -> (quads, elements)
    quads (bytes) holds 12 native int32 per Boundary with five XY points:
    layer, data type, x0, y0, ..., x4, y4. Library cells consist almost
    entirely of those (rectangles). All other elements are returned in
    elements as (kind, records): kind is the record type that starts the
    element (BOUNDARY, PATH, ...), records maps record type to value (bytes
    for strings, else a number for one value, a tuple for multiple values).

The functions come from the C extension _gdsrecords if it is built. The
pure-Python versions below (scan_py, read_structure_py) are equivalent, but
take about a microsecond per record.
"""

import struct
import array

UNITS = 0x03
ENDLIB = 0x04
STRNAME = 0x06
ENDSTR = 0x07
BOUNDARY = 0x08
PATH = 0x09
SREF = 0x0A
AREF = 0x0B
TEXT = 0x0C
LAYER = 0x0D
DATATYPE = 0x0E
XY = 0x10
ENDEL = 0x11
SNAME = 0x12
COLROW = 0x13
NODE = 0x15
TEXTTYPE = 0x16
STRING = 0x19
STRANS = 0x1A
MAG = 0x1B
ANGLE = 0x1C
PATHTYPE = 0x21
BOX = 0x2D
BGNEXTN = 0x30
ENDEXTN = 0x31

header = struct.Struct('>HBB')

def record_header(data, pos, end):
    """Returns (length, record type, data type) of the record at pos."""
    if end - pos >= 4:
        length, rt, dt = header.unpack_from(data, pos)
        if 4 <= length <= end - pos:
            return length, rt, dt
    raise ValueError(f"Invalid GDS data: bad record at offset {pos}.")

def real8(b):
    """
    GDS real8: sign bit, 7-bit excess-64 exponent to base 16, 56-bit
    mantissa (a fraction, binary point left of the mantissa).
    """
    v = int.from_bytes(b[1:], 'big') * 16.0**((b[0] & 0x7f) - 64) / 2**56
    return -v if b[0] & 0x80 else v

def record_value(data, pos, length, dt):
    payload = bytes(data[pos+4:pos+length])
    if dt == 6:
        return payload.rstrip(b'\0')
    elif dt in (1, 2, 3):
        fmt = {1: 'H', 2: 'h', 3: 'i'}[dt]
        values = struct.unpack(f'>{len(payload) // struct.calcsize(fmt)}{fmt}', payload)
    elif dt == 5:
        values = tuple(real8(payload[i:i+8]) for i in range(0, len(payload) - 7, 8))
    else:
        return None
    if len(values) == 1:
        return values[0]
    return values

def scan_py(data):
    units = None
    structures = []
    name = None
    pos = 0
    end = len(data)
    while pos < end:
        length, rt, dt = record_header(data, pos, end)
        if rt == ENDLIB: # may be followed by padding
            return units, structures
        if rt == UNITS:
            units = record_value(data, pos, length, dt)
        elif rt == STRNAME:
            name = record_value(data, pos, length, dt)
            start = pos + length
        elif rt == ENDSTR and name is not None:
            structures.append((name, start, pos))
            name = None
        pos += length
    raise ValueError("Invalid GDS data: no ENDLIB record.") # truncated file

def read_structure_py(data, pos, end):
    if pos < 0 or end > len(data):
        raise ValueError("structure range outside of data")
    quads = array.array('i')
    elements = []
    kind = None
    records = {}
    while pos < end:
        length, rt, dt = record_header(data, pos, end)
        if rt == ENDEL:
            xy = records.get(XY, ())
            if kind == BOUNDARY and len(xy) == 10 \
                    and isinstance(records.get(LAYER), int) \
                    and isinstance(records.get(DATATYPE), int):
                quads.extend((records[LAYER], records[DATATYPE], *xy))
            elif kind is not None:
                elements.append((kind, records))
            kind = None
            records = {}
        else:
            if kind is None:
                kind = rt
            if dt != 0:
                records[rt] = record_value(data, pos, length, dt)
        pos += length
    if kind is not None:
        raise ValueError("Invalid GDS data: element without ENDEL.")
    return quads.tobytes(), elements

try:
    from ._gdsrecords import scan, read_structure
except ImportError:
    scan = scan_py
    read_structure = read_structure_py
