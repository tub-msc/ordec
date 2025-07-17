# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
from ordec.core import Cell

@pytest.mark.xfail
def test_ord_empty():
    from ordec.lib.ord_test import empty

@pytest.mark.xfail
def test_ord_empty2():
    from ordec.lib.ord_test import empty2

def test_ord_multicell():
    from ordec.lib.ord_test import multicell
    assert issubclass(multicell.Cell1, Cell)
    assert issubclass(multicell.Cell2, Cell)
