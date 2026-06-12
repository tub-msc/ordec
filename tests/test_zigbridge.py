# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for ordec.zigbridge: the canonical CBOR wire format shared with the
Zig implementation (zig/), and the C-library bridge to the Zig placer.

The wire-format tests run standalone. The end-to-end tests require the
shared library (cd zig && zig build) and are skipped without it.
"""

from fractions import Fraction

import cbor2
import pytest

from ordec.core.cell import Cell
from ordec.core.geoprim import D4, Vec2R, Vec2I, Rect4R, Rect4I
from ordec.core.rational import R
from ordec.core.schema import (
    Symbol, Pin, PinType, SymbolPoly, SymbolArc,
    Schematic, Net, SchemPort, SchemWire, SchemInstance,
    LayerStack, Layer, GdsLayer, RGBColor,
    Layout, LayoutRect, LayoutPoly, LayoutPath, LayoutLabel, LayoutPin,
    LayoutInstance, LayoutInstanceArray, PathEndType,
    Report,
)
from ordec.zigbridge import (
    wire, lib, place, content_hash, encode_transfer, collect_bundle,
    decode_bundle, WireError, UnsupportedNode, UnsupportedAttr, ZigBridgeError,
)

# Shared with zig/src/serialize_test.zig ("golden content hash"). If the wire
# format changes, the Zig and Python golden tests fail together: bump the
# format version and update both constants deliberately.
GOLDEN_HASH = "0639a27440a8963bda4f7e6c15a54e8f9dd0c1b7cdd20f001c8c8b83e3735900"

requires_zig_lib = pytest.mark.skipif(
    not lib.available(),
    reason="libordec_zig.so not built; run: cd zig && zig build",
)


# Fixtures
# --------

def make_symbol():
    s = Symbol(caption="inv", outline=Rect4R(0, 0, 4, 8))
    s.a = Pin(pintype=PinType.In, pos=Vec2R(0, 4))
    s.y = Pin(pintype=PinType.Out, pos=Vec2R(4, 4), align=D4.MY90)
    s % SymbolPoly(vertices=[Vec2R(1, 2), Vec2R(1, 6), Vec2R(3, 4)])
    s % SymbolArc(pos=Vec2R(3, 4), radius=R(1, 4))
    return s.freeze()


def make_layers():
    ls = LayerStack(unit=R('1n'))
    ls.nwell = Layer(gdslayer_shapes=GdsLayer(1, 0))
    ls.diff = Layer(gdslayer_shapes=GdsLayer(2, 0),
                    style_fill=RGBColor(0x10, 0x20, 0x30))
    ls.metal1 = Layer(gdslayer_shapes=GdsLayer(8, 0))
    return ls.freeze()


def make_fake_cell(layers, name, sites, npins):
    """A standard cell of `sites` * 100 width and 800 height (mirrors the
    fixtures in zig/src/placer.zig)."""
    s = Symbol(caption=name, outline=Rect4R(0, 0, 4, 4))
    pins = []
    for i in range(npins):
        p = Pin(pos=Vec2R(0, i))
        setattr(s, f"p{i}", p)
        pins.append(getattr(s, f"p{i}"))
    fsym = s.freeze()
    lay = Layout(symbol=fsym.subgraph, ref_layers=layers.subgraph)
    w = sites * 100
    lay % LayoutRect(layer=layers.nwell.nid, rect=Rect4I(0, 400, w, 800))
    shape = lay % LayoutRect(layer=layers.diff.nid, rect=Rect4I(0, 0, w, 400))
    lay % LayoutPin(ref=shape.nid, pin=pins[0].nid)
    return lay.freeze()


def make_unplaced(layers, cells):
    inv, nand2, dff = cells
    top = Layout(ref_layers=layers.subgraph)
    for _ in range(4):
        top % LayoutInstance(pos=Vec2I(0, 0), ref=inv.subgraph)
    for _ in range(3):
        top % LayoutInstance(pos=Vec2I(0, 0), ref=nand2.subgraph)
    top % LayoutInstance(pos=Vec2I(0, 0), ref=dff.subgraph)
    top % LayoutInstanceArray(pos=Vec2I(0, 0), ref=inv.subgraph,
                              cols=2, rows=2, vec_col=Vec2I(300, 0),
                              vec_row=Vec2I(0, 800))
    return top.freeze()


# Wire format (no shared library required)
# ----------------------------------------

def test_cbor2_canonical_defaults():
    # Tripwire separating cbor2 regressions from wire-table bugs: these are
    # the exact canonical encodings the Zig decoder expects.
    assert cbor2.dumps(Fraction(1, 4)).hex() == "d81e820104"      # tag 30
    assert cbor2.dumps(R("f'1/4")).hex() == "d81e820104"          # R subclass
    assert cbor2.dumps(2**64 - 1).hex() == "1bffffffffffffffff"   # head form
    assert cbor2.dumps(2**64).hex() == "c249010000000000000000"   # tag 2
    assert cbor2.dumps(-2**64).hex() == "3bffffffffffffffff"      # head form
    assert cbor2.dumps(-2**64 - 1).hex() == "c349010000000000000000"  # tag 3
    assert cbor2.dumps([23, 24]).hex() == "82171818"              # minimal heads


def test_golden_content_hash():
    s = Symbol(caption="golden")
    s.p = Pin(pintype=PinType.Out, pos=Vec2R(1, 2), align=D4.R90)
    f = s.freeze()
    assert content_hash(f.subgraph).hex() == GOLDEN_HASH


def roundtrip(fsg):
    blobs, deps = collect_bundle(fsg)
    decoded = decode_bundle(blobs, {})
    assert content_hash(decoded) == content_hash(fsg)
    # Re-encoding the decoded subgraph gives byte-identical blobs:
    blobs2, _ = collect_bundle(decoded)
    assert blobs2 == blobs
    return decoded


def test_roundtrip_symbol():
    f = make_symbol()
    decoded = roundtrip(f.subgraph)
    root = decoded.root_cursor
    assert root.caption == "inv"
    assert root.a.pintype == PinType.In
    assert root.y.align == D4.MY90
    poly = next(iter(decoded.root_cursor.all(SymbolPoly)))
    assert poly.vertices() == [Vec2R(1, 2), Vec2R(1, 6), Vec2R(3, 4)]


def test_roundtrip_big_rationals():
    # Values beyond +/-2^64 exercise the bignum tag 2/3 wire paths:
    s = Symbol()
    s % SymbolArc(pos=Vec2R(0, 0), radius=R(2**70 + 1, 3),
                  angle_start=R(-(2**100), 7))
    f = s.freeze()
    decoded = roundtrip(f.subgraph)
    arc = next(iter(decoded.root_cursor.all(SymbolArc)))
    assert arc.radius == R(2**70 + 1, 3)
    assert arc.angle_start == R(-(2**100), 7)


def test_roundtrip_layerstack():
    f = make_layers()
    decoded = roundtrip(f.subgraph)
    m1 = decoded.root_cursor.metal1
    assert m1.gdslayer_shapes == GdsLayer(8, 0)
    assert decoded.root_cursor.diff.style_fill == RGBColor(0x10, 0x20, 0x30)
    # NPath hierarchy survives:
    assert decoded.root_cursor.nwell.full_path_str() == "nwell"


def test_roundtrip_schematic():
    fsym = make_symbol()
    sch = Schematic(symbol=fsym.subgraph, outline=Rect4R(0, 0, 10, 10))
    sch.a = Net(pin=fsym.a.nid)
    sch.y = Net(pin=fsym.y.nid)
    sch.default_supply = sch.y
    sch % SchemPort(ref=sch.a.nid, pos=Vec2R(0, 5), align=D4.R180)
    sch % SchemWire(ref=sch.a.nid, vertices=[Vec2R(0, 5), Vec2R(2, 5)])
    sch.I0 = SchemInstance(pos=Vec2R(2, 3),
                           connect=fsym.portmap(a=sch.a, y=sch.y))
    f = sch.freeze()

    blobs, deps = collect_bundle(f.subgraph)
    # Bundle: symbol + schematic (symbol shared by root and instance, sent once):
    assert len(blobs) == 2
    decoded = roundtrip(f.subgraph)
    root = decoded.root_cursor
    assert root.default_supply.full_path_str() == "y"
    # ExternalRef into the symbol resolves on the reconstructed subgraph:
    assert root.a.pin.pintype == PinType.In
    conns = list(root.I0.conns())
    assert len(conns) == 2


def test_roundtrip_layout():
    layers = make_layers()
    fsym = make_symbol()
    lay = Layout(symbol=fsym.subgraph, ref_layers=layers.subgraph)
    r = lay % LayoutRect(layer=layers.metal1.nid, rect=Rect4I(0, 0, 400, 800))
    lay % LayoutPin(ref=r.nid, pin=fsym.a.nid)
    lay % LayoutPoly(layer=layers.diff.nid,
                     vertices=[Vec2I(0, 0), Vec2I(100, 0), Vec2I(100, 900)])
    # LayoutPath is the node whose wire attribute order differs from the
    # Python declaration order; make sure it round-trips:
    lay % LayoutPath(layer=layers.metal1.nid, width=50,
                     endtype=PathEndType.Square,
                     vertices=[Vec2I(0, 0), Vec2I(500, 0)])
    lay % LayoutLabel(layer=layers.metal1.nid, pos=Vec2I(7, 8), text="hi")
    inner = lay.freeze()

    top = Layout(ref_layers=layers.subgraph)
    top % LayoutInstance(pos=Vec2I(10, 20), orientation=D4.MX,
                         ref=inner.subgraph)
    top % LayoutInstanceArray(pos=Vec2I(0, 0), ref=inner.subgraph,
                              cols=3, rows=2, vec_col=Vec2I(500, 0),
                              vec_row=Vec2I(0, 1000))
    f = top.freeze()

    decoded = roundtrip(f.subgraph)
    arr = next(iter(decoded.root_cursor.all(LayoutInstanceArray)))
    assert (arr.cols, arr.rows) == (3, 2)
    inner_decoded = arr.ref.subgraph
    path = next(iter(inner_decoded.root_cursor.all(LayoutPath)))
    assert path.endtype == PathEndType.Square
    assert path.width == 50
    assert path.layer.gdslayer_shapes == GdsLayer(8, 0)
    label = next(iter(inner_decoded.root_cursor.all(LayoutLabel)))
    assert (label.pos, label.text) == (Vec2I(7, 8), "hi")


def test_reject_cell_attr():
    s = Symbol(caption="x")
    s.cell = Cell()
    f = s.freeze()
    with pytest.raises(UnsupportedAttr, match="cell"):
        encode_transfer(f.subgraph)
    # Explicit opt-in drops it; the hash treats cell as absent either way:
    blob = encode_transfer(f.subgraph, strip_cell=True)
    decoded = wire.decode_transfer(blob, {})
    assert decoded.root_cursor.cell is None
    assert content_hash(decoded) == content_hash(f.subgraph)


def test_reject_unsupported_root():
    rep = Report()
    with pytest.raises(UnsupportedNode):
        encode_transfer(rep.subgraph.freeze())


def test_reject_out_of_range_int():
    layers = make_layers()
    lay = Layout(ref_layers=layers.subgraph)
    lay % LayoutRect(layer=layers.nwell.nid, rect=Rect4I(0, 0, 2**31, 10))
    with pytest.raises(WireError, match="outside"):
        encode_transfer(lay.freeze().subgraph)


def test_decode_rejects_malformed():
    with pytest.raises(WireError):
        wire.decode_transfer(b"\x00garbage", {})
    # Missing dependency:
    fsym = make_symbol()
    sch = Schematic(symbol=fsym.subgraph)
    blob = encode_transfer(sch.freeze().subgraph)
    with pytest.raises(WireError, match="missing dependency"):
        wire.decode_transfer(blob, {})


# End-to-end through libordec_zig.so
# ----------------------------------

@requires_zig_lib
def test_echo_roundtrip():
    f = make_layers()
    blobs, deps = collect_bundle(f.subgraph)
    response = lib.call('ordec_echo', cbor2.dumps([lib.ABI_VERSION, None, blobs]))
    out_blobs = cbor2.loads(response)
    decoded = decode_bundle(out_blobs, deps)
    assert content_hash(decoded) == content_hash(f.subgraph)


def cell_bbox(layout_subgraph):
    """Bounding box over the LayoutRects of a test cell."""
    rects = [tuple(c.rect) for c in layout_subgraph.root_cursor.all(LayoutRect)]
    return (min(r[0] for r in rects), min(r[1] for r in rects),
            max(r[2] for r in rects), max(r[3] for r in rects))


def assert_legal(placed, die_width, site_width, row_height):
    """Python mirror of placer.zig's verifyLegal."""
    assert not list(placed.all(LayoutInstanceArray))
    by_row = {}
    for inst in placed.all(LayoutInstance):
        lx, ly, ux, uy = cell_bbox(inst.ref.subgraph)
        px, py = inst.pos
        if inst.orientation == D4.R0:
            rect = (px + lx, py + ly, px + ux, py + uy)
        elif inst.orientation == D4.MX:  # y negated
            rect = (px + lx, py - uy, px + ux, py - ly)
        else:
            raise AssertionError(f"unexpected orientation {inst.orientation}")
        assert rect[0] >= 0 and rect[2] <= die_width
        assert rect[0] % site_width == 0
        assert rect[1] % row_height == 0
        assert rect[3] - rect[1] == row_height
        row = rect[1] // row_height
        assert row >= 0
        expected = D4.R0 if row % 2 == 0 else D4.MX
        assert inst.orientation == expected
        for other in by_row.get(row, []):
            assert rect[2] <= other[0] or rect[0] >= other[2], "overlap"
        by_row.setdefault(row, []).append(rect)


