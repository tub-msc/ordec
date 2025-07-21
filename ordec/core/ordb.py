# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from pyrsistent import pmap, pvector, pset, PMap, PVector, PSet
from typing import Callable, Iterable
from typing import NamedTuple
from types import NoneType
from dataclasses import dataclass, field
from abc import ABC, ABCMeta, abstractmethod
import bisect
import string
from public import public

@public
class OrdbException(Exception):
    pass

@public
class QueryException(OrdbException):
    pass

@public
class ModelViolation(OrdbException):
    pass

@public
class Inserter(ABC):
    __slots__=()
    @abstractmethod
    def insert_into(self, sgu):
        pass

@public
class FuncInserter(Inserter):
    __slots__=("insert_into",)
    def __init__(self, inserter_func):
        self.insert_into = inserter_func

class IndexKey(NamedTuple):
    index: 'Index'
    value: tuple|int

class IndexQuery(NamedTuple):
    index_key: IndexKey

class GenericIndex(ABC):
    @abstractmethod
    def index_add(self, sgu: 'SubgraphUpdater', node, nid):
        """This method must not fail on constraint violations!"""
        pass

    @abstractmethod
    def index_remove(self, sgu: 'SubgraphUpdater', node, nid):
        """This method must not fail on constraint violations!"""
        pass
    
    @abstractmethod
    def check_contraints(self, sgu: 'SubgraphUpdater', node, nid):
        pass

@public
@dataclass(frozen=True, eq=True)
class UniqueViolation(ModelViolation):
    index: GenericIndex
    value: tuple

@public
@dataclass(frozen=True, eq=True)
class DanglingLocalRef(ModelViolation):
    nid: int

@public
@dataclass(frozen=False, eq=False)
class Attr:
    """
    Schema attribute for use in Node subclasses. # TODO: update this doc
    """

    def default_factory(val):
        if isinstance(val, Node):
            raise TypeError("Nodes can only be added to LocalRef, ExternalRef or SubgraphRef attributes.")
        return val

    type: type
    default: object = None
    indices : list[GenericIndex] = field(default_factory=list)
    factory: Callable = default_factory

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
        if obj == None: # for the class: return NodeAttrDescriptor object
            return self
        else: # for instances: return value of attribute
            assert owner == self.ntype.Tuple
            return obj[self.index]

    def __repr__(self):
        return f"NodeTupleAttrDescriptor({self.ntype.__name__}.{self.name})"

@dataclass(frozen=True, eq=False)
class NodeAttrDescriptor:
    """Like NodeTupleAttrDescriptor, but for the Node instead of the NodeTuple"""
    ntype: type
    index: int
    name: str
    attr: Attr

    def __get__(self, cursor, owner=None):
        if cursor == None: # for the class: return Attr object
            return self.attr
        else: # for instances: return value of attribute
            assert issubclass(owner, self.ntype)
            #return cursor.node[self.index]
            return self.attr.read_hook(cursor.node[self.index], cursor)

    def __set__(self, cursor, value):
        cursor.subgraph.update(cursor.node.set_index(self.index, value), cursor.nid)

    def __delete__(self, cursor):
        raise TypeError("Attributes cannot be deleted.")

@public
@dataclass(frozen=False, eq=False)
class LocalRef(Attr):
    """
    Reference to a node in the same subgraph by nid.
    """
    refs_ntype: type = None
    type: type = int
    optional: bool = True
    def __post_init__(self):
        self.indices.append(LocalRefIndex(self))

    @staticmethod
    def localref_factory(val: 'int|Node|NoneType'):
        if val==None or isinstance(val, int):
            return val
        elif isinstance(val, Node):
            return val.nid
        else:
            raise TypeError('Only None, int or Node can be assigned to LocalRef.')

    factory: Callable = localref_factory

    def read_hook(self, value, cursor):
        if value is None:
            return value
        else:
            return cursor.subgraph.cursor_at(value)

@public
@dataclass(frozen=False, eq=False)
class ExternalRef(Attr):
    """
    Reference to a node in another subgraph by nid.
    """
    refs_ntype: type = None
    of_subgraph: Callable = None
    type: type = int
    optional: bool = True

    def read_hook(self, value, cursor):
        return self.of_subgraph(cursor).cursor_at(value)

    @staticmethod
    def externalref_factory(val: 'int|Node|NoneType'):
        if val==None or isinstance(val, int):
            return val
        elif isinstance(val, Node):
            return val.nid
        else:
            raise TypeError('Only None, int or Node can be assigned to ExternalRef.')

    factory: Callable = externalref_factory

