// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

//! Core subgraph implementation for ORDB.
//!
//! This module provides `MutableSubgraph` and `FrozenSubgraph`, which are
//! Rust-accelerated replacements for the pyrsistent-based subgraph
//! implementation in Python.

use crate::attr::{AttrValue, RawNodeTuple};
use crate::index::{
    compute_index_key, index_insert_nid, index_remove_nid, IndexKey, IndexValue,
};
use crate::schema::{with_registry, IndexKind};
use imbl::HashMap;
use pyo3::exceptions::{PyKeyError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyTuple};

/// Internal store data shared between mutable and frozen variants.
#[derive(Clone, Debug, PartialEq)]
struct StoreData {
    /// Node storage: nid -> RawNodeTuple
    nodes: HashMap<u32, RawNodeTuple>,

    /// Index storage: IndexKey -> IndexValue
    index: HashMap<IndexKey, IndexValue>,

    /// Next available nid for allocation
    nid_alloc_start: u32,
}

impl Default for StoreData {
    fn default() -> Self {
        Self {
            nodes: HashMap::new(),
            index: HashMap::new(),
            nid_alloc_start: 1, // 0 is reserved for root
        }
    }
}

impl StoreData {
    /// Add indexes for a node.
    fn index_add(&mut self, node: &RawNodeTuple, nid: u32) {
        // Add to NType index (always present)
        let ntype_key = IndexKey::NType {
            ntype_id: node.ntype_id,
        };
        let ntype_value = self
            .index
            .get(&ntype_key)
            .cloned()
            .unwrap_or_else(IndexValue::empty_nids);
        let new_ntype_value = index_insert_nid(&ntype_value, nid, &None, node);
        self.index.insert(ntype_key, new_ntype_value);

        // Add to schema-defined indexes
        with_registry(|registry| {
            if let Some(schema) = registry.get(node.ntype_id) {
                for idx_schema in &schema.indexes {
                    if let Some(key) = compute_index_key(idx_schema, node, nid) {
                        let current = self
                            .index
                            .get(&key)
                            .cloned()
                            .unwrap_or_else(|| match idx_schema.kind {
                                IndexKind::LocalRef => IndexValue::empty_backrefs(),
                                _ => IndexValue::empty_nids(),
                            });
                        let new_value = index_insert_nid(&current, nid, &idx_schema.sortkey, node);
                        self.index.insert(key, new_value);
                    }
                }
            }
        });
    }

    /// Remove indexes for a node.
    fn index_remove(&mut self, node: &RawNodeTuple, nid: u32) {
        // Remove from NType index
        let ntype_key = IndexKey::NType {
            ntype_id: node.ntype_id,
        };
        if let Some(value) = self.index.get(&ntype_key) {
            let new_value = index_remove_nid(value, nid);
            if new_value.is_empty() {
                self.index.remove(&ntype_key);
            } else {
                self.index.insert(ntype_key, new_value);
            }
        }

        // Remove from schema-defined indexes
        with_registry(|registry| {
            if let Some(schema) = registry.get(node.ntype_id) {
                for idx_schema in &schema.indexes {
                    if let Some(key) = compute_index_key(idx_schema, node, nid) {
                        if let Some(value) = self.index.get(&key) {
                            let new_value = index_remove_nid(value, nid);
                            if new_value.is_empty() {
                                self.index.remove(&key);
                            } else {
                                self.index.insert(key, new_value);
                            }
                        }
                    }
                }
            }
        });
    }
}

/// Mutable subgraph store.
///
/// This is the Rust equivalent of Python's MutableSubgraph storage layer.
#[pyclass]
#[derive(Clone)]
pub struct MutableSubgraph {
    data: StoreData,
}

#[pymethods]
impl MutableSubgraph {
    /// Create a new empty mutable store.
    #[new]
    pub fn new() -> Self {
        Self {
            data: StoreData::default(),
        }
    }

    /// Get the number of nodes in the store.
    pub fn node_count(&self) -> usize {
        self.data.nodes.len()
    }

    /// Check if a nid exists in the store.
    pub fn contains_nid(&self, nid: u32) -> bool {
        self.data.nodes.contains_key(&nid)
    }

    /// Get a node by nid, returning as Python tuple.
    pub fn get_node(&self, py: Python<'_>, nid: u32) -> PyResult<Option<PyObject>> {
        match self.data.nodes.get(&nid) {
            Some(node) => {
                let tuple = self.node_to_py(py, node)?;
                Ok(Some(tuple))
            }
            None => Ok(None),
        }
    }

