// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

//! Generic subgraph storage infrastructure.
//!
//! This module provides reusable storage components for all subgraph types
//! (Symbol, Schematic, Layout, etc.).

use imbl::{HashMap, Vector};
use std::hash::Hash;
use std::marker::PhantomData;

/// Node identifier - index into subgraph storage.
pub type Nid = u32;

/// Typed reference to another node within the same subgraph.
///
/// The type parameter `T` indicates the expected node type at the target nid.
/// This provides compile-time type safety without runtime overhead - internally
/// it's just a `u32`.
///
/// Implements `Copy` since it's just a thin wrapper around a `Nid` (u32).
/// Note: We manually implement Clone/Copy to avoid requiring `T: Copy`.
pub struct LocalRef<T> {
    nid: Nid,
    _marker: PhantomData<T>,
}

// Manual implementations to avoid requiring T: Copy/Clone/Eq/Hash
impl<T> Clone for LocalRef<T> {
    fn clone(&self) -> Self {
        *self
    }
}

impl<T> Copy for LocalRef<T> {}

impl<T> PartialEq for LocalRef<T> {
    fn eq(&self, other: &Self) -> bool {
        self.nid == other.nid
    }
}

impl<T> Eq for LocalRef<T> {}

impl<T> std::hash::Hash for LocalRef<T> {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        self.nid.hash(state);
    }
}

impl<T> LocalRef<T> {
    #[inline]
    pub const fn new(nid: Nid) -> Self {
        Self {
            nid,
            _marker: PhantomData,
        }
    }

    #[inline]
    pub const fn nid(&self) -> Nid {
        self.nid
    }
}

impl<T> std::fmt::Debug for LocalRef<T> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "LocalRef<{}>({})", std::any::type_name::<T>(), self.nid)
    }
}

impl<T> std::fmt::Display for LocalRef<T> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "@{}", self.nid)
    }
}

/// Identifies the type of a node.
///
/// Each node type has a unique ID. Values are explicitly assigned to ensure
/// stability across code changes.
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
#[repr(u16)]
pub enum NodeTypeId {
    // Symbol schema (1-99)
    Symbol = 1,
    Pin = 2,
    SymbolPoly = 3,
    SymbolArc = 4,
    PolyVec2R = 5,

    // Reserved ranges for future schemas:
    // Schematic schema: 100-199
    // Layout schema: 200-299
}

/// Trait for node enum types (SymbolNode, SchematicNode, etc.).
///
/// This trait is implemented by the enum that contains all node variants
/// for a particular subgraph type.
pub trait SubgraphNode: Sized + Clone + PartialEq + Eq + Hash {
    /// Get the type ID for this node variant.
    fn type_id(&self) -> NodeTypeId;

    /// Get the human-readable type name.
    fn type_name(&self) -> &'static str;
}

/// Generic subgraph storage - reused by Symbol, Schematic, Layout, etc.
///
/// Provides:
/// - Node storage by nid
/// - Type index for querying nodes by type
/// - Nid allocation
/// - Freeze/thaw semantics via `imbl` persistent data structures
#[derive(Clone, Debug)]
pub struct Subgraph<N: SubgraphNode> {
    nodes: HashMap<Nid, N>,
    type_index: HashMap<NodeTypeId, Vector<Nid>>,
    nid_alloc: Nid,
}

impl<N: SubgraphNode> Default for Subgraph<N> {
    fn default() -> Self {
        Self::new()
    }
}

impl<N: SubgraphNode> Subgraph<N> {
    /// Create a new empty subgraph.
    pub fn new() -> Self {
        Self {
            nodes: HashMap::new(),
            type_index: HashMap::new(),
            nid_alloc: 1, // 0 is reserved for root
        }
    }

    /// Insert a node with auto-allocated nid.
    pub fn insert(&mut self, node: N) -> Nid {
        let nid = self.nid_alloc;
        self.insert_at(nid, node);
        nid
    }

