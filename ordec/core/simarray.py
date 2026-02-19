# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import struct
from numbers import Integral
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

    @property
    def size(self):
        """Byte size of this field within a record."""
        try:
            return {'f8': 8, 'c16': 16}[self.dtype]
        except KeyError:
            raise ValueError(f"Unknown field dtype: {self.dtype!r}")


class SimColumn:
    """Lazy strided column view into SimArray packed binary data.

    Reads values on demand from the underlying bytes buffer,
    avoiding materializing the entire column as a Python tuple.
    """

    __slots__ = ('_data', '_offset', '_stride', '_length', '_dtype')

    def __init__(self, data, offset, stride, length, dtype):
        self._data = data
        self._offset = offset
        self._stride = stride
        self._length = length
        self._dtype = dtype

    def __len__(self):
        return self._length

    def _unpack(self, i):
        pos = i * self._stride + self._offset
        if self._dtype == 'f8':
            return struct.unpack_from('<d', self._data, pos)[0]
        else:
            return complex(*struct.unpack_from('<dd', self._data, pos))

    def __getitem__(self, key):
        if isinstance(key, Integral):
            if key < 0:
                key += self._length
            if not (0 <= key < self._length):
                raise IndexError(f"index {key} out of range")
            return self._unpack(key)
        elif isinstance(key, slice):
            return [self._unpack(i) for i in range(*key.indices(self._length))]
        raise TypeError(f"indices must be integers or slices, not {type(key).__name__}")

    def __iter__(self):
        for i in range(self._length):
            yield self._unpack(i)

    def __contains__(self, value):
        for i in range(self._length):
            if self._unpack(i) == value:
                return True
        return False

    def __bool__(self):
        return self._length > 0

    def __repr__(self):
        dtype_name = 'float64' if self._dtype == 'f8' else 'complex128'
        return f"SimColumn({self._length} {dtype_name} values)"

    def dump(self):
        """Return a string like '[1.234e-05, 5.678e+00]' for test reference data."""
        def fmt(v):
            if isinstance(v, complex):
                sign = '+' if v.imag >= 0 else ''
                return f"({fmt(v.real)}{sign}{fmt(v.imag)}j)"
            return f"{v:.3e}"
        return '[' + ', '.join(fmt(self._unpack(i)) for i in range(self._length)) + ']'


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
        return sum(f.size for f in self.fields)

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
        """Return a lazy SimColumn view for the given field."""
        if isinstance(fid_or_index, str):
            idx = self._field_index(fid_or_index)
        else:
            idx = fid_or_index

        field = self.fields[idx]
        offset = sum(f.size for f in self.fields[:idx])

        return SimColumn(self.data, offset, self.record_size, len(self), field.dtype)

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
