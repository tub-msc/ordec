# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
from contextlib import contextmanager
from dataclasses import dataclass
import tempfile

from ..core.rational import R

#: U+2126 OHM SIGN for value labels. The web UI's Inconsolata font covers it,
#: unlike the Greek capital omega, which would render in a fallback font.
OHM = '\u2126'

@dataclass(frozen=True)
class TechInfo:
    """Technology description queried uniformly by cross-PDK tools, one
    instance per PDK module (`ihp130.tech`, `sky130.tech`). Layer names
    refer to attributes of the PDK's LayerStack. Lengths are in nm."""
    manufacturing_grid: int
    nominal_vdd: R
    #: Drawn layers that carry a net. Conduction through device internals
    #: (a MOS channel, a resistor body) is the consumer's concern.
    conductors: tuple
    #: Layers each cut layer connects: a cut shape connects the shapes it
    #: overlaps on the listed layers.
    via_connects: dict
    #: The subset of conductors that form device internals (MOS and tap
    #: diffusion, capacitor plates): a conduction model that stops at
    #: device terminals excludes these.
    device_bodies: tuple = ()

def format_si(value: float) -> str:
    """Format a number at 3 significant digits with an SI suffix."""
    return str(R(f"{value:.3g}"))

def check_dir(path: Path) -> Path:
    if not path.is_dir():
        raise Exception(f"Directory {path} not found.")
    return path

def check_file(path: Path) -> Path:
    if not path.is_file():
        raise Exception(f"File {path} not found.")
    return path

@contextmanager
def rundir(name: str, use_tempdir: bool):
    if use_tempdir:
        with tempfile.TemporaryDirectory() as cwd_str:
            yield Path(cwd_str)
    else:
        d = Path.cwd() / name
        d.mkdir(exist_ok=True)
        yield d


class PdkDict(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__
