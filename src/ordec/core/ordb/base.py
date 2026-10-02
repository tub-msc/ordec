# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from typing import Callable, Iterable, NamedTuple
from collections.abc import Mapping
from types import NoneType
from dataclasses import dataclass
from abc import ABC, ABCMeta, abstractmethod
import dis
import inspect
import string
import warnings
from public import public

from . import _ordb
from .backend import StorageBackend, default_backend, get_backend

@public
class OrdbException(Exception):
    """Base class for all ORDB custom exceptions."""
    pass

@public
class QueryException(OrdbException):
    """Raised when a query fails."""
    pass

@public
class ModelViolation(OrdbException):
    """Raised when a data integrity condition is violated, e.g.
    :class:`UniqueViolation`, :class:`DanglingLocalRef`."""
    pass

@public
class Inserter(ABC):
    __slots__=()
    @abstractmethod
    def insert_into(self, sgu: 'SubgraphUpdater', primary_nid: int):
        """
        Args:
            sgu: SubgraphUpdater for insertion.
            primary_nid: Hint about which node ID should be used to insert
                the primary (or only) node that is inserted. If more than one
                node is inserted by the inserter, sgu.nid_generate() is used
                to generate the further needed node IDs.
                (Note: An more beautiful solution might be something like:
                itertools.starmap(sgu.nid_generate, itertools.repeat(())) as the
                default value and itertools.chain(custom_primary_nid, 
                itertools.starmap(sgu.nid_generate, itertools.repeat(()))).
        """
        pass

@public
class FuncInserter(Inserter):
    __slots__=("insert_into",)
    def __init__(self, inserter_func):
        self.insert_into = inserter_func

class IndexKey(NamedTuple):
    index: 'Index'
    value: tuple|int

@public
class IndexQuery(NamedTuple):
    """Pass IndexQuery objects to :meth:`SubgraphRoot.all` or
    :meth:`SubgraphRoot.one` to run query on a specific subgraph."""
    index_key: IndexKey

class GenericIndex(ABC):
    """
    Indices and reference checks of node types. They are declared in the
    schema and evaluated by the native core; check_constraints is the
    reference implementation that raises the exact exception once the core
    has found a violation.
    """
    @abstractmethod
    def check_constraints(self, sgu: 'SubgraphUpdater', node, nid):
        pass

@public
@dataclass(eq=True)
class UniqueViolation(ModelViolation):
    """Exception raised when a unique constraint is violated."""
    index: GenericIndex #: :class:`GenericIndex` violating the unique constraint.
    value: tuple #: Value violating the unique constraint.

@public
@dataclass(eq=True)
class DanglingLocalRef(ModelViolation):
    """
    Exception raised when a :class:`LocalRef` attribute ends up referencing
    an inexistent nid.
    """
    nid: int

@public
@dataclass(eq=True)
class DanglingExternalRef(ModelViolation):
    """
    Exception raised when an :class:`ExternalRef` attribute ends up
    referencing an inexistent nid in the referenced subgraph.
    """
    nid: int

def must_be_type(t):
    if not isinstance(t, type):
        raise TypeError(f"{t} is not type.")

@public
class Attr:
    """
    Defines a node attribute of a primitive type such as string, int or Vec2R.

    Args:
        type: Defines the type of attribute values.
        default: Default attribute value.
        factory: Function applied to each value before assignment to attribute.
        typecheck_custom: If this argument is not provided, type checking
            is performed through isinstance(val, type). If it is provided,
            typecheck_custom is called with val instead of the default
            type check. This is for example used in NPath to support both int
            and str values.
        name (str): Name of the attribute.

    Attributes:
        indices (list[GenericIndex]): list of all indices associated with attribute
    """

    def __init__(self, type: type, default=None, optional: bool=True, factory: Callable=None, typecheck_custom: Callable=None):
        if typecheck_custom:
            self.typecheck = typecheck_custom
        else:
            must_be_type(type)
            self.typecheck = lambda val: isinstance(val, type)
        self._default_typecheck = typecheck_custom is None

        self.type = type
        self.default = default
        self.custom_factory = factory
        self.optional = optional
        self.indices = []
        self.name = None

    def factory(self, val):
        if val is None:
            val = self.default
        if self.custom_factory:
            val = self.custom_factory(val)
        if isinstance(val, Node):
            raise TypeError("Nodes can only be added to LocalRef, ExternalRef or SubgraphRef attributes.")

        if val is None:
            return val
            
        if not self.typecheck(val):
            raise TypeError(f"Incorrect type {type(val).__name__} for attribute.")
        
        return val
        
    def read_hook(self, value, cursor):
        return value

@dataclass(frozen=True, eq=False)
class NodeTupleAttrDescriptor:
    ntype: type
    index: int
    name: str
    attr: Attr

    def is_nid(self):
        return isinstance(self.attr, LocalRef)

    def __get__(self, obj, owner=None):
        if obj is None: # for the class: return the descriptor itself
            return self
        else: # for instances: return value of attribute
            assert owner == self.ntype.Tuple
            return obj[self.index]

    def __repr__(self):
        return f"NodeTupleAttrDescriptor({self.ntype.__name__}.{self.name})"

@public
class LocalRef(Attr):
    """
    Defines a node attribute referencing a node within the same subgraph. The
    reference is internally stored as integer nid. The :class:`Node` interface
    hides the nid in two ways: On reading the LocalRef attribute, the Node
    object is returned instead of a nid. Node objects of the same subgraph can
    also be assigned directly to the attribute.

    Args:
        refs_ntype: The Node subclass that this reference points to.
        optional: Specifies whether the reference can be None.
    """

    def __init__(self, refs_ntype: type, optional: bool=True, factory: Callable=None, refcheck_custom: Callable=None):
        super().__init__(type=int, optional=optional, factory=factory)
        self.refs_ntype = refs_ntype

        if refcheck_custom:
            self.refcheck = refcheck_custom
        else:
            must_be_type(refs_ntype)
            self.refcheck = lambda val: issubclass(val, refs_ntype)

        self.indices.append(LocalRefIndex(self))

    def factory(self, val: 'int|Node|NoneType'):
        if val is None:
            return val
        if self.custom_factory:
            val = self.custom_factory(val)
        if isinstance(val, Node):
            val = val.nid
        if not isinstance(val, int):
            raise TypeError('Only int or Node (or None if optional) can be assigned to LocalRef.')
        return val

    def read_hook(self, value, cursor):
        if value is None:
            return value
        else:
            return cursor.subgraph.cursor_at(value)

@public
class SubgraphRef(Attr):
    """
    References another subgraph. Can serve as base reference for zero or more
    :class:`ordec.core.ordb.ExternalRef` attributes.

    Either a SubgraphRoot or a FrozenSubgraph can be assigned to a SubgraphRef.
    Reading a SubgraphRef always returns a SubgraphRoot object.

    The referenced subgraph must be frozen.

    Args:
        type: SubgraphRoot class of the referenced subgraph.
    """
    
    def read_hook(self, value, cursor):
        if value is None:
            return None
        else:
            return value.root_cursor

    def factory(self, val: 'FrozenSubgraph|SubgraphRoot|NoneType'):
        if val is None:
            return val
        if isinstance(val, Node):
            val = val.subgraph

        if not isinstance(val, FrozenSubgraph):
            if isinstance(val, MutableSubgraph):
                raise TypeError('MutableSubgraph cannot be assigned to SubgraphRef (must be frozen).')
            else:
                raise TypeError('Only None, FrozenSubgraph or SubgraphRoot can be assigned to SubgraphRef.')

        if not self.typecheck(val.root_cursor):
            raise TypeError(f"Incorrect type {type(val.root_cursor).__name__} for SubgraphRef.")
        
        return val

# Opcodes that load the first argument of a function (3.14 adds the BORROW
# variant).
_LOAD_ARG_OPS = ('LOAD_FAST', 'LOAD_FAST_CHECK', 'LOAD_FAST_BORROW')

def _attr_chain(fn) -> 'tuple[str]|NoneType':
    """
    Names of the attributes read by fn if fn does nothing but read a chain of
    attributes from its single argument and return the result, e.g.
    ('root', 'ref_layers') for lambda c: c.root.ref_layers. None for any
    other callable.

    This is decided from the bytecode, without calling fn: the core
    evaluates sortkey and of_subgraph functions of this form natively and
    calls all other functions per node.
    """
    code = getattr(fn, '__code__', None)
    if code is None or code.co_argcount != 1 or code.co_kwonlyargcount:
        return None
    if code.co_flags & (inspect.CO_VARARGS | inspect.CO_VARKEYWORDS):
        return None
    ops = [i for i in dis.get_instructions(code) if i.opname not in ('RESUME', 'NOP')]
    if len(ops) < 3 or ops[0].opname not in _LOAD_ARG_OPS or ops[0].argval != code.co_varnames[0]:
        return None
    if ops[-1].opname != 'RETURN_VALUE' or any(i.opname != 'LOAD_ATTR' for i in ops[1:-1]):
        return None
    return tuple(i.argval for i in ops[1:-1])

