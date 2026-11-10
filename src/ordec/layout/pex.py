# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ..core.schema import PexReport, PexNet, PexCoupling, Report


def webdata(report: PexReport):
    """Builds a Report on the nets of a PexReport for display in the web UI."""
    nets = sorted(report.all(PexNet), key=lambda net: net.capacitance, reverse=True)
    couplings = list(report.all(PexCoupling))

    largest = {}
    for coupling in couplings:
        for net, other in ((coupling.a, coupling.b), (coupling.b, coupling.a)):
            if net.nid not in largest or coupling.capacitance > largest[net.nid][0]:
                largest[net.nid] = (coupling.capacitance, other)

    fF = lambda c: f"{float(c) * 1e15:.3f}"
    rows = [
        "| Net | Nodes | Resistors | Capacitance (fF) | Largest coupling (fF) |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for net in nets:
        coupling = ""
        if net.nid in largest:
            c, other = largest[net.nid]
            coupling = f"`{other.net.full_path_str()}` ({fF(c)})"
        rows.append(f"| `{net.net.full_path_str()}` | {net.nodes} | {net.resistors} "
            f"| {fF(net.capacitance)} | {coupling} |")

    ret = Report()
    ret.markdown(f"{len(nets)} nets with {sum(net.resistors for net in nets)} "
        f"parasitic resistors and {fF(sum(c.capacitance for c in couplings))} fF "
        "of parasitic capacitance between them.")
    ret.markdown("\n".join(rows))
    return ret.webdata_static()
