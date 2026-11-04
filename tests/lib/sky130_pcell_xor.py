# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0
"""
KLayout batch script (klayout -b -r): XOR ORDeC layouts against GDS files of
the PDK's generated cells, written by magic.

Script variables (-rd):
    cases: JSON file, a list of {"id", "gds", "ref_gds"}
    result_file: JSON file to write, per case id {"layer/datatype": XOR area
        in um²}

The layouts are flattened and aligned on the centers of their bounding
boxes. Text shapes are ignored.
"""

import json

import pya


def regions(layout):
    top = layout.top_cells()[0]
    result = {}
    for li in layout.layer_indexes():
        info = layout.get_info(li)
        region = pya.Region(top.begin_shapes_rec(li))
        if not region.is_empty():
            key = f"{info.layer}/{info.datatype}"
            result[key] = (result.get(key, pya.Region()) + region).merged()
    return result


def bbox_center(regions):
    box = pya.Box()
    for region in regions.values():
        box += region.bbox()
    return box.center()


result = {}
for case in json.load(open(cases)):
    pdk_layout = pya.Layout()
    pdk_layout.read(case["ref_gds"])

    ordec_layout = pya.Layout()
    ordec_layout.read(case["gds"])

    a, b = regions(ordec_layout), regions(pdk_layout)
    ca, cb = bbox_center(a), bbox_center(b)
    shift = pya.Vector(cb.x - ca.x, cb.y - ca.y)
    diffs = {}
    for key in set(a) | set(b):
        xor = a.get(key, pya.Region()).moved(shift) ^ b.get(key, pya.Region())
        if not xor.is_empty():
            diffs[key] = xor.area() * 1e-6
    result[case["id"]] = diffs

json.dump(result, open(result_file, "w"), indent=1)