@public
@dataclass(frozen=False, eq=False)
class SubgraphRef(Attr):
    """
    Reference to a node in another subgraph by nid.
    """
    refs_cursortype: type = None
    type: type = 'FrozenSubgraph'
    optional: bool = True

    def read_hook(self, value, cursor):
        return value.root_cursor

    @staticmethod
    def externalref_factory(val: 'FrozenSubgraph|SubgraphRoot|NoneType'):
        if val==None or isinstance(val, FrozenSubgraph):
            return val
        elif isinstance(val, Node):
            if val.subgraph.mutable:
                raise TypeError('SubgraphRoot for externalref_factory must be frozen.')
            return val.subgraph
        else:
            raise TypeError('Only None, FrozenSubgraph or SubgraphRoot can be assigned to SubgraphRef.')

    factory: Callable = externalref_factory


@public
class Index(GenericIndex):
    def __init__(self, attr: Attr, unique:bool=False, sortkey: Callable=None):
        self.attr = attr
        self.unique = unique
        self.sortkey = sortkey
      
        attr.indices.append(self)

    def index_key(self, node, nid):
        val = node[node._attrdesc_by_attr[self.attr].index]
        if val == None:
            return None
        else:
            return IndexKey(self, val)

    def index_value(self, node, nid):
        return nid

    def index_add(self, sgu: 'SubgraphUpdater', node, nid):
        # This method must not fail on constraint violations!
        key = self.index_key(node, nid)
        if key == None:
            return
        value = self.index_value(node, nid)
        values = sgu.index.get(key, pvector())
        if self.sortkey:
            insert_at = bisect.bisect_left(values, self.sortkey(node),
                key = lambda nid_here: self.sortkey(sgu.nodes[nid_here]))
        else:
            insert_at = bisect.bisect_left(values, value)
        if insert_at == len(values):
            values = values.append(value)
        else:
            # TODO: This is probably inefficient with pyrsistent, but maybe we can make this case rare.
            values = values[:insert_at].append(value) + values[insert_at:]

        sgu.index = sgu.index.set(key, values)

    def index_remove(self, sgu: 'SubgraphUpdater', node, nid):
        # This method must not fail on constraint violations!
        key = self.index_key(node, nid)
        if key == None:
            return
        value = self.index_value(node, nid)
        values = sgu.index[key]
        values = values.remove(value)
        if len(values) > 0:
            sgu.index = sgu.index.set(key, values)
        else:
            sgu.index = sgu.index.remove(key)
    
    def check_contraints(self, sgu: 'SubgraphUpdater', node, nid):
        if self.unique:
            key = self.index_key(node, nid)
            if not key:
                return
            vals = sgu.index[key]
            if len(vals) > 1:
                raise UniqueViolation(self, key)
            else:
                assert vals == pvector((self.index_value(node, nid), ))

    def __repr__(self):
        return f"<{type(self).__name__} {id(self):x}>"

    def query(self, key):
        return IndexQuery(IndexKey(self, key))

@public
class CombinedIndex(Index):
    def __init__(self, attrs: list[Attr], unique:bool=False, sortkey: Callable=None):
        self.attrs = attrs
        self.unique = unique
        self.sortkey = sortkey
        for attr in self.attrs:
            attr.indices.append(self)

    def index_key(self, node, nid):
        return IndexKey(self, tuple((node[node._attrdesc_by_attr[a].index] for a in self.attrs)))

class NTypeIndex(Index):
    def __init__(self):
        self.sortkey = None

    def index_key(self, node, nid):
        return type(node)

    def index_value(self, node, nid):
        return nid

    def query(self, key):
        return IndexQuery(key)

class LocalRefIndex(Index):
    """
    LocalRefIndex is meant for integrity checking only. For lookups, use a separate fine-grained index.

    LocalRefIndex uses pset instead of pvector as its keys cannot be ordered meaningfully.
    """
    def index_key(self, node, nid):
        ref = node[node._attrdesc_by_attr[self.attr].index]
        if ref == None:
            return None
        else:
            return ref

    def index_value(self, node, nid):
        return IndexKey(self, nid)

    def index_add(self, sgu: 'SubgraphUpdater', node, nid):
        key = self.index_key(node, nid)
        if key == None:
            return
        value = self.index_value(node, nid)
        values = sgu.index.get(key, pset())
        values = values.add(value)
        sgu.index = sgu.index.set(key, values)

    def index_remove(self, sgu: 'SubgraphUpdater', node, nid):
        key = self.index_key(node, nid)
        if key == None:
            return
        value = self.index_value(node, nid)
        values = sgu.index[key]
        values = values.remove(value)
        if len(values) > 0:
            sgu.index = sgu.index.set(key, values)
        else:
            sgu.index = sgu.index.remove(key)

    def check_contraints(self, sgu: 'SubgraphUpdater', node, nid):
        ref = node[node._attrdesc_by_attr[self.attr].index]

        if node._attrdesc_by_attr[self.attr].attr.optional and ref == None:
            return
        if not isinstance(ref, int):
            raise ModelViolation("LocalRefs must be int (or None if optional).")

        if ref not in sgu.nodes:
            raise DanglingLocalRef(ref)