    /// Get the ntype_id for a node.
    pub fn get_ntype_id(&self, nid: u32) -> PyResult<Option<u64>> {
        Ok(self.data.nodes.get(&nid).map(|n| n.ntype_id))
    }

    /// Set a node in the store.
    ///
    /// Args:
    ///     nid: Node ID
    ///     ntype_id: Node type identifier
    ///     attrs: Tuple of attribute values
    #[pyo3(signature = (nid, ntype_id, attrs))]
    pub fn set_node(
        &mut self,
        _py: Python<'_>,
        nid: u32,
        ntype_id: u64,
        attrs: &Bound<'_, PyTuple>,
    ) -> PyResult<()> {
        // Convert Python tuple to RawNodeTuple
        let attr_values: Vec<AttrValue> = attrs
            .iter()
            .map(|item| AttrValue::from_py(&item))
            .collect::<PyResult<Vec<_>>>()?;

        let node = RawNodeTuple::new(ntype_id, attr_values);

        // Remove old node's indexes if replacing (clone to avoid borrow issues)
        if let Some(old_node) = self.data.nodes.get(&nid).cloned() {
            self.data.index_remove(&old_node, nid);
        }

        // Add new node and indexes
        self.data.index_add(&node, nid);
        self.data.nodes.insert(nid, node);

        // Update nid_alloc_start if needed
        if nid >= self.data.nid_alloc_start {
            self.data.nid_alloc_start = nid + 1;
        }

        Ok(())
    }

    /// Create a node by type name with auto-allocated nid.
    ///
    /// This allows creating nodes purely in Rust without Python NodeTuple objects.
    ///
    /// Args:
    ///     type_name: Name of the node type (e.g., "NPath", "Pin")
    ///     attrs: Tuple of attribute values in schema order
    ///
    /// Returns:
    ///     The allocated nid for the new node
    #[pyo3(signature = (type_name, attrs))]
    pub fn create_node(
        &mut self,
        _py: Python<'_>,
        type_name: &str,
        attrs: &Bound<'_, PyTuple>,
    ) -> PyResult<u32> {
        // Look up schema by name
        let ntype_id = with_registry(|registry| registry.get_id_by_name(type_name))
            .ok_or_else(|| {
                PyValueError::new_err(format!("Unknown node type: {}", type_name))
            })?;

        // Allocate nid
        let nid = self.data.nid_alloc_start;
        self.data.nid_alloc_start = nid + 1;

        // Convert Python tuple to RawNodeTuple
        let attr_values: Vec<AttrValue> = attrs
            .iter()
            .map(|item| AttrValue::from_py(&item))
            .collect::<PyResult<Vec<_>>>()?;

        let node = RawNodeTuple::new(ntype_id, attr_values);

        // Add node and indexes
        self.data.index_add(&node, nid);
        self.data.nodes.insert(nid, node);

        Ok(nid)
    }

    /// Create a node by type name at a specific nid.
    ///
    /// This allows creating nodes at specific positions (e.g., nid=0 for root).
    #[pyo3(signature = (nid, type_name, attrs))]
    pub fn create_node_at(
        &mut self,
        _py: Python<'_>,
        nid: u32,
        type_name: &str,
        attrs: &Bound<'_, PyTuple>,
    ) -> PyResult<()> {
        // Look up schema by name
        let ntype_id = with_registry(|registry| registry.get_id_by_name(type_name))
            .ok_or_else(|| {
                PyValueError::new_err(format!("Unknown node type: {}", type_name))
            })?;

        // Convert Python tuple to RawNodeTuple
        let attr_values: Vec<AttrValue> = attrs
            .iter()
            .map(|item| AttrValue::from_py(&item))
            .collect::<PyResult<Vec<_>>>()?;

        let node = RawNodeTuple::new(ntype_id, attr_values);

        // Remove old node's indexes if replacing
        if let Some(old_node) = self.data.nodes.get(&nid).cloned() {
            self.data.index_remove(&old_node, nid);
        }

        // Add new node and indexes
        self.data.index_add(&node, nid);
        self.data.nodes.insert(nid, node);

        // Update nid_alloc_start if needed
        if nid >= self.data.nid_alloc_start {
            self.data.nid_alloc_start = nid + 1;
        }

        Ok(())
    }

