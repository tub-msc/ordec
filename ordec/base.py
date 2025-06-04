# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from typing import Type
from enum import Enum
from pyrsistent import freeze, pmap, PMap, PVector
from dataclasses import dataclass
from .rational import Rational as R
from .geoprim import Vec2R, Rect4R, D4
from collections.abc import Mapping
from warnings import warn
permitted_scalar_types = (str, int, R, Vec2R, Rect4R, D4, Enum, type(None), float)

class attr:
    """
    This is a Python descriptor for defining Node attributes.
    """
    def __init__(self, type, default=None, freezer=lambda x:x, help=""):
        self.type = type
        self.default = default
        self.freezer = freezer
        self.__doc__ = help

    def __set_name__(self, owner, name):
        self.private_name = '_attr_' + name

    def __get__(self, obj, objtype=None):
        return getattr(obj, self.private_name)

    def __set__(self, obj, value):
        setattr(obj, self.private_name, value)


class GraphIntegrityError(Exception):
    pass
    
class IllegalGraphOperation(Exception):
    pass

class IntegrityError(Exception):
    pass

class NodePath(tuple):
    def __str__(self):
        return str(self[0]) + self.local()

    def __str__(self):
        ret = []
        for elem in self:
            if isinstance(elem, int):
                ret.append(f"[{elem}]")
            else:
                if len(ret) > 0:
                    ret.append('.')
                ret.append(str(elem))
        return "".join(ret)

    def __getitem__(self, key):
        ret = super().__getitem__(key)
        if isinstance(ret, tuple):
            # This makes it so that slicing a NodePath (e.,g. path()[1:3]) returns a NodePath, not a tuple.
            return NodePath(ret)
        else:
            return ret

    def __repr__(self):
        return type(self).__name__ + super().__repr__()

class UnattachedNode:
    __slots__ = ('node_cls', 'args', 'kwargs', 'attached')

    def __init__(self, node_cls, args, kwargs):
        self.node_cls = node_cls
        self.args = args
        self.kwargs = kwargs
        self.attached = False

    def attach(self, parent, name):
        if self.attached:
            raise IllegalGraphOperation(f"Attempt to attach {self} to two parents.")
        obj = self.node_cls.__new__(self.node_cls, parent, name, *self.args, **self.kwargs)
        obj.__init__(parent, name, *self.args, **self.kwargs)
        self.attached = True
        return obj

    def __repr__(self):
        args_repr = [repr(a) for a in self.args] + [f"{k}={repr(v)}" for k, v in self.kwargs.items()]
        return f"UnattachedNode({self.node_cls.__name__}({', '.join(args_repr)}))"

class MetaNode(type):
    def __new__(mcls, name, bases, attrs):
        node_attributes = {}
        attrs.setdefault('__annotations__', {'children': None})
        for k, v in attrs.items():
            if isinstance(v, attr):
                node_attributes[k] = v
                attrs['__annotations__'][k] = v.type # Only for documentation purposes.
        
        attrs['_attrs_'] = node_attributes
        # _children slot is always there, but not always used.
        # The problem here is that we need to know our slots before super().__new__,
        # but the __annotations__ can be set / modified afterwards or come from a superclass.
        slots = ['_parent', '_name', '_frozen', '_children']
        slots += ['_attr_'+k for k in node_attributes]

        assert '__slots__' not in attrs
        attrs['__slots__'] = slots
        cls = super().__new__(mcls, name, bases, attrs)

        #def fix_children_self_reference(cls):
        #    if cls.__annotations__['children'] == None:
        #        return
        #    print(cls.__annotations__['children'])
        #    #assert issubclass(Mapping, cls.__annotations__['children'])
        #    k, v = cls.__annotations__['children'].__args__
        #    cls.__annotations__['children'] = Mapping[k, [e for e in v]]
        #
        #fix_children_self_reference(cls)
        
        return cls

    #def __init__(cls, name, bases, attrs):
    #    super().__init__(cls, name, bases, attrs)

    def __call__(cls, *args, **kwargs):
        return UnattachedNode(cls, args, kwargs)

