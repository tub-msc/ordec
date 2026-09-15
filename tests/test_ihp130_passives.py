# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""IHP130-specific passive device behavior: meander geometry details and
parameter bounds. DRC, LVS and ngspice characterization of the passives run
cross-PDK in test_pdks.py."""

import pytest

from ordec.core import ParameterError
from ordec.lib import ihp130


def test_resistor_meander_geometry():
    """b+1 stripes of l - w, joined at alternating ends, terminals at
    stripe 0 bottom and the last stripe's free end."""
    lay = ihp130.Rhigh(l="2u", w="500n", b=2, ps="400n").layout
    stripe = 2000 - 500
    for i in range(3):
        r = lay.poly_body[i].rect
        assert (int(r.lx), int(r.ly), int(r.ux), int(r.uy)) == (
            i * 900, 0, i * 900 + 500, stripe)
    top = lay.poly_bend[0].rect
    assert (int(top.ly), int(top.uy)) == (stripe, stripe + 500)
    bot = lay.poly_bend[1].rect
    assert (int(bot.ly), int(bot.uy)) == (-500, 0)
    # Odd stripe count: the p terminal sits at the top of the last stripe.
    assert int(lay.term_p.rect.ly) > stripe
    assert int(lay.term_n.rect.uy) < 0


@pytest.mark.parametrize("kind", [ihp130.Rppd, ihp130.Rhigh])
def test_resistor_meander_ps_floor(kind):
    with pytest.raises(ParameterError, match="ps >= 400 nm"):
        kind(l="2.0u", w="0.5u", b=2, ps="180n").layout
