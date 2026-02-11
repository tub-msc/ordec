# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
import ordec.importer
from ordec.core import Cell

def test_ord_empty():
    from .lib.ord1 import empty

def test_ord_empty2():
    from .lib.ord1 import empty2

def test_ord_multicell():
    from .lib.ord1 import multicell
    assert issubclass(multicell.Cell1, Cell)
    assert issubclass(multicell.Cell2, Cell)
