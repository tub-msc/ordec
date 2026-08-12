# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Lesson checks for the 'layout_tutorial' course.

Each gen_lesson* function takes the lesson namespace (globals) and returns the
lesson() view generator for that lesson: a @viewgen_noctx building a Report
whose PassFail elements decide whether the lesson is passed (the course UI
considers a lesson passed when all its PassFail elements pass). Exceptions
during checking are converted into failing PassFail elements, so the view
never crashes on a broken user design. Note that a broken or underconstrained
layout raises on view access (there is no Layout equivalent of
Schematic.has_errors()), so every geometry check must guard the layout access.

Exceptions: lesson 1 is a task-free welcome lesson (generic course.json flag
welcome: solved right away) and the final what's-next lesson is a task-free
epilogue (generic flag epilogue: solved right away, no callout, no source
editor in its layout). Their reports carry only instructions and no PassFail
elements.

Lessons 8, 9 and 11 run KLayout DRC/LVS inside their checks, so re-checking
after an edit takes a few seconds there. (The DRC/LVS result panels of those
lessons are a different matter: their viewgens are declared with
auto_refresh=False in the lesson sources and update only via their Refresh
overlay.)
"""

import traceback

from ordec.core import *
from ordec.lib import ihp130

# The SG13G2 layer stack; cells and views are cached, so this is the same
# subgraph that the lesson sources reference via SG13G2().layers.
layers = ihp130.SG13G2().layers


def exception_text() -> str:
    """Format the current exception for display in a PassFail element."""
    return "The check raised an exception:\n" + traceback.format_exc()


def rects_on(layout, layer):
    """All top-level LayoutRects of a layout on the given layer."""
    return [r for r in layout.all(LayoutRect) if r.layer == layer]


def paths_on(layout, layer):
    """All top-level LayoutPaths of a layout on the given layer."""
    return [p for p in layout.all(LayoutPath) if p.layer == layer]


def fmt_rects(rects):
    """Compact geometry listing for check instructions."""
    if not rects:
        return "none"
    return ", ".join(f"({r.rect.lx}, {r.rect.ly}, {r.rect.ux}, {r.rect.uy})"
        for r in rects)


# Lesson 1: Welcome to the layout editor
# --------------------------------------

def gen_lesson1(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            Welcome to the layout tutorial! In this course, you learn how to
            describe IC layouts in ORD: drawing shapes, positioning them with
            geometric constraints, placing and wiring transistors, and
            verifying the result with DRC and LVS. The technology is IHP's
            open SG13G2 130 nm process.

            A *layout* describes the geometry that is manufactured on the
            chip: rectangles and polygons on named *layers* (metal levels,
            polysilicon, doped regions, vias). The source code below builds
            the small example layout shown in the viewer on the right.
            Two things to know about layout coordinates:

            1. All coordinates are **integers in nanometers** (the database
               unit of SG13G2). `3000` means 3 µm.
            2. The y axis points **up**.

            **Take a moment to explore the layout viewer:**

            1. Open the *Layers* sidebar (top right corner of the viewer)
               and hide/show individual layers, e.g. `Metal2`.
            2. Hover over the layout: the current cursor position in
               nanometers is shown in the sidebar.
            3. Zoom with the mouse wheel, pan by dragging. Press `f` to
               zoom back to the full layout.
            4. Zoom into the transistor on the right: it is built from
               rectangles on several layers.

            There is nothing to solve here. Press the *next* arrow above
            to continue with your first own rectangles.
        """)
        return report
    return lesson


# Lesson 2: Drawing rectangles
# ----------------------------

