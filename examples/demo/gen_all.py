# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import ordec.importer
from top import *

# For time measurement

SimHierarchy.from_schematic(Vco().schematic)
Top().schematic
extlib['counter'].schematic

VcoRing().layout
