# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.core import *


def layout_x_extent(layout) -> tuple[int, int]:
    """(lx, ux) over all rect and polygon geometry of a leaf layout."""
    xs = []
    for r in layout.all(LayoutRect):
        xs += [int(r.rect.lx), int(r.rect.ux)]
    for p in layout.all(LayoutPoly):
        xs += [int(v.x) for v in p.vertices]
    return min(xs), max(xs)


def gallery_wrapper_cell(inners: list[Cell], name: str) -> Cell:
    """Wrap leaf primitive instances in one parameter-less Cell for LVS/DRC.

    Leaf primitives (SimLeafCells) have no schematic, but ``run_lvs()`` needs
    one. This returns a Cell with auto-generated symbol, schematic and layout
    holding all given devices side by side, each on its own pins. Deck startup
    dominates KLayout runtime, so one DRC and one LVS run cover the whole
    gallery.

    Ports come from each inner *layout* pins, not symbol pins: an LVS port
    needs both, so the valid set is their intersection (= the layout pins). A
    resistor's bulk pin ``bn`` has a symbol pin but no layout pin, so it is
    wired internally rather than exposed; exposing it would fail LVS.

    Device and pin names carry the device class plus its list index
    (``rsil0``, ``rsil0_p``, ...), so LVS and DRC reports point back to the
    offending gallery entry.
    """
    names = [f"{type(c).__name__.lower()}{i}" for i, c in enumerate(inners)]

    class GalleryWrapper(Cell):
        @viewgen_noctx
        def symbol(self):
            s = Symbol(cell=self)
            for dev, inner in zip(names, inners):
                for lp in inner.layout.all(LayoutPin):
                    ip = inner.symbol[lp.pin.npath.name]
                    setattr(s, f"{dev}_{lp.pin.npath.name}",
                        Pin(pintype=ip.pintype, align=ip.align))
            s.place_pins()
            return s

        @viewgen_noctx
        def schematic(self):
            s = Schematic(cell=self, symbol=self.symbol)
            # All unexposed pins (resistor bulks) share one internal net,
            # matching the extracted layout where the bodies sit in the
            # common substrate.
            sub = None
            for i, (dev, inner) in enumerate(zip(names, inners)):
                ports = {lp.pin.npath.name for lp in inner.layout.all(LayoutPin)}

                nets = {}
                for pin in inner.symbol.all(Pin):
                    name = pin.npath.name
                    if name in ports:
                        setattr(s, f"{dev}_{name}",
                            Net(pin=self.symbol[f"{dev}_{name}"]))
                        nets[name] = getattr(s, f"{dev}_{name}")
                    else:
                        if sub is None:
                            s.sub = Net()
                            sub = s.sub
                        nets[name] = sub

                setattr(s, dev, SchemInstance(inner.symbol.portmap(**nets),
                    pos=(4 + 16 * i, 4)))
                inst = getattr(s, dev)
                for name in ports:
                    getattr(s, f"{dev}_{name}") % SchemPort(
                        pos=inst.loc_transform() * inner.symbol[name].pos,
                        align=inner.symbol[name].align,
                    )
            s.auto_wire()
            return s

        @viewgen_noctx
        def layout(self):
            l = Layout(ref_layers=inners[0].layout.ref_layers, cell=self,
                symbol=self.symbol)
            # Gap between devices in nm, safely above the SG13G2 min
            # spacing and marker rules.
            gap = 2000
            xoff = 0
            for dev, inner in zip(names, inners):
                lx, ux = layout_x_extent(inner.layout)
                setattr(l, dev, LayoutInstance(ref=inner.layout, pos=(xoff - lx, 0)))
                inst = getattr(l, dev)
                for lp in inner.layout.all(LayoutPin):
                    name = lp.pin.npath.name
                    r = inst.loc_transform() * lp.ref.rect
                    setattr(l, f"pin_{dev}_{name}",
                        LayoutRect(layer=lp.ref.layer, rect=r))
                    getattr(l, f"pin_{dev}_{name}").create_pin(
                        self.symbol[f"{dev}_{name}"])
                xoff += ux - lx + gap
            return l

    GalleryWrapper.__name__ = name
    GalleryWrapper.__qualname__ = name
    return GalleryWrapper()