class NPathIndex(CombinedIndex):
    def check_contraints(self, sgu: 'SubgraphUpdater', node, nid):
        try:
            super().check_contraints(sgu, node, nid)
        except UniqueViolation:
            raise ModelViolation("Path exists") # TODO: Report actual path?

# TODO: fix docs: Nodes subclasses make up the schema (like table definitions). Node instances are like database rows.

@public
class NodeTuple(tuple):
    """
    Why is this a custom tuple subclass rather than building upon PClass, NamedTuple, recordclass.dataobject or pydantic?

    - This is somewhere between NamedTuple and pyrsistent's PClass.
    - For PClass, the behaviour of field() is difficult to change without touching everything.
    - Also, the overhead of mutating PClass seems a bit high (just from reading the code).
    - Downside of all tuples compared to PClass: all attribute references must be copied when a single attribute is updated
    - Sublassing NamedTuple is cursed (no inheritance etc.)
    - recordclass.dataobject would be an additional dependency, and its readonly=True option seems to be a (buggy) afterthought only.
    - pydantic is too heavyweight.
    """

    __slots__ = ()

    def check_hashable(self):
        try:
            hash(self)
        except TypeError:
            raise TypeError("All attributes of NodeTuple must be hashable.")

    def __new__(cls, **kwargs):
        ret=super().__new__(cls, (ad.attr.factory(kwargs.pop(ad.name)) if (ad.name in kwargs) else ad.attr.default for ad in cls._layout))
        if len(kwargs) > 0:
            unknown_attrs = ', '.join(kwargs.keys())
            raise AttributeError(f"Unknown attributes provided: {unknown_attrs}")
        ret.check_hashable()
        return ret

    def vals_repr(self):
        return ', '.join([f"{ad.name}={self[ad.index]!r}" for ad in self._layout])

    def __repr__(self):
        return f"{type(self).__name__}({self.vals_repr()})"

    def set(self, **kwargs):
        # Bypasses NodeTuple.__new__:

        ret=super().__new__(type(self), (ad.attr.factory(kwargs.pop(ad.name)) if (ad.name in kwargs) else self[ad.index] for ad in self._layout))
        if len(kwargs) > 0:
            unknown_attrs = ', '.join(kwargs.keys())
            raise AttributeError(f"Unknown attributes provided: {unknown_attrs}")
        ret.check_hashable() # We could also check only the updated values for hashability.
        return  ret 

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
        ret=super().__new__(type(self), (nid_map[self[ad.index]] if ad.is_nid() and self[ad.index]!=None else self[ad.index] for ad in self._layout))
        return ret

    def index_add(self, sgu: 'SubgraphUpdater', nid):
        self.index_ntype.index_add(sgu, self, nid)
        for ns in self.indices:
            ns.index_add(sgu, self, nid)

    def index_remove(self, sgu: 'SubgraphUpdater', nid):
        self.index_ntype.index_remove(sgu, self, nid)
        for ns in self.indices:
            ns.index_remove(sgu, self, nid)

    def check_contraints(self, sgu: 'SubgraphUpdater', nid):
        for ns in self.indices:
            ns.check_contraints(sgu, self, nid)

    def insert_into(self, sgu):
        return sgu.add_single(self, sgu.nid_generate())

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

    index_ntype = NTypeIndex()
    "Subgraph-wide index of nodes by their type (table)"

# Register NodeTuple as virtual subclass of Inserter. Combining tuple and ABC seems like it could cause problems.
Inserter.register(NodeTuple)