    /// Insert a node at a specific nid.
    pub fn insert_at(&mut self, nid: Nid, node: N) {
        // Remove from indexes if replacing
        if let Some(old) = self.nodes.get(&nid) {
            self.remove_from_type_index(nid, old.type_id());
        }

        // Add to type index
        self.add_to_type_index(nid, node.type_id());

        // Store node
        self.nodes.insert(nid, node);

        // Update allocator
        if nid >= self.nid_alloc {
            self.nid_alloc = nid + 1;
        }
    }

    /// Get a node by nid.
    #[inline]
    pub fn get(&self, nid: Nid) -> Option<&N> {
        self.nodes.get(&nid)
    }

    /// Remove a node by nid.
    pub fn remove(&mut self, nid: Nid) -> Option<N> {
        if let Some(node) = self.nodes.remove(&nid) {
            self.remove_from_type_index(nid, node.type_id());
            Some(node)
        } else {
            None
        }
    }

    /// Query all nids of nodes with a specific type ID.
    pub fn all_by_type(&self, type_id: NodeTypeId) -> impl Iterator<Item = Nid> + '_ {
        self.type_index
            .get(&type_id)
            .into_iter()
            .flat_map(|v| v.iter().copied())
    }

    /// Iterate over all nodes.
    pub fn iter(&self) -> impl Iterator<Item = (Nid, &N)> + '_ {
        self.nodes.iter().map(|(nid, node)| (*nid, node))
    }

    /// Number of nodes.
    #[inline]
    pub fn len(&self) -> usize {
        self.nodes.len()
    }

    /// Check if empty.
    #[inline]
    pub fn is_empty(&self) -> bool {
        self.nodes.is_empty()
    }

    /// Check if a nid exists.
    #[inline]
    pub fn contains(&self, nid: Nid) -> bool {
        self.nodes.contains_key(&nid)
    }

    /// Freeze into an immutable subgraph.
    pub fn freeze(self) -> FrozenSubgraph<N> {
        FrozenSubgraph {
            nodes: self.nodes,
            type_index: self.type_index,
            nid_alloc: self.nid_alloc,
        }
    }

    // Internal helpers

    fn add_to_type_index(&mut self, nid: Nid, type_id: NodeTypeId) {
        let vec = self.type_index.entry(type_id).or_default();
        // Insert sorted
        let pos = vec.binary_search(&nid).unwrap_or_else(|p| p);
        vec.insert(pos, nid);
    }

    fn remove_from_type_index(&mut self, nid: Nid, type_id: NodeTypeId) {
        if let Some(vec) = self.type_index.get_mut(&type_id) {
            if let Ok(pos) = vec.binary_search(&nid) {
                vec.remove(pos);
            }
        }
    }
}

/// Frozen (immutable) subgraph.
///
/// Created by calling `freeze()` on a `Subgraph`. Can be thawed back to
/// a mutable subgraph with `thaw()`.
#[derive(Clone, Debug)]
pub struct FrozenSubgraph<N: SubgraphNode> {
    nodes: HashMap<Nid, N>,
    type_index: HashMap<NodeTypeId, Vector<Nid>>,
    nid_alloc: Nid,
}

impl<N: SubgraphNode> FrozenSubgraph<N> {
    /// Get a node by nid.
    #[inline]
    pub fn get(&self, nid: Nid) -> Option<&N> {
        self.nodes.get(&nid)
    }

    /// Query all nids of nodes with a specific type ID.
    pub fn all_by_type(&self, type_id: NodeTypeId) -> impl Iterator<Item = Nid> + '_ {
        self.type_index
            .get(&type_id)
            .into_iter()
            .flat_map(|v| v.iter().copied())
    }

    /// Iterate over all nodes.
    pub fn iter(&self) -> impl Iterator<Item = (Nid, &N)> + '_ {
        self.nodes.iter().map(|(nid, node)| (*nid, node))
    }

    /// Number of nodes.
    #[inline]
    pub fn len(&self) -> usize {
        self.nodes.len()
    }

    /// Check if empty.
    #[inline]
    pub fn is_empty(&self) -> bool {
        self.nodes.is_empty()
    }

    /// Check if a nid exists.
    #[inline]
    pub fn contains(&self, nid: Nid) -> bool {
        self.nodes.contains_key(&nid)
    }

    /// Thaw into a mutable subgraph.
    pub fn thaw(self) -> Subgraph<N> {
        Subgraph {
            nodes: self.nodes,
            type_index: self.type_index,
            nid_alloc: self.nid_alloc,
        }
    }
}

