# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from enum import Enum
import inspect
from math import isfinite
import re
from public import public

from ..ordb import *
from ..context import ReportViewBuilder
from ..simarray import SimColumn, SimSeries
from .simhier import SimNet, SimPin, SimParam

WIRE_DOMAIN = 8 << 16

@public
class Report(SubgraphRoot):
    """
    Represents a list of vertically stacked report elements.

    Report elements are stored as ORDB nodes. The helper methods preserve the
    append-style API for building reports programmatically.
    """
    view_builder = ReportViewBuilder
    wire_id = WIRE_DOMAIN | 1

    fill_height = Attr(bool, default=False, optional=False)

    def elements(self):
        sg = self.subgraph
        for nid in sorted(sg.nodes):
            node = sg.nodes[nid]
            if issubclass(node._cursor_type, ReportElement):
                yield sg.cursor_at(nid)

    # All element helpers return the inserted element's cursor.

    def markdown(self, markdown: str):
        """
        Append a Markdown element. The text is cleaned up docstring-style
        (inspect.cleandoc), so indented triple-quoted strings can be passed
        directly without their indentation turning into markdown code blocks.
        """
        return self % Markdown(markdown=inspect.cleandoc(markdown))

    def pre(self, text: str):
        return self % PreformattedText(text=text)

    def html(self, html: str):
        return self % Html(html=html)

    def svg(self, view):
        return self % Svg.from_view(view)

    def plot2d(self, *ys, **kwargs):
        """
        Append a Plot2D element. Each argument is one 2D series carrying
        its own x axis; returns the Plot2D cursor. A series is:

        - a SimNet, SimPin or SimParam node: the hierarchical path
          becomes the series name and the recorded result series
          (voltage, current or value) provides the data, with its scale
          (time, frequency or sweep) as x;
        - a (name, series) pair, where series is a SimSeries with
          exactly one scale;
        - a (name, x, y) triple pairing two signals point-wise, e.g. a
          transfer curve of one net voltage over another. x and y are
          data vectors (a SimSeries such as net.voltage, a SimColumn or
          a plain iterable of numbers), never nodes; when both carry a
          scale, they must share it.

        Axis labels not given explicitly are inferred from the Quantity
        carried by the result columns: xlabel from the series' scale
        quantities, ylabel from their values quantities, joining
        distinct quantity labels with ", ".

        height defaults to 300 pixels; pass height=None to fill the
        available height instead (for fill_height reports).
        """
        if not ys:
            raise ValueError("plot2d requires at least one series")
        # Resolve all series before touching the subgraph, so that a bad
        # series argument does not leave a partial Plot2D in the report.
        series = [plot2d_series(y) for y in ys]
        kwargs.setdefault('height', 300)
        # Columns packed from plain iterables carry no quantity; a
        # single None among the quantities suppresses the inference.
        if 'xlabel' not in kwargs:
            quantities = list(dict.fromkeys(
                s.scales[0].quantity for _, s in series))
            if None not in quantities:
                kwargs['xlabel'] = ", ".join(q.value for q in quantities)
        if 'ylabel' not in kwargs:
            quantities = list(dict.fromkeys(
                s.values.quantity for _, s in series))
            if None not in quantities:
                kwargs['ylabel'] = ", ".join(q.value for q in quantities)
        plot = self % Plot2D(**kwargs)
        for node, _ in series:
            plot % node
        return plot

    def passfail(self, label: str, passed: bool, instructions: str="", hint: str=None):
        # A passing check is stored as a bare pass: instructions and hint
        # only matter while the check fails.
        if passed:
            return self % PassFail(label=label, passed=True)
        else:
            return self % PassFail(label=label, passed=False,
                instructions=instructions, hint=hint)

    def bode_plot(self, *signals, **kwargs):
        """
        Append a Bode magnitude/phase plot pair from AC simulation results;
        see ordec.sim.helpers.bode_plot for the full signature. Imported
        lazily to keep the core schema independent of the sim subsystem.
        Returns the (magnitude, phase) pair of Plot2D cursors.
        """
        from ...sim.helpers import bode_plot
        return bode_plot(self, *signals, **kwargs)

    def webdata_static(self):
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
    wire_id = WIRE_DOMAIN | 2
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
    wire_id = WIRE_DOMAIN | 3
    text = Attr(str, optional=False)

    def element_webdata(self) -> dict:
        return {"element_type": "preformatted_text", "text": self.text}


