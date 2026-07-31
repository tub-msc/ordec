# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from enum import Enum
import inspect
import re
from public import public

from ..ordb import *
from ..context import ReportViewContext

@public
class Report(SubgraphRoot):
    """
    Represents a list of vertically stacked report elements.

    Report elements are stored as ORDB nodes. The helper methods preserve the
    append-style API for building reports programmatically.
    """
    view_context = ReportViewContext

    fill_height = Attr(bool, default=False, optional=False)

    def elements(self):
        sg = self.subgraph
        for nid in sorted(sg.nodes):
            node = sg.nodes[nid]
            if issubclass(node._cursor_type, ReportElement):
                yield sg.cursor_at(nid)

    def markdown(self, markdown: str):
        """
        Append a Markdown element. The text is cleaned up docstring-style
        (inspect.cleandoc), so indented triple-quoted strings can be passed
        directly without their indentation turning into markdown code blocks.
        """
        self % Markdown(markdown=inspect.cleandoc(markdown))

    def pre(self, text: str):
        self % PreformattedText(text=text)

    def html(self, html: str):
        self % Html(html=html)

    def svg(self, view):
        self % Svg.from_view(view)

    def plot2d(self, series, **kwargs):
        plot = self % Plot2D(**kwargs)
        if isinstance(series, dict):
            series = series.items()
        for name, values in series:
            plot % Plot2DSeries(name=str(name), values=values)

    def passfail(self, label: str, passed: bool, instructions: str="", hint: str=None):
        # A passing check is stored as a bare pass: instructions and hint
        # only matter while the check fails.
        if passed:
            self % PassFail(label=label, passed=True)
        else:
            self % PassFail(label=label, passed=False,
                instructions=instructions, hint=hint)

    def bode_plot(self, *signals, **kwargs):
        """
        Append a Bode magnitude/phase plot pair from AC simulation results;
        see ordec.sim.helpers.bode_plot for the full signature. Imported
        lazily to keep the core schema independent of the sim subsystem.
        """
        from ...sim.helpers import bode_plot
        bode_plot(self, *signals, **kwargs)

    def webdata(self):
        return "report", {
            "elements": [element.element_webdata() for element in self.elements()],
            "fill_height": self.fill_height,
        }


@public
class ReportElement(Node):
    """Base class for all report element nodes."""
    in_subgraphs = [Report]

    def element_webdata(self) -> dict:
        """Returns JSON-serializable web representation."""
        raise NotImplementedError


@public
class Markdown(ReportElement):
    """
    Markdown text rendered as HTML in the web interface.

    Links using the 'docs:' pseudo-scheme, e.g. [WebUI](docs:webui.html),
    point to the ORDeC documentation matching the installed version.

    TeX math delimited by $...$ (inline) or $$...$$ (display) is rendered
    via KaTeX; dollar signs inside code spans are left alone.
    """
    markdown = Attr(str, optional=False)

    # TeX math spans are protected from markdown2 (which would otherwise
    # parse e.g. *...* inside a formula as emphasis) and re-emitted verbatim
    # for KaTeX to render in the browser. Code spans and fenced blocks win
    # over math by position, so dollar signs inside them (e.g. `.$r=1k`) are
    # never treated as math. Inline math must not span lines and must not
    # start or end with whitespace.
    _md_math_regex = re.compile(
        r"```.*?```"                          # fenced code block
        r"|`[^`\n]*`"                         # inline code span
        r"|(?P<math>\$\$.+?\$\$"              # display math
        r"|\$[^\s$](?:[^$\n]*[^\s$])?\$)",    # inline math
        re.DOTALL)

    def element_webdata(self) -> dict:
        import markdown2
        from html import escape
        from ...version import doc_url
        base = doc_url()
        # Rewrite 'docs:' pseudo-scheme links to version-matched documentation
        # URLs before rendering, so markdown2 sees ordinary https links.
        md = self.markdown.replace('](docs:', f']({base}')
        # Replace math spans with inert placeholder tokens so that markdown2
        # leaves their contents alone; see _md_math_regex.
        math_spans = []
        def protect(m):
            if m.group('math') is None:
                return m.group(0)  # code span/block: keep, do not scan inside
            math_spans.append(m.group('math'))
            return f"ordecmathspan{len(math_spans) - 1}end"
        md = self._md_math_regex.sub(protect, md)
        # No safe_mode: inline HTML (e.g. <sup> exponents in result tables)
        # passes through. Report content comes from the user's own trusted
        # cells, and the Html report element passes raw HTML anyway, so
        # escaping here would add no security.
        html = markdown2.markdown(
            md,
            extras=["fenced-code-blocks", "code-friendly", "tables"],
        )
        for i, span in enumerate(math_spans):
            # Re-emitted with delimiters for KaTeX's in-browser auto-render;
            # HTML-escaped, as this is substituted into finished HTML.
            html = html.replace(f"ordecmathspan{i}end", escape(span))
        # target=_blank so that following a documentation link does not
        # navigate away from the web app.
        html = html.replace(f'href="{base}',
            f'target="_blank" rel="noopener" href="{base}')
        return {
            "element_type": "markdown",
            "html": html,
        }