    /// Remove a node from the store.
    pub fn remove_node(&mut self, nid: u32) -> PyResult<()> {
        if let Some(node) = self.data.nodes.get(&nid).cloned() {
            self.data.index_remove(&node, nid);
            self.data.nodes.remove(&nid);
            Ok(())
        } else {
            Err(PyKeyError::new_err(format!("nid {} not found", nid)))
        }
    }

    /// Get the current nid allocation start.
    pub fn nid_alloc_start(&self) -> u32 {
        self.data.nid_alloc_start
    }

    /// Set the nid allocation start.
    pub fn set_nid_alloc_start(&mut self, start: u32) {
        self.data.nid_alloc_start = start;
    }

    /// Query all nids matching an index key.
    ///
    /// Args:
    ///     index_id: The index identifier
    ///     key_type: "ntype", "simple", or "combined"
    ///     key_value: The key value (ntype_id for ntype, attr value for simple,
    ///                tuple of attr values for combined)
    #[pyo3(signature = (index_id, key_type, key_value))]
    pub fn index_query(
        &self,
        py: Python<'_>,
        index_id: u64,
        key_type: &str,
        key_value: &Bound<'_, PyAny>,
    ) -> PyResult<Vec<u32>> {
        let key = self.build_index_key(py, index_id, key_type, key_value)?;

        match self.data.index.get(&key) {
            Some(IndexValue::Nids(nids)) => Ok(nids.iter().copied().collect()),
            Some(IndexValue::LocalRefBackrefs(_)) => {
                // Return empty for backref queries through this interface
                Ok(vec![])
            }
            None => Ok(vec![]),
        }
    }

    /// Check if a nid is referenced by any LocalRef.
    pub fn is_referenced(&self, nid: u32) -> bool {
        // Check all LocalRef indexes for references to this nid
        // This is used for dangling reference detection
        self.data.index.iter().any(|(key, value)| {
            if let IndexKey::LocalRef { referenced_nid, .. } = key {
                if *referenced_nid == nid {
                    return !value.is_empty();
                }
            }
            false
        })
    }

    /// Freeze the store into an immutable FrozenSubgraph.
    pub fn freeze(&self) -> FrozenSubgraph {
        FrozenSubgraph {
            data: self.data.clone(),
        }
    }

    /// Create a copy of this store.
    pub fn copy(&self) -> MutableSubgraph {
        self.clone()
    }

    /// Iterate over all (nid, ntype_id) pairs.
    pub fn iter_nids(&self) -> Vec<(u32, u64)> {
        self.data
            .nodes
            .iter()
            .map(|(nid, node)| (*nid, node.ntype_id))
            .collect()
    }

    /// Get all node data as a dict (for debugging/serialization).
    pub fn to_dict(&self, py: Python<'_>) -> PyResult<PyObject> {
        let dict = PyDict::new_bound(py);
        for (nid, node) in &self.data.nodes {
            let tuple = self.node_to_py(py, node)?;
            dict.set_item(nid, tuple)?;
        }
        Ok(dict.into())
    }
}

impl MutableSubgraph {
    /// Convert RawNodeTuple to Python tuple.
    fn node_to_py(&self, py: Python<'_>, node: &RawNodeTuple) -> PyResult<PyObject> {
        let py_attrs: Vec<PyObject> = node.attrs.iter().map(|a| a.to_py(py)).collect();
        let tuple = PyTuple::new_bound(py, py_attrs);
        // Return as (ntype_id, attrs_tuple) for Python to reconstruct NodeTuple
        let result = PyTuple::new_bound(py, [node.ntype_id.to_object(py), tuple.into()]);
        Ok(result.into())
    }

    /// Build an IndexKey from Python arguments.
    fn build_index_key(
        &self,
        _py: Python<'_>,
        index_id: u64,
        key_type: &str,
        key_value: &Bound<'_, PyAny>,
    ) -> PyResult<IndexKey> {
        match key_type {
            "ntype" => {
                let ntype_id: u64 = key_value.extract()?;
                Ok(IndexKey::NType { ntype_id })
            }
            "simple" => {
                let value = AttrValue::from_py(key_value)?;
                Ok(IndexKey::Simple { index_id, value })
            }
            "combined" => {
                let tuple: &Bound<'_, PyTuple> = key_value.downcast()?;
                let values: Vec<AttrValue> = tuple
                    .iter()
                    .map(|item| AttrValue::from_py(&item))
                    .collect::<PyResult<Vec<_>>>()?;
                Ok(IndexKey::Combined { index_id, values })
            }
            "localref" => {
                let referenced_nid: u32 = key_value.extract()?;
                Ok(IndexKey::LocalRef {
                    index_id,
                    referenced_nid,
                })
            }
            _ => Err(PyValueError::new_err(format!(
                "Unknown key_type: {}",
                key_type
            ))),
        }
    }
}