class NodeMeta(type):
    @staticmethod
    def _collect_raw_attrs(d, bases):
        raw_attrs = {} # The order in raw_attrs defines the tuple layout later on.

        # First come inherited attributes:
        for b in bases:
            try:
                raw_attrs |= b._raw_attrs
            except AttributeError:
                pass

        # Then newly added attributes:
        for k, v in list(d.items()):
            if isinstance(v, Attr):
                raw_attrs[k] = v
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
            # Build descriptors from raw attributes:
            attrdesc_by_attr = {}
            attrdesc_by_name = {}
            nodetuple_dict = {'_raw_attrs': cls._raw_attrs, '__slots__':()}
            layout = []
            #attrs.setdefault('__annotations__', {})
            cls.__annotations__ = {}
            nt_indices = []

            for n, (k, v) in enumerate(cls._raw_attrs.items()):
                nt_ad = NodeTupleAttrDescriptor(ntype=cls, index=n, name=k, attr=v)
                nodetuple_dict[k] = nt_ad
                c_ad = NodeAttrDescriptor(ntype=cls, index=n, name=k, attr=v)
                setattr(cls, k, c_ad)
                cls.__annotations__[k] = v.type # Not so nice; for Sphinx.
                layout.append(nt_ad)
                attrdesc_by_attr[v] = nt_ad
                attrdesc_by_name[k] = nt_ad
                for ns in v.indices:
                    if ns not in nt_indices:
                        nt_indices.append(ns)

            nodetuple_dict['indices'] = nt_indices
            nodetuple_dict['_attrdesc_by_name'] = attrdesc_by_name
            nodetuple_dict['_attrdesc_by_attr'] = attrdesc_by_attr
            nodetuple_dict['_layout'] = layout
            nodetuple_dict['_cursor_type'] = cls
            cls.Tuple = type(name+'.Tuple', (NodeTuple,), nodetuple_dict)
            cls.Mutable = type(name+'.Mutable', (cls, MutableNode), {'__slots__':()}, build_node=False)
            cls.Frozen = type(name+'.Frozen', (cls, FrozenNode), {'__slots__':()}, build_node=False)

            # Not sure whether this is a good idea, but it is nice for the
            # inheritance diagrams in the docs.
            cls.Tuple.__module__ = cls.__module__
            cls.Mutable.__module__ = cls.__module__
            cls.Frozen.__module__ = cls.__module__

        return super().__init__(name, bases, attrs)

@public
class Node(tuple, metaclass=NodeMeta, build_node=False):
    """
    Node provides a cursor-like access layer to NodeTuples within mutable or immutable subgraphs.

    Node objects are 3-tuples (subgraph, nid ,npath_nid).

    The hash() and == behviour of Node is implemented by tuple.__hash__ and
    tuple.__eq__ and relies on the hash() and == behavior of MutableSubgraph
    (for MutableNodes) or FrozenSubgraph (for FrozenNodes).
    """

    @classmethod
    def raw_cursor(cls, subgraph: 'Subgraph', nid: int|NoneType, npath_nid: int|NoneType):
        return super().__new__(cls, (subgraph, nid, npath_nid))

    def __new__(self, **kwargs):
        return self.Tuple(**kwargs)

    @property
    def subgraph(self) -> 'Subgraph':
        """The subgraph in which this Node moves."""
        return super().__getitem__(0)

    @property
    def nid(self) -> int|NoneType:
        """The nid of the node to which this Node points."""
        return super().__getitem__(1)

    @property
    def node(self):
        return self.subgraph.nodes[self.nid]

    @property
    def npath_nid(self) -> int|NoneType:
        """The nid of the NPath node matching the nid attribute."""    
        return super().__getitem__(2)

    @property
    def npath(self):
        if self.npath_nid == None:
            return None
        else:
            return self.subgraph.nodes[self.npath_nid]

    def full_path_list(self) -> list[str|int]:
        if self.nid == 0:
            # Root node special case:
            return []
        if not self.npath_nid:
            raise TypeError("Requested path of cursor without NPath.")
        here = [self.npath.name]
        if self.npath.parent == None:
            return here
        else:
            return self.parent.full_path_list() + here

    def full_path_str(self):
        it = iter(self.full_path_list())
        try:
            first = next(it)
        except StopIteration:
            return "root_cursor" # TODO: This seems wrong.

        ret = []
        if not isinstance(first, str):
            raise TypeError("First element of full path must be a string.")
        ret.append(first)

        for elem in it:
            if isinstance(elem, int):
                ret.append(f'[{elem!r}]')
            elif isinstance(elem, str):
                ret.append(f".{elem}")
            else:
                raise TypeError("Path must only contain str and int.")

        return ''.join(ret)

    def __repr__(self):
        info = []
        if self.npath_nid != None:
            info.append(f"path={self.full_path_str()}")
        if self.nid != None:
            info.append(f"nid={self.nid}")
            info.append(self.node.vals_repr())

        return f"{type(self).__name__}({', '.join(info)})"

    @property
    def parent(self):
        if self.npath == None:
            raise QueryException("Subgraph root has no parent.")
        if self.npath.parent == None:
            return self.subgraph.root_cursor
        else:
            npath_next_nid = self.npath.parent
            npath_next = self.subgraph.nodes[npath_next_nid]
            return self.subgraph.cursor_at(npath_next.ref, npath_next_nid)

    def update(self, **kwargs):
        self.subgraph.update(self.node.set(**kwargs), self.nid)

    def delete(self):
        if self.npath_nid != None:
            self.subgraph.remove_nid(self.npath_nid)
        if self.nid != None:
            self.subgraph.remove_nid(self.nid)

    def __mod__(self, node: Inserter) -> 'Node':
        """
        Inserts node and sets 'ref' attribute (which should be a LocalRef) to the cursor nid.
        """
        if isinstance(node, NodeTuple):
            # Simple case: just update the node before inserting:
            # This could also be done by the complex case below, so this is a performance optimization:
            nid_new = self.subgraph.add(node.set(ref=self.nid))
        else:
            # Complex case:
            def inserter_func(sgu):
                main_nid = node.insert_into(sgu)
                sgu.update(sgu.nodes[main_nid].set(ref=self.nid), main_nid)
                return main_nid
            nid_new = self.subgraph.add(FuncInserter(inserter_func))
        # Optimization: lookup_npath is disabled, because this newly added node has no NPath.
        return self.subgraph.cursor_at(nid_new, lookup_npath=False)

    @property
    def root(self):
        return self.subgraph.root_cursor

    @property
    def mutable(self):
        raise TypeError("n.mutable is unavailable where n is not subclass of MutableNode or FrozenNode.")

    def __copy__(self) -> 'Self':
        return self # tuple is immutable (at shallow level), thus no copy needed.