@public
class PreformattedText(ReportElement):
    """Preformatted text rendered using a monospace font."""
    text = Attr(str, optional=False)

    def element_webdata(self) -> dict:
        return {"element_type": "preformatted_text", "text": self.text}


@public
class Html(ReportElement):
    """Raw HTML content rendered directly in the web interface."""
    html = Attr(str, optional=False)

    def element_webdata(self) -> dict:
        return {"element_type": "html", "html": self.html}


@public
class PassFail(ReportElement):
    """
    Single pass/fail check result, e.g. for course lessons. A lesson is
    considered passed when all PassFail elements of its report pass.
    """
    label = Attr(str, optional=False) #: short name of the check
    passed = Attr(bool, optional=False)
    instructions = Attr(str, default="", optional=False) #: what the user should achieve / status details; failing checks only
    hint = Attr(str) #: optional hint, shown only on user request; failing checks only

    def element_webdata(self) -> dict:
        webdata = {
            "element_type": "passfail",
            "label": self.label,
            "passed": self.passed,
        }
        if not self.passed:
            webdata["instructions"] = self.instructions
            webdata["hint"] = self.hint
        return webdata


@public
class Svg(ReportElement):
    """Static SVG element rendered without zoom."""
    inner = Attr(str, optional=False) #: SVG markup inside the <svg> element
    viewbox_min_x = Attr(float, optional=False) #: viewBox left edge
    viewbox_min_y = Attr(float, optional=False) #: viewBox top edge
    viewbox_width = Attr(float, optional=False) #: viewBox width
    viewbox_height = Attr(float, optional=False) #: viewBox height
    width = Attr(str) #: CSS width string (e.g. "120px")
    height = Attr(str) #: CSS height string (e.g. "80px")

    @classmethod
    def from_view(cls, view) -> "Svg":
        """Creates an SVG report element from an object exposing webdata()."""
        view_type, data = view.webdata()
        if view_type != "svg":
            raise ValueError(f"Expected svg webdata, got {view_type!r}")
        vb = data["viewbox"]
        return cls(
            inner=data["inner"],
            viewbox_min_x=float(vb[0]),
            viewbox_min_y=float(vb[1]),
            viewbox_width=float(vb[2]),
            viewbox_height=float(vb[3]),
            width=data["width"],
            height=data["height"],
        )

    def element_webdata(self) -> dict:
        return {
            "element_type": "svg",
            "inner": self.inner,
            "viewbox": [
                self.viewbox_min_x,
                self.viewbox_min_y,
                self.viewbox_width,
                self.viewbox_height
            ],
            "width": self.width,
            "height": self.height,
        }


@public
class ScaleType(Enum):
    Linear = 'linear'
    Log = 'log'

    def __repr__(self):
        return f'{self.__class__.__name__}.{self.name}'

def coerce_plot_x(x):
    x = tuple(float(v) for v in x)
    if len(x) < 2:
        raise ValueError("x must contain at least two values")
    for i in range(1, len(x)):
        if x[i] < x[i - 1]:
            raise ValueError("x values must be sorted in ascending order")
    return x

@public
class PlotGroup(Node):
    """Groups Plot2D elements that share a synchronized x-axis."""
    in_subgraphs = [Report]

@public
class Plot2D(ReportElement):
    """2D plot element rendered with the frontend simulation plot component."""
    x = Attr(tuple, optional=False, factory=coerce_plot_x)
    xlabel = Attr(str, default="", optional=False)
    ylabel = Attr(str, default="", optional=False)
    xscale = Attr(ScaleType, default=ScaleType.Linear, optional=False, factory=ScaleType)
    yscale = Attr(ScaleType, default=ScaleType.Linear, optional=False, factory=ScaleType)
    height = Attr(float, factory=lambda v: float(v) if v is not None else None) #: plot height in pixels
    group = LocalRef(PlotGroup)

    def series(self):
        return self.subgraph.all(Plot2DSeries.ref_idx.query(self))

    def element_webdata(self) -> dict:
        return {
            "element_type": "plot2d",
            "x": list(self.x),
            "series": [
                {"name": s.name, "values": list(s.values)}
                for s in self.series()
            ],
            "xlabel": self.xlabel,
            "ylabel": self.ylabel,
            "xscale": self.xscale.value,
            "yscale": self.yscale.value,
            "height": f"{self.height:g}px" if self.height is not None else None,
            "group": self.group.nid if self.group is not None else None,
        }

def coerce_plot_values(values):
    return tuple(float(v) for v in values)

@public
class Plot2DSeries(Node):
    """A single data series belonging to a Plot2D element."""
    in_subgraphs = [Report]
    ref = LocalRef(Plot2D, optional=False)
    ref_idx = Index(ref)
    name = Attr(str, optional=False)
    values = Attr(tuple, optional=False, factory=coerce_plot_values)