@public
class Html(ReportElement):
    """Raw HTML content rendered directly in the web interface."""
    wire_id = WIRE_DOMAIN | 4
    html = Attr(str, optional=False)

    def element_webdata(self) -> dict:
        return {"element_type": "html", "html": self.html}


@public
class PassFail(ReportElement):
    """
    Single pass/fail check result, e.g. for course lessons. A lesson is
    considered passed when all PassFail elements of its report pass.
    """
    wire_id = WIRE_DOMAIN | 5
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
    wire_id = WIRE_DOMAIN | 6
    inner = Attr(str, optional=False) #: SVG markup inside the <svg> element
    viewbox_min_x = Attr(float, optional=False) #: viewBox left edge
    viewbox_min_y = Attr(float, optional=False) #: viewBox top edge
    viewbox_width = Attr(float, optional=False) #: viewBox width
    viewbox_height = Attr(float, optional=False) #: viewBox height
    width = Attr(str) #: CSS width string (e.g. "120px")
    height = Attr(str) #: CSS height string (e.g. "80px")

    @classmethod
    def from_view(cls, view) -> "Svg":
        """Creates an SVG report element from an object exposing webdata_static()."""
        view_type, data = view.webdata_static()
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

@public
class PlotGroup(Node):
    """Groups Plot2D elements that share a synchronized x-axis."""
    in_subgraphs = [Report]
    wire_id = WIRE_DOMAIN | 7

@public
class Plot2D(ReportElement):
    """
    2D plot element rendered with the frontend simulation plot
    component. Holds only presentation state; the plotted data lives in
    the attached Plot2DSeries nodes, each carrying its own x axis.
    """
    wire_id = WIRE_DOMAIN | 8
    xlabel = Attr(str, default="", optional=False)
    ylabel = Attr(str, default="", optional=False)
    xscale = Attr(ScaleType, default=ScaleType.Linear, optional=False, factory=ScaleType)
    yscale = Attr(ScaleType, default=ScaleType.Linear, optional=False, factory=ScaleType)
    height = Attr(int) #: plot height in pixels; None fills the available height
    group = LocalRef(PlotGroup)

    def series(self):
        return self.subgraph.all(Plot2DSeries.ref_idx.query(self))

    def element_webdata(self) -> dict:
        # Non-finite values cross the protocol as null: JSON has no
        # NaN/Infinity, and json.dumps would emit bare NaN tokens that the
        # frontend's JSON.parse rejects, losing the whole view message.
        # SimPlot.setData maps null back to NaN for gap rendering.
        return {
            "element_type": "plot2d",
            "series": [
                {
                    "name": s.name,
                    "x": [v if isfinite(v) else None
                        for v in s.series.scales[0]],
                    "values": [v if isfinite(v) else None
                        for v in s.series.values],
                }
                for s in self.series()
            ],
            "xlabel": self.xlabel,
            "ylabel": self.ylabel,
            "xscale": self.xscale.value,
            "yscale": self.yscale.value,
            "height": f"{self.height}px" if self.height is not None else None,
            "group": self.group.nid if self.group is not None else None,
        }

def signal_series(y):
    """
    Resolve a SimNet / SimPin / SimParam node to its recorded SimSeries
    (voltage, current or value); raises ValueError if no simulation
    data is recorded on the node.
    """
    if isinstance(y, SimNet):
        s = y.voltage
    elif isinstance(y, SimPin):
        s = y.current
    else:
        s = y.value
    if s is None:
        raise ValueError(
            f"no simulation data recorded for {y.full_path_str()}")
    return s

