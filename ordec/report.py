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
