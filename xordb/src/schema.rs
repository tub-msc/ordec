// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

//! Schema registry for node types.
//!
//! Python Node classes register their schema here at import time,
//! allowing Rust to understand the structure for indexing and
//! constraint checking.

use once_cell::sync::Lazy;
use pyo3::prelude::*;
use std::collections::HashMap;
use std::sync::RwLock;

/// Global schema registry, populated at Python import time.
pub static SCHEMA_REGISTRY: Lazy<RwLock<SchemaRegistry>> =
    Lazy::new(|| RwLock::new(SchemaRegistry::new()));

/// Registry of all known node type schemas.
#[derive(Debug, Default)]
pub struct SchemaRegistry {
    /// Schemas indexed by ntype_id
    schemas: HashMap<u64, NTypeSchema>,
    /// Name to ntype_id mapping for lookup by name
    name_to_id: HashMap<String, u64>,
}

impl SchemaRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    /// Register a new node type schema.
    pub fn register(&mut self, schema: NTypeSchema) {
        self.name_to_id.insert(schema.name.clone(), schema.ntype_id);
        self.schemas.insert(schema.ntype_id, schema);
    }

    /// Look up schema by ntype_id.
    pub fn get(&self, ntype_id: u64) -> Option<&NTypeSchema> {
        self.schemas.get(&ntype_id)
    }

    /// Look up schema by name.
    pub fn get_by_name(&self, name: &str) -> Option<&NTypeSchema> {
        self.name_to_id.get(name).and_then(|id| self.schemas.get(id))
    }

    /// Get ntype_id by name.
    pub fn get_id_by_name(&self, name: &str) -> Option<u64> {
        self.name_to_id.get(name).copied()
    }

    /// Get number of registered schemas.
    pub fn len(&self) -> usize {
        self.schemas.len()
    }

    /// Check if registry is empty.
    pub fn is_empty(&self) -> bool {
        self.schemas.is_empty()
    }

    /// Get all registered type names.
    pub fn type_names(&self) -> Vec<&str> {
        self.name_to_id.keys().map(|s| s.as_str()).collect()
    }
}

/// Schema definition for a Node type.
#[derive(Debug, Clone)]
pub struct NTypeSchema {
    /// Unique identifier for this node type (typically id(cls) from Python)
    pub ntype_id: u64,

    /// Human-readable name (e.g., "Pin", "Net", "SchemInstance")
    pub name: String,

    /// Number of attributes
    pub attr_count: usize,

    /// Attribute definitions in order
    pub attrs: Vec<AttrSchema>,

    /// Index definitions
    pub indexes: Vec<IndexSchema>,

    /// Indices of attributes that are LocalRefs (for integrity checking)
    pub localref_indices: Vec<usize>,
}

/// Schema for a single attribute.
#[derive(Debug, Clone)]
pub struct AttrSchema {
    /// Attribute name
    pub name: String,

    /// Attribute kind (determines storage strategy)
    pub kind: AttrKind,

    /// Position in the attribute vector
    pub index: usize,

    /// Whether the attribute is optional (can be None)
    pub optional: bool,
}

/// Kind of attribute, determining storage and indexing behavior.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AttrKind {
    /// Simple integer attribute
    Int,

    /// String attribute
    String,

    /// LocalRef - stores nid as integer
    LocalRef,

    /// SubgraphRef - stores reference to another subgraph
    SubgraphRef,

    /// ExternalRef - stores nid referencing node in another subgraph
    ExternalRef,

    /// Arbitrary Python object
    PyObject,
}

/// Schema for an index.
#[derive(Debug, Clone)]
pub struct IndexSchema {
    /// Unique identifier for this index
    pub index_id: u64,

    /// Kind of index
    pub kind: IndexKind,

    /// Attribute indices that form the index key
    pub attr_indices: Vec<usize>,

    /// Whether this is a unique constraint
    pub unique: bool,

    /// Sort key specification (if any)
    pub sortkey: Option<SortKeySpec>,
}

/// Kind of index.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IndexKind {
    /// Simple single-attribute index
    Simple,

    /// Combined multi-attribute index
    Combined,

    /// Node type index (all nodes by type)
    NType,

    /// LocalRef index (for integrity checking)
    LocalRef,

    /// NPath index (for path uniqueness)
    NPath,
}

/// Specification for index sorting.
#[derive(Debug, Clone)]
pub enum SortKeySpec {
    /// Sort by nid (default)
    ByNid,

