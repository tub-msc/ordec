# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Bridge to the Zig implementation of ORDeC's core (zig/).

Subgraphs are serialized to the canonical CBOR wire format shared with the
Zig implementation (see zig/src/serialize.zig and docs/dev/zigbridge.rst) and
passed into the libordec_zig.so shared library for compute-heavy work.
"""

from .wire import (
    content_hash, encode_transfer, collect_bundle, decode_transfer,
    decode_bundle, WireError, UnsupportedNode, UnsupportedAttr,
)
from .lib import ZigBridgeError, available, library_path
from .placer import place