class Node(metaclass=MetaNode):
    """
    Basic data record around which ORDeC is organized.
    Every node is part of a tree that ends at a Cell.
    """

    children: None

    def __init__(self, parent, name, **kwargs):
        super().__setattr__('_frozen', False)
        self._parent = parent
        self._name = name
        if name in parent.children:
            raise IllegalGraphOperation('Overwriting existing children is prohibited to prevent accidental errors. Please delete child using "del" before attaching a new child.')
        parent.children[name] = self
        if self.__annotations__['children'] != None:
            self._children = {}
        else:
            self._children = None

        for k, v in self._attrs_.items():
            setattr(self, k, v.default)
        for k, v in kwargs.items():
            setattr(self, k, v)

    def child_expected_key_type(self):
        return self.__annotations__['children'].__args__[0]

    def child_expected_value_type(self):
        node = self
        while node.__annotations__['children'].__args__[1] == 'inherit':
            node = node._parent
        return node.__annotations__['children'].__args__[1]

    def freeze(self):
        if self._frozen:
            return
        
        if self._children != None:
            expected_key_type = self.child_expected_key_type()
            expected_value_type = self.child_expected_value_type()
            for k, v in self._children.items():
                if not isinstance(k, expected_key_type):
                    raise TypeError(f"Node {self} has child key {k} of illegal type {type(k).__name__}.")
                if not isinstance(v, expected_value_type):
                    raise TypeError(f"Node {self} has child {v} of illegal type {type(v).__name__}.")

            self._children = pmap(self._children)
            for c in self.children.values():
                c.freeze()
        for k, v in self._attrs_.items():
            v_new = v.freezer(getattr(self, k))
            if not isinstance(v_new, v.type):
                raise TypeError(f"Node {self} has attribute {k} of illegal type {type(v_new).__name__}.")
            setattr(self, k, v_new)
        self._frozen = True

    @classmethod
    def check_attribute_value_integrity(cls, val):
        if isinstance(val, permitted_scalar_types):
            return

        if isinstance(val, Node):
            if not val._frozen:
                raise GraphIntegrityError(f"Encountered reference to non-frozen (mutable) Node: {val}")        
            return

        if isinstance(val, PMap):
            for k, v in val.items():
                cls.check_attribute_value_integrity(k)
                cls.check_attribute_value_integrity(v)
            return

        if isinstance(val, PVector):
            for elem in val:
                cls.check_attribute_value_integrity(elem)
            return

        raise GraphIntegrityError(f"Encountered illegal attribute value: {val} {type(val)}")

    def check_frozen_integrity(self):
        """
        Check that all children are frozen nodes and that all attributes are
        frozen (pyrsistent) data structures with references only to other frozen nodes.
        """

        if not self._frozen:
            raise GraphIntegrityError("Node in tree is not frozen.")

        if not isinstance(self.parent, (Node, Cell)):
            raise GraphIntegrityError("Node parents are neither Node nor Cell.")

        if self.children != None:
            if not isinstance(self.children, PMap):
                raise GraphIntegrityError("Node children are not frozen.")

            for k, v in self.children.items():
                if not isinstance(k, (int, str)):
                    raise GraphIntegrityError("Child key is not int or str.")
                if not isinstance(v, Node): # we could skip this, as check_frozen_integrity() should only be there for nodes.
                    raise GraphIntegrityError("Child is not Node.")
                v.check_frozen_integrity()

        #if not isinstance(self.attrs, PMap):
        #    raise GraphIntegrityError("Node children are not frozen.")

        for k, v in self._attrs_.items():
            if not isinstance(k, str):
                raise GraphIntegrityError("Attribute keys must be str.")
            self.check_attribute_value_integrity(getattr(self, k))

        self.check_integrity()

    def check_integrity(self):
        """
        Override this in subclasses to add specific integrity checks.
        The integrity checks are performed after freezing and general frozen integrity checking.
        """
        pass

    def root_view(self):
        cur = self
        while not isinstance(cur, View):
            cur = cur.parent
        return cur

    def path(self):
        cur = self
        p = []
        while isinstance(cur, Node):
            p.insert(0, cur.name)
            cur = cur.parent
        p.insert(0, cur)
        return NodePath(p)

    def anonymous(self, subnode: UnattachedNode) -> 'Node':
        if not isinstance(subnode, UnattachedNode):
            raise TypeError("anonymous() only supports UnattachedNode objects.")
        auto_name = f"anon_{len(self.children)}"
        subnode.attach(self, auto_name)
        return self.children[auto_name]

    def __mod__(self, other):
        return self.anonymous(other)

    def __setattr__(self, name, value):
        if self._frozen:
            raise PermissionError(f"Cannot setattr of frozen node {self}.")

        if isinstance(value, UnattachedNode):
            # This adds a child:
            value.attach(self, name)
        else:
            return super().__setattr__(name, value)

    def __setitem__(self, name, value):
        if self._frozen:
            raise PermissionError(f"Cannot setattr of frozen node {self}.")
        if not isinstance(name, int):
            raise TypeError("int key required for child access via [].")

        if not isinstance(value, UnattachedNode):
            raise TypeError("Only nodes (UnattachedNode) can be set via [].")
        value.attach(self, name)

    def __getitem__(self, name):
        if not isinstance(name, int):
            raise TypeError("int key required for child access via [].")
        return self.children[name]

    def __delitem__(self, name):
        if not isinstance(name, int):
            raise TypeError("int key required for child access via [].")
        del self.children[name]

    def __getattr__(self, name):
        if name == 'name':
            return self._name
        elif name == 'parent':
            return self._parent
        elif name == 'children':
            return self._children
        #elif name.startswith("_"):
        #    raise AttributeError(f"{name} not found")
        #elif name in self._attrs_.keys():
        #    return getattr(self,"_attr_"+name)
        elif self._children and (name in self._children.keys()):
            return self._children[name]
        else:
            raise AttributeError(f"{name} found neither as attribute nor as child of {self}.")

    def attributes(self) -> dict:
        """
        Returns the node attributes in form of a dictionary.
        Warning: (re-)assigning entries in the returned dictionary does not modify
        the Node's attributes!
        """
        return {name:getattr(self, name) for name in self._attrs_}

    def __delattr__(self, name):
        if name in self._attrs_.keys():
            raise TypeError("Cannot delete node attributes.")
        elif name in self._children.keys():
            del self._children[name]
        else:
            raise AttributeError(f"{name} found neither as attribute nor as child of {self}.")

    def __repr__(self):
        return f"{type(self).__name__}({self.path()[-1]})"
        
        #return f"{type(self).__name__}({self.children}, {self.attrs})"
        
        # desc = []
        # for k, v in self.attrs.items():
        #     desc.append(f"{k}={v}")
        # if len(self.children) > 0:
        #     desc.append("children=("+", ".join([str(k) for k in self.children.keys()])+")")
        # return f"{type(self).__name__}({', '.join(desc)})"

    def tree_array(self):
        indent = "  "
        ret = [f"{self.name} -> {type(self).__name__}"]
        for k in self._attrs_.keys():
            v = getattr(self, k)
            if v != None:
                ret.append(f"{indent}{k}: {v}")
        if self.children != None:
            for k, v in self.children.items():
                ret += [indent+l for l in v.tree_array()]
        return ret

    def tree(self):
        return "\n".join(self.tree_array())

    def traverse(self, filtertype=None):
        if filtertype == None or isinstance(self, filtertype):
            yield self
        if self.children == None:
            return
        for c in self.children.values():
            yield from c.traverse(filtertype=filtertype)

