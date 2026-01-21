// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

//! xORDB - aXellerated ORDB backend in Rust.
//!
//! This crate provides native Rust types for IC design schema entities,
//! with compile-time type safety and efficient persistent data structures.
//!
//! # Architecture
//!
//! - `rational`: Rational number type with SI prefix support
//! - `geoprim`: 2D geometric primitives (Vec2R, Rect4R, D4, TD4R)
//! - `subgraph`: Generic subgraph storage infrastructure
//! - `symbol`: Symbol schema types and SymbolSubgraph

pub mod geoprim;
pub mod rational;
pub mod subgraph;
pub mod symbol;

// Re-export commonly used types
pub use geoprim::{D4, PinType, Rect4R, RectError, TD4R, Vec2R};
pub use rational::{ParseRationalError, Rational};
pub use subgraph::{FrozenSubgraph, LocalRef, Nid, NodeTypeId, Subgraph, SubgraphNode};
pub use symbol::{
    FrozenSymbolSubgraph, Pin, PolyVec2R, Symbol, SymbolArc, SymbolNode, SymbolPoly,
    SymbolSubgraph,
};

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_create_symbol() {
        let outline = Rect4R::new(
            Rational::from_integer(0),
            Rational::from_integer(0),
            Rational::from_integer(100),
            Rational::from_integer(50),
        )
        .unwrap();

        let mut sg = SymbolSubgraph::with_root(Symbol::new(outline).with_caption("NMOS"));

        // Add pins
        let _in_pin = sg.insert(
            Pin::new(Vec2R::new(Rational::from_integer(0), Rational::from_integer(25)))
                .with_pintype(PinType::In),
        );
        let _out_pin = sg.insert(
            Pin::new(Vec2R::new(
                Rational::from_integer(100),
                Rational::from_integer(25),
            ))
            .with_pintype(PinType::Out),
        );

        // Add a decorative polygon
        let poly_nid = sg.insert(SymbolPoly::new());
        let poly_ref = LocalRef::new(poly_nid);

        sg.insert(PolyVec2R::new(
            poly_ref,
            0,
            Vec2R::new(Rational::from_integer(10), Rational::from_integer(10)),
        ));
        sg.insert(PolyVec2R::new(
            poly_ref,
            1,
            Vec2R::new(Rational::from_integer(90), Rational::from_integer(10)),
        ));
        sg.insert(PolyVec2R::new(
            poly_ref,
            2,
            Vec2R::new(Rational::from_integer(90), Rational::from_integer(40)),
        ));

        assert_eq!(sg.root().unwrap().caption, Some("NMOS".to_string()));
        assert_eq!(sg.all_pins().count(), 2);
        assert_eq!(sg.poly_vertex_positions(poly_nid).len(), 3);

        // Freeze and verify
        let frozen = sg.freeze();
        assert_eq!(frozen.all_pins().count(), 2);
    }
}
