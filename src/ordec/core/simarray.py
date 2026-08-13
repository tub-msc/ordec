# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import struct
from enum import Enum
from numbers import Integral
from typing import NamedTuple, Optional
from public import public
from pyrsistent import pmap


@public
class Quantity(Enum):
    """Physical quantity of a simulation result column, with the plot
    axis label as value.

    Mirrors the ngspice vector types that have a defined unit (see
    typesdef.c).

    Phase types are missing here for now as their unit is ambiguous.
    """
    TIME = 'Time (s)'
    FREQUENCY = 'Frequency (Hz)'
    VOLTAGE = 'Voltage (V)'
    CURRENT = 'Current (A)'
    VOLTAGE_DENSITY = 'Voltage density (V/√Hz)'
    CURRENT_DENSITY = 'Current density (A/√Hz)'
    VOLTAGE_SQUARED_DENSITY = 'Voltage² density (V²/Hz)'
    CURRENT_SQUARED_DENSITY = 'Current² density (A²/Hz)'
    VOLTAGE_SQUARED = 'Voltage² (V²)'
    CURRENT_SQUARED = 'Current² (A²)'
    TEMPERATURE = 'Temperature (°C)'
    RESISTANCE = 'Resistance (Ω)'
    IMPEDANCE = 'Impedance (Ω)'
    ADMITTANCE = 'Admittance (S)'
    POWER = 'Power (W)'
    DECIBEL = 'Magnitude (dB)'
    CAPACITANCE = 'Capacitance (F)'
    CHARGE = 'Charge (C)'

    def __repr__(self):
        return f'{self.__class__.__name__}.{self.name}'


@public
class SimArrayField(NamedTuple):
    fid: str #: Field ID, unique within a SimArray.
    dtype: str  # 'f8' (float64) or 'c16' (complex128)
    quantity: Optional[Quantity] = None #: Physical quantity, or None if unknown.

    @property
    def size(self):
        """Byte size of this field within a record."""
        try:
            return {'f8': 8, 'c16': 16}[self.dtype]
        except KeyError:
            raise ValueError(f"Unknown field dtype: {self.dtype!r}")


@public
class SimColumn:
    """Lazy strided column view into SimArray packed binary data.

    Reads values on demand from the underlying bytes buffer,
    avoiding materializing the entire column as a Python tuple.

    A column may carry the Quantity it holds, taken from its
    SimArrayField; consumers such as Report.plot2d use it to infer axis
    labels.
    """

    __slots__ = ('_data', '_offset', '_stride', '_length', '_dtype', 'quantity')

    def __init__(self, data, offset, stride, length, dtype, quantity):
        self._data = data
        self._offset = offset
        self._stride = stride
        self._length = length
        self._dtype = dtype
        self.quantity = quantity

    @property
    def real(self):
        """Lazy view of the real part of a complex column.

        Complex values are packed as two consecutive float64 (real,
        imag), so the real part is a float64 view at the same offset
        and stride. For a real column, returns the column itself.
        """
        if self._dtype == 'f8':
            return self
        return SimColumn(self._data, self._offset, self._stride,
            self._length, 'f8', self.quantity)

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


@public
class SimArray(tuple):
    """Immutable, hashable structured array for simulation data.

    A SimArray is a tuple whose value is defined by its first two
    elements:
    - fields: tuple[SimArrayField, ...] describing columns
    - data: bytes containing packed little-endian records
    The further elements memoize the field layout (fid index, byte
    offsets, record size) derived from fields, kept in the tuple so
    that instances hold no mutable state (__slots__ is empty).

    Each record contains one value per field laid out consecutively.
    Float64 fields ('f8') occupy 8 bytes, complex128 fields ('c16')
    occupy 16 bytes (real then imaginary, both float64 LE).
    """

    __slots__ = ()

    def __new__(cls, fields, data):
        if not isinstance(fields, tuple):
            fields = tuple(fields)
        if not isinstance(data, (bytes, memoryview)):
            data = bytes(data)
        index = {}
        offsets = []
        offset = 0
        for i, f in enumerate(fields):
            index.setdefault(f.fid, i)
            offsets.append(offset)
            offset += f.size
        return tuple.__new__(cls,
            (fields, data, pmap(index), tuple(offsets), offset))

    def __hash__(self):
        """Hash based on fields and data length only.

        Avoids reading the full data buffer, which would defeat the
        purpose of mmap-backed storage. Collisions between arrays with
        identical schemas and record counts are resolved by __eq__.
        """
        return hash((self.fields, len(self.data)))

    def __eq__(self, other):
        if not isinstance(other, SimArray):
            return NotImplemented
        return tuple.__eq__(self, other)

    @property
    def fields(self):
        return tuple.__getitem__(self, 0)

    @property
    def data(self):
        return tuple.__getitem__(self, 1)

    @property
    def _fid_index(self):
        return tuple.__getitem__(self, 2)

    @property
    def _offsets(self):
        return tuple.__getitem__(self, 3)

    @property
    def record_size(self):
        """Bytes per record."""
        return tuple.__getitem__(self, 4)

    def __len__(self):
        """Number of records."""
        rs = self.record_size
        if rs == 0:
            return 0
        return len(self.data) // rs

    def _field_index(self, fid):
        try:
            return self._fid_index[fid]
        except KeyError:
            raise KeyError(f"No field with fid {fid!r}") from None

    def column(self, fid_or_index):
        """Return a lazy SimColumn view for the given field."""
        if isinstance(fid_or_index, str):
            idx = self._field_index(fid_or_index)
        else:
            idx = fid_or_index

        field = self.fields[idx]
        return SimColumn(self.data, self._offsets[idx], self.record_size,
            len(self), field.dtype, field.quantity)

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