impl Default for MutableSubgraph {
    fn default() -> Self {
        Self::new()
    }
}

// Pure Rust API (no Python dependency)
impl MutableSubgraph {
    /// Create a node with the given ntype_id and attributes (pure Rust).
    pub fn create_node_rust(&mut self, ntype_id: u64, attrs: Vec<AttrValue>) -> u32 {
        let nid = self.data.nid_alloc_start;
        self.data.nid_alloc_start = nid + 1;

        let node = RawNodeTuple::new(ntype_id, attrs);
        self.data.index_add(&node, nid);
        self.data.nodes.insert(nid, node);

        nid
    }

    /// Create a node at a specific nid (pure Rust).
    pub fn create_node_at_rust(&mut self, nid: u32, ntype_id: u64, attrs: Vec<AttrValue>) {
        let node = RawNodeTuple::new(ntype_id, attrs);

        // Remove old node's indexes if replacing
        if let Some(old_node) = self.data.nodes.get(&nid).cloned() {
            self.data.index_remove(&old_node, nid);
        }

        self.data.index_add(&node, nid);
        self.data.nodes.insert(nid, node);

        if nid >= self.data.nid_alloc_start {
            self.data.nid_alloc_start = nid + 1;
        }
    }

    /// Get a node's raw data (pure Rust).
    pub fn get_node_rust(&self, nid: u32) -> Option<&RawNodeTuple> {
        self.data.nodes.get(&nid)
    }

    /// Query nids by ntype (pure Rust).
    pub fn query_by_ntype(&self, ntype_id: u64) -> Vec<u32> {
        let key = IndexKey::NType { ntype_id };
        match self.data.index.get(&key) {
            Some(IndexValue::Nids(nids)) => nids.iter().copied().collect(),
            _ => vec![],
        }
    }

    /// Remove a node (pure Rust).
    pub fn remove_node_rust(&mut self, nid: u32) -> Option<RawNodeTuple> {
        if let Some(node) = self.data.nodes.get(&nid).cloned() {
            self.data.index_remove(&node, nid);
            self.data.nodes.remove(&nid);
            Some(node)
        } else {
            None
        }
    }
}

// Pure Rust API for FrozenSubgraph
impl FrozenSubgraph {
    /// Get a node's raw data (pure Rust).
    pub fn get_node_rust(&self, nid: u32) -> Option<&RawNodeTuple> {
        self.data.nodes.get(&nid)
    }

    /// Query nids by ntype (pure Rust).
    pub fn query_by_ntype(&self, ntype_id: u64) -> Vec<u32> {
        let key = IndexKey::NType { ntype_id };
        match self.data.index.get(&key) {
            Some(IndexValue::Nids(nids)) => nids.iter().copied().collect(),
            _ => vec![],
        }
    }
}

/// Immutable frozen subgraph store.
///
/// This is the Rust equivalent of Python's FrozenSubgraph storage layer.
/// FrozenSubgraph instances can be safely shared and have value equality semantics.
#[pyclass]
#[derive(Clone, Debug, PartialEq)]
pub struct FrozenSubgraph {
    data: StoreData,
}

#[pymethods]
impl FrozenSubgraph {
    /// Get the number of nodes in the store.
    pub fn node_count(&self) -> usize {
        self.data.nodes.len()
    }

    /// Check if a nid exists in the store.
    pub fn contains_nid(&self, nid: u32) -> bool {
        self.data.nodes.contains_key(&nid)
    }

    /// Get a node by nid, returning as Python tuple.
    pub fn get_node(&self, py: Python<'_>, nid: u32) -> PyResult<Option<PyObject>> {
        match self.data.nodes.get(&nid) {
            Some(node) => {
                let py_attrs: Vec<PyObject> = node.attrs.iter().map(|a| a.to_py(py)).collect();
                let tuple = PyTuple::new_bound(py, py_attrs);
                let result = PyTuple::new_bound(py, [node.ntype_id.to_object(py), tuple.into()]);
                Ok(Some(result.into()))
            }
            None => Ok(None),
        }
    }

    /// Get the ntype_id for a node.
    pub fn get_ntype_id(&self, nid: u32) -> PyResult<Option<u64>> {
        Ok(self.data.nodes.get(&nid).map(|n| n.ntype_id))
    }

