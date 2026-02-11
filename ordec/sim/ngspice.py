# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from collections import namedtuple
from enum import Enum
import numpy as np

from ..core import *
from .ngspice_subprocess import NgspiceSubprocess

class NgspiceBackend(Enum):
    """Available NgSpice backend types."""

    SUBPROCESS = "subprocess"

class Ngspice:
    @staticmethod
    def launch(debug: bool=False, backend: NgspiceBackend = NgspiceBackend.SUBPROCESS):
        if isinstance(backend, str):
            backend = NgspiceBackend(backend.lower())

        if debug:
            print(f"[Ngspice] Using backend: {backend.value}")

        backend_class = {
            NgspiceBackend.SUBPROCESS: NgspiceSubprocess,
        }[backend]

        return backend_class.launch(debug=debug)

    def __init__(self):
        raise TypeError("Please call Ngspice.launch(), instantiation of Ngspice is not supported!")


# Note: parse_raw() and RawVariable is currently unused.

RawVariable = namedtuple("RawVariable", ["name", "unit"])

def parse_raw(fn):
    info = {}
    info_vars = []

    with open(fn, "rb") as f:
        for i in range(100):
            l = f.readline()[:-1].decode("ascii")

            if l.startswith("\t"):
                _, var_idx, var_name, var_unit = l.split("\t")
                assert int(var_idx) == len(info_vars)
                info_vars.append(RawVariable(var_name, var_unit))
            else:
                lhs, rhs = l.split(":", 1)
                info[lhs] = rhs.strip()
                if lhs == "Binary":
                    break
        assert len(info_vars) == int(info["No. Variables"])
        no_points = int(info["No. Points"])

        dtype = np.dtype(
            {
                "names": [v.name for v in info_vars],
                "formats": [np.float64] * len(info_vars),
            }
        )

        np.set_printoptions(precision=5)

        data = np.fromfile(f, dtype=dtype, count=no_points)
    return data
