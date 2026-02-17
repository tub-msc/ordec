# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import struct
from typing import NamedTuple
from enum import Enum


class Quantity(Enum):
    TIME = 1
    FREQUENCY = 2
    VOLTAGE = 3
    CURRENT = 4
    OTHER = 99


class SimArrayField(NamedTuple):
    fid: str #: Field ID, unique within a SimArray.
    dtype: str  # 'f8' (float64) or 'c16' (complex128)
    quantity: Quantity = Quantity.OTHER


class SimArray(tuple):
    """Immutable, hashable structured array for simulation data.

    A SimArray is a 2-tuple of (fields, data) where:
    - fields: tuple[SimArrayField, ...] describing columns
    - data: bytes containing packed little-endian records

    Each record contains one value per field laid out consecutively.
    Float64 fields ('f8') occupy 8 bytes, complex128 fields ('c16')
    occupy 16 bytes (real then imaginary, both float64 LE).
    """

    def __new__(cls, fields, data):
        if not isinstance(fields, tuple):
            fields = tuple(fields)
        if not isinstance(data, bytes):
            data = bytes(data)
        return tuple.__new__(cls, (fields, data))

    @property
    def fields(self):
        return tuple.__getitem__(self, 0)

    @property
    def data(self):
        return tuple.__getitem__(self, 1)

    @property
    def record_size(self):
        """Bytes per record."""
        size = 0
        for f in self.fields:
            if f.dtype == 'f8':
                size += 8
            elif f.dtype == 'c16':
                size += 16
            else:
                raise ValueError(f"Unknown field dtype: {f.dtype!r}")
        return size

    def __len__(self):
        """Number of records."""
        rs = self.record_size
        if rs == 0:
            return 0
        return len(self.data) // rs

    def _field_index(self, fid):
        for i, f in enumerate(self.fields):
            if f.fid == fid:
                return i
        raise KeyError(f"No field with fid {fid!r}")

    def column(self, fid_or_index):
        """Extract a field as a tuple of Python float or complex values."""
        if isinstance(fid_or_index, str):
            idx = self._field_index(fid_or_index)
        else:
            idx = fid_or_index

        field = self.fields[idx]
        # Calculate byte offset of this field within a record
        offset = 0
        for f in self.fields[:idx]:
            offset += 8 if f.dtype == 'f8' else 16

        rs = self.record_size
        n = len(self)
        data = self.data

        if field.dtype == 'f8':
            return tuple(
                struct.unpack_from('<d', data, i * rs + offset)[0]
                for i in range(n)
            )
        elif field.dtype == 'c16':
            return tuple(
                complex(*struct.unpack_from('<dd', data, i * rs + offset))
                for i in range(n)
            )
        else:
            raise ValueError(f"Unknown field dtype: {field.dtype!r}")

    def __getitem__(self, key):
        if isinstance(key, str):
            return self.column(key)
        # Fall back to tuple indexing for integer keys
        return tuple.__getitem__(self, key)

    def __iter__(self):
        raise TypeError(
            "SimArray does not support iteration. "
            "Use .column(name) to access individual fields."
        )

    def __repr__(self):
        nfields = len(self.fields)
        nrecords = len(self)
        fids = ', '.join(f.fid for f in self.fields)
        return f"SimArray({nrecords} records, fields=[{fids}])"

    def to_numpy(self):
        """Convert to numpy structured array."""
        import numpy as np

        dtype_to_np = {'f8': np.float64, 'c16': np.complex128}
        dtype = np.dtype({
            'names': [f.fid for f in self.fields],
            'formats': [dtype_to_np[f.dtype] for f in self.fields],
        })
        return np.frombuffer(self.data, dtype=dtype).copy()