@public
class NonLeafNode(Node, build_node=False):
    # Attribute handlers wrapping the item handlers below
    # ---------------------------------------------------

    def __getattr__(self, k):
        # If attribute is not found, look for k as subpath:
        
        try:
            return self.__getitem__(k)
        except QueryException as e:
            # IPython needs an AttributeError here, else it does not use _repr_html_.
            raise AttributeError(*e.args) from None

    def __setattr__(self, k, v):
        try:
            # This triggers __set__ of descriptors such as NodeAttrDescriptor:
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

    # Item handlers (subpaths)
    # ------------------------

    def __setitem__(self, k, v):
        with self.subgraph.updater() as u:
            v_nid = v.insert_into(u)
            self.mkpath_addnode(k, v_nid, u)

    def __getitem__(self, k):
        """Returns cursor to a subpath."""
        
        try:
            npath_next_nid = self.subgraph.one(NPath.idx_parent_name.query((self.npath_nid, k)), wrap_cursor=False)
        except QueryException:
            raise QueryException(f"Attribute or path {k!r} not found.") from None
        npath_next_ref = self.subgraph.nodes[npath_next_nid].ref
        return self.subgraph.cursor_at(npath_next_ref, npath_next_nid)

    def __delitem__(self, k):
        self.__getitem__(k).delete()

    def mkpath(self, k, ref=None):
        with self.subgraph.updater() as u:
            self.mkpath_addnode(k, ref, u)
            
    def mkpath_addnode(self, k, ref, u: 'SubgraphUpdater'):
        """Creates NPath node below current cursor. NPath node is empty when ref=None."""
        if self.nid not in (None, 0):
            if self.npath_nid == None:
                raise OrdbException("Cannot add node at cursor without NPath.")
        NPath(parent=self.npath_nid, name=k, ref=ref).insert_into(u)

@public
class FrozenNode(Node, build_node=False):
    @property
    def mutable(self):
        return False

@public
class MutableNode(Node, build_node=False):
    @property
    def mutable(self):
        return True

@public
class PathNode(NonLeafNode):
    pass

