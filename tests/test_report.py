# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest

from ordec.core.ordb import SubgraphRoot
from ordec.core.schema import Markdown, PlotGroup, Report


def test_report_is_ordb_subgraph_root():
    report = Report()
    report.markdown("hello")

    assert isinstance(report, SubgraphRoot)
    assert [element.markdown for element in report.elements()] == ["hello"]
    assert [element.markdown for element in report.all(Markdown)] == ["hello"]

    frozen = report.freeze()
    assert isinstance(frozen, SubgraphRoot)
    assert frozen.mutable is False
    assert frozen.webdata() == report.webdata()


def test_plot2d_webdata():
    report = Report()
    report.tran = PlotGroup()
    report.plot2d(
        x=[1.0, 2.0, 3.0],
        series={"v(out)": [0.1, 0.2, 0.3]},
        xlabel="Time (s)",
        ylabel="Voltage (V)",
        height=180,
        plot_group=report.tran,
    )
    _, data = report.webdata()
    plot_data = data["elements"][0]
    assert plot_data["element_type"] == "plot2d"
    assert plot_data["x"] == [1.0, 2.0, 3.0]
    assert plot_data["series"] == [{"name": "v(out)", "values": [0.1, 0.2, 0.3]}]
    assert plot_data["height"] == "180px"
    assert plot_data["plot_group"] == report.tran.nid


def test_plot2d_rejects_unsorted_x():
    report = Report()
    with pytest.raises(ValueError):
        report.plot2d(
            x=[1.0, 0.5, 2.0],
            series={"v(out)": [0.1, 0.2, 0.3]},
        )


def test_plot2d_height_none():
    report = Report()
    report.plot2d(
        x=[1.0, 2.0, 3.0],
        series={"v(out)": [0.1, 0.2, 0.3]},
        height=None,
    )
    _, data = report.webdata()
    assert data["elements"][0]["height"] is None


def test_report_fill_height():
    report = Report(fill_height=True)
    report.markdown("hello")
    assert report.fill_height is True
    view_type, data = report.webdata()
    assert view_type == "report"
    assert data["fill_height"] is True


def test_report_fill_height_default():
    report = Report()
    assert report.fill_height is False
    _, data = report.webdata()
    assert data["fill_height"] is False
