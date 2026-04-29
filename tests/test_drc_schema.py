# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
import tempfile
from textwrap import dedent
from ordec.core import *
from ordec.core.schema import (
    DrcReport, DrcCategory, DrcItem, DrcBox, DrcEdge, DrcEdgePair,
    DrcPoly, DrcPath, DrcText, DrcValue, PolyVec2I
)
from ordec.layout.klayout import parse_rdb


@generate_func
def drc_test_layers():
    """Create a minimal LayerStack for testing."""
    layers = LayerStack()
    layers.unit = R('1n')
    layers % Layer(
        gdslayer_shapes=GdsLayer(1, 0),
        gdslayer_text=GdsLayer(1, 1),
        style_fill=RGBColor(255, 0, 0),
        style_stroke=RGBColor(200, 0, 0),
    )
    return layers


@generate_func
def drc_test_layout():
    """Create a minimal Layout with LayerStack for testing."""
    return Layout(ref_layers=drc_test_layers())


# DrcReport creation
# ------------------

def test_empty_report():
    layout = drc_test_layout()
    report = DrcReport(ref_layout=layout, top_cell_name='test')
    assert report.top_cell_name == 'test'
    assert report.nresults() == 0
    assert report.summary() == {}


def test_report_with_category():
    layout = drc_test_layout()
    report = DrcReport(ref_layout=layout, top_cell_name='test')
    cat = report % DrcCategory(name='min_space', description='Minimum spacing')
    assert cat.name == 'min_space'
    assert cat.description == 'Minimum spacing'
    assert cat.parent is None


def test_category_hierarchy():
    layout = drc_test_layout()
    report = DrcReport(ref_layout=layout, top_cell_name='test')
    parent = report % DrcCategory(name='metal', description='Metal rules')
    child = report % DrcCategory(name='m1_space', description='M1 spacing', parent=parent)
    assert child.parent == parent


def test_item_creation():
    layout = drc_test_layout()
    report = DrcReport(ref_layout=layout, top_cell_name='test')
    cat = report % DrcCategory(name='test_rule', description='Test')
    item = report % DrcItem(category=cat)
    assert item.category == cat
    assert item.cell is None


# DRC geometry nodes
# ------------------

def test_drc_box():
    layout = drc_test_layout()
    report = DrcReport(ref_layout=layout, top_cell_name='test')
    cat = report % DrcCategory(name='rule', description='')
    item = report % DrcItem(category=cat)
    box = report % DrcBox(item=item, rect=Rect4I(100, 200, 300, 400), tag='marker')
    assert box.rect == Rect4I(100, 200, 300, 400)
    assert box.tag == 'marker'
    assert box.order == 0


def test_drc_edge():
    layout = drc_test_layout()
    report = DrcReport(ref_layout=layout, top_cell_name='test')
    cat = report % DrcCategory(name='rule', description='')
    item = report % DrcItem(category=cat)
    edge = report % DrcEdge(item=item, p1=Vec2I(0, 0), p2=Vec2I(100, 100))
    assert edge.p1 == Vec2I(0, 0)
    assert edge.p2 == Vec2I(100, 100)


def test_drc_edge_pair():
    layout = drc_test_layout()
    report = DrcReport(ref_layout=layout, top_cell_name='test')
    cat = report % DrcCategory(name='rule', description='')
    item = report % DrcItem(category=cat)
    epair = report % DrcEdgePair(
        item=item,
        edge1_p1=Vec2I(0, 0), edge1_p2=Vec2I(100, 0),
        edge2_p1=Vec2I(0, 50), edge2_p2=Vec2I(100, 50)
    )
    assert epair.edge1_p1 == Vec2I(0, 0)
    assert epair.edge2_p2 == Vec2I(100, 50)


def test_drc_poly():
    layout = drc_test_layout()
    report = DrcReport(ref_layout=layout, top_cell_name='test')
    cat = report % DrcCategory(name='rule', description='')
    item = report % DrcItem(category=cat)
    poly = report % DrcPoly(item=item)
    report % PolyVec2I(ref=poly, order=0, pos=Vec2I(0, 0))
    report % PolyVec2I(ref=poly, order=1, pos=Vec2I(100, 0))
    report % PolyVec2I(ref=poly, order=2, pos=Vec2I(100, 100))
    vertices = poly.vertices()
    assert len(vertices) == 3
    assert vertices[0] == Vec2I(0, 0)
    assert vertices[2] == Vec2I(100, 100)


def test_drc_path():
    layout = drc_test_layout()
    report = DrcReport(ref_layout=layout, top_cell_name='test')
    cat = report % DrcCategory(name='rule', description='')
    item = report % DrcItem(category=cat)
    path = report % DrcPath(item=item, width=50)
    report % PolyVec2I(ref=path, order=0, pos=Vec2I(0, 0))
    report % PolyVec2I(ref=path, order=1, pos=Vec2I(200, 0))
    assert path.width == 50
    vertices = path.vertices()
    assert len(vertices) == 2


