# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from typing import Type
from enum import Enum
from pyrsistent import freeze, pmap, PMap
from functools import partial
from public import public
from .ordb import MutableNode

class ViewGenerator:
    def __new__(cls, func=None, **kwargs):
        # This __new__ makes @decorator() equivalent to @decorator.
        if func:
            return super().__new__(cls)
        else:
            return partial(cls, **kwargs)

    def __init__(self, func, auto_refresh: bool=True):
        self.func = func
        self.auto_refresh = auto_refresh

    def info_dict(self):
        return {
            'auto_refresh': self.auto_refresh,
        }

    def func_eval(self, *args):
        # New style: node is generated in method:
        ret = self.func(*args)
        # self.func has to attach node.cell, if desired.

        # Freeze if not already frozen:
        if isinstance(ret, MutableNode):
            if ret.nid != 0:
                raise TypeError("MutableNode returned by ViewGenerator must be SubgraphRoot.")
            ret = ret.freeze()
    
        # ViewGenerator return value must be hashable (not sure whether this is really useful):
        try:
            hash(ret)
        except TypeError:
            raise TypeError("ViewGenerator result must be hashable.") from None

        return ret

@public
class generate(ViewGenerator):
    """
    Decorator for view generator methods. Use in :class:`Cell` subclasses.
    The decorated function cannot have any parameters beyond 'self' (use
    Cell-level parameters instead).

    Decorated view generator methods are visible in the web UI.

    ``@generate`` returns a Python Descriptor.
    """
    def __get__(self, obj, owner=None):
        if obj == None: # for the class: return self
            return self
        else: # for instances: create view if not present yet, return view
            if self not in obj.cached_subgraphs:
                obj.cached_subgraphs[self] = self.func_eval(obj)    
            return obj.cached_subgraphs[self]

    def __set__(self, cursor, value):
        raise TypeError("ViewGenerator cannot be set.")

    def __delete__(self, cursor):
        raise TypeError("ViewGenerator cannot be deleted.")

@public
class generate_func(ViewGenerator):
    """
    Decorator for view generator functions. Use for module-level functions
    outside of :class:`Cell` subclasses. The decorated function cannot have
    any parameters.

    Decorated view generator functions are visible in the web UI.

    ``@generate_func`` is provided to simplify small examples. For anything
    complex, ``@generate`` should be prefered.

    ``@generate_func`` is similar to Python's functools.cache.
    """
    def __init__(self, *args, **kwargs):
        self.result = None
        self.evaluated = False
        return super().__init__(*args, **kwargs)

    def __call__(self):
        if not self.evaluated:
            self.result = self.func_eval()
            self.evaluated = True
        return self.result

class MetaCell(type):
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

@public
class Cell(metaclass=MetaCell):
    """
    Subclass this class to define (parametric) design cells.
    The magic of this class is accomplished by its metaclass :class:`MetaCell`.

    Attributes:
        params (PMap): parameters that were passed at instantiation.
        children (dict[str,Node]): all child views that were generated so far.
    """
    def __init__(self, params: PMap):
        self.params = params
        self.cached_subgraphs = {}
                
    def params_list(self, use_repr=False) -> list[str]:
        param_items = list(self.params.items())
        param_items.sort(key=lambda x: x[0])
        if use_repr:
            return [f"{k}={v!r}" for k, v in param_items]
        else:
            return [f"{k}={v}" for k, v in param_items]



    def __repr__(self):
        return f"{type(self).__name__}({','.join(self.params_list(use_repr=True))})"
