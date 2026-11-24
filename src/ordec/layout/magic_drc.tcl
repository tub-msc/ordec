# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# Magic batch script (ordec.layout.magic.run): full DRC of a GDS file.
#
# Script variables:
#     gds: GDS file to read
#     top: name of its top cell
#     report: file to write, with one line per error box of each cell of the
#         hierarchy: the cell name, the rule description and llx lly urx ury
#         in um, separated by tabs. Magic checks each cell flat together with
#         its subcells, in the coordinates of the cell.

crashbackups stop
drc euclidean on
drc style drc(full)
# drc listall why checks on demand, without the background checker.
drc off
gds read $gds
set scale [cif scale out]
set f [open $report w]
set cells [list $top]
for {set i 0} {$i < [llength $cells]} {incr i} {
    set cell [lindex $cells $i]
    foreach child [cellname list children $cell] {
        if {$child ni $cells} {lappend cells $child}
    }
    load $cell
    select top cell
    foreach {why boxes} [drc listall why] {
        foreach box $boxes {
            puts $f "$cell\t$why\t[lmap v $box {expr {$scale * $v}}]"
        }
    }
}
close $f