def gen_lesson2(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            The source code below defines a layout view: `.ref_layers`
            selects the technology's layer stack (this must come first), and
            `layers` makes it available under a short name. A rectangle is
            drawn by creating a `LayoutRect` with a layer and corner
            coordinates `(lx, ly, ux, uy)`, lower left, then upper right,
            in nanometers:

            ```
            LayoutRect base: .layer=layers.Metal1; .rect=(0, 0, 3000, 500)
            ```

            **Add the following three rectangles below the EDIT HERE
            marker:**

            1. A `Metal2` rectangle from (0, 900) to (3000, 1400).
            2. An `Activ` rectangle from (500, 2000) to (1500, 2600).
            3. A `GatPoly` rectangle from (2000, 2000) to (2200, 2900).

            `Activ` (the doped silicon area) and `GatPoly` (the transistor
            gate material) are the layers transistors are made of; we will
            meet them again soon.

            *Tip: besides rectangles, there are `LayoutPoly` (polygons),
            `LayoutPath` (wires with a width) and `LayoutLabel` (text
            labels). Rectangles will take us surprisingly far.*
        """)

        def check_rect(label, layer, layer_name, rect):
            hint = (f"Add `LayoutRect r: .layer=layers.{layer_name}; "
                f".rect={rect}` at the EDIT HERE marker.")
            try:
                found = rects_on(g['Example']().layout, layer)
                report.passfail(label, any(r.rect == Rect4I(*rect)
                        for r in found), hint=hint,
                    instructions=f"Looking for a {layer_name} rectangle at "
                        f"{rect}. Found on {layer_name}: {fmt_rects(found)}.")
            except Exception:
                report.passfail(label, False, instructions=exception_text(),
                    hint=hint)

        check_rect("Metal2 rectangle drawn", layers.Metal2, "Metal2",
            (0, 900, 3000, 1400))
        check_rect("Activ rectangle drawn", layers.Activ, "Activ",
            (500, 2000, 1500, 2600))
        check_rect("GatPoly rectangle drawn", layers.GatPoly, "GatPoly",
            (2000, 2000, 2200, 2900))
        return report
    return lesson


# Lesson 3: Geometric constraints
# -------------------------------

def gen_lesson3(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            Fixed coordinates become unwieldy quickly. Instead, ORDeC lets
            you describe *where shapes are relative to each other* with
            geometric constraints, written as lines starting with `!`. A
            solver then computes all coordinates.

            Every rectangle offers *anchors* you can constrain: the edges
            `lx`, `ly`, `ux`, `uy`, the center coordinates `cx`, `cy`, the
            dimensions `width`, `height`, `size`, and the points `center`,
            `north`, `south`, `east`, `west`, `northwest` … `southeast`
            (edge midpoints and corners).

            **Task 1: bridge the gap between the pads:** at the
            `EDIT HERE (bridge)` marker, add a Metal1 rectangle that
            connects `pad_w` and `pad_e`. Start with only the two
            attachment constraints:

            ```
            LayoutRect bridge:
                .layer = layers.Metal1
                ! .west == pad_w.east
                ! .east == pad_e.west
            ```

            The layout viewer now shows an error: the solver reports the
            layout as *underconstrained* and names the remaining degree of
            freedom: nothing determines the bridge's height yet. (While
            the layout is unsolvable, all checks below fail; that is
            expected.) Complete the bridge with:

            ```
                ! .height == 400
            ```

            **Task 2: center a pad between two others:** `pad_w2` and
            `pad_e2` form a second row below. Constraints do not have to
            pin a shape to a known coordinate. They can also be used to *relate
            distances*. At the `EDIT HERE (center)` marker, add a third
            pad of the same size whose gap to `pad_w2` equals its gap to
            `pad_e2`:

            ```
            LayoutRect pad_c:
                .layer = layers.Metal1
                ! .size == (800, 800)
                ! .ly == pad_w2.ly
                ! .lx - pad_w2.ux == pad_e2.lx - .ux
            ```

            The last constraint names no position at all. It only
            demands that two distances match, and the solver settles the
            pad exactly midway between its neighbors.

            *Tip: point anchors can be shifted by a tuple, e.g.
            `! .southwest == pad_w.northwest + (0, 300)`. And since
            constraints are linear equations, weighted anchors work too:
            `! .cx == 0.5*pad_w2.cx + 0.5*pad_e2.cx` centers `pad_c` in
            a single constraint.*
        """)

        def bridges():
            return [r for r in rects_on(g['Example']().layout, layers.Metal1)
                if r.rect.lx == 800 and r.rect.ux == 4000
                and r.rect.ly + r.rect.uy == 4800]

        hint_bridge = ("Add the `bridge` block from task 1 at the "
            "EDIT HERE (bridge) marker. As long as the solver reports the "
            "layout as underconstrained, all checks fail.")
        try:
            report.passfail("Bridge spans between the pads", bool(bridges()),
                hint=hint_bridge,
                instructions="Looking for a Metal1 rectangle attached to "
                    "pad_w.east and pad_e.west.")
        except Exception:
            report.passfail("Bridge spans between the pads", False,
                instructions=exception_text(), hint=hint_bridge)

        hint_height = ("Complete the bridge with `! .height == 400`. The "
            "solver error message in the layout viewer lists what is still "
            "undetermined.")
        try:
            report.passfail("Bridge fully constrained",
                any(r.rect.uy - r.rect.ly == 400 for r in bridges()),
                hint=hint_height,
                instructions="The bridge must have a height of 400 nm.")
        except Exception:
            report.passfail("Bridge fully constrained", False,
                instructions=exception_text(), hint=hint_height)

        def center_pads():
            # 800x800 Metal1 pads in the lower row, excluding the given
            # pad_w2 and pad_e2.
            return [r for r in rects_on(g['Example']().layout, layers.Metal1)
                if r.rect.ux - r.rect.lx == 800
                and r.rect.uy - r.rect.ly == 800
                and r.rect.ly == 0 and r.rect.lx not in (0, 4000)]

        hint_center = ("Add the `pad_c` block from task 2 at the "
            "EDIT HERE (center) marker.")
        try:
            report.passfail("Third pad drawn in the lower row",
                bool(center_pads()), hint=hint_center,
                instructions="Looking for an 800x800 Metal1 rectangle in "
                    "the row of pad_w2 and pad_e2.")
        except Exception:
            report.passfail("Third pad drawn in the lower row", False,
                instructions=exception_text(), hint=hint_center)

        hint_match = ("Center the pad with the matched-distance constraint "
            "`! .lx - pad_w2.ux == pad_e2.lx - .ux`.")
        try:
            report.passfail("Gaps to both neighbors match",
                any(r.rect.lx - 800 == 4000 - r.rect.ux
                    for r in center_pads()),
                hint=hint_match,
                instructions="The pad's gap to pad_w2 must equal its gap "
                    "to pad_e2.")
        except Exception:
            report.passfail("Gaps to both neighbors match", False,
                instructions=exception_text(), hint=hint_match)
        return report
    return lesson


# Lesson 4: Inequalities and enclosures
# -------------------------------------