class PathNode(Node):
    """
    PathNodes can have children of the same node types as the parent.
    Use only ContainerStruct and ContainerArray, never Container directly.
    """
    children: Mapping[None, "inherit"]
    
class PathStruct(PathNode):
    """
    PathStruct is a Container whose children have string keys.
    """
    children: Mapping[str, "inherit"]

class PathArray(PathNode):
    """
    PathArray is a Container whose children have int keys.
    """
    children: Mapping[int, "inherit"]




class View(Node):
    """
    Views are generated by view generators and are direct children of Cell objects.
    """
    pass


def generates_view(obj) -> None | Type[View]:
    """
    Checks whether obj is a function/method that has a subclass of View as
    annotated return type. If this is the case, the specified View subclass is
    returned. Otherwise, None is returned.
    """
    if not callable(obj):
        return False
    try:
        returntype = obj.__annotations__.get('return')
    except AttributeError:
        return False
    if isinstance(returntype, type) and issubclass(returntype, View):
        return returntype
    return False


class ViewGenerator:
    __slots__ = ('view_cls', 'gen_func')
    def __init__(self, view_cls, gen_func):
        self.view_cls = view_cls
        self.gen_func = gen_func

generate = lambda view_cls: lambda gen_func: ViewGenerator(view_cls, gen_func)

