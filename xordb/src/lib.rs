// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

//! xORDB - aXellerated ORDB backend in Rust.
//!
//! This module provides high-performance implementations of ORDB's core
//! data structures using Rust's `imbl` crate for persistent immutable
//! collections.

use pyo3::prelude::*;

mod attr;
mod index;
mod schema;
mod store;

pub use attr::AttrValue;
pub use index::{IndexKey, IndexValue};
pub use schema::{AttrKind, AttrSchema, IndexKind, IndexSchema, NTypeSchema, SchemaRegistry};
pub use store::{FrozenSubgraph, MutableSubgraph};

/// Check if Rust backend is available (always true when this module loads).
#[pyfunction]
fn is_rust_backend() -> bool {
    true
}

/// Get version information.
#[pyfunction]
fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

/// Python module definition.
#[pymodule]
fn xordb(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Module-level functions
    m.add_function(wrap_pyfunction!(is_rust_backend, m)?)?;
    m.add_function(wrap_pyfunction!(version, m)?)?;

    // Schema registration and lookup
    m.add_function(wrap_pyfunction!(schema::register_ntype, m)?)?;
    m.add_function(wrap_pyfunction!(schema::get_schema_info, m)?)?;
    m.add_function(wrap_pyfunction!(schema::get_ntype_id, m)?)?;
    m.add_function(wrap_pyfunction!(schema::get_schema, m)?)?;
    m.add_function(wrap_pyfunction!(schema::get_type_names, m)?)?;

    // Core classes
    m.add_class::<MutableSubgraph>()?;
    m.add_class::<FrozenSubgraph>()?;

    Ok(())
}
