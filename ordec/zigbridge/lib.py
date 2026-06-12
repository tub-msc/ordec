# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
ctypes loader and call wrapper for libordec_zig.so (built from zig/ via
``zig build``; see zig/src/capi.zig for the C ABI and envelope formats).
"""

import ctypes
import functools
import os
from pathlib import Path

import cbor2

ABI_VERSION = 1


class ZigBridgeError(Exception):
    """Error reported by the Zig library (code + message from the error
    envelope; codes: 1 bad envelope, 2 blob decode error, 3 domain error,
    4 out of memory, 5 internal)."""

    def __init__(self, code, message):
        super().__init__(f"libordec_zig error {code}: {message}")
        self.code = code
        self.message = message


def library_path() -> Path:
    """$ORDEC_ZIG_LIB if set, else the in-repo build output."""
    env = os.environ.get('ORDEC_ZIG_LIB')
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / 'zig/zig-out/lib/libordec_zig.so'


@functools.cache
def _load():
    lib = ctypes.CDLL(str(library_path()))
    lib.ordec_abi_version.restype = ctypes.c_uint32
    lib.ordec_abi_version.argtypes = ()
    argtypes = (
        ctypes.c_char_p, ctypes.c_size_t,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
        ctypes.POINTER(ctypes.c_size_t),
    )
    for name in ('ordec_echo', 'ordec_place'):
        fn = getattr(lib, name)
        fn.restype = ctypes.c_int32
        fn.argtypes = argtypes
    lib.ordec_free.restype = None
    lib.ordec_free.argtypes = (ctypes.POINTER(ctypes.c_ubyte), ctypes.c_size_t)
    abi = lib.ordec_abi_version()
    if abi != ABI_VERSION:
        raise ZigBridgeError(0, f"ABI version mismatch: library has {abi}, "
                                f"this bridge expects {ABI_VERSION}")
    return lib


def available() -> bool:
    """Whether the shared library exists and has a compatible ABI."""
    try:
        _load()
        return True
    except (OSError, ZigBridgeError):
        return False


def call(func: str, request: bytes) -> bytes:
    """Invoke an exported function with a request envelope; returns the
    response bytes or raises ZigBridgeError from the error envelope."""
    lib = _load()
    out_ptr = ctypes.POINTER(ctypes.c_ubyte)()
    out_len = ctypes.c_size_t(0)
    rc = getattr(lib, func)(
        request, len(request), ctypes.byref(out_ptr), ctypes.byref(out_len),
    )
    if not out_ptr or out_len.value == 0:
        if rc == 0:
            raise ZigBridgeError(5, "empty success response")
        raise ZigBridgeError(rc, "no detail (allocation failed in library)")
    try:
        data = ctypes.string_at(out_ptr, out_len.value)
    finally:
        lib.ordec_free(out_ptr, out_len.value)
    if rc == 0:
        return data
    try:
        code, message = cbor2.loads(data)
    except Exception:
        code, message = rc, f"undecodable error envelope: {data!r}"
    raise ZigBridgeError(code, message)