def paired_series(x, y):
    """
    Build the SimSeries for a (name, x, y) plot2d triple: y plotted
    point-wise over x. Operands are data vectors (SimSeries, SimColumn
    or plain iterables), never nodes: which recorded signal of a node is
    meant must be spelled out, e.g. net.voltage. When both operands
    carry scales, they must share their (single) scale: pairing two
    signals point-wise is only meaningful over a common axis, e.g. two
    voltages recorded by the same transient run.
    """
    for operand in (x, y):
        if isinstance(operand, (SimNet, SimPin, SimParam)):
            raise TypeError(
                "triple operands must be data vectors, not nodes; pass "
                "the recorded signal explicitly, e.g. net.voltage, "
                "pin.current or param.value")
    if isinstance(x, SimSeries) and isinstance(y, SimSeries) \
            and x.scales and y.scales:
        # Identity fast path: the simulator shares one scale column
        # object across all series of a run.
        if len(x.scales) != 1 or len(y.scales) != 1 or not (
                x.scales[0] is y.scales[0] or x.scales[0] == y.scales[0]):
            raise ValueError(
                "cannot pair the two signals: they do not share a "
                "common axis (scale)")
    xcol = x.values if isinstance(x, SimSeries) else SimColumn.coerce(x)
    ycol = y.values if isinstance(y, SimSeries) else SimColumn.coerce(y)
    # The SimSeries constructor supplies the equal-length check.
    return SimSeries(ycol, (xcol,))

def plot2d_series(y):
    """
    Resolve one Report.plot2d series argument to an uninserted
    Plot2DSeries node plus its resolved SimSeries.

    Accepts a SimNet / SimPin / SimParam node, a (name, series) pair or
    a (name, x, y) triple; see Report.plot2d. Node names are the
    hierarchical paths (full_path_str), e.g. "stage[0].m7.d" for a pin
    or "stage[0].m7.gm" for a parameter.
    """
    if isinstance(y, (SimNet, SimPin, SimParam)):
        name, s = y.full_path_str(), signal_series(y)
    elif isinstance(y, (tuple, list)) and len(y) == 2 and isinstance(y[0], str):
        name, s = y[0], SimSeries.coerce(y[1])
        if s is None:
            raise ValueError(f"no data for series {name!r}")
    elif isinstance(y, (tuple, list)) and len(y) == 3 and isinstance(y[0], str):
        name, s = y[0], paired_series(y[1], y[2])
    else:
        raise TypeError(
            f"plot2d series must be a SimNet/SimPin/SimParam node, a "
            f"(name, series) pair or a (name, x, y) triple, got "
            f"{type(y).__name__}")
    # Constructing the node validates the series (via the series attr
    # factory) exactly once and raises on bad values before
    # Report.plot2d mutates the subgraph.
    return Plot2DSeries(name=name, series=s), s

def coerce_plot_series(s):
    s = SimSeries.coerce(s)
    if s is None:
        return None # rejected at insertion (the attr is non-optional)
    if len(s.scales) != 1:
        raise ValueError(
            f"plot series must carry exactly one x axis (scale), "
            f"got {len(s.scales)}")
    x = s.scales[0]
    # Plot data is f8-only; complex AC data gets a hint towards the
    # proper workflows.
    if s.values.dtype != 'f8' or x.dtype != 'f8':
        raise TypeError(
            "Plot2D series values must be real numbers; convert complex "
            "AC data via abs()/cmath.phase() or use Report.bode_plot()")
    if len(s) < 2:
        raise ValueError("plot series must contain at least two values")
    # O(n) read through the (possibly strided) x column view. The
    # explicit finiteness check matters: NaN compares false against
    # everything and would slip through the sortedness check.
    prev = None
    for v in x:
        if not isfinite(v):
            raise ValueError("x values must be finite")
        if prev is not None and v < prev:
            raise ValueError("x values must be sorted in ascending order")
        prev = v
    return s

@public
class Plot2DSeries(Node):
    """
    A single data series belonging to a Plot2D element: a display name
    plus a SimSeries whose single scale column is the series' x axis.
    """
    in_subgraphs = [Report]
    wire_id = WIRE_DOMAIN | 9
    ref = LocalRef(Plot2D, optional=False)
    ref_idx = Index(ref)
    name = Attr(str, optional=False)
    series = Attr(SimSeries, optional=False, factory=coerce_plot_series)
