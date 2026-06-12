# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
High-level wrapper for the Zig standard-cell placer (zig/src/placer.zig).
"""

import cbor2

from ..core.ordb import FrozenSubgraph, MutableSubgraph
from . import lib, wire


def place(layout, *, die_width: int, site_width: int, row_height: int):
    """
    Legalize the LayoutInstances of ``layout`` with the Zig placer: pack them
    into standard-cell rows on a site grid within die_width, alternating row
    orientation (odd rows MX-flipped). LayoutInstanceArrays are expanded into
    individual instances.

    Args:
        layout: A Layout root cursor, FrozenSubgraph, or mutable Layout
            (frozen on entry). The input is never modified.

    Returns:
        The placed Layout as a frozen root cursor. The root's ``cell``
        attribute (which has no wire representation) is carried over from
        the input. SubgraphRefs in the result (standard cells, layer stack,
        symbol) resolve to the *same* FrozenSubgraph objects referenced by
        the input — the response is decoded against the dependency set
        collected at encode time, so no duplicate subgraph copies are
        created.
    """
    sgobj = layout.subgraph if not isinstance(layout, (FrozenSubgraph, MutableSubgraph)) else layout
    if isinstance(sgobj, MutableSubgraph):
        sgobj = sgobj.freeze()
    fsg = wire._as_frozen_subgraph(sgobj)

    root = fsg.nodes[0]
    cell = root[root._attrdesc_by_name['cell'].index]

    blobs, deps = wire.collect_bundle(fsg, strip_cell=True)
    request = cbor2.dumps([
        lib.ABI_VERSION,
        [int(die_width), int(site_width), int(row_height)],
        blobs,
    ])
    response = lib.call('ordec_place', request)
    try:
        out_blobs = cbor2.loads(response)
    except Exception as e:
        raise wire.WireError(f"undecodable response: {e}")
    result = wire.decode_bundle(out_blobs, deps)

    if cell is not None:
        # Re-attach the input's cell attribute, which was stripped at encode:
        mutable = result.thaw()
        mutable.root_cursor.cell = cell
        result = mutable.freeze()
    return result.root_cursor