    /// Sort by a specific attribute's value
    ByAttr { attr_index: usize },
}

// Python interface functions

/// Register a node type schema from Python.
#[pyfunction]
#[pyo3(signature = (ntype_id, name, attrs, indexes, localref_indices))]
pub fn register_ntype(
    ntype_id: u64,
    name: String,
    attrs: Vec<(String, String, usize, bool)>, // (name, kind, index, optional)
    indexes: Vec<(u64, String, Vec<usize>, bool, Option<usize>)>, // (id, kind, attr_indices, unique, sortkey_attr)
    localref_indices: Vec<usize>,
) -> PyResult<()> {
    let attr_schemas: Vec<AttrSchema> = attrs
        .into_iter()
        .map(|(name, kind_str, index, optional)| {
            let kind = match kind_str.as_str() {
                "int" => AttrKind::Int,
                "str" => AttrKind::String,
                "localref" => AttrKind::LocalRef,
                "subgraphref" => AttrKind::SubgraphRef,
                "externalref" => AttrKind::ExternalRef,
                _ => AttrKind::PyObject,
            };
            AttrSchema {
                name,
                kind,
                index,
                optional,
            }
        })
        .collect();

    let index_schemas: Vec<IndexSchema> = indexes
        .into_iter()
        .map(|(index_id, kind_str, attr_indices, unique, sortkey_attr)| {
            let kind = match kind_str.as_str() {
                "simple" => IndexKind::Simple,
                "combined" => IndexKind::Combined,
                "ntype" => IndexKind::NType,
                "localref" => IndexKind::LocalRef,
                "npath" => IndexKind::NPath,
                _ => IndexKind::Simple,
            };
            let sortkey = sortkey_attr.map(|idx| SortKeySpec::ByAttr { attr_index: idx });
            IndexSchema {
                index_id,
                kind,
                attr_indices,
                unique,
                sortkey,
            }
        })
        .collect();

    let schema = NTypeSchema {
        ntype_id,
        name,
        attr_count: attr_schemas.len(),
        attrs: attr_schemas,
        indexes: index_schemas,
        localref_indices,
    };

    let mut registry = SCHEMA_REGISTRY
        .write()
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;
    registry.register(schema);

    Ok(())
}

/// Get information about registered schemas (for debugging).
#[pyfunction]
pub fn get_schema_info() -> PyResult<Vec<(u64, String, usize)>> {
    let registry = SCHEMA_REGISTRY
        .read()
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

    Ok(registry
        .schemas
        .values()
        .map(|s| (s.ntype_id, s.name.clone(), s.attr_count))
        .collect())
}

/// Get ntype_id for a type name.
#[pyfunction]
pub fn get_ntype_id(name: &str) -> PyResult<Option<u64>> {
    let registry = SCHEMA_REGISTRY
        .read()
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

    Ok(registry.get_id_by_name(name))
}

/// Get detailed schema for a type by name.
#[pyfunction]
pub fn get_schema(name: &str) -> PyResult<Option<(u64, String, Vec<(String, String, usize, bool)>)>> {
    let registry = SCHEMA_REGISTRY
        .read()
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

    Ok(registry.get_by_name(name).map(|s| {
        let attrs: Vec<(String, String, usize, bool)> = s
            .attrs
            .iter()
            .map(|a| {
                let kind_str = match a.kind {
                    AttrKind::Int => "int",
                    AttrKind::String => "str",
                    AttrKind::LocalRef => "localref",
                    AttrKind::SubgraphRef => "subgraphref",
                    AttrKind::ExternalRef => "externalref",
                    AttrKind::PyObject => "pyobject",
                };
                (a.name.clone(), kind_str.to_string(), a.index, a.optional)
            })
            .collect();
        (s.ntype_id, s.name.clone(), attrs)
    }))
}

/// Get list of all registered type names.
#[pyfunction]
pub fn get_type_names() -> PyResult<Vec<String>> {
    let registry = SCHEMA_REGISTRY
        .read()
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

    Ok(registry.type_names().into_iter().map(|s| s.to_string()).collect())
}

/// Access the global schema registry (internal use).
pub fn with_registry<F, R>(f: F) -> R
where
    F: FnOnce(&SchemaRegistry) -> R,
{
    let registry = SCHEMA_REGISTRY.read().expect("Schema registry poisoned");
    f(&registry)
}
