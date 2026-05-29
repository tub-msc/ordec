# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.core import *


def thin_wrapper_cell(inner: Cell) -> Cell:
    """Wrap a leaf primitive instance in a parameter-less Cell for LVS/DRC.

    Leaf primitives (SimLeafCells) have no schematic, but ``run_lvs()`` needs
    one. This returns a Cell with auto-generated symbol, schematic (a single
    instance of the inner symbol) and layout (the inner layout, re-pinned).

    Ports come from the inner *layout* pins, not symbol pins: an LVS port needs
    both, so the valid set is their intersection (= the layout pins). A
    resistor's bulk pin ``bn`` has a symbol pin but no layout pin, so it is
    wired internally rather than exposed; exposing it would fail LVS.
    """
    inner_symbol = inner.symbol

    class ThinWrapper(Cell):
        @generate
        def symbol(self):
            s = Symbol(cell=self)
            for lp in inner.layout.all(LayoutPin):
                ip = inner_symbol[lp.pin.npath.name]
                setattr(s, lp.pin.npath.name, Pin(pintype=ip.pintype, align=ip.align))
            s.place_pins()
            return s

        @generate
        def schematic(self):
            s = Schematic(cell=self, symbol=self.symbol)
            ports = {lp.pin.npath.name for lp in inner.layout.all(LayoutPin)}

            nets = {}
            for pin in inner_symbol.all(Pin):
                name = pin.npath.name
                if name in ports:
                    net = Net(pin=self.symbol[name])
                else:
                    net = Net()
                setattr(s, name, net)
                nets[name] = getattr(s, name)

            s.dev = SchemInstance(inner_symbol.portmap(**nets), pos=(4, 4))
            for name in ports:
                getattr(s, name) % SchemPort(
                    pos=s.dev.loc_transform() * inner_symbol[name].pos,
                    align=inner_symbol[name].align,
                )
            s.auto_wire()
            return s

        @generate
        def layout(self):
            l = Layout(ref_layers=inner.layout.ref_layers, cell=self,
                symbol=self.symbol)
            l.dev = LayoutInstance(ref=inner.layout, pos=(0, 0))
            for lp in inner.layout.all(LayoutPin):
                name = lp.pin.npath.name
                setattr(l, f"pin_{name}", LayoutRect(layer=lp.ref.layer, rect=lp.ref.rect))
                getattr(l, f"pin_{name}").create_pin(self.symbol[name])
            return l

    ThinWrapper.__name__ = f"ThinWrapper_{inner.escaped_name()}"
    ThinWrapper.__qualname__ = ThinWrapper.__name__
    return ThinWrapper()