class MetaCell(type):
    def __new__(mcls, name, bases, attrs, **kwargs):
        # Replace methods returning a view with appropriate ViewGenerators in
        # the class under construction:
        for k in attrs:
            view_cls=generates_view(attrs[k])
            if view_cls:
                warn("Use @generate decorator to create ViewGenerator instead of implicit definition via annotated return type.", DeprecationWarning, stacklevel=2)
                attrs[k] = ViewGenerator(view_cls, attrs[k])
        return super(MetaCell, mcls).__new__(mcls, name, bases, attrs, **kwargs)

    def __init__(cls, name, bases, attrs):
        cls.instances = {}
        return super().__init__(name, bases, attrs)

    def __call__(cls, *args, **kwargs):
        #print(f"__call__ called with {cls}, {args}, {kwargs}")
        if len(args) == 0:
            params = freeze(kwargs)
        elif len(args) == 1:
            params = freeze(args[0])
        else:
            raise Exception("Too many arguments to MetaCell.__call__")

        if not isinstance(params, PMap):
            raise TypeError("Incompatible parameters supplied.")
        if params in cls.instances:
            return cls.instances[params]
        else:
            obj = cls.__new__(cls, params)
            cls.instances[params] = obj
            cls.__init__(obj, params)
            return obj

class Cell(metaclass=MetaCell):
    """
    Subclass this class to define (parametric) design cells.
    The magic of this class is accomplished by its metaclass :class:`MetaCell`.

    Attributes:
        params (PMap): parameters that were passed at instantiation.
        children (dict[str,Node]): all child views that were generated so far.
    """
    def __init__(self, params: PMap):
        super().__setattr__('params', params)
        super().__setattr__('children', {})

    def __getattribute__(self, name):
        ret=super().__getattribute__(name)
        if isinstance(ret, ViewGenerator):
            view = ret.view_cls().attach(self, name)
            try:
                super().__setattr__(name, view)
                ret.gen_func(self, view)
            except:
                del self.children[name]
                super().__delattr__(name)
                raise
            
            view.freeze()
            view.check_frozen_integrity()

            # Override the original method with a View in the
            # instance __dict__ -- __getattr__ not needed:
            # The attribute has changed now, ensure that subsequent __getattribute__ calls will return the correct value.
            assert super().__getattribute__(name) is view
            return view
        else:
            return ret
                
    def params_list(self) -> list[str]:
        param_items = list(self.params.items())
        param_items.sort(key=lambda x: x[0])
        return [f"{k}={v}" for k, v in param_items]

    def __repr__(self):
        return f"{type(self).__name__}({','.join(self.params_list())})"

    def __delattr__(self, name):
        # If we permit __delattr__, the following statements would create
        # two views a and b of the same name and cell that are not the same object:
        #  a = cell.x
        #  del cell
        #  b = cell.x
        raise TypeError("Cannot delete attribute of Cell.")

    def __setattr__(self, name, value):
        # The reason why we prohibit this is mainly to prevent accidentally
        # Modifying "self" instead of "node" in a view method.
        raise TypeError("Cannot set attribute of Cell.")

def empty_pmap(obj):
    """This is a leaf node."""
    if obj != pmap():
        raise TypeError("Expected empty pmap.")
    return pmap()
