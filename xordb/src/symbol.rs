// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

//! Symbol schema: visual representation of a cell.
//!
//! This module contains:
//! - Node types: Symbol, Pin, SymbolPoly, SymbolArc, PolyVec2R
//! - Node enum: SymbolNode
//! - Subgraph wrapper: SymbolSubgraph with schema-specific indexes

use crate::geoprim::{D4, PinType, Rect4R, Vec2R};
use crate::rational::Rational;
use crate::subgraph::{FrozenSubgraph, LocalRef, Nid, NodeTypeId, Subgraph, SubgraphNode};
use imbl::{HashMap, Vector};

// ============================================================================
// Node Types
// ============================================================================

/// Symbol root node - visual representation of a cell.
#[derive(Clone, PartialEq, Eq, Hash, Debug)]
pub struct Symbol {
    /// Bounding box of the symbol.
    pub outline: Rect4R,
    /// Caption text displayed with the symbol.
    pub caption: Option<String>,
}

impl Symbol {
    pub fn new(outline: Rect4R) -> Self {
        Self {
            outline,
            caption: None,
        }
    }

    pub fn with_caption(mut self, caption: impl Into<String>) -> Self {
        self.caption = Some(caption.into());
        self
    }
}

/// Pin in a symbol - electrical connection point.
#[derive(Clone, PartialEq, Eq, Hash, Debug)]
pub struct Pin {
    /// Pin direction (In, Out, Inout).
    pub pintype: PinType,
    /// Position in symbol coordinates.
    pub pos: Vec2R,
    /// Alignment/orientation of pin.
    pub align: D4,
}

impl Default for Pin {
    fn default() -> Self {
        Self {
            pintype: PinType::Inout,
            pos: Vec2R::ZERO,
            align: D4::R0,
        }
    }
}

impl Pin {
    pub fn new(pos: Vec2R) -> Self {
        Self {
            pos,
            ..Default::default()
        }
    }

    pub fn with_pintype(mut self, pintype: PinType) -> Self {
        self.pintype = pintype;
        self
    }

    pub fn with_align(mut self, align: D4) -> Self {
        self.align = align;
        self
    }
}

/// Polygonal chain for visual decoration in Symbol.
///
/// Vertices are stored as separate PolyVec2R nodes that reference this node.
#[derive(Clone, PartialEq, Eq, Hash, Debug, Default)]
pub struct SymbolPoly {}

impl SymbolPoly {
    pub fn new() -> Self {
        Self {}
    }
}

/// Arc/circle for visual decoration in Symbol.
#[derive(Clone, PartialEq, Eq, Hash, Debug)]
pub struct SymbolArc {
    /// Center point.
    pub pos: Vec2R,
    /// Radius.
    pub radius: Rational,
    /// Start angle (normalized: 0..1 where 1 = 360 degrees).
    pub angle_start: Rational,
    /// End angle (normalized: 0..1 where 1 = 360 degrees).
    pub angle_end: Rational,
}

impl Default for SymbolArc {
    fn default() -> Self {
        Self {
            pos: Vec2R::ZERO,
            radius: Rational::ONE,
            angle_start: Rational::ZERO,
            angle_end: Rational::ONE, // Full circle
        }
    }
}

impl SymbolArc {
    pub fn circle(pos: Vec2R, radius: Rational) -> Self {
        Self {
            pos,
            radius,
            angle_start: Rational::ZERO,
            angle_end: Rational::ONE,
        }
    }

    pub fn arc(pos: Vec2R, radius: Rational, angle_start: Rational, angle_end: Rational) -> Self {
        Self {
            pos,
            radius,
            angle_start,
            angle_end,
        }
    }
}

/// Vertex of a polygonal chain (rational coordinates).
#[derive(Clone, PartialEq, Eq, Hash, Debug)]
pub struct PolyVec2R {
    /// Reference to the parent polygon.
    pub ref_: LocalRef<SymbolPoly>,
    /// Order in the chain (for sorting).
    pub order: i32,
    /// Position of this vertex.
    pub pos: Vec2R,
}