    /// Get the current nid allocation start.
    pub fn nid_alloc_start(&self) -> u32 {
        self.data.nid_alloc_start
    }

    /// Query all nids matching an index key.
    #[pyo3(signature = (index_id, key_type, key_value))]
    pub fn index_query(
        &self,
        py: Python<'_>,
        index_id: u64,
        key_type: &str,
        key_value: &Bound<'_, PyAny>,
    ) -> PyResult<Vec<u32>> {
        // Reuse MutableSubgraph's implementation by creating temporary wrapper
        let temp = MutableSubgraph {
            data: self.data.clone(),
        };
        temp.index_query(py, index_id, key_type, key_value)
    }

    /// Thaw into a mutable store.
    pub fn thaw(&self) -> MutableSubgraph {
        MutableSubgraph {
            data: self.data.clone(),
        }
    }

    /// FrozenSubgraph is already frozen, return self.
    pub fn freeze(&self) -> FrozenSubgraph {
        self.clone()
    }

    /// Iterate over all (nid, ntype_id) pairs.
    pub fn iter_nids(&self) -> Vec<(u32, u64)> {
        self.data
            .nodes
            .iter()
            .map(|(nid, node)| (*nid, node.ntype_id))
            .collect()
    }

    /// Hash the store for equality comparison.
    fn __hash__(&self) -> u64 {
        use std::collections::hash_map::DefaultHasher;
        use std::hash::{Hash, Hasher};

        let mut hasher = DefaultHasher::new();

        // Hash nid_alloc_start
        self.data.nid_alloc_start.hash(&mut hasher);

        // Hash nodes in sorted order for deterministic hash
        let mut nids: Vec<_> = self.data.nodes.keys().copied().collect();
        nids.sort();
        for nid in nids {
            nid.hash(&mut hasher);
            if let Some(node) = self.data.nodes.get(&nid) {
                node.hash(&mut hasher);
            }
        }

        hasher.finish()
    }

