# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
from contextlib import contextmanager
import tempfile

from ..core.rational import R

#: U+2126 OHM SIGN for value labels. The web UI's Inconsolata font covers it,
#: unlike the Greek capital omega, which would render in a fallback font.
OHM = '\u2126'

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