impl PolyVec2R {
    pub fn new(ref_: LocalRef<SymbolPoly>, order: i32, pos: Vec2R) -> Self {
        Self { ref_, order, pos }
    }
}

// ============================================================================
// Node Enum
// ============================================================================

/// All node types in a Symbol subgraph.
#[derive(Clone, PartialEq, Eq, Hash, Debug)]
pub enum SymbolNode {
    Symbol(Symbol),
    Pin(Pin),
    SymbolPoly(SymbolPoly),
    SymbolArc(SymbolArc),
    PolyVec2R(PolyVec2R),
}

impl SubgraphNode for SymbolNode {
    fn type_id(&self) -> NodeTypeId {
        match self {
            SymbolNode::Symbol(_) => NodeTypeId::Symbol,
            SymbolNode::Pin(_) => NodeTypeId::Pin,
            SymbolNode::SymbolPoly(_) => NodeTypeId::SymbolPoly,
            SymbolNode::SymbolArc(_) => NodeTypeId::SymbolArc,
            SymbolNode::PolyVec2R(_) => NodeTypeId::PolyVec2R,
        }
    }

    fn type_name(&self) -> &'static str {
        match self {
            SymbolNode::Symbol(_) => "Symbol",
            SymbolNode::Pin(_) => "Pin",
            SymbolNode::SymbolPoly(_) => "SymbolPoly",
            SymbolNode::SymbolArc(_) => "SymbolArc",
            SymbolNode::PolyVec2R(_) => "PolyVec2R",
        }
    }
}

// Type-specific accessors on the enum
impl SymbolNode {
    pub fn as_symbol(&self) -> Option<&Symbol> {
        match self { SymbolNode::Symbol(x) => Some(x), _ => None }
    }

    pub fn as_pin(&self) -> Option<&Pin> {
        match self { SymbolNode::Pin(x) => Some(x), _ => None }
    }

    pub fn as_poly(&self) -> Option<&SymbolPoly> {
        match self { SymbolNode::SymbolPoly(x) => Some(x), _ => None }
    }

    pub fn as_arc(&self) -> Option<&SymbolArc> {
        match self { SymbolNode::SymbolArc(x) => Some(x), _ => None }
    }

    pub fn as_vertex(&self) -> Option<&PolyVec2R> {
        match self { SymbolNode::PolyVec2R(x) => Some(x), _ => None }
    }
}

// From implementations for ergonomic insertion

impl From<Symbol> for SymbolNode {
    fn from(n: Symbol) -> Self {
        SymbolNode::Symbol(n)
    }
}

impl From<Pin> for SymbolNode {
    fn from(n: Pin) -> Self {
        SymbolNode::Pin(n)
    }
}

impl From<SymbolPoly> for SymbolNode {
    fn from(n: SymbolPoly) -> Self {
        SymbolNode::SymbolPoly(n)
    }
}

impl From<SymbolArc> for SymbolNode {
    fn from(n: SymbolArc) -> Self {
        SymbolNode::SymbolArc(n)
    }
}

impl From<PolyVec2R> for SymbolNode {
    fn from(n: PolyVec2R) -> Self {
        SymbolNode::PolyVec2R(n)
    }
}

// ============================================================================
// SymbolSubgraph - Wrapper with schema-specific indexes
// ============================================================================

/// Symbol subgraph with additional polygon vertex index.
///
/// Wraps the generic `Subgraph<SymbolNode>` and adds:
/// - `poly_vertex_index`: polygon nid -> sorted list of vertex nids
#[derive(Clone, Debug)]
pub struct SymbolSubgraph {
    inner: Subgraph<SymbolNode>,
    /// Index: polygon nid -> vertex nids (sorted by order)
    poly_vertex_index: HashMap<Nid, Vector<Nid>>,
}

impl Default for SymbolSubgraph {
    fn default() -> Self {
        Self::new()
    }
}

impl SymbolSubgraph {
    /// Create a new empty symbol subgraph.
    pub fn new() -> Self {
        Self {
            inner: Subgraph::new(),
            poly_vertex_index: HashMap::new(),
        }
    }

