# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest

from ordec.report import Plot2D


def test_plot2d_webdata():
    plot = Plot2D(
        x=[1.0, 2.0, 3.0],
        series={"v(out)": [0.1, 0.2, 0.3]},
        xlabel="Time (s)",
        ylabel="Voltage (V)",
        height=180,
        plot_group="tran",
    )
    data = plot.element_webdata()
    assert data["element_type"] == "plot2d"
    assert data["x"] == [1.0, 2.0, 3.0]
    assert data["series"] == [{"name": "v(out)", "values": [0.1, 0.2, 0.3]}]
    assert data["height"] == "180px"
    assert data["plot_group"] == "tran"


def test_plot2d_rejects_mismatched_series_length():
    with pytest.raises(ValueError):
        Plot2D(
            x=[1.0, 2.0, 3.0],
            series={"i(v1)": [0.1, 0.2]},
        )


def test_plot2d_rejects_unsorted_x():
    with pytest.raises(ValueError):
        Plot2D(
            x=[1.0, 0.5, 2.0],
            series={"v(out)": [0.1, 0.2, 0.3]},
        )
