# xORDB

xORDB (aXellerated ORDB) - Rust-accelerated backend for ORDB (ORDeC's graph database).

## Overview

This crate provides high-performance implementations of ORDB's core data
structures using Rust's `imbl` crate for persistent immutable collections.
It is an **optional** dependency - ORDeC works perfectly fine with the pure
Python implementation when this crate is not installed.

## Building

### Development (editable install)

```bash
cd xordb
pip install maturin
maturin develop
```

### Release build

```bash
cd xordb
maturin build --release
pip install target/wheels/xordb-*.whl
```

## Usage

The module is automatically used by `ordec.core.ordb` when available:

```python
# Check which backend is active
import xordb
print(xordb.is_rust_backend())  # True
print(xordb.version())          # "0.1.0"
```

## Architecture

- `MutableStore` / `FrozenStore`: Rust replacements for pyrsistent-based storage
- `AttrValue`: Efficient representation of node attribute values
- `IndexKey` / `IndexValue`: Index structures for fast queries
- Schema registry: Python Node classes register their schema at import time

## Testing

Run the ORDeC test suite with the Rust backend:

```bash
# Build and install
cd xordb && maturin develop && cd ..

# Run tests (will use Rust backend if available)
pytest tests/test_ordb.py
```