    /// Create a symbol subgraph with an initial root node.
    pub fn with_root(root: Symbol) -> Self {
        let mut sg = Self::new();
        sg.inner.insert_at(0, SymbolNode::Symbol(root));
        sg
    }

    /// Get the root Symbol (at nid 0).
    pub fn root(&self) -> Option<&Symbol> {
        self.inner.get(0)?.as_symbol()
    }

    /// Insert a node with auto-allocated nid.
    pub fn insert<N: Into<SymbolNode>>(&mut self, node: N) -> Nid {
        let node = node.into();
        let nid = self.inner.insert(node.clone());
        self.update_poly_vertex_index_add(nid, &node);
        nid
    }

    /// Insert a node at a specific nid.
    pub fn insert_at<N: Into<SymbolNode>>(&mut self, nid: Nid, node: N) {
        // Remove old from poly_vertex_index if present
        if let Some(old) = self.inner.get(nid).cloned() {
            self.update_poly_vertex_index_remove(nid, &old);
        }

        let node = node.into();
        self.inner.insert_at(nid, node.clone());
        self.update_poly_vertex_index_add(nid, &node);
    }

    /// Get a node by nid.
    #[inline]
    pub fn get(&self, nid: Nid) -> Option<&SymbolNode> {
        self.inner.get(nid)
    }

    /// Remove a node by nid.
    pub fn remove(&mut self, nid: Nid) -> Option<SymbolNode> {
        if let Some(node) = self.inner.get(nid).cloned() {
            self.update_poly_vertex_index_remove(nid, &node);
        }
        self.inner.remove(nid)
    }

    // --- Type-specific accessors ---

    /// Get a Pin by nid.
    pub fn get_pin(&self, nid: Nid) -> Option<&Pin> {
        self.inner.get(nid)?.as_pin()
    }

    /// Get a SymbolPoly by nid.
    pub fn get_poly(&self, nid: Nid) -> Option<&SymbolPoly> {
        self.inner.get(nid)?.as_poly()
    }

    /// Get a SymbolArc by nid.
    pub fn get_arc(&self, nid: Nid) -> Option<&SymbolArc> {
        self.inner.get(nid)?.as_arc()
    }

    /// Get a PolyVec2R by nid.
    pub fn get_vertex(&self, nid: Nid) -> Option<&PolyVec2R> {
        self.inner.get(nid)?.as_vertex()
    }