@public
class SubgraphRoot(NonLeafNode):
    """
    Each subgraph has a single SubgraphRoot node. The subclass of SubgraphRoot
    defines what kind of design data the subgraph represents.
    """

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
        nid_new = self.subgraph.add(node)
        # Optimization: lookup_npath is disabled, because this newly added node has no NPath.
        return self.subgraph.cursor_at(nid_new, lookup_npath=False)

    # Convenience forwards to self.subgraph
    # -------------------------------------

    def updater(self) -> 'SubgraphUpdater':
        return SubgraphUpdater(self.subgraph)

    def cursor_at(self, *args, **kwargs) -> Node:
        return self.subgraph.cursor_at(*args, **kwargs)

    def all(self, *args, **kwargs) -> Iterable[Node]:
        return self.subgraph.all(*args, **kwargs)

    def one(self, *args, **kwargs) -> Node:
        return self.subgraph.one(*args, **kwargs)

    def matches(self, other):
        if not isinstance(other, SubgraphRoot):
            return False
        assert other.nid == 0
        return self.subgraph.matches(other.subgraph)

    def freeze(self):
        return self.subgraph.freeze().root_cursor

    def thaw(self):
        return self.subgraph.thaw().root_cursor

    def tables(self) -> str:
        return self.subgraph.tables()

    def dump(self) -> str:
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

class SubgraphUpdater:
    """
    A SubgraphUpdater collects changes to a subgraph as a kind of
    transaction. The SubgraphUpdater is used in a 'with' context. When this
    context is exited, the current state of SubgraphUpdater is checked for
    consistency. When no problem is found, the MutableSubgraph from which the
    SubgraphUpdater was created is updated.
    """
    __slots__ = (
        'target_subgraph',
        'nodes',
        'index',
        'commit',
        'check_nids',
        'removed_nids',
        'valid',
        'nid_gen_counter',
        'nid_max_encountered',
    )

    def __init__(self, target_subgraph: 'Subgraph'):
        self.target_subgraph = target_subgraph
        self.valid = False

    def __enter__(self):
        #if not self.target_subgraph.mutable:
        #    raise OrdbException("Frozen Subgraph is immutable.")
        self.nid_gen_counter = self.target_subgraph.nid_alloc.start
        self.nid_max_encountered = self.target_subgraph.nid_alloc.start-1
        
        self.nodes = self.target_subgraph.nodes
        self.index = self.target_subgraph.index
        self.commit = True
        self.check_nids = {} # used as ordered set
        self.removed_nids = {} # used as ordered set
        self.valid = True
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type:
            self.commit = False
        if self.commit:
            if 0 not in self.nodes:
                raise ModelViolation("Missing root node (nid 0).")

            for nid in self.check_nids:
                self.nodes[nid].check_contraints(self, nid)

            for nid in self.removed_nids:
                if nid in self.index:
                    raise DanglingLocalRef(nid)

            self.target_subgraph.mutate(self.nodes, self.index, range(self.nid_max_encountered+1, self.target_subgraph.nid_alloc.stop))

        self.valid = False

    def nid_generate(self):
        if self.nid_gen_counter not in self.target_subgraph.nid_alloc:
            raise OrdbException("nid allocation exhausted.")
        ret = self.nid_gen_counter
        self.nid_gen_counter += 1
        return ret

    def add_single(self, node: NodeTuple, nid: int) -> int:
        """
        Args:
            relaxed: Set to True to relax nid insertion order.
        Returns:
            nid of inserted node
        """
        if not self.valid:
            raise TypeError("Invalid SubgraphUpdater.")
        
        if not isinstance(node, NodeTuple):
            raise TypeError("node must be instance of NodeTuple.")

        if nid not in self.target_subgraph.nid_alloc:
            raise OrdbException(f"selected nid {nid} is outside allocated {self.target_subgraph.nid_alloc}.")

        if nid in self.nodes:
            raise OrdbException("Duplicate nid.")

        self.nid_max_encountered = max(self.nid_max_encountered, nid)
        self.nid_gen_counter = max(self.nid_gen_counter, self.nid_max_encountered+1)

        node.index_add(self, nid) # Update metadata first.
        self.nodes = self.nodes.set(nid, node) # Then add node.
        self.check_nids[nid] = True # Mark node for deferred constraint check.
        # Remove from removed_nids, in case it was removed in same SubgraphUpdater and is now re-added:
        self.removed_nids.pop(nid, None)

        return nid

    def remove_nid(self, nid):
        if not self.valid:
            raise TypeError("Invalid SubgraphUpdater.")
        
        if nid == 0:
            raise OrdbException("Cannot delete SubgraphRoot (nid=0).")
        node = self.nodes[nid]
        
        node.index_remove(self, nid) # Update metadata first.
        self.nodes = self.nodes.remove(nid) # Then remove node.
        self.check_nids.pop(nid, None) # Skip constraint check for this node, if it was previously selected.
        self.removed_nids[nid] = True # Mark nid as removed.

    def update(self, node: NodeTuple, nid: int):
        if not self.valid:
            raise TypeError("Invalid SubgraphUpdater.")

        if nid not in self.nodes:
            raise KeyError(f"nid {nid} not found in {self}")
        self.nodes[nid].index_remove(self, nid)
        self.nodes = self.nodes.set(nid, node)
        node.index_add(self, nid)

        self.check_nids[nid] = True # Mark node for deferred constraint check.

