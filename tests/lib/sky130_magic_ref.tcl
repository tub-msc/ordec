# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# Magic batch script (sky130.run_magic): write the PDK's generated cells
# (sky130A.tcl) to GDS.
#
# Script variables:
#     cases: flat list of id, device, parameters. Writes <id>.gds to the
#         current directory.

foreach {id device params} $cases {
    load case$id -silent
    box 0 0 0 0
    if {[string match *_draw $device]} {
        # A command drawing over a box, params its width and height in um.
        lassign $params w h
        box 0um 0um ${w}um ${h}um
        sky130::$device
    } else {
        magic::gencell sky130::$device g$id {*}$params
    }
    select top cell
    gds write $id.gds
}
