# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for viewEventBus communication between DRC viewer and layout-gl.
"""

import pytest
import time


def get_layout_state(web):
    """Query testState() from the layout viewer."""
    return web.driver.execute_script("""
        const rv = window.ordecClient.resultViewers.find(
            rv => rv.view && rv.view.testState
        );
        return rv ? rv.view.testState() : null;
    """)


def emit_drc_select(web, shapes):
    """Emit drc:select event with given shapes."""
    web.driver.execute_script(
        "window.viewEventBus.emit('drc:select', {shapes: arguments[0]});",
        shapes
    )


def emit_drc_clear(web):
    """Emit drc:clear event."""
    web.driver.execute_script("window.viewEventBus.emit('drc:clear');")


def load_layout_view(web):
    """Load the layoutgl_example in local mode."""
    qs_local = web.key.query_string_local("tests.lib.layoutgl_example", "layoutgl_example()")
    web.navigate(f'app.html#refreshall=true&{qs_local}')
    web.wait_for_ready()


@pytest.mark.web
def test_drc_select_highlights_layout(web):
    """Emitting drc:select should set highlight vertices in layout viewer."""
    load_layout_view(web)

    state = get_layout_state(web)
    assert state is not None, "Layout viewer not found"
    assert state['highlightNumVertices'] == 0, "Should start with no highlight"

    emit_drc_select(web, [{'type': 'box', 'rect': [0, 0, 1000, 1000]}])

    state = get_layout_state(web)
    assert state['highlightNumVertices'] > 0, "Should have highlight after drc:select"


@pytest.mark.web
def test_drc_clear_removes_highlight(web):
    """Emitting drc:clear should remove highlight from layout viewer."""
    load_layout_view(web)

    emit_drc_select(web, [{'type': 'box', 'rect': [0, 0, 500, 500]}])
    state = get_layout_state(web)
    assert state['highlightNumVertices'] > 0, "Precondition: should have highlight"

    emit_drc_clear(web)

    state = get_layout_state(web)
    assert state['highlightNumVertices'] == 0, "Should have no highlight after drc:clear"


@pytest.mark.web
def test_multiple_shape_types(web):
    """Different shape types should all create highlight vertices."""
    load_layout_view(web)

    shapes = [
        {'type': 'box', 'rect': [0, 0, 100, 100]},
        {'type': 'edge', 'p1': [200, 200], 'p2': [300, 300]},
        {'type': 'edge_pair', 'e1': [[400, 400], [500, 400]], 'e2': [[400, 450], [500, 450]]},
        {'type': 'poly', 'vertices': [[600, 600], [700, 600], [650, 700]]},
    ]
    emit_drc_select(web, shapes)

    state = get_layout_state(web)
    assert state['highlightNumVertices'] > 0, "Should highlight multiple shape types"


@pytest.mark.web
def test_pending_event_consumed_on_layout_open(web):
    """Pending drc:select should be consumed when layout view opens."""
    # Load layout module but don't auto-select a view
    qs = web.key.query_string_local("tests.lib.layoutgl_example", "")
    web.navigate(f'app.html#refreshall=true&viewsel_flat=true&{qs}')
    web.wait_for_ready()

    # Verify no layout is rendered yet (no view selected)
    state = get_layout_state(web)
    assert state is None, "No layout should be rendered initially"

    # Set pending drc:select event BEFORE selecting layout view
    web.driver.execute_script("""
        window.viewEventBus.setPending('drc:select', {
            shapes: [{type: 'box', rect: [100, 100, 500, 500]}]
        });
    """)

    # Now select the layout view - this should consume pending
    web.driver.execute_script("""
        const rv = window.ordecClient.resultViewers[0];
        const sel = rv.viewSelector;
        for (let i = 0; i < sel.options.length; i++) {
            if (sel.options[i].value === 'layoutgl_example()') {
                sel.selectedIndex = i;
                rv.viewSelectorOnChange();
                break;
            }
        }
    """)

    web.wait_for_ready()
    time.sleep(0.5)

    # Verify layout opened and consumed pending event
    state = get_layout_state(web)
    assert state is not None, "Layout should be open after selecting view"
    assert state['highlightNumVertices'] > 0, "Should have highlight from pending event"

    # Verify pending was consumed
    pending = web.driver.execute_script(
        "return window.viewEventBus.consumePending('drc:select');"
    )
    assert pending is None, "Pending event should have been consumed"


def emit_lvs_layout_select(web, pos):
    """Emit lvs:layout-select event with given pos [x, y]."""
    web.driver.execute_script(
        "window.viewEventBus.emit('lvs:layout-select', {pos: arguments[0]});",
        pos
    )


def emit_lvs_schem_select_nid(web, schem_nid, item_type):
    """Emit lvs:schem-select event with given schem_nid and item_type."""
    web.driver.execute_script(
        "window.viewEventBus.emit('lvs:schem-select', {schem_nid: arguments[0], item_type: arguments[1]});",
        schem_nid, item_type
    )


def get_instance_nid(web, inst_name):
    """Get the data-nid of an instance group by matching its label text."""
    return web.driver.execute_script("""
        const svg = document.querySelector('.rescontent svg');
        if (!svg) return null;
        const inst = svg.querySelector(`g[data-nid]`);
        // Find all groups with data-nid, check if they contain the instance name in class
        const groups = svg.querySelectorAll('g[data-nid]');
        for (const g of groups) {
            // Instance groups have symbolOutline rect inside
            if (g.querySelector('rect.symbolOutline')) {
                const nid = g.getAttribute('data-nid');
                // Check text content for instance name
                const texts = g.querySelectorAll('text');
                for (const t of texts) {
                    if (t.textContent === arguments[0]) {
                        return parseInt(nid, 10);
                    }
                }
            }
        }
        return null;
    """, inst_name)


def get_net_nid(web, net_name):
    """Get the data-nid of a net by finding a port with matching label."""
    return web.driver.execute_script("""
        const svg = document.querySelector('.rescontent svg');
        if (!svg) return null;
        // Find port groups (they have portArrow inside)
        const groups = svg.querySelectorAll('g[data-nid]');
        for (const g of groups) {
            if (g.querySelector('path.portArrow')) {
                // Check if this port's label matches
                const label = g.querySelector('text.portLabel');
                if (label && label.textContent.toLowerCase() === arguments[0].toLowerCase()) {
                    return parseInt(g.getAttribute('data-nid'), 10);
                }
            }
        }
        return null;
    """, net_name)


def emit_lvs_clear(web):
    """Emit lvs:clear event."""
    web.driver.execute_script("window.viewEventBus.emit('lvs:clear');")


@pytest.mark.web
def test_lvs_select_highlights_layout(web):
    """Emitting lvs:layout-select should set highlight vertices in layout viewer."""
    load_layout_view(web)

    state = get_layout_state(web)
    assert state is not None, "Layout viewer not found"
    assert state['highlightNumVertices'] == 0, "Should start with no highlight"

    emit_lvs_layout_select(web, [500, 500])

    state = get_layout_state(web)
    assert state['highlightNumVertices'] > 0, "Should have highlight after lvs:layout-select"


@pytest.mark.web
def test_lvs_clear_removes_highlight(web):
    """Emitting lvs:clear should remove highlight from layout viewer."""
    load_layout_view(web)

    emit_lvs_layout_select(web, [250, 250])
    state = get_layout_state(web)
    assert state['highlightNumVertices'] > 0, "Precondition: should have highlight"

    emit_lvs_clear(web)

    state = get_layout_state(web)
    assert state['highlightNumVertices'] == 0, "Should have no highlight after lvs:clear"


def load_schematic_view(web):
    """Load a schematic view using the lvs_example."""
    qs_local = web.key.query_string_local("tests.lib.lvs_example", "schematic()")
    web.navigate(f'app.html#refreshall=true&{qs_local}')
    web.wait_for_ready()
    time.sleep(0.5)


def get_schematic_highlight_count(web):
    """Check if schematic has lvs highlight overlay."""
    return web.driver.execute_script("""
        const svg = document.querySelector('.rescontent svg');
        if (!svg) return 0;
        const highlights = svg.querySelectorAll('.lvs-highlight-group rect');
        return highlights.length;
    """)


@pytest.mark.web
def test_lvs_select_highlights_schematic_instance(web):
    """Emitting lvs:schem-select with schem_nid should highlight the instance in schematic."""
    load_schematic_view(web)

    count = get_schematic_highlight_count(web)
    assert count == 0, "Should start with no highlight"

    nid = get_instance_nid(web, 'pu')
    assert nid is not None, "Should find instance 'pu'"

    emit_lvs_schem_select_nid(web, nid, 'device')

    time.sleep(0.3)
    count = get_schematic_highlight_count(web)
    assert count > 0, "Should have highlight after lvs:schem-select with schem_nid"


@pytest.mark.web
def test_lvs_clear_removes_schematic_highlight(web):
    """Emitting lvs:clear should remove highlight from schematic."""
    load_schematic_view(web)

    nid = get_instance_nid(web, 'pd')
    assert nid is not None, "Should find instance 'pd'"

    emit_lvs_schem_select_nid(web, nid, 'device')
    time.sleep(0.2)
    count = get_schematic_highlight_count(web)
    assert count > 0, "Precondition: should have highlight"

    emit_lvs_clear(web)
    time.sleep(0.2)

    count = get_schematic_highlight_count(web)
    assert count == 0, "Should have no highlight after lvs:clear"


@pytest.mark.web
def test_lvs_select_hightlight_instance_pos(web):
    """Verify highlight position matches selected instance (regression test for Y-flip bug)."""
    def get_highlight_y():
        return web.driver.execute_script("""
            const svg = document.querySelector('.rescontent svg');
            if (!svg) return null;
            const rect = svg.querySelector('.lvs-highlight-group rect');
            if (!rect) return null;
            return parseFloat(rect.getAttribute('y'));
        """)

    def get_instance_y_by_nid(nid):
        return web.driver.execute_script("""
            const svg = document.querySelector('.rescontent svg');
            if (!svg) return null;
            const inst = svg.querySelector(`[data-nid="${arguments[0]}"]`);
            if (!inst) return null;
            const rect = inst.querySelector('rect');
            if (!rect) return null;
            return parseFloat(rect.getAttribute('y'));
        """, nid)

    load_schematic_view(web)

    pd_nid = get_instance_nid(web, 'pd')
    pu_nid = get_instance_nid(web, 'pu')
    assert pd_nid is not None, "Should find pd instance"
    assert pu_nid is not None, "Should find pu instance"

    # pd is at y=2, pu is at y=8 in the test schematic
    emit_lvs_schem_select_nid(web, pd_nid, 'device')
    time.sleep(0.3)

    highlight_y = get_highlight_y()
    pd_y = get_instance_y_by_nid(pd_nid)
    pu_y = get_instance_y_by_nid(pu_nid)

    assert highlight_y is not None, "Should have highlight rect"
    assert pd_y is not None, "Should find pd instance Y"
    assert pu_y is not None, "Should find pu instance Y"

    # Highlight should be near pd (y=2), not near pu (y=8)
    # Allow 1.0 tolerance for padding
    assert abs(highlight_y - pd_y) < 1.0, f"Highlight Y ({highlight_y}) should be near pd Y ({pd_y}), not pu Y ({pu_y})"

    # Also test pu highlight
    emit_lvs_schem_select_nid(web, pu_nid, 'device')
    time.sleep(0.3)

    highlight_y = get_highlight_y()
    assert highlight_y is not None, "Should have highlight rect for pu"
    assert abs(highlight_y - pu_y) < 1.0, f"Highlight Y ({highlight_y}) should be near pu Y ({pu_y}), not pd Y ({pd_y})"


@pytest.mark.web
def test_lvs_select_highlights_net(web):
    """Verify net/pin highlighting creates overlay elements for wires and connection points."""
    def get_net_highlight_count():
        return web.driver.execute_script("""
            const svg = document.querySelector('.rescontent svg');
            if (!svg) return {paths: 0, circles: 0};
            const group = svg.querySelector('.lvs-highlight-group');
            if (!group) return {paths: 0, circles: 0};
            return {
                paths: group.querySelectorAll('path').length,
                circles: group.querySelectorAll('circle').length
            };
        """)

    load_schematic_view(web)

    # Get the nid for 'vss' net
    nid = get_net_nid(web, 'vss')
    assert nid is not None, "Should find vss net"

    emit_lvs_schem_select_nid(web, nid, 'net')
    time.sleep(0.3)

    counts = get_net_highlight_count()
    total = counts['paths'] + counts['circles']
    assert total > 0, f"Should have net highlights (paths={counts['paths']}, circles={counts['circles']})"


@pytest.mark.web
def test_lvs_select_highlights_pin(web):
    """Verify pin highlighting creates a circle overlay at the port location."""
    def get_pin_highlight_count():
        return web.driver.execute_script("""
            const svg = document.querySelector('.rescontent svg');
            if (!svg) return {circles: 0, paths: 0, rects: 0};
            const group = svg.querySelector('.lvs-highlight-group');
            if (!group) return {circles: 0, paths: 0, rects: 0};
            return {
                circles: group.querySelectorAll('circle').length,
                paths: group.querySelectorAll('path').length,
                rects: group.querySelectorAll('rect').length
            };
        """)

    load_schematic_view(web)

    # Get the nid for 'vss' pin (same as net nid)
    nid = get_net_nid(web, 'vss')
    assert nid is not None, "Should find vss pin"

    emit_lvs_schem_select_nid(web, nid, 'pin')
    time.sleep(0.3)

    counts = get_pin_highlight_count()
    # Pin highlighting should create exactly one circle, no paths or rects
    assert counts['circles'] == 1, f"Pin highlight should have 1 circle, got {counts['circles']}"
    assert counts['paths'] == 0, f"Pin highlight should have no paths (wires), got {counts['paths']}"