@public
class Subgraph(ABC):
    # Using __slots__ to prevent accidental creation of 'stray' attributes.
    __slots__ = (
        '_nodes',
        '_index',
        '_nid_alloc',
        '_root_cursor',
    )

    # Non-mutating methods
    # --------------------

    def __repr__(self):
        return f"<{type(self).__name__} {id(self)} root={self.nodes[0]!r}, {len(self.nodes)} nodes>"

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

    def tables(self) -> str:
        from tabulate import tabulate

        ret = [f'Subgraph {self.nodes[0]}:']
        for ntype, nodes in self.iter_tables():
            if issubclass(ntype._cursor_type, SubgraphRoot):
                continue
            ret.append(ntype._cursor_type.__name__)
            table = []
            for nid, node in nodes:
                table.append([nid]+[val for val in tuple.__iter__(node)])

            ret.append(tabulate(
                table,
                headers = ['nid']+[ad.name for ad in ntype._layout],
                tablefmt="github"
                ))
        return "\n".join(ret).replace('\n', '\n  ')

    def node_dict(self, mode='canonical') -> dict[int,NodeTuple]:
        """
        Returns an ordered dict of nodes (values) by their nids (keys).

        Args:
            mode: If 'canonical', the return dict is ordered by nid. If 'pretty',
                the return dict is ordered by node type and nid.
        """
        if mode == 'canonical':
            # sort by nid:
            sortkey = lambda item: item[0]
        elif mode == 'pretty':
            def sortkey_pretty(item):
                nid, node = item
                return (
                    not isinstance(node, SubgraphRoot), # 1. Sort SubgraphRoot to front.
                    type(node).__name__, # 2. Sort alphabetically by ntype name.
                    nid, # 3. Sort by nid
                )
            sortkey = sortkey_pretty
        else:
            raise ValueError("mode must be 'canonical' or 'pretty'")
        
        return {k: v for k, v in sorted(self.nodes.items(), key=sortkey)}

    def matches(self, other):
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
        return (self.nodes == other.nodes) and (self.nid_alloc == other.nid_alloc)

    def dump(self) -> str:
        d = self.node_dict('canonical')
        return 'MutableSubgraph.load({\n' + ''.join([f'\t{k!r}: {v!r},\n' for k, v in d.items()]) + '})'

    def all(self, query: IndexQuery, wrap_cursor:bool=True):
        if isinstance(query, type):
            assert issubclass(query, Node)
            query = NodeTuple.index_ntype.query(query.Tuple)
        try:
            nids = self.index[query.index_key]
        except KeyError:
            return ()
        else:
            if wrap_cursor:
                return (self.cursor_at(nid) for nid in nids)
            else:
                return nids

    def one(self, *args, **kwargs):
        def single(it):
            try:
                r = next(it)
            except StopIteration:
                raise QueryException("Query returned less than one element.")
            try:
                r = next(it)
            except StopIteration:
                return r
            else:
                raise QueryException("Query returned more than one element.")

        return single(iter(self.all(*args, **kwargs)))

    def cursor_at(self, nid: int, npath_nid: NoneType|int=None, lookup_npath: bool=True):
        if nid == None:
            # NPath without node
            assert npath_nid != None
            cursor_cls = PathNode
        else:
            cursor_cls = self.nodes[nid]._cursor_type
            if lookup_npath and npath_nid == None:
                try:
                    npath_nid = self.one(NPath.idx_path_of.query(nid), wrap_cursor=False)
                except QueryException:
                    pass
        if self.mutable:
            return cursor_cls.Mutable.raw_cursor(self, nid, npath_nid)
        else:
            return cursor_cls.Frozen.raw_cursor(self, nid, npath_nid)


    # The private _nodes, _index, _nid_alloc and _root_cursor are hidden behind
    # properties to prevent accidental mutation.

    @property
    def nodes(self) -> PMap:
        """A persistent mapping of nids to NodeTuples."""
        return self._nodes

    @property
    def index(self) -> PMap:
        """A persistent mapping of index keys to index values."""
        return self._index

    @property
    def nid_alloc(self) -> range:
        """An allocation range from which new nids must be generated."""
        return self._nid_alloc

    @property
    def root_cursor(self) -> Node:
        """Root cursor pointing to subgraph root."""
        return self._root_cursor

    # Abstract methods
    # ----------------

    # We want the interfaces of our subclasses (FrozenSubgraph and MutableSubgraph)
    # to be as similar as possible.

    @property
    @abstractmethod
    def mutable(self) -> bool:
        pass

    @abstractmethod
    def freeze(self) -> 'FrozenSubgraph':
        pass

    @abstractmethod
    def thaw(self) -> 'MutableSubgraph':
        pass

    @abstractmethod
    def copy(self) -> 'Self':
        """Returns a copy of the subgraph."""
        pass

    @abstractmethod
    def mutate(self, nodes, index, nid_alloc):
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
        """Insets node and returns nid."""
        with self.updater() as u:
            return node.insert_into(u)

