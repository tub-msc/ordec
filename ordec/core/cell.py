# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from typing import Type
from enum import Enum
from pyrsistent import freeze, pmap, PMap
from warnings import warn
from public import public

class ViewGenerator:
    def __init__(self, head_class, func):
        self.head_class = head_class
        self.func = func

    def __get__(self, obj, owner=None):
        if obj == None: # for the class: return self
            return self
        else: # for instances: create view if not present yet, return view
            
            try:
                return obj.cached_subgraphs[self]
            except KeyError:
                if self.head_class:
                    # Compatibility with old @generate: node is generated outside the method and passed as argument:
                    node = self.head_class()
                    self.func(obj, node)
                    node.cell = obj
                else:
                    # New style: node is generated in method:
                    node = self.func(obj)
                    # self.func has to attach node.cell, if desired.
                node = node.freeze()
                obj.cached_subgraphs[self] = node
                return node

    def __set__(self, cursor, value):
        raise TypeError("ViewGenerator cannot be set.")

    def __delete__(self, cursor):
        raise TypeError("ViewGenerator cannot be deleted.")

@public
def generate(arg):
    """
    TODO: add docs here.
    """
    if isinstance(arg, type):
        # old @generate
        return lambda func: ViewGenerator(arg, func)
    else:
        # new @generate
        return ViewGenerator(None, arg)

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
