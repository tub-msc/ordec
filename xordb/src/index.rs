// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

//! Index structures for efficient node lookups.
//!
//! ORDB uses indexes for:
//! - Fast attribute-based queries (all/one)
//! - Unique constraint enforcement
//! - LocalRef integrity checking
//! - NPath hierarchy management

use crate::attr::{AttrValue, RawNodeTuple};
use crate::schema::{IndexKind, IndexSchema, SortKeySpec};
use imbl::Vector;
use std::cmp::Ordering;
use std::hash::{Hash, Hasher};

/// Key for index lookups.
///
/// Index keys combine the index identifier with the indexed value(s).
#[derive(Clone, Debug)]
pub enum IndexKey {
    /// Key for NType index (all nodes of a type)
    NType { ntype_id: u64 },

    /// Key for simple single-attribute index
    Simple { index_id: u64, value: AttrValue },

    /// Key for combined multi-attribute index
    Combined { index_id: u64, values: Vec<AttrValue> },

    /// Key for LocalRef backref tracking
    LocalRef {
        index_id: u64,
        referenced_nid: u32,
    },
}

impl PartialEq for IndexKey {
    fn eq(&self, other: &Self) -> bool {
        match (self, other) {
            (IndexKey::NType { ntype_id: a }, IndexKey::NType { ntype_id: b }) => a == b,
            (
                IndexKey::Simple {
                    index_id: a_id,
                    value: a_val,
                },
                IndexKey::Simple {
                    index_id: b_id,
                    value: b_val,
                },
            ) => a_id == b_id && a_val == b_val,
            (
                IndexKey::Combined {
                    index_id: a_id,
                    values: a_vals,
                },
                IndexKey::Combined {
                    index_id: b_id,
                    values: b_vals,
                },
            ) => a_id == b_id && a_vals == b_vals,
            (
                IndexKey::LocalRef {
                    index_id: a_id,
                    referenced_nid: a_nid,
                },
                IndexKey::LocalRef {
                    index_id: b_id,
                    referenced_nid: b_nid,
                },
            ) => a_id == b_id && a_nid == b_nid,
            _ => false,
        }
    }
}

impl Eq for IndexKey {}

impl Hash for IndexKey {
    fn hash<H: Hasher>(&self, state: &mut H) {
        std::mem::discriminant(self).hash(state);
        match self {
            IndexKey::NType { ntype_id } => ntype_id.hash(state),
            IndexKey::Simple { index_id, value } => {
                index_id.hash(state);
                value.hash(state);
            }
            IndexKey::Combined { index_id, values } => {
                index_id.hash(state);
                for v in values {
                    v.hash(state);
                }
            }
            IndexKey::LocalRef {
                index_id,
                referenced_nid,
            } => {
                index_id.hash(state);
                referenced_nid.hash(state);
            }
        }
    }
}

/// Value stored in an index entry.
///
/// For most indexes, this is just a list of nids. For LocalRef indexes,
/// we store additional metadata for integrity checking.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum IndexValue {
    /// Simple list of nids (sorted by nid or custom sort key)
    Nids(Vector<u32>),

    /// Set of (index_id, nid) pairs for LocalRef backrefs
    LocalRefBackrefs(Vector<(u64, u32)>),
}

impl IndexValue {
    /// Create an empty nid list.
    pub fn empty_nids() -> Self {
        IndexValue::Nids(Vector::new())
    }

    /// Create an empty backref set.
    pub fn empty_backrefs() -> Self {
        IndexValue::LocalRefBackrefs(Vector::new())
    }

    /// Get nids if this is a Nids value.
    pub fn as_nids(&self) -> Option<&Vector<u32>> {
        match self {
            IndexValue::Nids(v) => Some(v),
            _ => None,
        }
    }

    /// Check if empty.
    pub fn is_empty(&self) -> bool {
        match self {
            IndexValue::Nids(v) => v.is_empty(),
            IndexValue::LocalRefBackrefs(v) => v.is_empty(),
        }
    }

    /// Get length.
    pub fn len(&self) -> usize {
        match self {
            IndexValue::Nids(v) => v.len(),
            IndexValue::LocalRefBackrefs(v) => v.len(),
        }
    }
}