@public
class FrozenSubgraph(Subgraph):
    """
    FrozenSubgraph has custom __hash__ and __eq__ methods, which treat subgraphs
    with the equal nodes and nid_alloc as equal. Thus, its hash() and ==
    behavior matches that of immutable types like tuple and str. 'index' is
    not checked for equivalence, as it should be equal by construction.
    """

    __slots__=()
    def __init__(self, subgraph):
        self._nodes= subgraph.nodes
        self._index = subgraph.index
        self._nid_alloc = subgraph.nid_alloc
        self._root_cursor = self.cursor_at(0)
    
    def __copy__(self) -> 'FrozenSubgraph':
        return self # Since FrozenSubgraph is immutable, copies are never needed?!

    def copy(self):
        return self # No need to copy frozen subgraph

    @property
    def mutable(self):
        return False

    def thaw(self) -> 'MutableSubgraph':
        """
        Create new mutable subgraph existing immutable subgraph.
        """
        ret = MutableSubgraph()
        ret.mutate(self.nodes, self.index, self.nid_alloc)
        return ret

    def __eq__(self, other):
        if not isinstance(other, FrozenSubgraph):
            return False
        return (self.nodes == other.nodes) and (self.nid_alloc == other.nid_alloc)

    def __hash__(self):
        return hash((self.nodes, self.nid_alloc))

    def freeze(self) -> 'FrozenSubgraph':
        raise TypeError("Subgraph is already frozen.")

    def mutate(self, nodes, index, nid_alloc):
        raise TypeError("Unsupported operation on FrozenSubgraph.")

    def updater(self) -> SubgraphUpdater:
        # This is not really needed, as mutate will prevent mutation anyway,
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

    @property
    def mutable(self):
        return True

    def thaw(self) -> 'MutableSubgraph':
        raise TypeError("Subgraph is already mutable.")

    @classmethod
    def load(cls, nodes: dict[int,NodeTuple]):
        s = cls()
        with s.updater() as u:
            for nid, node in nodes.items():
                u.add_single(node=node, nid=nid)
        return s.root_cursor

    def __init__(self):
        self._nodes = pmap() # self._nodes is the one true location at which data within the Subgraph is recorded.
        self._index = pmap() # Combined index for fast lookups.
        self._root_cursor = None # Will be set in first call to mutate.
        self._nid_alloc = range(0, 2**32) # Invariant: All nids in the _nid_alloc range must be available (not present in _nodes)

    def mutate(self, nodes, index, nid_alloc):
        self._nodes = nodes
        self._index = index
        self._nid_alloc = nid_alloc
        if self._root_cursor is None:
            self._root_cursor = self.cursor_at(0)

    def __copy__(self) -> 'MutableSubgraph': # For Python's copy module
        # Alternative: return self.freeze().thaw(), but this might have disadvantages in the future (freeze as checkpoint).
        ret = MutableSubgraph()
        ret.mutate(self.nodes, self.index, self.nid_alloc)
        return ret

    def copy(self) -> 'MutableSubgraph':
        """
        Create new mutable subgraph from existing mutable subgraph.
        """
        return self.__copy__()

    def freeze(self):
        return FrozenSubgraph(self)


@public
class NPath(Node):
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

    parent  = LocalRef('Path|type(None)')
    name    = Attr(str|int, factory=check_name)
    ref     = LocalRef(object|type(None))

    idx_parent_name = NPathIndex([parent, name], unique=True)
    idx_path_of = Index(ref, unique=True)