def gen_lesson4(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            Constraints are not limited to `==`. Inequalities with `>=` and
            `<=` express *minimum clearances*, and the solver *pulls them
            tight*: it places shapes as close to the bound as allowed, so an
            inequality often both limits and positions a shape at once.
            This mirrors how chips are actually designed: a fab's design
            rulebook (you will meet it later in this course as *DRC*) is
            largely a list of minimum widths, spacings and enclosures, and
            inequalities are how such rules read as constraints.

            **Task 1: keep your distance.** Suppose the rulebook demands
            400 nm between Metal1 shapes. At the `EDIT HERE (clearance)`
            marker, add a pad with a clearance to `wall_a`:

            ```
            LayoutRect pad:
                .layer = layers.Metal1
                ! .size == (1200, 1200)
                ! .ly == 1200
                ! .lx >= wall_a.ux + 400
            ```

            The solver pulls the bound tight: the pad sits exactly 400 nm
            right of `wall_a` — and crashes into `wall_b`, because an
            inequality only limits what it names. Add the second rule:

            ```
                ! .lx >= wall_b.ux + 400
            ```

            Now both clearances hold, and the solver settles the pad
            against the *binding* one. That is the point of inequalities:
            you state all the limits, and the solver finds which of them
            matters.

            **Task 2: enclose the devices.** Doped regions must enclose
            the devices built inside them — an *enclosure* rule. The two
            Activ rectangles on the right stand in for such devices. At
            the `EDIT HERE (well)` marker, wrap them in a well:

            ```
            LayoutRect well:
                .layer = layers.NWell
                ! .contains(dev_a.rect)
                ! .contains(dev_b.rect)
            ```

            `contains` is four inequalities at once (one per edge).
            Nothing else positions `well`, yet it is fully determined: the
            solver pulls all four edges tight and the well shrink-wraps
            around both devices. You will use exactly this constraint
            later to draw the n-well of an inverter.
        """)

        def pads():
            # The user's 1200x1200 pad; the walls have other dimensions.
            return [r for r in rects_on(g['Example']().layout, layers.Metal1)
                if r.rect.ux - r.rect.lx == 1200
                and r.rect.uy - r.rect.ly == 1200
                and r.rect.ly == 1200]

        hint_pad = ("Add the `pad` block from task 1 at the "
            "EDIT HERE (clearance) marker.")
        try:
            report.passfail("Pad drawn next to the walls", bool(pads()),
                hint=hint_pad,
                instructions="Looking for a 1200x1200 Metal1 rectangle "
                    "with ly == 1200.")
        except Exception:
            report.passfail("Pad drawn next to the walls", False,
                instructions=exception_text(), hint=hint_pad)

        hint_clear = ("With only the wall_a clearance, the pad lands on "
            "wall_b. Add `! .lx >= wall_b.ux + 400`; the solver then "
            "settles the pad against the binding bound.")
        try:
            report.passfail("Pad clears both walls",
                any(r.rect.lx == 2200 for r in pads()),
                hint=hint_clear,
                instructions="The pad must sit 400 nm right of wall_b, "
                    f"starting at x = 2200. Found: {fmt_rects(pads())}.")
        except Exception:
            report.passfail("Pad clears both walls", False,
                instructions=exception_text(), hint=hint_clear)

        def wells():
            return rects_on(g['Example']().layout, layers.NWell)

        hint_well = ("Add the `well` block from task 2 at the "
            "EDIT HERE (well) marker.")
        try:
            report.passfail("Well encloses both devices",
                any(r.rect.lx <= 4000 and r.rect.ly <= 0
                    and r.rect.ux >= 6400 and r.rect.uy >= 2400
                    for r in wells()),
                hint=hint_well,
                instructions="Looking for an NWell rectangle containing "
                    "both dev_a and dev_b.")
        except Exception:
            report.passfail("Well encloses both devices", False,
                instructions=exception_text(), hint=hint_well)

        hint_wrap = ("Constrain the well only with the two `contains` "
            "constraints; the solver shrink-wraps it onto the devices.")
        try:
            report.passfail("Well shrink-wrapped by the solver",
                any((r.rect.lx, r.rect.ly, r.rect.ux, r.rect.uy)
                    == (4000, 0, 6400, 2400) for r in wells()),
                hint=hint_wrap,
                instructions="All four edges must be pulled tight: the "
                    "well must be exactly the bounding box of the two "
                    f"devices, (4000, 0, 6400, 2400). Found: "
                    f"{fmt_rects(wells())}.")
        except Exception:
            report.passfail("Well shrink-wrapped by the solver", False,
                instructions=exception_text(), hint=hint_wrap)
        return report
    return lesson


# Lesson 5: Routing with SRouter
# ------------------------------

def gen_lesson5(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            Drawing every wire as a rectangle gets tedious, and changing
            layers requires vias: cut rectangles plus landing pads on both
            metals. The stack router `SRouter` automates this. It works like
            a pen: `move()` sets the starting layer and position, `wire_x()`
            and `wire_y()` draw horizontal and vertical wire segments, and
            `layer()` changes the routing layer, dropping a complete via
            stack at the current position.

            **Connect `pad_w` and `pad_e` without touching the `obstacle`
            bar between them.** On `Metal1` this is impossible, so cross
            the obstacle on `Metal2`. At the `EDIT HERE (route)` marker,
            add:

            ```
            sr = SRouter(SG13G2().default_routing_spec)
            sr.move(layers.Metal1, pad_w.center)
            sr.wire_x(obstacle.lx - 500)
            sr.layer(layers.Metal2)
            sr.wire_x(obstacle.ux + 500)
            sr.layer(layers.Metal1)
            sr.wire_x(pad_e.cx)
            ```

            Zoom into the two layer changes: `sr.layer()` generated the
            `Via1` cuts and the landing pads enclosing them on both metals
            automatically, with dimensions from the routing spec. The 500 nm
            setback keeps the landing pads clear of the obstacle.

            *Tip: `wire(pos)` draws to an arbitrary point, and
            `push()`/`pop()` save and restore the pen position for
            T-shaped branches. Positions may be anchors of other shapes, so
            routes follow when the placement changes.*
        """)

        hint = ("Add the SRouter block from the instructions at the "
            "EDIT HERE (route) marker.")
        try:
            n = len(list(g['Example']().layout.all(LayoutPath)))
            report.passfail("Wires drawn with SRouter", n > 0, hint=hint,
                instructions=f"Looking for LayoutPath wires. Found: {n}.")
        except Exception:
            report.passfail("Wires drawn with SRouter", False,
                instructions=exception_text(), hint=hint)

        hint_m2 = ("Change to Metal2 before the obstacle with "
            "`sr.layer(layers.Metal2)` and back to Metal1 after it. The "
            "crossing segment must span the obstacle.")
        try:
            crossed = False
            for p in paths_on(g['Example']().layout, layers.Metal2):
                xs = [v.x for v in p.vertices()]
                if min(xs) <= 1800 and max(xs) >= 2100:
                    crossed = True
            report.passfail("Obstacle crossed on Metal2", crossed,
                hint=hint_m2,
                instructions="Looking for a Metal2 wire spanning the "
                    "obstacle (x = 1800 to 2100).")
        except Exception:
            report.passfail("Obstacle crossed on Metal2", False,
                instructions=exception_text(), hint=hint_m2)

        hint_vias = ("Each `sr.layer()` call generates one via stack; the "
            "route needs two of them (up before and down after the "
            "obstacle).")
        try:
            n = len(rects_on(g['Example']().layout, layers.Via1))
            report.passfail("Via stacks in place", n >= 2, hint=hint_vias,
                instructions=f"Looking for at least two Via1 cuts. "
                    f"Found: {n}.")
        except Exception:
            report.passfail("Via stacks in place", False,
                instructions=exception_text(), hint=hint_vias)
        return report
    return lesson


# Lessons 6-9: the inverter
# -------------------------

def instances_of(layout, cell_type):
    """All LayoutInstances of a layout referencing a cell of cell_type."""
    return [inst for inst in layout.all(LayoutInstance)
        if isinstance(inst.ref.cell, cell_type)]


def rect_contains(outer, inner):
    return (outer.lx <= inner.lx and outer.ly <= inner.ly
        and outer.ux >= inner.ux and outer.uy >= inner.uy)