/// Compute the index key for a node given an index schema.
pub fn compute_index_key(
    schema: &IndexSchema,
    node: &RawNodeTuple,
    _nid: u32,
) -> Option<IndexKey> {
    match schema.kind {
        IndexKind::NType => Some(IndexKey::NType {
            ntype_id: node.ntype_id,
        }),

        IndexKind::Simple => {
            let attr_idx = schema.attr_indices.first()?;
            let value = node.get(*attr_idx)?.clone();
            if value.is_none() {
                return None; // Don't index None values
            }
            Some(IndexKey::Simple {
                index_id: schema.index_id,
                value,
            })
        }

        IndexKind::Combined => {
            let values: Vec<AttrValue> = schema
                .attr_indices
                .iter()
                .filter_map(|&idx| node.get(idx).cloned())
                .collect();
            if values.len() != schema.attr_indices.len() {
                return None;
            }
            // Don't index if any value is None? Or index anyway?
            // Following Python behavior: index anyway (the tuple itself is the key)
            Some(IndexKey::Combined {
                index_id: schema.index_id,
                values,
            })
        }

        IndexKind::LocalRef => {
            let attr_idx = schema.attr_indices.first()?;
            let value = node.get(*attr_idx)?;
            let referenced_nid = value.as_nid()?;
            Some(IndexKey::LocalRef {
                index_id: schema.index_id,
                referenced_nid,
            })
        }

        IndexKind::NPath => {
            // NPath uses Combined index logic but with special constraint checking
            let values: Vec<AttrValue> = schema
                .attr_indices
                .iter()
                .filter_map(|&idx| node.get(idx).cloned())
                .collect();
            if values.len() != schema.attr_indices.len() {
                return None;
            }
            Some(IndexKey::Combined {
                index_id: schema.index_id,
                values,
            })
        }
    }
}

/// Insert a nid into an index value, maintaining sort order.
pub fn index_insert_nid(
    value: &IndexValue,
    nid: u32,
    sortkey: &Option<SortKeySpec>,
    _node: &RawNodeTuple,
) -> IndexValue {
    match value {
        IndexValue::Nids(nids) => {
            let insert_pos = match sortkey {
                None | Some(SortKeySpec::ByNid) => {
                    // Sort by nid (binary search)
                    nids.binary_search(&nid).unwrap_or_else(|pos| pos)
                }
                Some(SortKeySpec::ByAttr { attr_index: _ }) => {
                    // For attribute-based sorting, we'd need access to all nodes
                    // to compare. For now, append and let Python handle complex sorts.
                    // TODO: Implement proper attribute-based sorting
                    nids.len()
                }
            };

            let mut new_nids = nids.clone();
            new_nids.insert(insert_pos, nid);
            IndexValue::Nids(new_nids)
        }
        IndexValue::LocalRefBackrefs(refs) => {
            // LocalRef backrefs don't maintain sort order, just append
            let mut new_refs = refs.clone();
            // We store (index_id, nid) but index_id comes from caller context
            // For now, store with 0 as placeholder
            new_refs.push_back((0, nid));
            IndexValue::LocalRefBackrefs(new_refs)
        }
    }
}

/// Remove a nid from an index value.
pub fn index_remove_nid(value: &IndexValue, nid: u32) -> IndexValue {
    match value {
        IndexValue::Nids(nids) => {
            let new_nids: Vector<u32> = nids.iter().filter(|&&n| n != nid).copied().collect();
            IndexValue::Nids(new_nids)
        }
        IndexValue::LocalRefBackrefs(refs) => {
            let new_refs: Vector<(u64, u32)> =
                refs.iter().filter(|(_, n)| *n != nid).copied().collect();
            IndexValue::LocalRefBackrefs(new_refs)
        }
    }
}

/// Compare two nids for index sorting (with optional custom sort key).
#[allow(dead_code)] // Will be used for sorted index queries
pub fn compare_for_sort(
    a: u32,
    b: u32,
    sortkey: &Option<SortKeySpec>,
    get_node: impl Fn(u32) -> Option<RawNodeTuple>,
) -> Ordering {
    match sortkey {
        None | Some(SortKeySpec::ByNid) => a.cmp(&b),
        Some(SortKeySpec::ByAttr { attr_index }) => {
            let node_a = get_node(a);
            let node_b = get_node(b);

            match (node_a, node_b) {
                (Some(na), Some(nb)) => {
                    let val_a = na.get(*attr_index);
                    let val_b = nb.get(*attr_index);

                    match (val_a, val_b) {
                        (Some(AttrValue::Int(ia)), Some(AttrValue::Int(ib))) => ia.cmp(ib),
                        (Some(AttrValue::String(sa)), Some(AttrValue::String(sb))) => sa.cmp(sb),
                        // For other types, fall back to nid ordering
                        _ => a.cmp(&b),
                    }
                }
                // If nodes not found, fall back to nid ordering
                _ => a.cmp(&b),
            }
        }
    }
}
