// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

//! Attribute value representation.
//!
//! ORDB nodes store heterogeneous attribute values. This module defines
//! how these values are represented in Rust for efficient storage and
//! indexing.

use pyo3::prelude::*;
use std::hash::{Hash, Hasher};
use std::sync::Arc;

/// Represents a single attribute value in a node tuple.
///
/// Most attribute values are stored as opaque Python objects, but common
/// types (integers, strings, None) are stored natively for efficiency.
#[derive(Debug)]
pub enum AttrValue {
    /// None/null value
    None,

    /// Integer value (used for nids in LocalRef, and int attributes)
    Int(i64),

    /// String value (common for labels, names, etc.)
    String(Arc<str>),

    /// Arbitrary Python object (Vec2R, Cell, PinType, etc.)
    /// Uses PyObject for thread-safe reference counting.
    PyObject(PyObject),
}

impl Clone for AttrValue {
    fn clone(&self) -> Self {
        match self {
            AttrValue::None => AttrValue::None,
            AttrValue::Int(i) => AttrValue::Int(*i),
            AttrValue::String(s) => AttrValue::String(s.clone()),
            AttrValue::PyObject(obj) => {
                Python::with_gil(|py| AttrValue::PyObject(obj.clone_ref(py)))
            }
        }
    }
}

impl AttrValue {
    /// Create an AttrValue from a Python object.
    pub fn from_py(obj: &Bound<'_, PyAny>) -> PyResult<Self> {
        // Check for None first
        if obj.is_none() {
            return Ok(AttrValue::None);
        }

        // Try to extract as native types for efficiency
        if let Ok(i) = obj.extract::<i64>() {
            return Ok(AttrValue::Int(i));
        }

        if let Ok(s) = obj.extract::<String>() {
            return Ok(AttrValue::String(Arc::from(s)));
        }

        // Fall back to storing as opaque Python object
        Ok(AttrValue::PyObject(obj.clone().unbind()))
    }

    /// Convert back to a Python object.
    pub fn to_py(&self, py: Python<'_>) -> PyObject {
        match self {
            AttrValue::None => py.None(),
            AttrValue::Int(i) => i.to_object(py),
            AttrValue::String(s) => s.as_ref().to_object(py),
            AttrValue::PyObject(obj) => obj.clone_ref(py),
        }
    }

    /// Check if this is a None value.
    pub fn is_none(&self) -> bool {
        matches!(self, AttrValue::None)
    }

    /// Try to get as an integer (for nid lookups).
    pub fn as_int(&self) -> Option<i64> {
        match self {
            AttrValue::Int(i) => Some(*i),
            _ => None,
        }
    }

    /// Try to get as a u32 nid.
    pub fn as_nid(&self) -> Option<u32> {
        self.as_int().and_then(|i| u32::try_from(i).ok())
    }
}

// Implement PartialEq for AttrValue
impl PartialEq for AttrValue {
    fn eq(&self, other: &Self) -> bool {
        match (self, other) {
            (AttrValue::None, AttrValue::None) => true,
            (AttrValue::Int(a), AttrValue::Int(b)) => a == b,
            (AttrValue::String(a), AttrValue::String(b)) => a == b,
            (AttrValue::PyObject(a), AttrValue::PyObject(b)) => {
                // Compare Python objects by calling Python's __eq__
                Python::with_gil(|py| {
                    a.bind(py)
                        .eq(b.bind(py))
                        .unwrap_or(false)
                })
            }
            _ => false,
        }
    }
}

impl Eq for AttrValue {}

// Implement Hash for AttrValue
impl Hash for AttrValue {
    fn hash<H: Hasher>(&self, state: &mut H) {
        // Discriminant first for type differentiation
        std::mem::discriminant(self).hash(state);

        match self {
            AttrValue::None => {}
            AttrValue::Int(i) => i.hash(state),
            AttrValue::String(s) => s.hash(state),
            AttrValue::PyObject(obj) => {
                // Use Python's hash function
                Python::with_gil(|py| {
                    if let Ok(h) = obj.bind(py).hash() {
                        h.hash(state);
                    } else {
                        // Unhashable objects get hashed by pointer
                        // (this matches pyrsistent behavior for unhashable items)
                        std::ptr::hash(obj.as_ptr(), state);
                    }
                });
            }
        }
    }
}

/// A node tuple stored in the subgraph.
///
/// This is a thin wrapper around a vector of attribute values, tagged
/// with the node type ID for schema lookups.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct RawNodeTuple {
    /// Node type identifier (maps to Python Node subclass)
    pub ntype_id: u64,

    /// Attribute values in schema-defined order
    pub attrs: Vec<AttrValue>,
}

impl RawNodeTuple {
    /// Create a new node tuple.
    pub fn new(ntype_id: u64, attrs: Vec<AttrValue>) -> Self {
        Self { ntype_id, attrs }
    }

    /// Get an attribute by index.
    pub fn get(&self, index: usize) -> Option<&AttrValue> {
        self.attrs.get(index)
    }

    /// Create a new tuple with one attribute changed.
    pub fn with_attr(&self, index: usize, value: AttrValue) -> Self {
        let mut attrs = self.attrs.clone();
        if index < attrs.len() {
            attrs[index] = value;
        }
        Self {
            ntype_id: self.ntype_id,
            attrs,
        }
    }
}