@requires_zig_lib
def test_place():
    layers = make_layers()
    cells = (make_fake_cell(layers, "inv", 3, 2),
             make_fake_cell(layers, "nand2", 4, 3),
             make_fake_cell(layers, "dff", 9, 3))
    f = make_unplaced(layers, cells)

    placed = place(f, die_width=2000, site_width=100, row_height=800)

    insts = list(placed.all(LayoutInstance))
    assert len(insts) == 12  # 4 + 3 + 1 + expanded 2x2 array
    assert_legal(placed, die_width=2000, site_width=100, row_height=800)

    # The input is untouched:
    assert len(list(f.all(LayoutInstance))) == 8
    assert len(list(f.all(LayoutInstanceArray))) == 1

    # Determinism: same input, same result bytes:
    placed2 = place(f, die_width=2000, site_width=100, row_height=800)
    assert content_hash(placed.subgraph) == content_hash(placed2.subgraph)


@requires_zig_lib
def test_place_preserves_cell_attr():
    layers = make_layers()
    inv = make_fake_cell(layers, "inv", 3, 2)
    top = Layout(ref_layers=layers.subgraph)
    top % LayoutInstance(pos=Vec2I(0, 0), ref=inv.subgraph)
    c = Cell()
    top.cell = c
    f = top.freeze()
    placed = place(f, die_width=2000, site_width=100, row_height=800)
    assert placed.cell is c


@requires_zig_lib
def test_place_domain_error():
    layers = make_layers()
    dff = make_fake_cell(layers, "dff", 9, 3)  # 900 wide
    top = Layout(ref_layers=layers.subgraph)
    top % LayoutInstance(pos=Vec2I(0, 0), ref=dff.subgraph)
    with pytest.raises(ZigBridgeError) as exc_info:
        place(top.freeze(), die_width=800, site_width=100, row_height=800)
    assert exc_info.value.code == 3
    assert "CellTooWide" in exc_info.value.message


@requires_zig_lib
def test_lib_error_envelope():
    with pytest.raises(ZigBridgeError) as exc_info:
        lib.call('ordec_echo', b"\x00garbage")
    assert exc_info.value.code == 1