def test_drc_text():
    layout = drc_test_layout()
    report = DrcReport(ref_layout=layout, top_cell_name='test')
    cat = report % DrcCategory(name='rule', description='')
    item = report % DrcItem(category=cat)
    text = report % DrcText(item=item, pos=Vec2I(500, 500), text='error_label')
    assert text.text == 'error_label'
    assert text.pos == Vec2I(500, 500)


def test_drc_value():
    layout = drc_test_layout()
    report = DrcReport(ref_layout=layout, top_cell_name='test')
    cat = report % DrcCategory(name='rule', description='')
    item = report % DrcItem(category=cat)
    v = report % DrcValue(item=item, value='some info')
    assert v.value == 'some info'


# DrcReport helper methods
# ------------------------

def test_nresults():
    layout = drc_test_layout()
    report = DrcReport(ref_layout=layout, top_cell_name='test')
    cat = report % DrcCategory(name='rule1', description='')
    report % DrcItem(category=cat)
    report % DrcItem(category=cat)
    cat2 = report % DrcCategory(name='rule2', description='')
    report % DrcItem(category=cat2)
    assert report.nresults() == 3


def test_summary():
    layout = drc_test_layout()
    report = DrcReport(ref_layout=layout, top_cell_name='test')
    cat1 = report % DrcCategory(name='spacing', description='')
    cat2 = report % DrcCategory(name='width', description='')
    report % DrcItem(category=cat1)
    report % DrcItem(category=cat1)
    report % DrcItem(category=cat2)
    summary = report.summary()
    assert summary == {'spacing': 2, 'width': 1}


# Freezing
# --------

def test_freeze_report():
    layout = drc_test_layout()
    report = DrcReport(ref_layout=layout, top_cell_name='test')
    cat = report % DrcCategory(name='rule', description='')
    report % DrcItem(category=cat)
    frozen = report.freeze()
    assert frozen.nresults() == 1
    assert frozen.top_cell_name == 'test'


# RDB parsing
# -----------

def test_parse_simple_rdb():
    layout = drc_test_layout()
    rdb_content = dedent('''\
        <?xml version="1.0" encoding="utf-8"?>
        <report-database>
          <description>DRC Report</description>
          <top-cell>top</top-cell>
          <categories>
            <category>
              <name>test_rule</name>
              <description>Test rule description</description>
            </category>
          </categories>
          <cells>
            <cell id="c1">
              <name>top</name>
            </cell>
          </cells>
          <items>
            <item>
              <category>'test_rule'</category>
              <cell>c1</cell>
              <values>
                <value>(0,0;0.1,0.1)</value>
              </values>
            </item>
          </items>
        </report-database>
        ''')
    with tempfile.NamedTemporaryFile(mode='w', suffix='.lyrdb') as f:
        f.write(rdb_content)
        f.flush()
        report = parse_rdb(f.name, layout)
        assert report.top_cell_name == 'top'
        assert report.nresults() == 1
        categories = list(report.all(DrcCategory))
        assert len(categories) == 1
        assert categories[0].name == 'test_rule'


def test_parse_edge_pair():
    layout = drc_test_layout()
    rdb_content = dedent('''\
        <?xml version="1.0" encoding="utf-8"?>
        <report-database>
          <top-cell>top</top-cell>
          <categories>
            <category>
              <name>spacing</name>
              <description>Spacing violation</description>
            </category>
          </categories>
          <cells></cells>
          <items>
            <item>
              <category>'spacing'</category>
              <cell>top</cell>
              <values>
                <value>(0,0;0.1,0)/(0,0.05;0.1,0.05)</value>
              </values>
            </item>
          </items>
        </report-database>
        ''')
    with tempfile.NamedTemporaryFile(mode='w', suffix='.lyrdb') as f:
        f.write(rdb_content)
        f.flush()
        report = parse_rdb(f.name, layout)
        assert report.nresults() == 1
        items = list(report.all(DrcItem))
        edge_pairs = list(report.all(DrcEdgePair.item_idx.query(items[0])))
        assert len(edge_pairs) == 1
        # 0.1um = 100nm = 100 dbu (since unit=1n)
        assert edge_pairs[0].edge1_p2.x == 100


def test_parse_polygon():
    layout = drc_test_layout()
    rdb_content = dedent('''\
        <?xml version="1.0" encoding="utf-8"?>
        <report-database>
          <top-cell>top</top-cell>
          <categories>
            <category>
              <name>poly_rule</name>
              <description></description>
            </category>
          </categories>
          <cells></cells>
          <items>
            <item>
              <category>'poly_rule'</category>
              <cell>top</cell>
              <values>
                <value>(0,0;0.1,0;0.1,0.1;0,0.1)</value>
              </values>
            </item>
          </items>
        </report-database>
        ''')
    with tempfile.NamedTemporaryFile(mode='w', suffix='.lyrdb') as f:
        f.write(rdb_content)
        f.flush()
        report = parse_rdb(f.name, layout)
        items = list(report.all(DrcItem))
        polys = list(report.all(DrcPoly.item_idx.query(items[0])))
        assert len(polys) == 1
        vertices = polys[0].vertices()
        assert len(vertices) == 4