def center(rect):
    return Vec2I((rect.lx + rect.ux) // 2, (rect.ly + rect.uy) // 2)


def inv_devices(layout):
    """The inverter's four devices, matched by cell type (the instance
    names are the user's choice in lesson 6). Raises if any is missing or
    duplicated; the callers' try/except converts that into a failing check.
    """
    devs = {}
    for key, cell_type in (('mn', ihp130.Nmos), ('mp', ihp130.Pmos),
            ('ptap', ihp130.Ptap), ('ntap', ihp130.Ntap)):
        insts = instances_of(layout, cell_type)
        if len(insts) != 1:
            raise ValueError(f"Expected exactly one {cell_type.__name__} "
                f"instance, found {len(insts)}.")
        devs[key] = insts[0]
    return devs


def gen_lesson6(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            Time for a real circuit. Over the next four lessons, we build
            the layout of the CMOS inverter whose schematic you see on the
            right, up to a design that passes the fab's checks.

            Transistors are not drawn by hand: the PDK cells generate their
            layouts, and you place them as *instances*. Writing a cell name
            inside a layout view instantiates its layout, `.$name = value`
            sets the cell's parameters, and constraints position it. Place
            the NMOS at the `EDIT HERE (devices)` marker:

            ```
            Nmos mn:
                .$w = 1u
                .$l = 130n
                ! .pos == (0, 0)
            ```

            Instances expose their inner geometry as anchors, transformed
            into your coordinates: `mn.activ` (the diffusion area),
            `mn.poly[0]` (the gate finger), `mn.sd[0]` and `mn.sd[1]` (the
            source/drain metal strips), and for taps `.m1` (their metal
            contact area).

            **Complete the device column** below the NMOS: the PMOS
            2500 nm above it, and one well tap below and above, each
            centered on its transistor:

            ```
            Pmos mp:
                .$w = 1u
                .$l = 130n
                ! .pos.x == mn.pos.x
                ! .pos.y == mn.pos.y + 2500
            Ptap ptap:
                .$l = 0.7u
                .$w = 0.7u
                ! .activ.cx == mn.activ.cx
                ! .activ.uy + 600 == mn.poly[0].ly
            Ntap ntap:
                .$l = 0.7u
                .$w = 0.7u
                ! .activ.cx == mp.activ.cx
                ! .activ.ly - 600 == mp.poly[0].uy
            ```

            The taps (`Ptap`, `Ntap`) connect the silicon bulk beneath the
            transistors to the supply rails we add in lesson 7; every
            manufacturable layout needs them.

            *Tip: instances can also be rotated and mirrored via
            `.orientation`. Note that the compass names (`North`, `East`,
            …) denote where the cell's top edge points; they are not
            rotation angles.*
        """)

        hint_mn = ("Add `Nmos mn:` with `.$w = 1u`, `.$l = 130n` and "
            "`! .pos == (0, 0)` at the EDIT HERE (devices) marker.")
        try:
            insts = instances_of(g['Inv']().layout, ihp130.Nmos)
            found = (len(insts) == 1
                and insts[0].ref.cell.w == R('1u')
                and insts[0].ref.cell.l == R('130n')
                and insts[0].pos == Vec2I(0, 0))
            report.passfail("NMOS placed at the origin", found, hint=hint_mn,
                instructions="Looking for one Nmos(w=1u, l=130n) instance "
                    "at position (0, 0).")
        except Exception:
            report.passfail("NMOS placed at the origin", False,
                instructions=exception_text(), hint=hint_mn)

        hint_mp = ("Add the `mp` block from the instructions: same x "
            "position as the NMOS, 2500 nm above it.")
        try:
            l = g['Inv']().layout
            nmos = instances_of(l, ihp130.Nmos)
            pmos = instances_of(l, ihp130.Pmos)
            found = (len(nmos) == 1 and len(pmos) == 1
                and pmos[0].ref.cell.w == R('1u')
                and pmos[0].ref.cell.l == R('130n')
                and pmos[0].pos.x == nmos[0].pos.x
                and pmos[0].pos.y == nmos[0].pos.y + 2500)
            report.passfail("PMOS placed 2500 nm above the NMOS", found,
                hint=hint_mp,
                instructions="Looking for one Pmos(w=1u, l=130n) instance "
                    "2500 nm above the Nmos.")
        except Exception:
            report.passfail("PMOS placed 2500 nm above the NMOS", False,
                instructions=exception_text(), hint=hint_mp)

        def check_tap(label, key, hint):
            try:
                d = inv_devices(g['Inv']().layout)
                tap = d[key]
                mos = d['mn'] if key == 'ptap' else d['mp']
                tap_activ = tap.activ.rect
                mos_activ = mos.activ.rect
                poly = mos.poly[0].rect
                centered = (tap_activ.lx + tap_activ.ux
                    == mos_activ.lx + mos_activ.ux)
                if key == 'ptap':
                    gap_ok = tap_activ.uy + 600 == poly.ly
                else:
                    gap_ok = tap_activ.ly - 600 == poly.uy
                report.passfail(label, centered and gap_ok, hint=hint,
                    instructions="The tap must be centered on the "
                        "transistor with a 600 nm gap to its gate poly.")
            except Exception:
                report.passfail(label, False,
                    instructions=exception_text(), hint=hint)

        check_tap("P-tap centered below the NMOS", 'ptap',
            "Add the `ptap` block from the instructions below the NMOS.")
        check_tap("N-tap centered above the PMOS", 'ntap',
            "Add the `ntap` block from the instructions above the PMOS.")
        return report
    return lesson


def gen_lesson7(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            The four devices are in place; now connect them. Three nets
            need internal wiring: the shared gate (input), the shared drain
            (output), and the supplies.

            **1. Join the gates** at the `EDIT HERE (gate)` marker. The two
            gate fingers must become one piece of polysilicon. Poly is not
            a routing layer, so this is a plain rectangle spanning between
            the fingers:

            ```
            LayoutRect polybar:
                .layer = layers.GatPoly
                ! .south == mn.poly[0].north
                ! .north == mp.poly[0].south
                ! .width == mn.poly[0].width
            ```

            **2. Connect the drains** at the `EDIT HERE (output)` marker.
            This is a metal connection, so use the router from lesson 5:

            ```
            sr = SRouter(SG13G2().default_routing_spec)
            sr.move(layers.Metal1, mn.sd[1].center)
            sr.wire_y(mp.sd[1].cy)
            ```

            **3. Add the supplies** at the `EDIT HERE (power)` marker: one
            horizontal Metal1 rail over each tap, and wires from the outer
            source/drain strips down/up to them (reusing `sr` from step 2):

            ```
            LayoutRect m1_vss:
                .layer = layers.Metal1
                ! .height == 160
                ! .cy == ptap.m1.cy
                ! .lx == mn.activ.lx - 400
                ! .ux == mn.activ.ux + 400
            LayoutRect m1_vdd:
                .layer = layers.Metal1
                ! .height == 160
                ! .cy == ntap.m1.cy
                ! .lx == mp.activ.lx - 400
                ! .ux == mp.activ.ux + 400
            sr.move(layers.Metal1, mn.sd[0].center)
            sr.wire_y(m1_vss.cy)
            sr.move(layers.Metal1, mp.sd[0].center)
            sr.wire_y(m1_vdd.cy)
            LayoutRect nwell:
                .layer = layers.NWell
                ! .contains(mp.nwell.rect)
                ! .contains(ntap.nwell.rect)
            ```

            The final `nwell` rectangle merges the PMOS's and the N-tap's
            wells into one: the PMOS sits in a well that is biased to vdd
            through the tap.

            *Tip: overlapping shapes on the same layer are one electrical
            net. The rails overlap the taps' `m1` areas, the wires end on
            the rails; no explicit "connect" operation is needed.*
        """)

        hint_gate = ("Add the `polybar` rectangle from step 1 at the "
            "EDIT HERE (gate) marker.")
        try:
            d = inv_devices(g['Inv']().layout)
            poly_n = d['mn'].poly[0].rect
            poly_p = d['mp'].poly[0].rect
            found = any(r.rect.ly == poly_n.uy and r.rect.uy == poly_p.ly
                    and r.rect.lx == poly_n.lx and r.rect.ux == poly_n.ux
                for r in rects_on(g['Inv']().layout, layers.GatPoly))
            report.passfail("Gate fingers joined with poly", found,
                hint=hint_gate,
                instructions="Looking for a GatPoly rectangle spanning "
                    "between the two gate fingers.")
        except Exception:
            report.passfail("Gate fingers joined with poly", False,
                instructions=exception_text(), hint=hint_gate)

        def vertical_wire_between(layout, x, y_from, y_to):
            for p in paths_on(layout, layers.Metal1):
                xs = [v.x for v in p.vertices()]
                ys = [v.y for v in p.vertices()]
                if all(vx == x for vx in xs) \
                        and min(ys) <= min(y_from, y_to) \
                        and max(ys) >= max(y_from, y_to):
                    return True
            return False

        hint_out = ("Add the SRouter wire from step 2 at the "
            "EDIT HERE (output) marker.")
        try:
            l = g['Inv']().layout
            d = inv_devices(l)
            sd_n = d['mn'].sd[1].rect
            sd_p = d['mp'].sd[1].rect
            found = vertical_wire_between(l, (sd_n.lx + sd_n.ux) // 2,
                (sd_n.ly + sd_n.uy) // 2, (sd_p.ly + sd_p.uy) // 2)
            report.passfail("Output wire connects the drains", found,
                hint=hint_out,
                instructions="Looking for a vertical Metal1 wire between "
                    "mn.sd[1] and mp.sd[1].")
        except Exception:
            report.passfail("Output wire connects the drains", False,
                instructions=exception_text(), hint=hint_out)

        def find_rail(layout, tap):
            tap_m1_center = center(tap.m1.rect)
            for r in rects_on(layout, layers.Metal1):
                if r.rect.uy - r.rect.ly == 160 and tap_m1_center in r.rect:
                    return r
            return None

        hint_rails = ("Add the two rail rectangles from step 3; each must "
            "overlap its tap's m1 area.")
        try:
            l = g['Inv']().layout
            d = inv_devices(l)
            found = (find_rail(l, d['ptap']) is not None
                and find_rail(l, d['ntap']) is not None)
            report.passfail("Supply rails drawn over the taps", found,
                hint=hint_rails,
                instructions="Looking for two 160 nm high Metal1 rails, "
                    "one over each tap's m1 area.")
        except Exception:
            report.passfail("Supply rails drawn over the taps", False,
                instructions=exception_text(), hint=hint_rails)

        hint_src = ("Add the two `sr.move`/`sr.wire_y` pairs from step 3 "
            "connecting mn.sd[0] and mp.sd[0] to their rails.")
        try:
            l = g['Inv']().layout
            d = inv_devices(l)
            ok = True
            for mos, tap in ((d['mn'], d['ptap']), (d['mp'], d['ntap'])):
                rail = find_rail(l, tap)
                sd = mos.sd[0].rect
                if rail is None or not vertical_wire_between(l,
                        (sd.lx + sd.ux) // 2, (sd.ly + sd.uy) // 2,
                        (rail.rect.ly + rail.rect.uy) // 2):
                    ok = False
            report.passfail("Sources connected to the rails", ok,
                hint=hint_src,
                instructions="Looking for vertical Metal1 wires from "
                    "mn.sd[0] to the vss rail and from mp.sd[0] to the "
                    "vdd rail.")
        except Exception:
            report.passfail("Sources connected to the rails", False,
                instructions=exception_text(), hint=hint_src)

        hint_nwell = ("Add the `nwell` rectangle from step 3 containing "
            "both `mp.nwell.rect` and `ntap.nwell.rect`.")
        try:
            l = g['Inv']().layout
            d = inv_devices(l)
            found = any(rect_contains(r.rect, d['mp'].nwell.rect)
                    and rect_contains(r.rect, d['ntap'].nwell.rect)
                for r in rects_on(l, layers.NWell))
            report.passfail("N-well covers PMOS and tap", found,
                hint=hint_nwell,
                instructions="Looking for an NWell rectangle containing "
                    "the PMOS's and the N-tap's wells.")
        except Exception:
            report.passfail("N-well covers PMOS and tap", False,
                instructions=exception_text(), hint=hint_nwell)
        return report
    return lesson


def gen_lesson8(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            Two things remain before the inverter's geometry is complete:
            the input needs a way down to the gate poly, and the layout must
            obey the fab's *design rules*.

            **1. Contact the gate** at the `EDIT HERE (input)` marker. The
            input arrives on Metal1, but the gate is polysilicon; a `Cont`
            cut connects the two layers. The cut needs a poly landing area
            and a metal pad on top:

            ```
            LayoutRect polyext:
                .layer = layers.GatPoly
                ! .size == (500, 500)
                ! .east == polybar.west
            LayoutRect polycont:
                .layer = layers.Cont
                ! .size == (160, 160)
                ! .center == polyext.center
            LayoutRect m1_a:
                .layer = layers.Metal1
                ! .y_extent == polycont.y_extent
                ! .ux == polycont.ux + 200
                ! .width == 1500
            ```

            **2. Run DRC.** The *design rule check* verifies the geometry
            against the fab's rulebook: minimum widths, spacings and
            enclosures. Because it runs KLayout in the background and takes
            a few seconds, the DRC panel on the right only updates when you
            press its *Refresh* overlay.

            This layout contains a rule violation that is easy to miss by
            eye. Run the DRC, open the violation category in the report,
            and click an entry: the offending geometry is highlighted in
            the layout viewer. **Then fix the flaw at the
            `EDIT HERE (rail height)` marker** and re-run the check.

            *Tip: `variant="minimal"` runs the main rule deck; there is
            also `variant="maximal"` with additional rule tables for final
            signoff.*
        """)

        def find_polyext(layout):
            bar = layout.polybar.rect
            for r in rects_on(layout, layers.GatPoly):
                if (r.rect.ux - r.rect.lx == 500
                        and r.rect.uy - r.rect.ly == 500
                        and r.rect.ux == bar.lx
                        and r.rect.ly + r.rect.uy == bar.ly + bar.uy):
                    return r
            return None

        def find_polycont(layout):
            ext = find_polyext(layout)
            if ext is None:
                return None
            for r in rects_on(layout, layers.Cont):
                if (r.rect.ux - r.rect.lx == 160
                        and r.rect.uy - r.rect.ly == 160
                        and center(r.rect) == center(ext.rect)):
                    return r
            return None

        hint_ext = ("Add the `polyext` rectangle from step 1 at the "
            "EDIT HERE (input) marker.")
        try:
            found = find_polyext(g['Inv']().layout) is not None
            report.passfail("Poly landing area added", found, hint=hint_ext,
                instructions="Looking for a 500x500 GatPoly rectangle "
                    "attached to polybar's west edge.")
        except Exception:
            report.passfail("Poly landing area added", False,
                instructions=exception_text(), hint=hint_ext)

        hint_cont = ("Add the `polycont` cut from step 1, centered in "
            "polyext.")
        try:
            found = find_polycont(g['Inv']().layout) is not None
            report.passfail("Contact cut placed", found, hint=hint_cont,
                instructions="Looking for a 160x160 Cont cut centered in "
                    "the poly landing area.")
        except Exception:
            report.passfail("Contact cut placed", False,
                instructions=exception_text(), hint=hint_cont)

        hint_pad = ("Add the `m1_a` pad from step 1 over the contact cut.")
        try:
            l = g['Inv']().layout
            cont = find_polycont(l)
            found = cont is not None and any(
                r.rect.ux - r.rect.lx == 1500
                and r.rect.ly == cont.rect.ly and r.rect.uy == cont.rect.uy
                and r.rect.ux == cont.rect.ux + 200
                for r in rects_on(l, layers.Metal1))
            report.passfail("Metal1 input pad added", found, hint=hint_pad,
                instructions="Looking for a 1500 nm wide Metal1 pad over "
                    "the contact cut.")
        except Exception:
            report.passfail("Metal1 input pad added", False,
                instructions=exception_text(), hint=hint_pad)

        hint_rail = ("The vss rail is only 100 nm high, below the minimum "
            "Metal1 width. Change the height to 160 at the "
            "EDIT HERE (rail height) marker.")
        try:
            r = g['Inv']().layout.m1_vss.rect
            report.passfail("vss rail meets the minimum width",
                r.uy - r.ly == 160, hint=hint_rail,
                instructions=f"The vss rail must be 160 nm high; it is "
                    f"{r.uy - r.ly} nm.")
        except Exception:
            report.passfail("vss rail meets the minimum width", False,
                instructions=exception_text(), hint=hint_rail)

        hint_drc = ("Open the DRC panel on the right, press Refresh, and "
            "click the reported violation to highlight it in the layout. "
            "Fix the geometry until no violations remain.")
        try:
            summary = g['Inv']().drc.summary()
            report.passfail("DRC clean", summary == {}, hint=hint_drc,
                instructions="No DRC violations." if summary == {} else
                    "DRC violations found: "
                    + ", ".join(f"{k}: {v}" for k, v in summary.items())
                    + ". See the DRC panel for details.")
        except Exception:
            report.passfail("DRC clean", False,
                instructions=exception_text(), hint=hint_drc)
        return report
    return lesson


def gen_lesson9(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            DRC only checks geometry against the rulebook; it cannot know
            *which circuit* the polygons implement. That is the job of LVS
            (*layout versus schematic*): it extracts transistors and nets
            back out of the layout and compares them against the schematic.

            For the comparison to work, the layout must declare where its
            ports are: each port needs a labeled *pin* on a shape. There
            are two forms, `create_pin` on a named rectangle and
            `create_pin` on a routed wire via `sr.path`:

            **Add the four pins at the EDIT HERE markers:**

            1. `(a pin)` inside the `m1_a` block: `.create_pin(self.symbol.a)`
            2. `(y pin)` after the output wire: `sr.path.create_pin(self.symbol.y)`
            3. `(vdd pin)` inside the `m1_vdd` block: `.create_pin(self.symbol.vdd)`
            4. `(vss pin)` inside the `m1_vss` block: `.create_pin(self.symbol.vss)`

            Then press *Refresh* on the LVS panel. The extracted netlist is
            compared device by device and net by net; the check below
            passes once the layout matches the schematic.

            Once it does, try swapping the vdd and vss pins for a moment:
            the layout looks identical and stays DRC-clean, but LVS
            reports the mismatch immediately. This is why layouts are
            verified against the schematic, not by eye.
        """)

        hint_pins = ("Add the four `create_pin` lines at the EDIT HERE "
            "markers, exactly as listed in the instructions.")
        try:
            l = g['Inv']().layout
            sym = g['Inv']().symbol
            pinned = {p.pin for p in l.all(LayoutPin)}
            found = pinned == {sym.a, sym.y, sym.vdd, sym.vss}
            report.passfail("All four ports pinned", found, hint=hint_pins,
                instructions="Looking for pins on a, y, vdd and vss. "
                    f"Found: {len(pinned)} pin(s).")
        except Exception:
            report.passfail("All four ports pinned", False,
                instructions=exception_text(), hint=hint_pins)

        hint_ypin = ("Create the y pin on the routed output wire: "
            "`sr.path.create_pin(self.symbol.y)` directly after the "
            "`sr.wire_y(mp.sd[1].cy)` line.")
        try:
            l = g['Inv']().layout
            sym = g['Inv']().symbol
            y_pins = [p for p in l.all(LayoutPin) if p.pin == sym.y]
            paths = list(l.all(LayoutPath))
            found = bool(y_pins) and any(y_pins[0].ref == p for p in paths)
            report.passfail("Output pin on the routed wire", found,
                hint=hint_ypin,
                instructions="The y pin must sit on the routed Metal1 "
                    "output wire (a LayoutPath), not on a rectangle.")
        except Exception:
            report.passfail("Output pin on the routed wire", False,
                instructions=exception_text(), hint=hint_ypin)

        hint_lvs = ("Press Refresh on the LVS panel to run the comparison; "
            "clicking a mismatch item highlights it in the layout and the "
            "schematic.")
        try:
            l = g['Inv']().layout
            sym = g['Inv']().symbol
            pinned = {p.pin for p in l.all(LayoutPin)}
            if pinned != {sym.a, sym.y, sym.vdd, sym.vss}:
                report.passfail("Layout matches schematic (LVS)", False,
                    hint=hint_pins,
                    instructions="LVS runs once all four pins are in "
                        "place.")
            else:
                lvs = g['Inv']().lvs
                if lvs.clean():
                    report.passfail("Layout matches schematic (LVS)", True)
                else:
                    items = [f"{i.item_type.name}: layout "
                        f"{i.layout_name!r} vs schematic {i.schem_name!r} "
                        f"({i.status.name})"
                        for i in lvs.all(LvsItem)
                        if i.status not in (LvsStatus.Match,
                            LvsStatus.MatchWarning)]
                    report.passfail("Layout matches schematic (LVS)", False,
                        hint=hint_lvs,
                        instructions="LVS mismatch: "
                            + ("; ".join(items) if items
                                else f"status {lvs.status.name}")
                            + ". See the LVS panel for details.")
        except Exception:
            report.passfail("Layout matches schematic (LVS)", False,
                instructions=exception_text(), hint=hint_lvs)
        return report
    return lesson


# Lessons 10-11: the differential pair
# ------------------------------------

def diffpair_row(layout):
    """The four unit devices of the differential pair, sorted from west to
    east. Raises if there are not exactly four; the callers' try/except
    converts that into a failing check."""
    insts = instances_of(layout, ihp130.Nmos)
    if len(insts) != 4:
        raise ValueError(f"Expected four Nmos instances, found "
            f"{len(insts)}.")
    return sorted(insts, key=lambda i: i.pos.x)


def gen_lesson10(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            The final circuit of this course is analog: a differential
            pair. Its two branches must be as identical as possible; any
            mismatch between them turns into an input offset error. In the
            schematic, each branch is a single transistor with the
            *multiplier* parameter `m=2`: two identical unit devices in
            parallel. The layout is where those units take shape, and
            where matching is won or lost. The classic technique is
            *interdigitation*: the four units are arranged as the row
            **m1a m2a m2b m1b**, so both branches see the same
            neighborhood.

            **1. Build the matched row** at the `EDIT HERE (row)` marker.
            Declare all four unit devices in one statement and set their
            parameters in one loop - a single source of truth, so the
            branches cannot drift apart. A device's inner geometry
            (`.sd`, `.poly`) only takes shape once its parameters are
            known, so the parameter loop must come first; the placement
            constraints then follow as standalone statements naming each
            device, instead of living in the instance blocks as in
            lesson 6. Rather than positioning each device by hand, chain
            them: constraining a device's first source/drain strip onto
            its neighbor's last one makes the two share one diffusion
            strip, perfectly aligned by construction:

            ```
            Nmos m1a, m2a, m2b, m1b
            for m in m1a, m2a, m2b, m1b:
                m.$w = 1u
                m.$l = 130n

            ! m1a.pos == (0, 0)
            ! m2a.sd[0].center == m1a.sd[1].center
            ! m2a.pos.y == m1a.pos.y
            ! m2b.sd[0].center == m2a.sd[1].center
            ! m2b.pos.y == m1a.pos.y
            ! m1b.sd[0].center == m2b.sd[1].center
            ! m1b.pos.y == m1a.pos.y
            ```

            The five strips of the row now alternate between the nets
            outn, tail, outp, tail, outn.

            **2. Join the middle gates (inn)** at the `EDIT HERE (gates)`
            marker with a poly *comb*: a horizontal bar above the row plus
            one vertical drop onto each gate finger, and the contact stack
            from lesson 8 on top of the bar:

            ```
            LayoutRect inn_bar:
                .layer = layers.GatPoly
                ! .lx == m2a.poly[0].lx
                ! .ux == m2b.poly[0].ux
                ! .ly == m2a.poly[0].uy + 250
                ! .height == 130
            LayoutRect inn_drop_a:
                .layer = layers.GatPoly
                ! .x_extent == m2a.poly[0].x_extent
                ! .uy == inn_bar.uy
                ! .ly == m2a.poly[0].uy - 100
            LayoutRect inn_drop_b:
                .layer = layers.GatPoly
                ! .x_extent == m2b.poly[0].x_extent
                ! .uy == inn_bar.uy
                ! .ly == m2b.poly[0].uy - 100
            LayoutRect inn_ext:
                .layer = layers.GatPoly
                ! .size == (500, 500)
                ! .south == inn_bar.north
            LayoutRect inn_cont:
                .layer = layers.Cont
                ! .size == (160, 160)
                ! .center == inn_ext.center
            LayoutRect m1_inn:
                .layer = layers.Metal1
                ! .center == inn_cont.center
                ! .size == (500, 200)
            ```

            The bar keeps 250 nm clearance to the diffusion area (a design
            rule), and the drops overlap the gate fingers' ends by 100 nm
            to merge with them.

            *Tip: the outer pair (inp) needs the same comb mirrored
            downward; it is prepared for you in the next lesson.*
        """)

        hint_row = ("Add the unit-device declarations and chaining "
            "constraints from step 1 at the EDIT HERE (row) marker.")
        try:
            row = diffpair_row(g['DiffPair']().layout)
            found = all(i.ref.cell.w == R('1u') and i.ref.cell.l == R('130n')
                for i in row)
            report.passfail("Four matched unit transistors placed", found,
                hint=hint_row,
                instructions="Looking for four Nmos(w=1u, l=130n) "
                    "instances.")
        except Exception:
            report.passfail("Four matched unit transistors placed", False,
                instructions=exception_text(), hint=hint_row)

        hint_shared = ("Chain the devices with "
            "`! .sd[0].center == <left neighbor>.sd[1].center` and "
            "`! .pos.y == m1a.pos.y` so neighbors share a diffusion "
            "strip.")
        try:
            row = diffpair_row(g['DiffPair']().layout)
            found = all(
                row[i+1].sd[0].rect == row[i].sd[1].rect
                and row[i+1].pos.y == row[i].pos.y
                for i in range(3))
            report.passfail("Shared-diffusion row formed", found,
                hint=hint_shared,
                instructions="Neighboring devices must share their "
                    "source/drain strips (sd[0] on sd[1]) at equal y.")
        except Exception:
            report.passfail("Shared-diffusion row formed", False,
                instructions=exception_text(), hint=hint_shared)

        def find_inn_bar(layout):
            row = diffpair_row(layout)
            p_a = row[1].poly[0].rect
            p_b = row[2].poly[0].rect
            for r in rects_on(layout, layers.GatPoly):
                if (r.rect.lx == p_a.lx and r.rect.ux == p_b.ux
                        and r.rect.ly == p_a.uy + 250
                        and r.rect.uy - r.rect.ly == 130):
                    return r
            return None

        hint_comb = ("Add the `inn_bar`, `inn_drop_a` and `inn_drop_b` "
            "rectangles from step 2. The bar spans between the two middle "
            "gate fingers, the drops connect it down onto them.")
        try:
            l = g['DiffPair']().layout
            row = diffpair_row(l)
            bar = find_inn_bar(l)
            drops_ok = bar is not None and all(any(
                    r.rect.lx == dev.poly[0].rect.lx
                    and r.rect.ux == dev.poly[0].rect.ux
                    and r.rect.uy == bar.rect.uy
                    and r.rect.ly == dev.poly[0].rect.uy - 100
                for r in rects_on(l, layers.GatPoly))
                for dev in (row[1], row[2]))
            report.passfail("inn gates joined with a poly comb", drops_ok,
                hint=hint_comb,
                instructions="Looking for a 130 nm poly bar 250 nm above "
                    "the middle gate fingers, with one drop per finger.")
        except Exception:
            report.passfail("inn gates joined with a poly comb", False,
                instructions=exception_text(), hint=hint_comb)

        hint_cont = ("Add the `inn_ext`, `inn_cont` and `m1_inn` blocks "
            "from step 2 on top of the bar.")
        try:
            l = g['DiffPair']().layout
            bar = find_inn_bar(l)
            found = False
            if bar is not None:
                for ext in rects_on(l, layers.GatPoly):
                    if not (ext.rect.ux - ext.rect.lx == 500
                            and ext.rect.uy - ext.rect.ly == 500
                            and ext.rect.ly == bar.rect.uy):
                        continue
                    has_cont = any(r.rect.ux - r.rect.lx == 160
                            and center(r.rect) == center(ext.rect)
                        for r in rects_on(l, layers.Cont))
                    has_m1 = any(r.rect.ux - r.rect.lx == 500
                            and r.rect.uy - r.rect.ly == 200
                            and center(r.rect) == center(ext.rect)
                        for r in rects_on(l, layers.Metal1))
                    if has_cont and has_m1:
                        found = True
            report.passfail("inn contacted down to Metal1", found,
                hint=hint_cont,
                instructions="Looking for a 500x500 poly landing on the "
                    "bar with a Cont cut and a 500x200 Metal1 pad.")
        except Exception:
            report.passfail("inn contacted down to Metal1", False,
                instructions=exception_text(), hint=hint_cont)
        return report
    return lesson


def gen_lesson11(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            The matched row is complete: the inp comb (mirrored downward,
            with its contact west of the row), the substrate tap and the
            vss rail are already prepared below your lesson 10 code. What
            remains is metal routing, the pins, and signoff.

            **1. Route the remaining nets** at the `EDIT HERE (route)`
            marker. The two *tail* strips are strapped below the row on
            Metal1; the two outer *outn* strips are bridged over the row on
            Metal2, exactly like the obstacle crossing in lesson 5. Both
            routed wires directly receive their pins:

            ```
            sr = SRouter(SG13G2().default_routing_spec)
            sr.move(layers.Metal1, m1a.sd[1].center)
            sr.wire_y(m1a.pos.y - 600)
            sr.wire_x(m2b.sd[1].cx)
            sr.wire_y(m2b.sd[1].cy)
            sr.path.create_pin(self.symbol.tail)
            sr.move(layers.Metal1, m1a.sd[0].center)
            sr.wire_y(m1a.pos.y + 2400)
            sr.layer(layers.Metal2)
            sr.wire_x(m1b.sd[1].cx)
            sr.path.create_pin(self.symbol.outn)
            sr.layer(layers.Metal1)
            sr.wire_y(m1b.sd[1].cy)
            ```

            **2. Pin the remaining ports** at the `EDIT HERE (pins)`
            marker: outp gets a rectangle on the middle strip, and the
            prepared input pads and the vss rail are labeled directly:

            ```
            LayoutRect m1_outp:
                .layer = layers.Metal1
                ! .rect == m2a.sd[1].rect
                .create_pin(self.symbol.outp)
            m1_inp.create_pin(self.symbol.inp)
            m1_inn.create_pin(self.symbol.inn)
            m1_vss.create_pin(self.symbol.vss)
            ```

            **3. Signoff:** press *Refresh* on the DRC and LVS panels.
            Both must come back clean; then the
            differential pair is ready, and so are you: this was the last
            design of the course.
        """)

        def structural_ok(l):
            row = diffpair_row(l)
            tail_1 = center(row[0].sd[1].rect)
            tail_2 = center(row[2].sd[1].rect)
            strapped = any(
                tail_1 in [v for v in p.vertices()]
                and tail_2 in [v for v in p.vertices()]
                for p in paths_on(l, layers.Metal1))
            outn_x1 = center(row[0].sd[0].rect).x
            outn_x2 = center(row[3].sd[1].rect).x
            bridged = any(
                min(v.x for v in p.vertices()) <= outn_x1
                and max(v.x for v in p.vertices()) >= outn_x2
                for p in paths_on(l, layers.Metal2))
            sym = g['DiffPair']().symbol
            pinned = {p.pin for p in l.all(LayoutPin)} == {sym.inp, sym.inn,
                sym.outp, sym.outn, sym.tail, sym.vss}
            return strapped, bridged, pinned

        hint_route = ("Add the SRouter block from step 1 at the "
            "EDIT HERE (route) marker.")
        hint_pins = ("Add the pin block from step 2 at the "
            "EDIT HERE (pins) marker.")
        try:
            strapped, bridged, pinned = structural_ok(
                g['DiffPair']().layout)
        except Exception:
            for label, hint in (("Tail strips strapped", hint_route),
                    ("outn bridged over the row on Metal2", hint_route),
                    ("All six ports pinned", hint_pins)):
                report.passfail(label, False,
                    instructions=exception_text(), hint=hint)
            strapped = bridged = pinned = False
        else:
            report.passfail("Tail strips strapped", strapped,
                hint=hint_route,
                instructions="Looking for a Metal1 wire connecting the "
                    "two tail strips below the row.")
            report.passfail("outn bridged over the row on Metal2", bridged,
                hint=hint_route,
                instructions="Looking for a Metal2 wire spanning from the "
                    "leftmost to the rightmost strip.")
            report.passfail("All six ports pinned", pinned, hint=hint_pins,
                instructions="Looking for pins on inp, inn, outp, outn, "
                    "tail and vss.")

        if not (strapped and bridged and pinned):
            report.passfail("DRC clean", False,
                instructions="DRC runs once routing and pins are in "
                    "place.", hint=hint_route)
            report.passfail("Layout matches schematic (LVS)", False,
                instructions="LVS runs once routing and pins are in "
                    "place.", hint=hint_pins)
            return report

        hint_drc = ("Open the DRC panel, press Refresh, and click a "
            "violation to highlight it in the layout.")
        try:
            summary = g['DiffPair']().drc.summary()
            report.passfail("DRC clean", summary == {}, hint=hint_drc,
                instructions="No DRC violations." if summary == {} else
                    "DRC violations found: "
                    + ", ".join(f"{k}: {v}" for k, v in summary.items())
                    + ". See the DRC panel for details.")
        except Exception:
            report.passfail("DRC clean", False,
                instructions=exception_text(), hint=hint_drc)

        hint_lvs = ("Press Refresh on the LVS panel; clicking a mismatch "
            "item highlights it in the layout and the schematic.")
        try:
            lvs = g['DiffPair']().lvs
            if lvs.clean():
                report.passfail("Layout matches schematic (LVS)", True)
            else:
                items = [f"{i.item_type.name}: layout {i.layout_name!r} "
                    f"vs schematic {i.schem_name!r} ({i.status.name})"
                    for i in lvs.all(LvsItem)
                    if i.status not in (LvsStatus.Match,
                        LvsStatus.MatchWarning)]
                report.passfail("Layout matches schematic (LVS)", False,
                    hint=hint_lvs,
                    instructions="LVS mismatch: "
                        + ("; ".join(items) if items
                            else f"status {lvs.status.name}")
                        + ". See the LVS panel for details.")
        except Exception:
            report.passfail("Layout matches schematic (LVS)", False,
                instructions=exception_text(), hint=hint_lvs)
        return report
    return lesson


# Epilogue: What's next?
# ----------------------

def gen_epilogue(g):
    @viewgen_noctx
    def lesson() -> Report:
        report = Report()
        report.markdown("""
            **Congratulations &mdash; you have completed the Layout
            Tutorial!**

            You now know the full path from geometry to signoff: drawing
            shapes on layers, positioning them with equality and inequality
            constraints, routing with SRouter, placing and wiring
            transistors and taps, contacting between layers, and verifying
            a layout with DRC and LVS &mdash; for a digital inverter and a
            matched analog differential pair.

            Here is where you can go from here:

            - **Study a larger design.** The
              <a href="app.html#example=vco_pseudodiff" target="_blank"
              rel="noopener">pseudodifferential VCO example</a> applies
              everything from this course to a complete oscillator with
              constraint-based layout.

            - **Consult the [layout how-to](docs:howto_layout.html)** in
              the documentation &mdash; it condenses this course's
              techniques into a reference, including orientations, pin
              creation and verification.

            - **Continue with the other courses** on the
              <a href="." target="_blank" rel="noopener">start page</a>,
              or start your own design.

            Your course progress and edits stay in this browser; use
            *Export* in the toolbar above to save them as a zip file.
        """)
        return report
    return lesson