    /// Query all Pins.
    pub fn all_pins(&self) -> impl Iterator<Item = (Nid, &Pin)> + '_ {
        self.inner
            .all_by_type(NodeTypeId::Pin)
            .filter_map(move |nid| self.get_pin(nid).map(|p| (nid, p)))
    }

    /// Query all SymbolPolys.
    pub fn all_polys(&self) -> impl Iterator<Item = (Nid, &SymbolPoly)> + '_ {
        self.inner
            .all_by_type(NodeTypeId::SymbolPoly)
            .filter_map(move |nid| self.get_poly(nid).map(|p| (nid, p)))
    }

    /// Query all SymbolArcs.
    pub fn all_arcs(&self) -> impl Iterator<Item = (Nid, &SymbolArc)> + '_ {
        self.inner
            .all_by_type(NodeTypeId::SymbolArc)
            .filter_map(move |nid| self.get_arc(nid).map(|a| (nid, a)))
    }

    /// Query vertices of a polygon in order.
    pub fn poly_vertices(&self, poly_nid: Nid) -> impl Iterator<Item = (Nid, &PolyVec2R)> + '_ {
        self.poly_vertex_index
            .get(&poly_nid)
            .into_iter()
            .flat_map(|v| v.iter().copied())
            .filter_map(move |nid| self.get_vertex(nid).map(|v| (nid, v)))
    }

    /// Get vertex positions of a polygon as a Vec.
    pub fn poly_vertex_positions(&self, poly_nid: Nid) -> Vec<Vec2R> {
        self.poly_vertices(poly_nid).map(|(_, v)| v.pos).collect()
    }

    // --- Generic access ---

    /// Iterate over all nodes.
    pub fn iter(&self) -> impl Iterator<Item = (Nid, &SymbolNode)> + '_ {
        self.inner.iter()
    }

    /// Number of nodes.
    #[inline]
    pub fn len(&self) -> usize {
        self.inner.len()
    }

    /// Check if empty.
    #[inline]
    pub fn is_empty(&self) -> bool {
        self.inner.is_empty()
    }

    /// Check if a nid exists.
    #[inline]
    pub fn contains(&self, nid: Nid) -> bool {
        self.inner.contains(nid)
    }

    /// Freeze into an immutable subgraph.
    pub fn freeze(self) -> FrozenSymbolSubgraph {
        FrozenSymbolSubgraph {
            inner: self.inner.freeze(),
            poly_vertex_index: self.poly_vertex_index,
        }
    }

    // --- Private index management ---

    fn update_poly_vertex_index_add(&mut self, nid: Nid, node: &SymbolNode) {
        if let SymbolNode::PolyVec2R(pv) = node {
            let poly_nid = pv.ref_.nid();
            let vec = self.poly_vertex_index.entry(poly_nid).or_default();

            // Insert sorted by order
            let pos = vec
                .binary_search_by(|&other_nid| {
                    if let Some(SymbolNode::PolyVec2R(other)) = self.inner.get(other_nid) {
                        other.order.cmp(&pv.order)
                    } else {
                        std::cmp::Ordering::Equal
                    }
                })
                .unwrap_or_else(|p| p);
            vec.insert(pos, nid);
        }
    }

    fn update_poly_vertex_index_remove(&mut self, nid: Nid, node: &SymbolNode) {
        if let SymbolNode::PolyVec2R(pv) = node {
            let poly_nid = pv.ref_.nid();
            if let Some(vec) = self.poly_vertex_index.get_mut(&poly_nid) {
                vec.retain(|&v| v != nid);
            }
        }
    }
}

// ============================================================================
// FrozenSymbolSubgraph
// ============================================================================

/// Frozen (immutable) Symbol subgraph.
#[derive(Clone, Debug)]
pub struct FrozenSymbolSubgraph {
    inner: FrozenSubgraph<SymbolNode>,
    poly_vertex_index: HashMap<Nid, Vector<Nid>>,
}

impl FrozenSymbolSubgraph {
    /// Get the root Symbol.
    pub fn root(&self) -> Option<&Symbol> {
        self.inner.get(0)?.as_symbol()
    }

    /// Get a node by nid.
    #[inline]
    pub fn get(&self, nid: Nid) -> Option<&SymbolNode> {
        self.inner.get(nid)
    }

    /// Get a Pin by nid.
    pub fn get_pin(&self, nid: Nid) -> Option<&Pin> {
        self.inner.get(nid)?.as_pin()
    }

    /// Get a PolyVec2R by nid.
    pub fn get_vertex(&self, nid: Nid) -> Option<&PolyVec2R> {
        self.inner.get(nid)?.as_vertex()
    }

    /// Query all Pins.
    pub fn all_pins(&self) -> impl Iterator<Item = (Nid, &Pin)> + '_ {
        self.inner
            .all_by_type(NodeTypeId::Pin)
            .filter_map(move |nid| self.get_pin(nid).map(|p| (nid, p)))
    }

    /// Query vertices of a polygon in order.
    pub fn poly_vertices(&self, poly_nid: Nid) -> impl Iterator<Item = (Nid, &PolyVec2R)> + '_ {
        self.poly_vertex_index
            .get(&poly_nid)
            .into_iter()
            .flat_map(|v| v.iter().copied())
            .filter_map(move |nid| self.get_vertex(nid).map(|v| (nid, v)))
    }

    /// Iterate over all nodes.
    pub fn iter(&self) -> impl Iterator<Item = (Nid, &SymbolNode)> + '_ {
        self.inner.iter()
    }

    /// Number of nodes.
    #[inline]
    pub fn len(&self) -> usize {
        self.inner.len()
    }

    /// Check if empty.
    #[inline]
    pub fn is_empty(&self) -> bool {
        self.inner.is_empty()
    }

    /// Thaw into a mutable subgraph.
    pub fn thaw(self) -> SymbolSubgraph {
        SymbolSubgraph {
            inner: self.inner.thaw(),
            poly_vertex_index: self.poly_vertex_index,
        }
    }
}