    /// Check equality with another FrozenSubgraph.
    fn __eq__(&self, other: &FrozenSubgraph) -> bool {
        self.data.nid_alloc_start == other.data.nid_alloc_start
            && self.data.nodes == other.data.nodes
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::schema::{AttrKind, AttrSchema, IndexKind, IndexSchema, NTypeSchema};

    // Test ntype_ids (arbitrary constants for testing)
    const NTYPE_ROOT: u64 = 1000;
    const NTYPE_NPATH: u64 = 1001;
    const NTYPE_NET: u64 = 1002;

    /// Register test schemas in the global registry.
    fn register_test_schemas() {
        use crate::schema::SCHEMA_REGISTRY;

        let mut registry = SCHEMA_REGISTRY.write().unwrap();

        // SubgraphRoot equivalent - no attributes
        if registry.get(NTYPE_ROOT).is_none() {
            registry.register(NTypeSchema {
                ntype_id: NTYPE_ROOT,
                name: "TestRoot".to_string(),
                attr_count: 0,
                attrs: vec![],
                indexes: vec![],
                localref_indices: vec![],
            });
        }

        // NPath equivalent - (parent: LocalRef?, name: str, ref: LocalRef)
        if registry.get(NTYPE_NPATH).is_none() {
            registry.register(NTypeSchema {
                ntype_id: NTYPE_NPATH,
                name: "TestPath".to_string(),
                attr_count: 3,
                attrs: vec![
                    AttrSchema {
                        name: "parent".to_string(),
                        kind: AttrKind::LocalRef,
                        index: 0,
                        optional: true,
                    },
                    AttrSchema {
                        name: "name".to_string(),
                        kind: AttrKind::String,
                        index: 1,
                        optional: false,
                    },
                    AttrSchema {
                        name: "ref".to_string(),
                        kind: AttrKind::LocalRef,
                        index: 2,
                        optional: false,
                    },
                ],
                indexes: vec![],
                localref_indices: vec![0, 2],
            });
        }

        // Net equivalent - simple node with 2 attributes
        if registry.get(NTYPE_NET).is_none() {
            registry.register(NTypeSchema {
                ntype_id: NTYPE_NET,
                name: "TestNet".to_string(),
                attr_count: 2,
                attrs: vec![
                    AttrSchema {
                        name: "label".to_string(),
                        kind: AttrKind::String,
                        index: 0,
                        optional: true,
                    },
                    AttrSchema {
                        name: "width".to_string(),
                        kind: AttrKind::Int,
                        index: 1,
                        optional: true,
                    },
                ],
                indexes: vec![
                    IndexSchema {
                        index_id: 2001,
                        kind: IndexKind::Simple,
                        attr_indices: vec![0],
                        unique: false,
                        sortkey: None,
                    },
                ],
                localref_indices: vec![],
            });
        }
    }

    #[test]
    fn test_create_empty_subgraph() {
        let sg = MutableSubgraph::new();
        assert_eq!(sg.node_count(), 0);
        assert_eq!(sg.nid_alloc_start(), 1);
    }

    #[test]
    fn test_create_node_rust() {
        register_test_schemas();

        let mut sg = MutableSubgraph::new();

        // Create root at nid=0
        sg.create_node_at_rust(0, NTYPE_ROOT, vec![]);
        assert_eq!(sg.node_count(), 1);
        assert!(sg.contains_nid(0));

        // Create a path node
        let nid = sg.create_node_rust(
            NTYPE_NPATH,
            vec![
                AttrValue::None,                        // parent = None
                AttrValue::String("test".into()),       // name = "test"
                AttrValue::Int(0),                      // ref = 0 (root)
            ],
        );

        assert_eq!(sg.node_count(), 2);
        assert!(sg.contains_nid(nid));
        assert_eq!(nid, 1); // First auto-allocated nid
    }

    #[test]
    fn test_get_node_rust() {
        register_test_schemas();

        let mut sg = MutableSubgraph::new();
        sg.create_node_at_rust(0, NTYPE_ROOT, vec![]);

        let nid = sg.create_node_rust(
            NTYPE_NPATH,
            vec![
                AttrValue::None,
                AttrValue::String("mypath".into()),
                AttrValue::Int(0),
            ],
        );

        let node = sg.get_node_rust(nid).expect("Node should exist");
        assert_eq!(node.ntype_id, NTYPE_NPATH);
        assert_eq!(node.attrs.len(), 3);
        assert_eq!(node.attrs[0], AttrValue::None);
        assert_eq!(node.attrs[1], AttrValue::String("mypath".into()));
        assert_eq!(node.attrs[2], AttrValue::Int(0));
    }

    #[test]
    fn test_query_by_ntype() {
        register_test_schemas();

        let mut sg = MutableSubgraph::new();

        // Create root
        sg.create_node_at_rust(0, NTYPE_ROOT, vec![]);

        // Create several path nodes
        let nid1 = sg.create_node_rust(
            NTYPE_NPATH,
            vec![AttrValue::None, AttrValue::String("a".into()), AttrValue::Int(0)],
        );
        let nid2 = sg.create_node_rust(
            NTYPE_NPATH,
            vec![AttrValue::None, AttrValue::String("b".into()), AttrValue::Int(0)],
        );

        // Create a net node
        let nid3 = sg.create_node_rust(
            NTYPE_NET,
            vec![AttrValue::String("vdd".into()), AttrValue::Int(1)],
        );

        // Query by type
        let roots = sg.query_by_ntype(NTYPE_ROOT);
        assert_eq!(roots, vec![0]);

        let mut paths = sg.query_by_ntype(NTYPE_NPATH);
        paths.sort();
        assert_eq!(paths, vec![nid1, nid2]);

        let nets = sg.query_by_ntype(NTYPE_NET);
        assert_eq!(nets, vec![nid3]);

        // Query non-existent type
        let empty = sg.query_by_ntype(9999);
        assert!(empty.is_empty());
    }

    #[test]
    fn test_remove_node_rust() {
        register_test_schemas();

        let mut sg = MutableSubgraph::new();
        sg.create_node_at_rust(0, NTYPE_ROOT, vec![]);

        let nid = sg.create_node_rust(
            NTYPE_NPATH,
            vec![AttrValue::None, AttrValue::String("x".into()), AttrValue::Int(0)],
        );

        assert_eq!(sg.node_count(), 2);

        // Remove the path node
        let removed = sg.remove_node_rust(nid);
        assert!(removed.is_some());
        assert_eq!(sg.node_count(), 1);
        assert!(!sg.contains_nid(nid));

        // Verify it's removed from index
        let paths = sg.query_by_ntype(NTYPE_NPATH);
        assert!(paths.is_empty());

        // Remove non-existent returns None
        assert!(sg.remove_node_rust(999).is_none());
    }

    #[test]
    fn test_freeze_thaw_cycle() {
        register_test_schemas();

        let mut sg = MutableSubgraph::new();
        sg.create_node_at_rust(0, NTYPE_ROOT, vec![]);
        sg.create_node_rust(
            NTYPE_NPATH,
            vec![AttrValue::None, AttrValue::String("frozen".into()), AttrValue::Int(0)],
        );

        // Freeze
        let frozen = sg.freeze();
        assert_eq!(frozen.node_count(), 2);

        // Verify frozen data
        let node = frozen.get_node_rust(1).expect("Node should exist");
        assert_eq!(node.attrs[1], AttrValue::String("frozen".into()));

        // Thaw
        let mut thawed = frozen.thaw();
        assert_eq!(thawed.node_count(), 2);

        // Modify thawed - should not affect frozen
        thawed.create_node_rust(
            NTYPE_NPATH,
            vec![AttrValue::None, AttrValue::String("new".into()), AttrValue::Int(0)],
        );

        assert_eq!(thawed.node_count(), 3);
        assert_eq!(frozen.node_count(), 2); // Unchanged
    }

    #[test]
    fn test_pure_rust_subgraph_hierarchy() {
        //! Build a complete subgraph hierarchy purely in Rust.
        //!
        //! Structure:
        //!   root (nid=0, TestRoot)
        //!   ├── module (nid=1, TestPath)
        //!   │   ├── class_a (nid=2, TestPath)
        //!   │   └── class_b (nid=3, TestPath)
        //!   └── utils (nid=4, TestPath)
        //!       └── helper (nid=5, TestPath)

        register_test_schemas();

        let mut sg = MutableSubgraph::new();

        // Create root
        sg.create_node_at_rust(0, NTYPE_ROOT, vec![]);

        // Top-level paths (parent=None, ref=root)
        let module_nid = sg.create_node_rust(
            NTYPE_NPATH,
            vec![AttrValue::None, AttrValue::String("module".into()), AttrValue::Int(0)],
        );
        let utils_nid = sg.create_node_rust(
            NTYPE_NPATH,
            vec![AttrValue::None, AttrValue::String("utils".into()), AttrValue::Int(0)],
        );

        // Children of module
        let class_a_nid = sg.create_node_rust(
            NTYPE_NPATH,
            vec![
                AttrValue::Int(module_nid as i64),
                AttrValue::String("class_a".into()),
                AttrValue::Int(0),
            ],
        );
        let _class_b_nid = sg.create_node_rust(
            NTYPE_NPATH,
            vec![
                AttrValue::Int(module_nid as i64),
                AttrValue::String("class_b".into()),
                AttrValue::Int(0),
            ],
        );

        // Child of utils
        let helper_nid = sg.create_node_rust(
            NTYPE_NPATH,
            vec![
                AttrValue::Int(utils_nid as i64),
                AttrValue::String("helper".into()),
                AttrValue::Int(0),
            ],
        );

        // Verify structure
        assert_eq!(sg.node_count(), 6);

        // Query by type
        let roots = sg.query_by_ntype(NTYPE_ROOT);
        assert_eq!(roots.len(), 1);

        let paths = sg.query_by_ntype(NTYPE_NPATH);
        assert_eq!(paths.len(), 5);

        // Verify node contents
        let module = sg.get_node_rust(module_nid).unwrap();
        assert_eq!(module.attrs[0], AttrValue::None); // No parent
        assert_eq!(module.attrs[1], AttrValue::String("module".into()));

        let class_a = sg.get_node_rust(class_a_nid).unwrap();
        assert_eq!(class_a.attrs[0], AttrValue::Int(module_nid as i64)); // Parent is module
        assert_eq!(class_a.attrs[1], AttrValue::String("class_a".into()));

        let helper = sg.get_node_rust(helper_nid).unwrap();
        assert_eq!(helper.attrs[0], AttrValue::Int(utils_nid as i64)); // Parent is utils
        assert_eq!(helper.attrs[1], AttrValue::String("helper".into()));

        // Freeze and verify
        let frozen = sg.freeze();
        assert_eq!(frozen.node_count(), 6);
        assert_eq!(frozen.query_by_ntype(NTYPE_NPATH).len(), 5);
    }

    #[test]
    fn test_pure_rust_netlist() {
        //! Build a simple netlist structure purely in Rust.

        register_test_schemas();

        let mut sg = MutableSubgraph::new();

        // Create root
        sg.create_node_at_rust(0, NTYPE_ROOT, vec![]);

        // Create nets
        let vdd_nid = sg.create_node_rust(
            NTYPE_NET,
            vec![AttrValue::String("VDD".into()), AttrValue::Int(1)],
        );
        let _gnd_nid = sg.create_node_rust(
            NTYPE_NET,
            vec![AttrValue::String("GND".into()), AttrValue::Int(1)],
        );
        let sig_nid = sg.create_node_rust(
            NTYPE_NET,
            vec![AttrValue::String("signal".into()), AttrValue::Int(8)],
        );

        assert_eq!(sg.node_count(), 4);

        // Query nets
        let nets = sg.query_by_ntype(NTYPE_NET);
        assert_eq!(nets.len(), 3);

        // Verify net data
        let vdd = sg.get_node_rust(vdd_nid).unwrap();
        assert_eq!(vdd.attrs[0], AttrValue::String("VDD".into()));
        assert_eq!(vdd.attrs[1], AttrValue::Int(1));

        let sig = sg.get_node_rust(sig_nid).unwrap();
        assert_eq!(sig.attrs[0], AttrValue::String("signal".into()));
        assert_eq!(sig.attrs[1], AttrValue::Int(8));
    }

    #[test]
    fn test_nid_allocation() {
        register_test_schemas();

        let mut sg = MutableSubgraph::new();
        assert_eq!(sg.nid_alloc_start(), 1);

        // Create at nid=0 doesn't affect alloc start
        sg.create_node_at_rust(0, NTYPE_ROOT, vec![]);
        assert_eq!(sg.nid_alloc_start(), 1);

        // Auto-allocate
        let nid1 = sg.create_node_rust(NTYPE_NET, vec![AttrValue::None, AttrValue::None]);
        assert_eq!(nid1, 1);
        assert_eq!(sg.nid_alloc_start(), 2);

        let nid2 = sg.create_node_rust(NTYPE_NET, vec![AttrValue::None, AttrValue::None]);
        assert_eq!(nid2, 2);
        assert_eq!(sg.nid_alloc_start(), 3);

        // Create at high nid advances alloc start
        sg.create_node_at_rust(10, NTYPE_NET, vec![AttrValue::None, AttrValue::None]);
        assert_eq!(sg.nid_alloc_start(), 11);

        // Next auto-allocate uses 11
        let nid3 = sg.create_node_rust(NTYPE_NET, vec![AttrValue::None, AttrValue::None]);
        assert_eq!(nid3, 11);
    }

    #[test]
    fn test_replace_node() {
        register_test_schemas();

        let mut sg = MutableSubgraph::new();
        sg.create_node_at_rust(0, NTYPE_ROOT, vec![]);

        // Create a path node
        sg.create_node_at_rust(
            1,
            NTYPE_NPATH,
            vec![AttrValue::None, AttrValue::String("original".into()), AttrValue::Int(0)],
        );

        // Replace it
        sg.create_node_at_rust(
            1,
            NTYPE_NPATH,
            vec![AttrValue::None, AttrValue::String("replaced".into()), AttrValue::Int(0)],
        );

        assert_eq!(sg.node_count(), 2); // Still 2 nodes

        let node = sg.get_node_rust(1).unwrap();
        assert_eq!(node.attrs[1], AttrValue::String("replaced".into()));

        // Type index should still have only one entry
        let paths = sg.query_by_ntype(NTYPE_NPATH);
        assert_eq!(paths.len(), 1);
    }

    #[test]
    fn test_frozen_equality() {
        register_test_schemas();

        let mut sg1 = MutableSubgraph::new();
        sg1.create_node_at_rust(0, NTYPE_ROOT, vec![]);
        sg1.create_node_rust(NTYPE_NET, vec![AttrValue::String("a".into()), AttrValue::Int(1)]);

        let mut sg2 = MutableSubgraph::new();
        sg2.create_node_at_rust(0, NTYPE_ROOT, vec![]);
        sg2.create_node_rust(NTYPE_NET, vec![AttrValue::String("a".into()), AttrValue::Int(1)]);

        let frozen1 = sg1.freeze();
        let frozen2 = sg2.freeze();

        // Same content = equal
        assert_eq!(frozen1, frozen2);

        // Different content = not equal
        let mut sg3 = MutableSubgraph::new();
        sg3.create_node_at_rust(0, NTYPE_ROOT, vec![]);
        sg3.create_node_rust(NTYPE_NET, vec![AttrValue::String("b".into()), AttrValue::Int(1)]);
        let frozen3 = sg3.freeze();

        assert_ne!(frozen1, frozen3);
    }
}
