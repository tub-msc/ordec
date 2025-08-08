# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from importlib.metadata import version, PackageNotFoundError

try:
    version = version("ordec")
except PackageNotFoundError:
    version = 'unknown'