impl<N: SubgraphNode> PartialEq for FrozenSubgraph<N> {
    fn eq(&self, other: &Self) -> bool {
        self.nodes == other.nodes
    }
}

impl<N: SubgraphNode> Eq for FrozenSubgraph<N> {}

impl<N: SubgraphNode> Hash for FrozenSubgraph<N> {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        // Hash nodes in sorted order for determinism
        let mut nids: Vec<_> = self.nodes.keys().copied().collect();
        nids.sort();
        for nid in nids {
            nid.hash(state);
            self.nodes.get(&nid).hash(state);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Simple test node enum
    #[derive(Clone, PartialEq, Eq, Hash, Debug)]
    enum TestNode {
        A(u32),
        B(String),
    }

    impl SubgraphNode for TestNode {
        fn type_id(&self) -> NodeTypeId {
            match self {
                // Reuse existing IDs for testing
                TestNode::A(_) => NodeTypeId::Symbol,
                TestNode::B(_) => NodeTypeId::Pin,
            }
        }

        fn type_name(&self) -> &'static str {
            match self {
                TestNode::A(_) => "A",
                TestNode::B(_) => "B",
            }
        }
    }

    #[test]
    fn test_insert_and_get() {
        let mut sg: Subgraph<TestNode> = Subgraph::new();

        let nid1 = sg.insert(TestNode::A(42));
        let nid2 = sg.insert(TestNode::B("hello".to_string()));

        assert_eq!(sg.get(nid1), Some(&TestNode::A(42)));
        assert_eq!(sg.get(nid2), Some(&TestNode::B("hello".to_string())));
        assert_eq!(sg.len(), 2);
    }

    #[test]
    fn test_type_index() {
        let mut sg: Subgraph<TestNode> = Subgraph::new();

        sg.insert(TestNode::A(1));
        sg.insert(TestNode::A(2));
        sg.insert(TestNode::B("x".to_string()));
        sg.insert(TestNode::A(3));

        let a_nids: Vec<_> = sg.all_by_type(NodeTypeId::Symbol).collect();
        let b_nids: Vec<_> = sg.all_by_type(NodeTypeId::Pin).collect();

        assert_eq!(a_nids.len(), 3);
        assert_eq!(b_nids.len(), 1);
    }

    #[test]
    fn test_remove() {
        let mut sg: Subgraph<TestNode> = Subgraph::new();

        let nid = sg.insert(TestNode::A(42));
        assert!(sg.contains(nid));

        let removed = sg.remove(nid);
        assert_eq!(removed, Some(TestNode::A(42)));
        assert!(!sg.contains(nid));
        assert!(sg.all_by_type(NodeTypeId::Symbol).next().is_none());
    }

    #[test]
    fn test_freeze_thaw() {
        let mut sg: Subgraph<TestNode> = Subgraph::new();
        sg.insert(TestNode::A(42));

        let frozen = sg.freeze();
        assert_eq!(frozen.len(), 1);

        let mut thawed = frozen.thaw();
        thawed.insert(TestNode::B("new".to_string()));
        assert_eq!(thawed.len(), 2);
    }

    #[test]
    fn test_frozen_equality() {
        let mut sg1: Subgraph<TestNode> = Subgraph::new();
        sg1.insert_at(0, TestNode::A(42));
        sg1.insert(TestNode::B("x".to_string()));

        let mut sg2: Subgraph<TestNode> = Subgraph::new();
        sg2.insert_at(0, TestNode::A(42));
        sg2.insert(TestNode::B("x".to_string()));

        assert_eq!(sg1.freeze(), sg2.freeze());
    }

    #[test]
    fn test_local_ref() {
        let r: LocalRef<TestNode> = LocalRef::new(42);
        assert_eq!(r.nid(), 42);
    }
}
