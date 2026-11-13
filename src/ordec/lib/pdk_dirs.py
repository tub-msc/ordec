# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# PDK directories used when the respective ORDEC_PDK_* environment variable is
# unset. The Nix build (support/nix/python.nix) replaces the None values with
# store paths, so that any Python importing the Nix-built ordec finds the PDKs.
sky130a = None
sky130b = None
ihp_sg13g2 = None