@public
class ExternalRef(Attr):
    """
    References a node in another subgraph.

    Each ExternalRef is resolved using a corresponding SubgraphRef. The
    corresponding SubgraphRef can be an attribute of the same node or of
    another node. The of_subgraph argument defines which SubgraphRef corresponds
    to the ExternalRef.

    Args:
        refs_ntype: The referenced node type.
        of_subgraph: Function receiving the current node as argument and
            returning the SubgraphRoot of the referenced subgraph by reading
            the SubgraphRef that corresponds to this instance of the
            ExternalRef. Plain attribute chains (lambda c: c.root.ref_layers,
            lambda c: c.ref.symbol, lambda c: c.subg) are checked natively;
            other functions are called per node on commit (slower).
        optional: Specifies whether the reference can be None.
    """

    def __init__(self, refs_ntype: type, of_subgraph: 'Callable[[Node], SubgraphRoot]', optional: bool = True):
        super().__init__(type=int, optional=optional)
        if not callable(of_subgraph):
            raise TypeError("of_subgraph must be a function, e.g. lambda c: c.root.ref_layers.")
        self.refs_ntype = refs_ntype
        self.of_subgraph = of_subgraph
        self.refcheck = lambda val: issubclass(val, refs_ntype)
        self.indices.append(ExternalRefIndex(self))

    def check_ref(self, sgu: 'SubgraphUpdater', node, nid):
        """
        Deferred consistency check for one ExternalRef value.

        Resolves the referenced subgraph via :attr:`of_subgraph`, then verifies
        that the stored nid exists in that subgraph and that the target node
        type matches :attr:`refs_ntype`.
        """
        attrdesc = node._attrdesc_by_attr[self]
        ref = node[attrdesc.index]
        if ref is None:
            assert self.optional
            return

        cursor = sgu.cursor_at(nid, lookup_npath=False)
        subgraph_root = self.of_subgraph(cursor)
        if subgraph_root is None:
            refs_name = getattr(self.refs_ntype, '__name__', str(self.refs_ntype))
            raise ModelViolation(
                f"ExternalRef {node._cursor_type.__name__}.{attrdesc.name}"
                f" (-> {refs_name}) could not resolve its referenced subgraph:"
                f" the corresponding SubgraphRef is unset (None). Make sure it"
                f" is assigned on the enclosing subgraph."
            )
        if not isinstance(subgraph_root, SubgraphRoot):
            raise ModelViolation(
                f"ExternalRef expected SubgraphRoot from of_subgraph, got {type(subgraph_root).__name__}."
            )
        target_subgraph = subgraph_root.subgraph
        try:
            target = target_subgraph.row(ref)
        except KeyError:
            raise DanglingExternalRef(ref) from None

        if not self.refcheck(target._cursor_type):
            raise ModelViolation(
                f"ExternalRef invalid reference {attrdesc.name}={ref} ({target._cursor_type.__name__})"
                f" in {node._cursor_type.__name__}(nid={nid}, ...)"
            ) from None

    def read_hook(self, value, cursor):
        if value is None:
            return None
        return self.of_subgraph(cursor).cursor_at(value)

    def factory(self, val: 'int|Node|NoneType'):
        if val is None:
            return None
        if isinstance(val, Node):
            val = val.nid
        if not isinstance(val, int):
            raise TypeError('Only None, int or Node can be assigned to ExternalRef.')
        return val


@public
class FarRef:
    """
    Placeholder for a live object residing on a foreign endpoint. FarRefs are
    created when decoding a :class:`LiveRef` attribute whose export reference
    was minted by a different process (see ordec.core.wire); they cannot be
    resolved locally. Equality and hash use (endpoint_id, obj_id) only; name
    is human-readable metadata chosen by the exporting endpoint.
    """
    __slots__ = ('endpoint_id', 'obj_id', 'name')

    def __init__(self, endpoint_id: bytes, obj_id: int, name: str=''):
        self.endpoint_id = endpoint_id
        self.obj_id = obj_id
        self.name = name

    def __eq__(self, other):
        if not isinstance(other, FarRef):
            return NotImplemented
        return (self.endpoint_id, self.obj_id) == (other.endpoint_id, other.obj_id)

    def __hash__(self):
        return hash((FarRef, self.endpoint_id, self.obj_id))

    def __repr__(self):
        return f"FarRef({self.endpoint_id.hex()}, {self.obj_id}, name={self.name!r})"

@public
class LiveRef(Attr):
    """
    Defines a node attribute holding a live Python object (e.g. a Cell) that
    stays resident on its endpoint. In-process, the object is stored in the
    node tuple directly, like a plain Attr value. On the wire
    (ordec.core.wire), the value is replaced by an export reference; decoding
    a reference minted by a foreign endpoint yields an opaque :class:`FarRef`,
    which is therefore also an accepted value.

    Args:
        type: The type that locally assigned values must be an instance of.
    """
    def __init__(self, type: type, **kwargs):
        super().__init__(type=type,
            typecheck_custom=lambda val: isinstance(val, (type, FarRef)),
            **kwargs)

@public
class Index(GenericIndex):
    """
    Index for equality queries on one attribute.

    Args:
        attr: Indexed attribute.
        unique: At most one node may have each value (None excepted).
        sortkey: Function receiving the node value (NodeTuple) and returning
            the int (or None) by which query results are ordered (ties: by
            nid). Without sortkey, results are ordered by nid. A plain
            attribute read (lambda node: node.order) is evaluated natively;
            other functions are called per index update and per query
            result (slower). sortkey must depend only on the values of the
            node: entries are validated by evaluating it again, so an entry
            whose sortkey result changed without a change of the node looks
            stale. Queries skip such entries, and merging index runs can
            drop them permanently.
    """
    def __init__(self, attr: Attr, unique:bool=False, sortkey: Callable=None):
        if sortkey is not None and not callable(sortkey):
            raise TypeError("sortkey must be a function, e.g. lambda node: node.order.")
        self.attr = attr
        self.unique = unique
        self.sortkey = sortkey
      
        attr.indices.append(self)

    def index_key(self, node, nid=None):
        val = node[node._attrdesc_by_attr[self.attr].index]
        if val is None:
            return None
        return IndexKey(self, val)

    def check_constraints(self, sgu: 'SubgraphUpdater', node, nid):
        if self.unique:
            key = self.index_key(node, nid)
            if not key:
                return
            vals = sgu.target_subgraph.query(self, key.value)
            if len(vals) > 1:
                raise UniqueViolation(self, key)

    def query(self, key) -> IndexQuery:
        """Returns IndexQuery object for equivalence query with key."""
        if isinstance(key, Node):
            key = key.nid
        return IndexQuery(IndexKey(self, key))

@public
class CombinedIndex(Index):
    """
    Index for equality queries on a tuple of attributes.

    Args:
        attrs: Indexed attributes; query keys are tuples in this order.
        unique: At most one node may have each key.
        sortkey: As for :class:`Index` (in particular, it must depend only
            on the values of the node).
    """
    def __init__(self, attrs: list[Attr], unique:bool=False, sortkey: Callable=None):
        if sortkey is not None and not callable(sortkey):
            raise TypeError("sortkey must be a function, e.g. lambda node: node.order.")
        self.attrs = attrs
        self.unique = unique
        self.sortkey = sortkey
        for attr in self.attrs:
            attr.indices.append(self)

    def index_key(self, node, nid=None):
        return IndexKey(self, tuple((node[node._attrdesc_by_attr[a].index] for a in self.attrs)))

    def query(self, key) -> IndexQuery:
        """Returns IndexQuery object for equivalence query with key."""
        key = tuple((elem.nid if isinstance(elem, Node) else elem for elem in key))
        return IndexQuery(IndexKey(self, key))


class NTypeIndex(Index):
    """Queries by node type (table)."""
    def __init__(self):
        self.sortkey = None
        self.unique = False

    def query(self, key):
        return IndexQuery(key)

class LocalRefIndex(GenericIndex):
    """
    Reference integrity of a LocalRef attribute: the target exists and has
    a permitted type, and a node cannot be removed while it is referenced
    (the native core counts the references per nid). For lookups, use a
    separate Index.
    """
    def __init__(self, attr: LocalRef):
        self.attr = attr

    def check_constraints(self, sgu: 'SubgraphUpdater', node, nid):
        attrdesc = node._attrdesc_by_attr[self.attr]
        ref = node[attrdesc.index]

        if  ref is None:
            # The optional check on which this assertion is based is in
            # LocalRef.factory.
            assert attrdesc.attr.optional
            return
        
        try:
            target = sgu.target_subgraph.row(ref)
        except KeyError:
            raise DanglingLocalRef(ref) from None
        
        if not attrdesc.attr.refcheck(target._cursor_type):
            raise ModelViolation(f"LocalRef invalid reference {attrdesc.name}={ref} ({target._cursor_type.__name__}) in {node._cursor_type.__name__}(nid={nid}, ...)") from None

