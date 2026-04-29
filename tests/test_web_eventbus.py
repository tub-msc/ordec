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
    web.driver.get(web.url + f'app.html#refreshall=true&{qs_local}')
    web.driver.refresh()
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
    web.driver.get(web.url + f'app.html#refreshall=true&viewsel_flat=true&{qs}')
    web.driver.refresh()
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


def emit_lvs_select(web, shapes, schem_path=None):
    """Emit lvs:select event with given shapes."""
    web.driver.execute_script(
        "window.viewEventBus.emit('lvs:select', {shapes: arguments[0], schem_path: arguments[1]});",
        shapes,
        schem_path or []
    )


def emit_lvs_clear(web):
    """Emit lvs:clear event."""
    web.driver.execute_script("window.viewEventBus.emit('lvs:clear');")


@pytest.mark.web
def test_lvs_select_highlights_layout(web):
    """Emitting lvs:select should set highlight vertices in layout viewer."""
    load_layout_view(web)

    state = get_layout_state(web)
    assert state is not None, "Layout viewer not found"
    assert state['highlightNumVertices'] == 0, "Should start with no highlight"

    emit_lvs_select(web, [{'type': 'box', 'rect': [0, 0, 1000, 1000]}])

    state = get_layout_state(web)
    assert state['highlightNumVertices'] > 0, "Should have highlight after lvs:select"


@pytest.mark.web
def test_lvs_clear_removes_highlight(web):
    """Emitting lvs:clear should remove highlight from layout viewer."""
    load_layout_view(web)

    emit_lvs_select(web, [{'type': 'box', 'rect': [0, 0, 500, 500]}])
    state = get_layout_state(web)
    assert state['highlightNumVertices'] > 0, "Precondition: should have highlight"

    emit_lvs_clear(web)

    state = get_layout_state(web)
    assert state['highlightNumVertices'] == 0, "Should have no highlight after lvs:clear"


def load_schematic_view(web):
    """Load a schematic view using the lvs_example."""
    qs_local = web.key.query_string_local("tests.lib.lvs_example", "schematic()")
    web.driver.get(web.url + f'app.html#refreshall=true&{qs_local}')
    web.driver.refresh()
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
    """Emitting lvs:select with schem_path should highlight the instance in schematic."""
    load_schematic_view(web)

    count = get_schematic_highlight_count(web)
    assert count == 0, "Should start with no highlight"

    web.driver.execute_script("""
        window.viewEventBus.emit('lvs:select', {
            shapes: [],
            schem_path: ['pu']
        });
    """)

    time.sleep(0.3)
    count = get_schematic_highlight_count(web)
    assert count > 0, "Should have highlight after lvs:select with schem_path"


@pytest.mark.web
def test_lvs_clear_removes_schematic_highlight(web):
    """Emitting lvs:clear should remove highlight from schematic."""
    load_schematic_view(web)

    web.driver.execute_script("""
        window.viewEventBus.emit('lvs:select', {
            shapes: [],
            schem_path: ['pd']
        });
    """)
    time.sleep(0.2)
    count = get_schematic_highlight_count(web)
    assert count > 0, "Precondition: should have highlight"

    emit_lvs_clear(web)
    time.sleep(0.2)

    count = get_schematic_highlight_count(web)
    assert count == 0, "Should have no highlight after lvs:clear"
