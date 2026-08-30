# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest

from ordec.core.ordb import SubgraphRoot
from ordec.core.schema import Markdown, PlotGroup, Report
from ordec.core.wire import ExportTable


def test_report_is_ordb_subgraph_root():
    report = Report()
    md = report.markdown("hello")

    # Element helpers return the inserted element's cursor.
    assert isinstance(md, Markdown)
    assert isinstance(report, SubgraphRoot)
    assert [element.markdown for element in report.elements()] == ["hello"]
    assert [element.markdown for element in report.all(Markdown)] == ["hello"]

    frozen = report.freeze()
    assert isinstance(frozen, SubgraphRoot)
    assert frozen.mutable is False
    ept = ExportTable()
    assert frozen.webdata(ept) == report.webdata(ept)


def test_plot2d_webdata():
    from ordec.core.schema import Plot2D

    report = Report()
    report.tran = PlotGroup()
    plot = report.plot2d(
        [1.0, 2.0, 3.0],
        ("v(out)", [0.1, 0.2, 0.3]),
        xlabel="Time (s)",
        ylabel="Voltage (V)",
        height=180,
        group=report.tran,
    )
    assert isinstance(plot, Plot2D)
    _, data = report.webdata(ExportTable())
    plot_data = data["elements"][0]
    assert plot_data["element_type"] == "plot2d"
    assert plot_data["x"] == [1.0, 2.0, 3.0]
    assert plot_data["series"] == [{"name": "v(out)", "values": [0.1, 0.2, 0.3]}]
    assert plot_data["height"] == "180px"
    assert plot_data["group"] == report.tran.nid


def test_plot2d_rejects_unsorted_x():
    report = Report()
    with pytest.raises(ValueError):
        report.plot2d(
            [1.0, 0.5, 2.0],
            ("v(out)", [0.1, 0.2, 0.3]),
        )


def test_plot2d_bad_series():
    report = Report()
    # A bare values iterable has no name and is rejected; a rejected
    # series must not leave a partial Plot2D in the report.
    with pytest.raises(TypeError, match="pair or a"):
        report.plot2d([1.0, 2.0], [0.1, 0.2, 0.3])
    with pytest.raises(TypeError, match="real numbers"):
        report.plot2d([1.0, 2.0], ("v(out)", [1 + 2j, 3 + 4j]))
    # A scalar instead of a sequence keeps its original error message.
    with pytest.raises(TypeError, match="not iterable"):
        report.plot2d([1.0, 2.0], ("v(out)", 5.0))
    _, data = report.webdata(ExportTable())
    assert data["elements"] == []


def test_plot2d_height_none():
    report = Report()
    report.plot2d(
        [1.0, 2.0, 3.0],
        ("v(out)", [0.1, 0.2, 0.3]),
        height=None,
    )
    _, data = report.webdata(ExportTable())
    assert data["elements"][0]["height"] is None


def test_passfail_webdata():
    report = Report()
    # A pass is a bare pass: instructions and hint are discarded.
    pf = report.passfail("Check A", True, instructions="Do the thing.",
        hint="Try harder.")
    assert pf.passed is True
    pf = report.passfail("Check B", False, instructions="Do the thing.",
        hint="Try harder.")
    assert pf.passed is False
    _, data = report.webdata(ExportTable())
    assert data["elements"][0] == {
        "element_type": "passfail",
        "label": "Check A",
        "passed": True,
    }
    assert data["elements"][1] == {
        "element_type": "passfail",
        "label": "Check B",
        "passed": False,
        "instructions": "Do the thing.",
        "hint": "Try harder.",
    }


def test_markdown_docs_links():
    report = Report()
    report.markdown("See [WebUI](docs:webui_design_organization.html#intermediate-local-mode) for details.")
    _, data = report.webdata(ExportTable())
    html = data["elements"][0]["html"]
    assert 'target="_blank" rel="noopener" ' \
        'href="https://ordec.readthedocs.io/en/' in html
    assert 'webui_design_organization.html#intermediate-local-mode"' in html
    assert 'docs:' not in html


def test_markdown_math():
    report = Report()
    report.markdown(
        "At $f = \\frac{1}{2*\\pi*\\sqrt{L C}}$ with `.$r=1k` code, "
        "$a<b$ and display: $$x^2 * y$$ Prices like 5 $ stay text.")
    _, data = report.webdata(ExportTable())
    html = data["elements"][0]["html"]
    # Math spans reach the client verbatim (markdown2 must not parse the
    # *...* as emphasis), HTML-escaped:
    assert "$f = \\frac{1}{2*\\pi*\\sqrt{L C}}$" in html
    assert "$$x^2 * y$$" in html
    assert "$a&lt;b$" in html
    # Dollar signs in code spans are not math:
    assert "<code>.$r=1k</code>" in html
    # An unpaired/whitespace-delimited dollar sign is not math either:
    assert "5 $ stay" in html


def test_report_fill_height():
    report = Report(fill_height=True)
    report.markdown("hello")
    assert report.fill_height is True
    view_type, data = report.webdata(ExportTable())
    assert view_type == "report"
    assert data["fill_height"] is True


def test_report_fill_height_default():
    report = Report()
    assert report.fill_height is False
    _, data = report.webdata(ExportTable())
    assert data["fill_height"] is False