class ExternalRefIndex(GenericIndex):
    """
    ExternalRefIndex is meant for integrity checking only.
    """
    def __init__(self, attr: ExternalRef):
        self.attr = attr

    def check_constraints(self, sgu: 'SubgraphUpdater', node, nid):
        self.attr.check_ref(sgu, node, nid)

class NPathIndex(CombinedIndex):
    def check_constraints(self, sgu: 'SubgraphUpdater', node, nid):
        try:
            super().check_constraints(sgu, node, nid)
        except UniqueViolation:
            raise ModelViolation("Path exists") # TODO: Report actual path?

@public
class NodeTuple(tuple):
    """
    NodeTuples are the values of nodes: calling a node type returns one,
    inserting it into a subgraph (e.g. with '%') creates a node, and
    :meth:`Subgraph.row` returns the NodeTuple of a node. Subgraphs do not
    store NodeTuples; the native core keeps the values in tables.
    """

    __slots__ = ()

    def check_hashable(self):
        try:
            hash(self)
        except TypeError:
            raise TypeError("All attributes of NodeTuple must be hashable.")

    # __new__(cls, **kwargs) is _ordb.ntuple_new (assigned below the class):
    # it applies the attribute factories, standard ones in C.

    def vals_repr(self):
        return ', '.join([f"{ad.name}={self[ad.index]!r}" for ad in self._layout])

    def __repr__(self):
        return f"{type(self).__name__}({self.vals_repr()})"

    def set(self, **kwargs):
        """Copy with the given attributes replaced."""
        return self._ntype.set(self, kwargs)

    def set_byattr(self, attr, value):
        # Bypasses NodeTuple.__new__:

        found = False
        def ensure_hashable_and_found(x):
            hash(x) # Ensure new value is hashable.
            nonlocal found
            assert not found, "Attribute should not appear twice in _layout."
            found = True
            return x

        ret=super().__new__(
            type(self),
            (
                (ensure_hashable_and_found(ad.attr.factory(value)) if ad.attr == attr else prev)
                for ad, prev in zip(self._layout, tuple.__iter__(self))
            ),
        )

        if not found:
            raise OrdbException(f"Attribute not found: {attr}")
        
        return ret

    def set_index(self, idx, value):
        value = self._layout[idx].attr.factory(value)
        # Check only the updated value for hashability:
        try:
            hash(value)
        except TypeError:
            raise TypeError("All attributes of NodeTuple must be hashable.")
        ret = super().__new__(type(self), (value if i == idx else elem for i, elem in enumerate(tuple.__iter__(self))))
        return ret

    def __iter__(self):
        raise TypeError(f"{type(self).__name__} is not iterable")

    def translate_nids(self, nid_map):
        # Bypasses NodeTuple.__new__:
        ret=super().__new__(type(self), (nid_map[self[ad.index]] if ad.is_nid() and self[ad.index] is not None else self[ad.index] for ad in self._layout))
        return ret

    def check_constraints(self, sgu: 'SubgraphUpdater', nid):
        """Reference implementation of the per-node commit checks (the
        native core runs them; see _check_callback)."""
        for attrdesc, val in zip(self._layout, tuple.__iter__(self)):
            if val is None and not attrdesc.attr.optional:
                raise ModelViolation(f"{attrdesc.name!r} is not optional (but set to None).")

        for ns in self.indices:
            ns.check_constraints(sgu, self, nid)

    def insert_into(self, sgu, primary_nid):
        return sgu.add_single(self, primary_nid)

    def __eq__(self, other):
        return type(self)==type(other) and tuple.__eq__(self, other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __lt__(self, other):
        return NotImplemented

    def __le__(self, other):
        return NotImplemented

    def __gt__(self, other):
        return NotImplemented

    def __ge__(self, other):
        return NotImplemented

    def __hash__(self):
        return hash((type(self), tuple.__hash__(self)))

    index_ntype = NTypeIndex() #: Queries by node type (table)

NodeTuple.__new__ = staticmethod(_ordb.ntuple_new)

# Register NodeTuple as virtual subclass of Inserter. Combining tuple and ABC seems like it could cause problems.
Inserter.register(NodeTuple)

@dataclass(frozen=True, eq=False)
class ArrayField:
    """
    One attribute of an arrayable node type (Node.arrayable) in array form:
    width int64 columns; vtype(*ints) rebuilds the attribute value when
    width > 1 (e.g. Rect4I), plain ints are used when vtype is None.
    """
    name: str
    index: int
    attr: Attr
    width: int
    vtype: type|NoneType

def _is_int_attr(attr) -> bool:
    return isinstance(attr, (LocalRef, ExternalRef)) or attr.type is int

def _vec_width(attr) -> int|NoneType:
    """Slot width of a fixed-size integer value type (Vec2I, Rect4I)."""
    t = attr.type
    width = getattr(t, 'array_width', None)
    if isinstance(width, int) and isinstance(t, type) and issubclass(t, tuple) \
            and not isinstance(attr, (SubgraphRef, LiveRef)):
        return width
    return None

def array_layout(name, layout) -> tuple[ArrayField]:
    fields = []
    for ad in layout:
        attr = ad.attr
        if _is_int_attr(attr):
            fields.append(ArrayField(ad.name, ad.index, attr, 1, None))
        elif _vec_width(attr) is not None:
            fields.append(ArrayField(ad.name, ad.index, attr, attr.type.array_width, attr.type))
        else:
            raise TypeError(f"{name}.{ad.name}: attribute type"
                f" {attr.type.__name__} is not array-representable.")
    return tuple(fields)

def _read_mode(attr) -> int:
    hook = type(attr).read_hook
    if hook is Attr.read_hook:
        return 0 # the stored value
    if hook is LocalRef.read_hook:
        return 1 # cursor at the stored nid
    return 2 # attr.read_hook(value, cursor)

def _subgraph_refs(classes, name) -> 'tuple[SubgraphRef]|NoneType':
    """The SubgraphRef attributes called name of the given node types, or
    None if one of them has no such SubgraphRef."""
    refs = tuple(getattr(c, '_raw_attrs', {}).get(name) for c in classes)
    if refs and all(isinstance(a, SubgraphRef) for a in refs):
        return refs
    return None

# Start node of a natively evaluated of_subgraph chain (else: position of a
# LocalRef attribute of the node).
_EXT_ROOT = -2
_EXT_SELF = -1

def _ext_native(cls, attr, by_name) -> 'tuple[int, tuple[SubgraphRef]]|NoneType':
    """
    The native form (start, SubgraphRefs) of an ExternalRef's of_subgraph, for
    the attribute chains c.root.X, c.X and c.L.X (L a LocalRef of the node),
    each ending in a SubgraphRef X. The core reads the SubgraphRef of the start
    node that is one of the given attributes. None for other functions.
    """
    chain = _attr_chain(attr.of_subgraph)
    if chain is None or len(chain) > 2:
        return None
    first_ad = by_name.get(chain[0])
    first = first_ad.attr if first_ad else None
    if len(chain) == 1:
        if isinstance(first, SubgraphRef):
            return _EXT_SELF, (first,)
    elif first is None and chain[0] == 'root':
        # Node.root, as no attribute of the node is called root.
        refs = _subgraph_refs(cls.in_subgraphs, chain[1])
        if refs:
            return _EXT_ROOT, refs
    elif isinstance(first, LocalRef) and isinstance(first.refs_ntype, type):
        refs = _subgraph_refs((first.refs_ntype,), chain[1])
        if refs:
            return first_ad.index, refs
    return None

def _sort_native(index, by_name) -> 'int|NoneType':
    """Position of the int attribute that the sortkey of index reads
    (lambda node: node.order), or None if the sortkey must be called."""
    chain = _attr_chain(index.sortkey)
    if chain and len(chain) == 1 and chain[0] in by_name:
        ad = by_name[chain[0]]
        if _is_int_attr(ad.attr):
            return ad.index
    return None

def _build_ntype(cls, ntuple, layout, attrdesc_by_attr, indices):
    """Describes a node type to the native core."""
    by_name = {ad.name: ad for ad in layout}
    attrs = []
    for ad in layout:
        attr = ad.attr
        width = _vec_width(attr)
        if _is_int_attr(attr):
            kind, width = _ordb.K_INT, 1
        elif width is not None:
            kind = _ordb.K_IVEC
        else:
            kind, width = _ordb.K_OBJ, 1
        ref_kind = 1 if isinstance(attr, LocalRef) else 2 if isinstance(attr, ExternalRef) else 0
        ext, ext_fn = None, None
        if isinstance(attr, ExternalRef):
            ext = _ext_native(cls, attr, by_name)
            if ext is None:
                ext_fn = attr.of_subgraph
        factory = type(attr).factory
        if factory is Attr.factory and attr.custom_factory is None and attr._default_typecheck:
            fmode = 0 # in C: default, then isinstance check
        elif factory in (LocalRef.factory, ExternalRef.factory) and attr.custom_factory is None:
            fmode = 1 # in C: Node -> nid, int
        else:
            fmode = 2 # attr.factory(value)
        attrs.append((ad.name, kind, width, attr.type if kind == _ordb.K_IVEC else None,
            attr.optional, attr, _read_mode(attr), ref_kind, ext,
            fmode, attr.type, attr.default, ext_fn))

    uses = []
    checks = []
    position = {attr: ad.index for attr, ad in attrdesc_by_attr.items()}
    for ns in indices:
        if isinstance(ns, LocalRefIndex):
            checks.append((1, position[ns.attr]))
        elif isinstance(ns, ExternalRefIndex):
            checks.append((2, position[ns.attr]))
        elif isinstance(ns, Index) and not isinstance(ns, NTypeIndex):
            combined = isinstance(ns, CombinedIndex)
            key_attrs = ns.attrs if combined else [ns.attr]
            if not all(a in position for a in key_attrs):
                continue
            sort, sortfn = -1, None
            if ns.sortkey is not None:
                sort = _sort_native(ns, by_name)
                if sort is None:
                    sort, sortfn = -1, ns.sortkey
            if ns.unique:
                checks.append((0, len(uses)))
            uses.append((ns, tuple(position[a] for a in key_attrs), sort, ns.unique, combined, sortfn))
    return _ordb.NType(ntuple, cls, attrs, uses, checks)

#: Maps declared wire_ids to their Node classes (see ordec.core.wire). Node
#: classes opt into wire serialization by declaring wire_id = WIRE_DOMAIN | n
#: in their class body, with WIRE_DOMAIN a per-module constant.
wire_registry = {}

WIRE_DOMAIN = 1 << 16 # ordb-internal node types (NPath)

class NodeMeta(type):
    @staticmethod
    def _collect_raw_attrs(d, bases):
        raw_attrs = {} # The order in raw_attrs defines the tuple layout later on.

        def register(k, v):
            raw_attrs[k] = v
            if v.name is None:
                v.name = k
            else:
                assert v.name == k

        # First come inherited attributes:
        for b in bases:
            try:
                # Base with already-collected raw attributes (a built Node
                # subclass): inherit them.
                raw_attrs |= b._raw_attrs
            except AttributeError:
                # Base without _raw_attrs: either a plain mixin or Node itself
                # (build_node=False). Collect Attr instances declared anywhere
                # in its MRO. These stay in the base's __dict__; the per-class
                # descriptor built later shadows them via the MRO.
                for cls in reversed(b.__mro__):
                    for k, v in vars(cls).items():
                        if isinstance(v, Attr):
                            register(k, v)

        # Then newly added attributes:
        for k, v in list(d.items()):
            if isinstance(v, Attr):
                register(k, v)
                del d[k] # Gets repopulated later.

        return raw_attrs

    def __new__(mcs, name, bases, attrs, build_node=True):
        attrs['__slots__'] = ()
        if build_node:
            raw_attrs = mcs._collect_raw_attrs(attrs, bases)
            # Populate special class attributes:
            attrs['_raw_attrs'] = raw_attrs
        return super(NodeMeta, mcs).__new__(mcs, name, bases, attrs)

    def __init__(cls, name, bases, attrs, build_node=True):
        if build_node:
            # Check that all non-Node bases define __slots__ to prevent __dict__
            for base in cls.__mro__:
                if base in (object, _ordb.NodeBase, cls):
                    continue
                if isinstance(base, NodeMeta):
                    continue
                if base.__dict__.get('__slots__') != ():
                    raise TypeError(
                        f"{name}: mixin {base.__name__} must define __slots__ = ()"
                    )

            attrdesc_by_attr = {}
            attrdesc_by_name = {}
            nodetuple_dict = {'_raw_attrs': cls._raw_attrs, '__slots__':()}
            layout = []
            attrs.setdefault('__annotations__', {})
            nt_indices = []

            for n, (k, v) in enumerate(cls._raw_attrs.items()):
                nt_ad = NodeTupleAttrDescriptor(ntype=cls, index=n, name=k, attr=v)
                nodetuple_dict[k] = nt_ad
                cls.__annotations__[k] = v.type # Not so nice; for Sphinx.
                layout.append(nt_ad)
                attrdesc_by_attr[v] = nt_ad
                attrdesc_by_name[k] = nt_ad
                for ns in v.indices:
                    if ns not in nt_indices:
                        nt_indices.append(ns)

            nodetuple_dict['indices'] = nt_indices
            # arrayable, like wire_id, applies to the declaring class only.
            nodetuple_dict['_array_layout'] = array_layout(name, layout) \
                if attrs.get('arrayable', False) else None
            nodetuple_dict['_attrdesc_by_name'] = attrdesc_by_name
            nodetuple_dict['_attrdesc_by_attr'] = attrdesc_by_attr
            nodetuple_dict['_layout'] = layout
            nodetuple_dict['_cursor_type'] = cls
            cls.Tuple = type(name+'.Tuple', (NodeTuple,), nodetuple_dict)

            ntype = _build_ntype(cls, cls.Tuple, layout, attrdesc_by_attr, nt_indices)
            cls.Tuple._ntype = ntype
            for ad in layout:
                setattr(cls, ad.name, _ordb.AttrDescriptor(ad.attr, ntype, ad.index))

            cls.Mutable = type(name+'.Mutable', (cls, MutableNode), {'__slots__':()}, build_node=False)
            cls.Frozen = type(name+'.Frozen', (cls, FrozenNode), {'__slots__':()}, build_node=False)
            ntype.set_cursors(cls.Mutable, cls.Frozen)

            # Not sure whether this is a good idea, but it is nice for the
            # inheritance diagrams in the docs.
            cls.Tuple.__module__ = cls.__module__
            cls.Mutable.__module__ = cls.__module__
            cls.Frozen.__module__ = cls.__module__

            # Register a wire_id declared in this class's own body (inherited
            # wire_ids are deliberately not registered: subclasses must declare
            # their own to be wire-serializable). Re-registration under the
            # same (module, qualname) is allowed, as module reloads (server
            # purge_modules, pytest) re-execute class definitions.
            wid = attrs.get('wire_id')
            if wid is not None:
                if not isinstance(wid, int) or wid <= 0:
                    raise TypeError(f"{name}: wire_id must be a positive int.")
                other = wire_registry.get(wid)
                if other is not None and (other.__module__, other.__qualname__) \
                        != (cls.__module__, cls.__qualname__):
                    raise TypeError(
                        f"wire_id {wid:#x} of {name} is already used by "
                        f"{other.__module__}.{other.__qualname__}."
                    )
                wire_registry[wid] = cls

        return super().__init__(name, bases, attrs)

@public
class Node(_ordb.NodeBase, metaclass=NodeMeta, build_node=False):
    """
    Subclass this class to define own node types (tables) for ORDB.

    Calling/instantiating a Node subclass X does not return an object of type
    X, but an object of type X.Tuple, which is a implicitly created subclass
    of :class:`NodeTuple`. A corresponding X object is only obtained when
    the the X.Tuple object is attached to a subgraph, for example using the
    modulo ('%') operator.

    Node objects are cursors: they select a node (subgraph, nid) and read
    its attributes from the subgraph on access. The cursor of an empty path
    (:class:`PathNode`) selects an NPath instead of a node.

    Two cursors are equal if they select the same node of equal subgraphs:
    mutable subgraphs are equal by identity, frozen subgraphs by content.
    """

    in_subgraphs = []

    #: Declares that rows of this node type may be inserted and read as
    #: arrays (SubgraphUpdater.insert_array, Subgraph.arrays) and are
    #: encoded as arrays on the wire. All attributes must be
    #: array-representable: int, LocalRef, ExternalRef or a value type with
    #: array_width (Vec2I, Rect4I). Rows with None values or ints outside
    #: the int64 range remain possible, but are not representable in
    #: arrays. Like wire_id, it applies to the declaring class only.
    arrayable = False

    def __new__(self, **kwargs):
        return self.Tuple(**kwargs)

    @property
    def tuple(self) -> NodeTuple:
        """The NodeTuple (values) of the selected node."""
        return self.subgraph.row(self.nid)

    @property
    def npath(self) -> 'NPath.Tuple':
        """The raw NPath.Tuple matching the selected node."""
        npath_nid = self.npath_nid
        if npath_nid is None:
            return None
        else:
            return self.subgraph.row(npath_nid)

    def full_path_list(self) -> list[str|int]:
        """Hierarchial path of the selected node in NPath hierarchy as list."""
        if self.nid == 0:
            # Root node special case:
            return []
        if not self.npath_nid:
            raise TypeError("Requested path of cursor without NPath.")
        here = [self.npath.name]
        if self.npath.parent is None:
            return here
        else:
            return self.parent.full_path_list() + here

    @staticmethod
    def format_path_list(path_list: list) -> str:
        """Format a path list as a string (e.g., ['I0', 'sub', 0] -> 'I0.sub[0]')."""
        it = iter(path_list)
        try:
            first = next(it)
        except StopIteration:
            return ''
        if not isinstance(first, str):
            raise TypeError("First element of path must be a string.")
        parts = [first]
        for elem in it:
            if isinstance(elem, int):
                parts.append(f'[{elem}]')
            elif isinstance(elem, str):
                parts.append(f'.{elem}')
            else:
                raise TypeError("Path must only contain str and int.")
        return ''.join(parts)

    def full_path_str(self) -> str:
        """Hierarchial path of the selected node in NPath hierarchy as string."""
        path_list = self.full_path_list()
        if not path_list:
            raise TypeError("SubgraphRoot does not support full_path_str().")
        return Node.format_path_list(path_list)

    def full_path_label(self) -> str:
        """
        Like full_path_str(), but returns a "??<nid>" placeholder for nodes
        without an NPath name (including root) instead of raising TypeError.
        """
        if self.npath_nid is None:
            return f"??{self.nid}"
        return self.full_path_str()

    def __repr__(self):
        info = []
        if self.npath_nid is not None:
            info.append(f"path={self.full_path_str()}")
        if self.nid is not None:
            info.append(f"nid={self.nid}")
            info.append(self.tuple.vals_repr())

        return f"{type(self).__name__}({', '.join(info)})"

    @property
    def parent(self) -> 'Node':
        """Parent node of selected node in NPath hierarchy."""
        if self.npath is None:
            raise QueryException("Subgraph root has no parent.")
        if self.npath.parent is None:
            return self.subgraph.root_cursor
        else:
            npath_next_nid = self.npath.parent
            npath_next = self.subgraph.row(npath_next_nid)
            return self.subgraph.cursor_at(npath_next.ref, npath_next_nid)

    def update(self, **kwargs):
        """
        Each key, value argument pair updates the attribute key of the
        selected node to the provided value.
        """

        self.subgraph.update(self.tuple.set(**kwargs), self.nid)

    def update_byattr(self, attr: Attr, value):
        """
        Update single attribute to specified value.
        """

        self.subgraph.update(self.tuple.set_byattr(attr, value), self.nid)

    def remove(self):
        """Removes selected node from subgraph, including NPath if applicable."""
        with self.subgraph.updater() as sgu:
            if self.npath_nid is not None:
                sgu.remove_nid(self.npath_nid)
            self.remove_node(sgu)

    def remove_node(self, sgu: 'SubgraphUpdater'):
        """Removes selected node from subgraph, *exluding* potential NPath."""
        if self.nid is not None:
            sgu.remove_nid(self.nid)

    def replace(self, inserter: Inserter):
        """
        Replaces the current node with a one newly inserted by provided inserter,
        reusing the nid as primary_nid to the inserter. By reusing the nid,
        existing NPaths and LocalRefs should be left intact.
        """
        if self.npath_nid is not None:
            children = self.subgraph.all(NPath.idx_parent.query(self.npath_nid), wrap_cursor=False)
            if len(list(children)) > 0:
                raise OrdbException("Cannot replace non-leaf node that has children.")
                # TODO: This error should really be raised by NPath.idx_parent, and only in case
                # a non-leaf node is replaced by a leaf node.
                # Apart from that, there are other data inconsistencies that could currently
                # be introduced by replace() but that are not caught anywhere?!

        with self.subgraph.updater() as u:
            self.remove_node(u)
            new_nid = inserter.insert_into(u, self.nid)

    def __mod__(self, node: Inserter) -> 'Node':
        """
        Inserts node and sets 'ref' attribute of the inserted node to
        the nid of the selected node.
        """
        if isinstance(node, NodeTuple):
            # Simple case, in one call of the native core:
            return self.subgraph._add1(node, self.nid)
        else:
            # Complex case:
            def inserter_func(sgu, primary_nid):
                main_nid = node.insert_into(sgu, primary_nid)
                sgu.update(sgu.target_subgraph.row(main_nid).set(ref=self.nid), main_nid)
                return main_nid
            nid_new = self.subgraph.add(FuncInserter(inserter_func))
        # Optimization: lookup_npath is disabled, because this newly added node has no NPath.
        return self.subgraph.cursor_at(nid_new, lookup_npath=False)

    @property
    def root(self) -> 'SubgraphRoot':
        """Returns SubgraphRoot of the selected subgraph."""
        return self.subgraph.root_cursor

    @property
    def mutable(self) -> bool:
        """Returns whether the selected subgraph is mutable."""
        raise TypeError("n.mutable is unavailable where n is not subclass of MutableNode or FrozenNode.")

    @classmethod
    def canonical_cls(cls) -> type:
        """
        Returns the plain (canonical) Node subclass, e.g.
        :class:`ordec.core.schema.Layout` for Layout.Frozen or
        Layout.Mutable. On a plain Node subclass, this method returns the
        class itself.

        Background: plain Node subclasses are never instantiated as cursors.
        Every cursor object is an instance of one of the auto-generated
        subclasses :attr:`Node.Frozen` or :attr:`Node.Mutable` (depending on
        whether its subgraph is frozen or mutable), so ``type(node)`` never
        returns the plain class. ``isinstance(node, Layout)`` works as
        expected, because the cursor classes subclass the plain class. But
        code that uses node classes as dictionary keys or compares them with
        ``==``/``is`` must normalize cursor classes via
        ``type(node).canonical_cls()`` — otherwise lookups silently miss
        (e.g. ``d[Layout]`` vs. an entry keyed by ``Layout.Frozen``).
        """
        return cls

    def ctx(self):
        """Return a Context for use as a context manager: ``with node.ctx(): ...``"""
        from ..context import NodeContext
        return NodeContext(self)

    def __copy__(self) -> 'Self':
        return self # Cursors are immutable.


@public
class NonLeafNode(Node, build_node=False):
    """
    NonLeafNodes differ from other Nodes in that they can have children
    in the NPath hierarchy.
    """

    # The attribute handlers wrap the item handlers:

    def __getattr__(self, k):
        # If attribute is not found, look for k as subpath:
        
        try:
            return self.__getitem__(k)
        except QueryException as e:
            # IPython needs an AttributeError here, else it does not use _repr_html_.
            raise AttributeError(*e.args) from None

    def __setattr__(self, k, v):
        try:
            # This triggers __set__ of descriptors such as the attribute descriptors:
            # See https://stackoverflow.com/a/61550073 on why object is used instead of super().
            object.__setattr__(self, k, v)
        except AttributeError:
            # If this is unsuccessful (e.g. no such attribute), try to create a child node with k as NPath:
            self.__setitem__(k, v)

    def __delattr__(self, k):
        try:
            object.__delattr__(self, k)
        except AttributeError:
            # Try to delete child node:
            self.__delitem__(k)

    # The item handlers allow accessing children in the NPath hierarchy:

    def __setitem__(self, k, v):
        with self.subgraph.updater() as u:
            if isinstance(v, Node):
                # v is a cursor to a node already in the subgraph: name that
                # existing node rather than inserting a copy. This is what makes
                # 'root.foo = some_existing_cursor' attach the name 'foo' to the
                # node some_existing_cursor points at (e.g. naming an SRouter
                # path created anonymously via '%').
                if v.subgraph is not self.subgraph:
                    raise OrdbException("Cannot name a node from a different subgraph.")
                if v.nid is None:
                    raise OrdbException("Cannot name a cursor without an associated node.")
                v_nid = v.nid
            elif v == PathNode.Tuple():
                # Create a new NPath without associated node.
                v_nid = None
            else:
                v_nid = v.insert_into(u, u.nid_generate())
            self._mkpath_addnode(k, v_nid, u)

    def __getitem__(self, k):
        """Returns cursor to a subpath."""
        
        return self.subgraph._child(self.npath_nid, k)

    def __delitem__(self, k):
        self.__getitem__(k).remove()

    def mkpath(self, k: str|int, ref=None):
        """
        Create empty NPath 'k' below selected node.

        .. deprecated::
            Use ``x.name = PathNode()`` (string key) or ``x[i] = PathNode()`` (integer key) instead.
        """
        warnings.warn(
            "mkpath() is deprecated. Use 'x.name = PathNode()' or 'x[i] = PathNode()' instead.",
            DeprecationWarning,
            stacklevel=2)
        with self.subgraph.updater() as u:
            self._mkpath_addnode(k, ref, u)

    def _mkpath_addnode(self, k, ref, u: 'SubgraphUpdater'):
        """Creates NPath node below current cursor. NPath node is empty when ref=None."""
        if self.nid not in (None, 0):
            if self.npath_nid is None:
                raise OrdbException("Cannot add node at cursor without NPath.")
        NPath.Tuple(parent=self.npath_nid, name=k, ref=ref).insert_into(u, u.nid_generate())

    def children(self) -> Iterable[Node]:
        """Iterate over direct children in the NPath hierarchy."""
        sg = self.subgraph
        child_npath_nids = sg.all(NPath.idx_parent.query(self.npath_nid), wrap_cursor=False)
        return (sg.cursor_at(sg.row(npath_nid).ref, npath_nid, lookup_npath=False)
            for npath_nid in child_npath_nids)

@public
class FrozenNode(Node, build_node=False):
    """Auxiliary base class for auto-generated :attr:`Node.Frozen` classes."""
    @property
    def mutable(self):
        return False

    @classmethod
    def canonical_cls(cls) -> type:
        # NodeMeta generates Frozen cursor classes with the plain class as
        # first base (and this override precedes Node in their MRO).
        return cls.__bases__[0]

@public
class MutableNode(Node, build_node=False):
    """Auxiliary base class for auto-generated :attr:`Node.Mutable` classes."""
    @property
    def mutable(self):
        return True

    @classmethod
    def canonical_cls(cls) -> type:
        # See FrozenNode.canonical_cls.
        return cls.__bases__[0]

@public
class SubgraphRoot(NonLeafNode):
    """
    Each subgraph has a single SubgraphRoot node. The subclass of SubgraphRoot
    defines what kind of design data the subgraph represents.
    """
    # No wire_id here: SubgraphRoot is never serialized as an exact class;
    # every wire-serializable root subclass declares its own.

    def __new__(cls, **kwargs):
        # __new__ calls super().__new__ via SubgraphRoot.Tuple(), but wraps the result in a Subgraph object.
        sg = MutableSubgraph()
        with sg.updater() as u:
            u.add_single(cls.Tuple(**kwargs), nid=0) # SubgraphRoots always have nid = 0
        return sg.root_cursor

    def __mod__(self, node) -> Node:
        """
        Add node and return cursor at created node.

        This is a simpler version of Node.__mod__ that does not set the 'ref'
        attribute of the inserted node.
        """
        if isinstance(node, NodeTuple):
            return self.subgraph._add1(node)
        nid_new = self.subgraph.add(node)
        # Optimization: lookup_npath is disabled, because this newly added node has no NPath.
        return self.subgraph.cursor_at(nid_new, lookup_npath=False)

    # Convenience forwards to self.subgraph
    # -------------------------------------

    def updater(self) -> 'SubgraphUpdater':
        """Convenience wrapper for :meth:`Subgraph.updater`."""
        return self.subgraph.updater()

    def cursor_at(self, *args, **kwargs) -> Node:
        """Convenience wrapper for :meth:`Subgraph.cursor_at`."""
        return self.subgraph.cursor_at(*args, **kwargs)

    def all(self, *args, **kwargs) -> Iterable[Node]:
        """Convenience wrapper for :meth:`Subgraph.all`."""
        return self.subgraph.all(*args, **kwargs)

    def arrays(self, *args, **kwargs) -> 'dict[str, numpy.ndarray]':
        """Convenience wrapper for :meth:`Subgraph.arrays`."""
        return self.subgraph.arrays(*args, **kwargs)

    def one(self, *args, **kwargs) -> Node:
        """Convenience wrapper for :meth:`Subgraph.one`."""
        return self.subgraph.one(*args, **kwargs)

    def matches(self, other):
        """Convenience wrapper for :meth:`Subgraph.matches`."""
        if not isinstance(other, SubgraphRoot):
            return False
        assert other.nid == 0
        return self.subgraph.matches(other.subgraph)

    def freeze(self):
        """Convenience wrapper for :meth:`Subgraph.freeze`."""
        return self.subgraph.freeze().root_cursor

    def thaw(self):
        """Convenience wrapper for :meth:`Subgraph.thaw`."""
        return self.subgraph.thaw().root_cursor

    def mutable_copy(self):
        """Convenience wrapper for :meth:`Subgraph.mutable_copy`."""
        return self.subgraph.mutable_copy().root_cursor

    def tables(self, html=False) -> str:
        """Convenience wrapper for :meth:`Subgraph.tables`."""
        return self.subgraph.tables(html=html)

    def dump(self) -> str:
        """Convenience wrapper for :meth:`Subgraph.dump`."""
        return self.subgraph.dump()

    def copy(self) -> 'Self':
        """
        For convenience, SubgraphRoot.copy and SubgraphRoot.__copy__ copy the
        Subgraph itself (deep copy) and return the root cursor of the new
        subgraph.
        """
        return self.subgraph.copy().root_cursor

    def __copy__(self) -> 'Self':
        return self.copy()

    def webdata(self, ept):
        """
        Web representation as (viewtype, data), rendered for the endpoint
        owning the given ExportTable. The default implementation delegates to
        webdata_static(); views whose webdata depends on the endpoint (e.g.
        wire hashes in LVS/DRC reports) override this method instead.
        """
        return self.webdata_static()

    def webdata_static(self):
        """
        Endpoint-independent web representation, same (viewtype, data) shape
        as webdata(). Exists only for views whose output cannot depend on an
        ExportTable, so it may be called without a connection (e.g. by
        Svg.from_view at report construction time).
        """
        from ..schema import Report
        report = Report()
        report.html(self.tables(html=True))
        return report.webdata_static()

class SubgraphQueryMixin:
    __slots__ = ()

    def all(self, query: IndexQuery, wrap_cursor: bool = True) -> Iterable[Node|int]:
        """
        Run query and return all matching nodes.

        Args:
            query: Query to run.
            wrap_cursor: If True, Nodes are returned, else nid ints are returned.
                The list of nids is a snapshot: the subgraph may be changed
                while it is iterated.
        """
        sg = self.target_subgraph
        if isinstance(query, type):
            assert issubclass(query, Node)
            nids = sg.nids(query.Tuple)
        else:
            key = query.index_key
            if isinstance(key, type): # NTypeIndex
                nids = sg.nids(key)
            else:
                nids = sg.query(key.index, key.value)
        if wrap_cursor:
            return sg._cursors(nids)
        else:
            return nids

    def one(self, query: IndexQuery, wrap_cursor: bool = True) -> Node|int:
        """
        Wrapper for :meth:`all` returning exactly one node. If zero or more
        than one node are found, a :class:`QueryException` is raised.
        """
        nids = self.all(query, wrap_cursor=False)
        if len(nids) < 1:
            raise QueryException("Query returned less than one element.")
        if len(nids) > 1:
            raise QueryException("Query returned more than one element.")
        if wrap_cursor:
            return self.target_subgraph.cursor_at(nids[0])
        return nids[0]

class NodesView(Mapping):
    """Read-only mapping of the nids of a subgraph to NodeTuples, materialized
    on access (see Subgraph.nodes)."""
    __slots__ = ('_sg',)

    def __init__(self, sg):
        self._sg = sg

    def __getitem__(self, nid):
        return self._sg.row(nid)

    def __contains__(self, nid):
        return self._sg.has(nid)

    def __iter__(self):
        return iter(self._sg.nids())

    def __len__(self):
        return self._sg.count()

@public
class SubgraphUpdater(SubgraphQueryMixin, _ordb.UpdaterBase):
    """
    A SubgraphUpdater collects changes to a subgraph as a kind of
    transaction. The SubgraphUpdater is used in a 'with' context. When this
    context is exited, the current state of SubgraphUpdater is checked for
    consistency. When no problem is found, the changes are committed;
    otherwise (or when the context exits with an exception, or when commit
    is set to False) they are undone.

    Changes are applied to the subgraph immediately: reads through the
    subgraph see them while the updater is open. Freezing or copying the
    subgraph is not possible while an updater is open. Updaters of the same
    subgraph can be nested; they must be closed in reverse order of opening.
    """
    __slots__ = ()

    @property
    def nodes(self):
        """Node state of the subgraph (including uncommitted changes)."""
        return NodesView(self.target_subgraph)

    @property
    def mutable(self):
        return True

    @property
    def root_cursor(self) -> Node:
        return self.target_subgraph.root_cursor

    def cursor_at(self, *args, **kwargs):
        return self.target_subgraph.cursor_at(*args, **kwargs)

    def insert_array(self, ntype: type, **values) -> range:
        """
        Inserts n nodes of an arrayable node type (Node.arrayable) from
        array values, e.g. insert_array(LayoutRect, layer=layer, rect=a)
        with a of shape (n, 4). Equivalent to n add_single() calls with
        consecutive new nids; see ordec.core.ordb.arrays for the value
        forms.

        Returns:
            The nids of the inserted nodes.
        """
        import numpy as np
        from .arrays import normalize
        n, cols = normalize(ntype, values)
        start = self.nid_gen_counter
        if n > 0 and start + n - 1 not in self.target_subgraph.nid_alloc:
            raise OrdbException("nid allocation exhausted.")
        self.insert_array_at(ntype, np.arange(start, start + n, dtype=np.int64), cols)
        return range(start, start + n)

    def insert_array_at(self, ntype: type, nids, cols, fresh: bool=False):
        """
        Like insert_array, with given nids (int64 array) and normalized
        columns (see ordec.core.ordb.arrays.normalize). Used by insert_array
        and wire_decode.
        """
        import numpy as np
        from .arrays import array_fields
        fields = array_fields(ntype)
        if len(nids) == 0:
            return
        nids = np.ascontiguousarray(nids, dtype=np.int64)
        self._insert_rows(ntype.Tuple, nids,
            [np.ascontiguousarray(cols[f.name], dtype=np.int64) for f in fields])

@public
class Subgraph(SubgraphQueryMixin, _ordb.SubgraphBase):
    """
    Subgraph state lives in the native core. Reading: :meth:`row`,
    :meth:`nids`, :meth:`query`, :meth:`cursor_at`; writing through
    :meth:`updater`.
    """
    __slots__ = ()

    # Non-mutating methods
    # --------------------

    def __repr__(self):
        root = self.row(0) if self.has(0) else None
        return f"<{type(self).__name__} {id(self)} root={root!r}, {self.count()} nodes>"

    @property
    def target_subgraph(self):
        return self

    def iter_tables(self):
        it = iter(self.node_dict('pretty').items())
        nid, node = next(it)
        cur_nodes = [(nid, node)]
        cur_ntype = type(node)
        for nid, node in it:
            if type(node) == cur_ntype:
                cur_nodes.append((nid, node))
            else:
                yield cur_ntype, cur_nodes
                cur_nodes = [(nid, node)]
                cur_ntype = type(node)
        yield cur_ntype, cur_nodes

    def tables(self, html=False) -> str:
        from tabulate import tabulate

        def fmt_val(val):
            if isinstance(val, Subgraph):
                return f"{type(val.root_cursor).__qualname__}({hex(id(val))})"
            return val

        if html:
            ret = [
                f'<p><b>Subgraph {type(self.root_cursor).__qualname__}({hex(id(self))}):</b></p>'
            ]
        else:
            ret = [f"Subgraph {type(self.root_cursor).__qualname__}({hex(id(self))}):"]

        for ntype, nodes in self.iter_tables():
            if not html:
                ret.append(ntype._cursor_type.__name__)
            table = []
            for nid, node in nodes:
                table.append([nid] + [fmt_val(val) for val in tuple.__iter__(node)])

            table_str = tabulate(
                table,
                headers = ['nid']+[ad.name for ad in ntype._layout],
                tablefmt="html" if html else "github"
                )
            if html:
                heading = f'<div class="ordb-table-heading">{ntype._cursor_type.__name__}</div>'
                table_str = table_str.replace('<table>', f'{heading}<div class="ordb-table"><table>', 1)
                table_str = table_str.replace('</table>', '</table></div>', 1)
            ret.append(table_str)
        return "\n".join(ret).replace('\n', '\n  ')

    def arrays(self, ntype: type, partial: bool=False) -> 'dict[str, numpy.ndarray]':
        """
        Returns all nodes of an arrayable node type (Node.arrayable) as
        read-only int64 arrays: 'nid' plus one array per attribute, rows
        ordered by nid. Raises ValueError if a node has values that are None
        or outside the int64 range; with partial, such nodes are left out.
        """
        from .arrays import arrays
        return arrays(self, ntype, partial)

    def node_dict(self, mode='canonical') -> dict[int,NodeTuple]:
        """
        Returns an ordered dict of nodes (values) by their nids (keys).

        Args:
            mode: If 'canonical', the return dict is ordered by nid. If 'pretty',
                the return dict is ordered by node type and nid.
        """
        if mode == 'canonical':
            return {nid: self.row(nid) for nid in self.nids()}
        elif mode == 'pretty':
            def sortkey(ntuple):
                return (
                    not issubclass(ntuple._cursor_type, SubgraphRoot), # 1. Sort SubgraphRoot to front.
                    ntuple.__name__, # 2. Sort alphabetically by ntype name.
                )
            return {nid: self.row(nid)
                for ntuple in sorted(self.ntuples(), key=sortkey)
                for nid in self.nids(ntuple)} # 3. Sort by nid
        else:
            raise ValueError("mode must be 'canonical' or 'pretty'")

    def matches(self, other: 'Subgraph') -> bool:
        """
        Check whether two subgraphs match regardless of nid numbers. While the nids
        and LocalRefs are ignored, the nid order (i.e. insertion order) must match
        for equivalence.

        This operation is based on canonical node lists.

        TODO: It is not clear whether this function is needed at all. Furthermore,
        ExternalRefs are not handled.
        """
        if not isinstance(other, Subgraph):
            return False

        nd_self = self.node_dict()
        nd_other = other.node_dict()
        if len(nd_self) != len(nd_other):
            return False

        self_to_other_nid = {}
        for item_self, item_other in zip(nd_self.items(), nd_other.items()):
            nid_self, n_self = item_self
            nid_other, n_other = item_other
            if type(n_self) != type(n_other):
                return False
            self_to_other_nid[nid_self] = nid_other

        for item_self, item_other in zip(nd_self.items(), nd_other.items()):
            nid_self, n_self = item_self
            nid_other, n_other = item_other

            n_self_translated = n_self.translate_nids(self_to_other_nid)
            if n_self_translated != n_other:
                return False

        return True

    def internally_equal(self, other) -> bool:
        if not isinstance(other, Subgraph):
            raise TypeError("Expected Subgraph.")
        return self._content_eq(other)

    def dump(self) -> str:
        d = self.node_dict('canonical')
        return 'MutableSubgraph.load({\n' + ''.join([f'\t{k!r}: {v!r},\n' for k, v in d.items()]) + '})'

    @property
    def nodes(self) -> Mapping:
        """A read-only mapping of nids to :class:`NodeTuple` instances,
        materialized on access (slow for bulk use; see :meth:`row`,
        :meth:`nids` and :meth:`arrays`)."""
        return NodesView(self)

    @property
    def backend(self) -> StorageBackend:
        """The storage engine this subgraph was created with."""
        return get_backend(self.engine)

    # Abstract methods
    # ----------------

    # We want the interfaces of our subclasses (FrozenSubgraph and MutableSubgraph)
    # to be as similar as possible.

    @property
    @abstractmethod
    def mutable(self) -> bool:
        """Returns True if Subgraph is mutable, False if frozen."""
        pass

    @abstractmethod
    def freeze(self) -> 'FrozenSubgraph':
        """Create :class:`FrozenSubgraph` from :class:`MutableSubgraph`.
        Future modifications of the original MutableSubgraph are not visible at
        the FrozenSubgraph."""
        pass

    @abstractmethod
    def thaw(self) -> 'MutableSubgraph':
        """Create :class:`MutableSubgraph` from :class:`FrozenSubgraph`.
        Future modifications of the MutableSubgraph are not visible at the
        original FrozenSubgraph."""
        pass

    @abstractmethod
    def mutable_copy(self) -> 'MutableSubgraph':
        """Create :class:`MutableSubgraph` copy.
        Future modifications of the MutableSubgraph are not visible at the
        original FrozenSubgraph."""
        pass

    @abstractmethod
    def copy(self) -> 'Self':
        """Returns a copy of the subgraph."""
        pass

    # Mutating methods, disabled for FrozenSubgraph via SubgraphUpdater
    # -----------------------------------------------------------------

    def updater(self) -> SubgraphUpdater:
        return SubgraphUpdater(self)

    def remove_nid(self, nid: int):
        with self.updater() as u:
            u.remove_nid(nid)

    def update(self, node: NodeTuple, nid: int) -> int:
        with self.updater() as u:
            u.update(node, nid)

    def add(self, node: Inserter) -> int:
        """Inserts node and returns nid."""
        if isinstance(node, NodeTuple):
            return self._add1(node).nid
        with self.updater() as u:
            return node.insert_into(u, u.nid_generate())

@public
class FrozenSubgraph(Subgraph):
    """
    FrozenSubgraph has custom __hash__ and __eq__ methods, which treat subgraphs
    with the equal nodes and nid_alloc as equal. Thus, its hash() and ==
    behavior matches that of immutable types like tuple and str.
    """

    __slots__ = ()

    def __new__(cls, *args, **kwargs):
        raise TypeError("FrozenSubgraphs are created by MutableSubgraph.freeze().")

    def __copy__(self) -> 'FrozenSubgraph':
        return self # Since FrozenSubgraph is immutable, copies are never needed?!

    # Wire-layer API: canonical CBOR serialization and session-scoped
    # hashing. The implementation lives in ordec.core.wire, which depends on
    # this module; the deferred imports below keep that dependency one-way
    # at import time.

    def wire_encode(self, ept) -> bytes:
        """
        Canonical CBOR wire bytes of this subgraph, with LiveRefs exported
        via the given ExportTable. Nested SubgraphRefs are represented by
        their wire_hash; use wire_deps() to collect the referenced subgraphs
        for transmission. The wire hash is a digest of these bytes and is
        memoized as a side effect.
        """
        from ..wire import encode_subgraph, hash_wire_bytes
        data = encode_subgraph(self, ept)
        self._cached_wire_hash = (ept, hash_wire_bytes(data))
        return data

    def wire_hash(self, ept) -> bytes:
        """
        Endpoint-scoped SHA-256 wire hash (32 bytes) of this subgraph under
        the given ExportTable, memoized per table (single entry; the normal
        case is one table per connection). Covers transitive SubgraphRef
        dependencies (Merkle-style).
        """
        cached = self._cached_wire_hash
        if cached is not None and cached[0] is ept:
            return cached[1]
        from ..wire import encode_subgraph, hash_wire_bytes
        h = hash_wire_bytes(encode_subgraph(self, ept))
        # Returned via the local, not by re-reading the memo slot: a
        # concurrent wire_hash/wire_encode under another ExportTable may
        # overwrite the slot in between with that table's hash.
        self._cached_wire_hash = (ept, h)
        return h

    def wire_deps(self, ept) -> dict:
        """
        Transitive SubgraphRef dependencies of this subgraph, keyed by their
        wire_hash under the given ExportTable. Suitable as the deps argument
        of ordec.core.wire.wire_decode.
        """
        from ..wire import collect_wire_deps
        return collect_wire_deps(self, ept)

    def copy(self):
        return self # No need to copy frozen subgraph

    @property
    def mutable(self):
        return False

    def thaw(self) -> 'MutableSubgraph':
        """
        Create new mutable subgraph existing immutable subgraph.
        """
        return self._snapshot(MutableSubgraph, False)

    def mutable_copy(self):
        return self.thaw()

    def compact(self) -> 'FrozenSubgraph':
        """
        Return a content-equal FrozenSubgraph with compacted storage (no
        tombstones, tables in nid order, one run per index).
        """
        ret = self._snapshot(FrozenSubgraph, True)
        ret._compact()
        return ret

    def __eq__(self, other):
        if not isinstance(other, FrozenSubgraph):
            return False
        if self is other:
            return True
        return self._content_eq(other)

    def __hash__(self):
        return self._content_hash()

    def freeze(self) -> 'FrozenSubgraph':
        raise TypeError("Subgraph is already frozen.")

    def updater(self) -> SubgraphUpdater:
        # This is not really needed, as the updater would refuse anyway,
        # but it will raise the error earlier.
        raise TypeError("Unsupported operation on FrozenSubgraph.")

@public
class MutableSubgraph(Subgraph):
    """
    MutableSubgraph does not override object.__eq__ and object.__hash__. Thus,
    hash() and == behavior is based purely on the id() / address of a
    MutableSubgraph. In contrast to the FrozenSubgraphs, a copy of a
    MutableSubgraph is not equal to the original and has a different hash.

    An alternative approach here would be to use the same __eq__ as
    FrozenSubgraph does. In this case, we would end up with with an unhashable
    type, which we can for example not use as key in dictionaries. We want
    MutableSubgraphs and MutableNodes (which reference MutableSubgraphs) to be
    hashable. Therefore, the default object behavior is the one that seems
    most sensible.

    To compare two MutableSubgraphs a and b for internal equivalence, either do
    a.freeze() == b.freeze() or subgraphs_match(a, b).
    """
    __slots__=()

    def __new__(cls, backend: StorageBackend = None):
        if backend is None:
            backend = default_backend()
        return super().__new__(cls, engine=backend.code)

    @property
    def mutable(self):
        return True

    def thaw(self) -> 'MutableSubgraph':
        raise TypeError("Subgraph is already mutable.")

    def mutable_copy(self):
        return self.copy()

    @classmethod
    def load(cls, nodes: dict[int,NodeTuple]):
        s = cls()
        with s.updater() as u:
            for nid, node in nodes.items():
                u.add_single(node=node, nid=nid)
        return s.root_cursor

    def __copy__(self) -> 'MutableSubgraph': # For Python's copy module
        return self._snapshot(MutableSubgraph, False)

    def copy(self) -> 'MutableSubgraph':
        """
        Create new mutable subgraph from existing mutable subgraph.
        """
        return self.__copy__()

    def freeze(self):
        return self._snapshot(FrozenSubgraph, True)

@public
class PathNode(NonLeafNode):
    """
    PathNode represents an empty path of a subgraph. Its selected nid is None,
    but it selects some path_nid.

    PathNode.Tuple has always length zero and is never inserted into a subgraph.
    """

@public
class NPath(Node):
    """
    NPath.Tuple is used to build a subgraph's path hierarchy. NPath itself
    (rather than NPath.Tuple) is never instantiated. Instead, reference an
    empty path (NPath with ref = None) use :class:`PathNode`. Non-empty
    paths (NPath.Tuple X with X.ref is not None) are referenced through the Node
    class correponding to X.ref.
    """
    @staticmethod
    def check_name(name: str|int):
        if isinstance(name, str):
            if (len(name) < 1) or (name[0] not in string.ascii_letters+'_'):
                raise ValueError("NPath name that is string must start with ASCII letter or underscore.")
            return name
        elif isinstance(name, int):
            return name
        else:
            raise TypeError("NPath name must be int or str.")

    @classmethod
    def raw_cursor(cls, subgraph: 'Subgraph', nid: int|NoneType, npath_nid: int|NoneType):
        raise TypeError("raw_cursor of NPath not supported. Use PathNode instead.")

    parent  = LocalRef('NPath', refcheck_custom=lambda val: issubclass(val, NPath))
    name    = Attr(str|int, factory=check_name,
        typecheck_custom=lambda val: isinstance(val, (str, int)))
    ref     = LocalRef(Node, refcheck_custom=lambda v: True)

    idx_parent = Index(parent)
    idx_parent_name = NPathIndex([parent, name], unique=True)
    idx_path_of = Index(ref, unique=True)

    in_subgraphs = [SubgraphRoot]
    wire_id = WIRE_DOMAIN | 1

# Callbacks of the native core
# ----------------------------

def _check_callback(kind: int, sgu: SubgraphUpdater, nid: int, obj):
    """
    Called by the native core when a commit check did not pass its fast
    path. Repeats the check in Python and raises the exact exception; if the
    check passes here after all, the core accepts the node.
    """
    sg = sgu.target_subgraph
    if kind == 6:
        raise ModelViolation("Missing root node (nid 0).")
    if kind == 5:
        raise DanglingLocalRef(nid)
    node = sg.row(nid)
    if kind == 0:
        root_cls = sg.row(0)._cursor_type
        if not any(issubclass(root_cls, cls) for cls in node._cursor_type.in_subgraphs):
            raise ModelViolation(f"{node._cursor_type.__name__} is not permitted in subgraph {root_cls.__name__}.")
    elif kind == 1:
        raise ModelViolation(f"{node._attrdesc_by_attr[obj].name!r} is not optional (but set to None).")
    elif kind in (2, 3):
        next(ns for ns in obj.indices if isinstance(ns, (LocalRefIndex, ExternalRefIndex))) \
            .check_constraints(sgu, node, nid)
    elif kind == 4:
        obj.check_constraints(sgu, node, nid)

_ordb._setup(
    OrdbException=OrdbException,
    QueryException=QueryException,
    check_callback=_check_callback,
    updater_class=SubgraphUpdater,
    pathnode_mutable=PathNode.Mutable,
    pathnode_frozen=PathNode.Frozen,
    npath_index=NPath.idx_path_of,
    npath_child_index=NPath.idx_parent_name,
)
