# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

def check_dir(path: Path) -> Path:
    if not path.is_dir():
        raise Exception(f"Directory {path} not found.")
    return path

def check_file(path: Path) -> Path:
    if not path.is_file():
        raise Exception(f"File {path} not found.")
    return path

class PdkDict(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__
