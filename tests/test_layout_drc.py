# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.lib import ihp130
#from ordec.layout import *


def test_drc():
    l = ihp130.Nmos(l="300n", w="200000n", ng=20).layout
    ret = ihp130.run_drc(l, variant='minimal') #TODO: 'maximal'
    print(ret.pretty())
    assert ret.summary() == {
        'AFil.g/g1': 1,
        'AFil.g2/g3': 1,
        'M1.j/k': 1,
        'M2.j/k': 1,
        'M3.j/k': 1,
        'M4.j/k': 1,
        'M5.j/k': 1,
        'M1Fil.h/k': 1,
        'M2Fil.h/k': 1,
        'M3Fil.h/k': 1,
        'M4Fil.h/k': 1,
        'M5Fil.h/k': 1,
        'TM1.c/d': 1,
        'TM2.c/d': 1
    }