impl PartialEq for FrozenSymbolSubgraph {
    fn eq(&self, other: &Self) -> bool {
        self.inner == other.inner
    }
}

impl Eq for FrozenSymbolSubgraph {}

impl std::hash::Hash for FrozenSymbolSubgraph {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        self.inner.hash(state);
    }
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    fn test_rect() -> Rect4R {
        Rect4R::new(
            Rational::from_integer(0),
            Rational::from_integer(0),
            Rational::from_integer(100),
            Rational::from_integer(100),
        )
        .unwrap()
    }

    #[test]
    fn test_symbol_subgraph_basic() {
        let mut sg = SymbolSubgraph::with_root(Symbol::new(test_rect()));

        assert!(sg.root().is_some());
        assert_eq!(sg.len(), 1);

        let pin_nid = sg.insert(Pin::new(Vec2R::new(
            Rational::from_integer(0),
            Rational::from_integer(50),
        )));

        assert!(sg.get_pin(pin_nid).is_some());
        assert_eq!(sg.all_pins().count(), 1);
    }

    #[test]
    fn test_polygon_with_vertices() {
        let mut sg = SymbolSubgraph::with_root(Symbol::new(test_rect()));

        // Insert a polygon
        let poly_nid = sg.insert(SymbolPoly::new());
        let poly_ref = LocalRef::new(poly_nid);

        // Insert vertices (out of order to test sorting)
        sg.insert(PolyVec2R::new(
            poly_ref,
            2,
            Vec2R::new(Rational::from_integer(20), Rational::from_integer(0)),
        ));
        sg.insert(PolyVec2R::new(
            poly_ref,
            0,
            Vec2R::new(Rational::from_integer(0), Rational::from_integer(0)),
        ));
        sg.insert(PolyVec2R::new(
            poly_ref,
            1,
            Vec2R::new(Rational::from_integer(10), Rational::from_integer(10)),
        ));

        // Vertices should be returned in order
        let positions = sg.poly_vertex_positions(poly_nid);
        assert_eq!(positions.len(), 3);
        assert_eq!(positions[0].x, Rational::from_integer(0));
        assert_eq!(positions[1].x, Rational::from_integer(10));
        assert_eq!(positions[2].x, Rational::from_integer(20));
    }

    #[test]
    fn test_freeze_thaw() {
        let mut sg = SymbolSubgraph::with_root(Symbol::new(test_rect()));
        sg.insert(Pin::default());

        let frozen = sg.freeze();
        assert_eq!(frozen.len(), 2);
        assert!(frozen.root().is_some());

        let mut thawed = frozen.thaw();
        thawed.insert(Pin::default());
        assert_eq!(thawed.len(), 3);
    }

    #[test]
    fn test_symbol_arc() {
        let mut sg = SymbolSubgraph::with_root(Symbol::new(test_rect()));

        let arc_nid = sg.insert(SymbolArc::circle(
            Vec2R::new(Rational::from_integer(50), Rational::from_integer(50)),
            Rational::from_integer(25),
        ));

        let arc = sg.get_arc(arc_nid).unwrap();
        assert_eq!(arc.radius, Rational::from_integer(25));
        assert_eq!(sg.all_arcs().count(), 1);
    }

    #[test]
    fn test_from_impls() {
        let _: SymbolNode = Symbol::new(test_rect()).into();
        let _: SymbolNode = Pin::default().into();
        let _: SymbolNode = SymbolPoly::new().into();
        let _: SymbolNode = SymbolArc::default().into();
        let _: SymbolNode = PolyVec2R::new(LocalRef::new(1), 0, Vec2R::ZERO).into();
    }
}
