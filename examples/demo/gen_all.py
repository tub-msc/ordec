# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import ordec.importer
from top import *

# Run this module to find out how long it takes to generate the following views:

SimHierarchy.from_schematic(Vco().schematic)
Top().schematic
extlib['counter'].schematic
VcoRing().layout
