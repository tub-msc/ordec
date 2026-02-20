# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

import markdown2
from public import public

class ReportElement(ABC):
    """Base class for all report elements."""

    @abstractmethod
    def element_webdata(self) -> dict:
        """Returns JSON-serializable web representation."""
        pass

@public
class Markdown(ReportElement):
    """Markdown text rendered as HTML in the web interface."""

    def __init__(self, markdown: str):
        self.markdown = markdown

    def element_webdata(self) -> dict:
        return {
            "element_type": "markdown",
            "markdown": self.markdown,
            "html": markdown2.markdown(
                self.markdown,
                extras=["fenced-code-blocks", "code-friendly", "tables"],
                safe_mode="escape",
            ),
        }

@public
class PreformattedText(ReportElement):
    """Preformatted text rendered using a monospace font."""

    def __init__(self, text: str):
        self.text = text

    def element_webdata(self) -> dict:
        return {"element_type": "preformatted_text", "text": self.text}

@public
class Svg(ReportElement):
    """Static SVG element (e.g. schematic/symbol) rendered without zoom."""

    def __init__(self, inner: str, viewbox, width: str, height: str):
        self.inner = inner
        self.viewbox = self._normalize_viewbox(viewbox)
        self.width = width
        self.height = height

    @staticmethod
    def _normalize_viewbox(viewbox) -> list[float]:
        values = [float(v) for v in viewbox]
        if len(values) != 4:
            raise ValueError("viewbox must contain exactly four numbers")
        return values

    @classmethod
    def from_view(cls, view) -> "Svg":
        """Creates an SVG report element from an object exposing webdata()."""
        view_type, data = view.webdata()
        if view_type != "svg":
            raise ValueError(f"Expected svg webdata, got {view_type!r}")
        return cls(
            inner=data["inner"],
            viewbox=data["viewbox"],
            width=data["width"],
            height=data["height"],
        )

    def element_webdata(self) -> dict:
        return {
            "element_type": "svg",
            "inner": self.inner,
            "viewbox": self.viewbox,
            "width": self.width,
            "height": self.height,
        }

@public
class Plot2D(ReportElement):
    """2D plot element rendered with the frontend simulation plot component."""

    def __init__(
        self,
        x: Iterable[float],
        series: (
            dict[str, Iterable[float]]
            | Iterable[tuple[str, Iterable[float]]]
        ),
        *,
        xlabel: str = "",
        ylabel: str = "",
        xscale: str = "linear",
        yscale: str = "linear",
        height: int | float | str = 260,
        plot_group: str | None = None,
    ):
        self.x = [float(v) for v in x]
        self._validate_x(self.x)
        self.series = self._normalize_series(series, len(self.x))
        self.xlabel = xlabel
        self.ylabel = ylabel
        self.xscale = self._validate_scale(xscale, "xscale")
        self.yscale = self._validate_scale(yscale, "yscale")
        self.height = self._normalize_height(height)
        self.plot_group = plot_group

    @staticmethod
    def _validate_x(x: list[float]):
        if len(x) < 2:
            raise ValueError("x must contain at least two values")
        for i in range(1, len(x)):
            if x[i] < x[i - 1]:
                raise ValueError("x values must be sorted in ascending order")

    @staticmethod
    def _normalize_series(
        series: (
            dict[str, Iterable[float]]
            | Iterable[tuple[str, Iterable[float]]]
        ),
        expected_len: int,
    ) -> list[dict]:
        if isinstance(series, dict):
            pairs = list(series.items())
        else:
            pairs = list(series)

        normalized = []
        for name, values in pairs:
            vals = [float(v) for v in values]
            if len(vals) != expected_len:
                raise ValueError(
                    f"Series {name!r} has length {len(vals)}, expected "
                    f"{expected_len}"
                )
            normalized.append({
                "name": str(name),
                "values": vals,
            })

        if not normalized:
            raise ValueError("Plot2D requires at least one series")
        return normalized

    @staticmethod
    def _validate_scale(scale: str, name: str) -> str:
        if scale not in ("linear", "log"):
            raise ValueError(f"{name} must be 'linear' or 'log'")
        return scale

    @staticmethod
    def _normalize_height(height: int | float | str) -> str:
        if isinstance(height, str):
            if not height.strip():
                raise ValueError("height string must not be empty")
            return height
        if not isinstance(height, (int, float)):
            raise TypeError("height must be int, float or string")
        if height <= 0:
            raise ValueError("height must be greater than zero")
        return f"{height:g}px"

    def element_webdata(self) -> dict:
        return {
            "element_type": "plot2d",
            "x": self.x,
            "series": self.series,
            "xlabel": self.xlabel,
            "ylabel": self.ylabel,
            "xscale": self.xscale,
            "yscale": self.yscale,
            "height": self.height,
            "plot_group": self.plot_group,
        }

@public
class Report:
    """
    Represents a list of vertically stacked report elements.

    The class is intentionally lightweight and extensible so additional
    element types and metadata fields can be added later without changing
    existing report producers.
    """

    def __init__(self, elements: Iterable[ReportElement] = ()):
        self._elements = list(elements)
        self._validate_elements(self._elements)

    @staticmethod
    def _validate_elements(elements: Iterable[ReportElement]):
        for element in elements:
            if not isinstance(element, ReportElement):
                raise TypeError(
                    "All report elements must be ReportElement instances"
                )

    @property
    def elements(self) -> tuple[ReportElement, ...]:
        return tuple(self._elements)

    def add(self, element: ReportElement) -> "Report":
        self._validate_elements((element,))
        self._elements.append(element)
        return self

    def extend(self, elements: Iterable[ReportElement]) -> "Report":
        new_elements = list(elements)
        self._validate_elements(new_elements)
        self._elements.extend(new_elements)
        return self

    def webdata(self):
        return "report", {
            "elements": [element.element_webdata() for element in self._elements]
        }
