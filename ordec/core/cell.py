# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from typing import Self
from functools import partial
from pyrsistent import freeze, PMap
from public import public
from .ordb import MutableNode
from .rational import R

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
    Decorator for **view generator methods** defined in :class:`Cell` subclasses.
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
    Decorator for **view generator functions**. Use for module-level functions
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

@public
class ParameterError(Exception):
    """
    Exception raised during :class:`Cell` instantiation upon:

    - missing mandatory parameter,
    - invalid type for parameter,
    - too many positional arguments
    - parameter set using both positional and keyword argument,
    - unknown paramter name,
    - parameter outside valid range,
    - inconsistent combination of parameter values.
    """
    pass

@public
class Parameter:
    """
    Defines a :class:`Cell` parameter.

    Accessing the parameter from a :class:`Cell` instance returns its value;
    accessing it from a :class:`Cell` class returns the :class:`Parameter`
    object. This behavior is achieved by Parameter acting as a Python
    Descriptor.

    Args:
        t: The type that the parameter must be an instance of. Instances of the
            type should be immutable and hashable.
        optional: Indicate whether None is a valid parameter value.
        default: Default value of the parameter.
    """
    def __init__(self, t: type, optional: bool = False, default=None):
        self.type = t
        self.optional = optional
        self.default = default
        self.name = None

    def __get__(self, obj, owner=None):
        if obj == None: # for the class: return self
            return self
        else: # for instances: return parameter value
            return obj.params[self.name]

    def __set__(self, obj, value):
        raise TypeError("Parameter cannot be set.")

    def __delete__(self, obj):
        raise TypeError("Parameter cannot be deleted.")

    def coerce_type(self, value):
        coerce_between_types = (R, float, int)
        if self.type in coerce_between_types and isinstance(value, coerce_between_types):
            return self.type(value)
        elif self.type == R and isinstance(value, str):
            return R(value)
        else:
            return value

    def check(self, value):
        if value == None:
            if self.optional:
                return
            else:
                raise ParameterError(f"Mandatory parameter {self.name!r} is missing.")    
        if not isinstance(value, self.type):
            raise ParameterError(f"Expected type {self.type.__name__} for parameter {self.name!r}.")

class MetaCell(type):
    def __init__(cls, name, bases, attrs):
        cls.instances = {}
        return super().__init__(name, bases, attrs)

    @staticmethod
    def _collect_class_params(d, bases):
        class_params = {} # The order in raw_attrs defines the tuple layout later on.

        # First come inherited attributes:
        for b in bases:
            try:
                class_params |= b._class_params
            except AttributeError:
                pass

        # Then newly added attributes:
        for k, v in list(d.items()):
            if isinstance(v, Parameter):
                class_params[k] = v
                if v.name:
                    assert v.name == k
                else:
                    v.name = k

        return class_params

    def __new__(mcs, name, bases, attrs):
        attrs['_class_params'] = mcs._collect_class_params(attrs, bases)
        return super(MetaCell, mcs).__new__(mcs, name, bases, attrs)

    def _process_params(cls, args, kwargs) -> PMap:
        args, kwargs = cls.params_preprocess(args, kwargs)

        # Map args, kwargs to params dict:
        params = {}
        missing_cls_params = list(cls._class_params.keys())
        for v in args:
            try:
                k = missing_cls_params.pop(0)
            except IndexError:
                raise ParameterError(f"Too many parameters passed as positional arguments to {cls.__name__}.") from None
            params[k] = v
        for k, v in kwargs.items():
            try:
                missing_cls_params.remove(k)
            except ValueError:
                if k in cls._class_params:
                    raise ParameterError(f"Parameter {k!r} to {cls.__name__} passed both as positional and keyword argument.") from None
                else:    
                    raise ParameterError(f"{cls.__name__} has no parameter {k!r}.") from None
            params[k] = v
        for k in missing_cls_params:
            params[k] = cls._class_params[k].default
        assert set(params.keys()) == set(cls._class_params.keys())

        # Parameter type coercion:
        for k in params:
            clsparam = cls._class_params[k]
            params[k] = clsparam.coerce_type(params[k])

        params = cls.params_rewrite(params)

        # Per-parameter type checking:
        for k in params:
            clsparam = cls._class_params[k]
            clsparam.check(params[k])

        cls.params_check(params)

        # We need a immutable dict as return type here. We use pyrsistent / PMap
        # for this purpose, because the library is already used elsewhere in ordec.
        return freeze(params)

    def __call__(cls, *args, **kwargs):
        #print(f"__call__ called with {cls}, {args}, {kwargs}")

        params = cls._process_params(args, kwargs)        

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

    When a Cell subclass is instantiated multiple times with identical effective
    parameters, the same instance is returned. In other words, each Cell
    subclass in combination with a particular parameter setting acts as
    singleton. This magic is accomplished by the metaclass :class:`MetaCell`.
    """
    def __init__(self, params: PMap):
        self.params = params
        self.cached_subgraphs = {}
    
    @classmethod
    def params_preprocess(cls, args, kwargs):
        """
        A subclass can override this method to modify args and kwargs at
        instantiation. This method is called using the original args and kwargs
        provided, before any processing of their values is done.

        Override this to modify how args and kwargs are handled.

        Example uses:

        - restrict use of positional parameters,
        - rename parameters (aliases).
        """
        return args, kwargs

    @classmethod
    def params_rewrite(cls, params: dict) -> dict:
        """
        A subclass can override this method to modify the parameter dict
        before per-parameter type checking.

        This method is called after args and kwargs are mapped to the parameter
        dict and after basic per-parameter type coercion.

        Example uses:

        - custom type conversion of parameters,
        - calculation of missing parameters based on parameters provided.
        """
        return params

    @classmethod
    def params_check(cls, params: dict):
        """
        A subclass can override this method to implement parameter checking.
        This method is called after successful per-parameter type checking and
        should not modify the parameter dictionary. If the parameters are found
        to be invalid, a descriptive :class:`ParameterError` should be raised.

        Example uses:

        - check whether transistor dimensions are within technology ranges,
        - check whether values of dependent parameters are consistent.
        """
        pass

    def params_list(self, use_repr=False) -> list[str]:
        param_items = [(k, getattr(self, k)) for k in self._class_params if getattr(self, k) != None]
        if use_repr:
            # Abbreviate x=R('1k') to x='1k', which is fine due to the coercion str -> R in Parameter.coerce_type
            return [f"{k}={str(v)!r}" if isinstance(v, R) else f"{k}={v!r}" for k, v in param_items]
        else:
            return [f"{k}={v}" for k, v in param_items]

    def __repr__(self):
        return f"{type(self).__name__}({','.join(self.params_list(use_repr=True))})"

    @classmethod
    def discoverable_instances(cls) -> list[Self]:
        """
        This classmethod defines which instances of a Cell subclass are
        discoverable for the web UI, i.e. shown to the user.

        By default, only the Cell's instance with empty parameter set is
        discoverable. If this instance is unavailable due to a ParameterError
        (e.g. mandatory parameters), no instances are discoverable. In this
        case, a Cell subclass could override this method and return a list
        of one or multiple of its instances created from valid parameters.
        """
        r = []
        try:
            r.append(cls())
        except ParameterError:
            pass
        return r
