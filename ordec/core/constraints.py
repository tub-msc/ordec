# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass
from public import public
from itertools import chain
import numpy as np
from .geoprim import *
from .ordb import Attr
from .geoprim import TD4, Vec2Generic, Rect4Generic
from .rational import *

@dataclass(frozen=True, eq=True)
class MissingAttrVal:
    nid: int
    attr: Attr

def coerce_term(x):
    if isinstance(x, (float, int)):
        return LinearTerm((), (), float(x))
    else:
        return x

@dataclass(frozen=True, eq=True, repr=False)
class Variable:
    """
    Represents scalar integer or rational variable whose value is to be
    determined using a solver.
    """
    nid: int
    attr: Attr
    subid: int

    def __repr__(self):
        return f"{type(self).__name__}({self})"

    def __str__(self):
        return f"nid{self.nid}.{self.attr.name}.{self.subid}"

    def term(self):
        return LinearTerm((self,), (1.0,), 0.0)

    def mav(self):
        return MissingAttrVal(self.nid, self.attr)

@dataclass(frozen=True)
class LinearTerm:
    variables: tuple[Variable]
    coefficients: tuple[float]
    constant: float

    def __repr__(self):
        assert len(self.variables) == len(self.coefficients)
        l = [f'{c}*{v}' for v, c in zip(self.variables, self.coefficients)]
        l = " + ".join(l)
        return f"LinearTerm({l} + {self.constant})"

    def __rmul__(self, other):
        return LinearTerm(
            self.variables,
            tuple((other*coeff for coeff in self.coefficients)),
            other*self.constant,
            )

    def __neg__(self):
        return LinearTerm(
            self.variables,
            tuple((-coeff for coeff in self.coefficients)),
            -self.constant,
            )

    def __add__(self, other):
        other = coerce_term(other)

        variables = list(self.variables)
        coefficients = list(self.coefficients)

        for v, c in zip(other.variables, other.coefficients):
            try:
                idx = variables.index(v)
            except ValueError:
                variables.append(v)
                coefficients.append(c)
            else:
                coefficients[idx] += c
            
        return LinearTerm(
            tuple(variables),
            tuple(coefficients),
            self.constant + other.constant
            )

    def __radd__(self, other):
        return self.__add__(other)

    def __rsub__(self, other):
        return -self.__sub__(other)

    def __sub__(self, other):
        other = coerce_term(other)
        return self + (-other)

    def __le__(self, other):
        return Inequality(self - other)

    def __ge__(self, other):
        return Inequality(-(self - other))

    def __eq__(self, other):
        return Equality(self - other)

    def same_as(self, other) -> bool:
        """
        Returns whether self and other is the identical term. Sort of a
        replacement for __eq__, since __eq__ returns Equality objects.
        """
        return type(self) == type(other) \
            and (self.variables == other.variables) \
            and (self.coefficients == other.coefficients) \
            and (self.constant == other.constant)

@public
class Vec2LinearTerm(Vec2Generic):
    """
    Point in 2D space.

    Attributes:
        x (LinearTerm): x coordinate
        y (LinearTerm): y coordinate
    """

    __slots__ = ()

    def __new__(cls, x, y):
        x = coerce_term(x)
        y = coerce_term(y)
        if not (isinstance(x, LinearTerm) and isinstance(y, LinearTerm)):
            raise TypeError(f"x and y must be LinearTerm instances, got {type(x)} and {type(y)}.")
        return tuple.__new__(cls, (x, y))

    @classmethod
    def make_placeholder(cls, cursor, attr):
        return cls(
            Variable(cursor.nid, attr, 0).term(),
            Variable(cursor.nid, attr, 1).term(),
        )

    @classmethod
    def make_solution(cls, mav, value_of_var):
        values = [value_of_var.get(Variable(mav.nid, mav.attr, subid), 0)
            for subid in range(2)]
        return Vec2I(*values)

    def transl(self) -> 'TD4LinearTerm':
        return TD4LinearTerm(transl=self)

@public
class Rect4LinearTerm(Rect4Generic):
    __slots__=()
    vector_cls = Vec2LinearTerm

    def __new__(cls, lx, ly, ux, uy):
        lx = coerce_term(lx)
        ly = coerce_term(ly)
        ux = coerce_term(ux)
        uy = coerce_term(uy)

        if not isinstance(lx, LinearTerm):
            raise TypeError(f"lx must be LinearTerm instance, got {type(lx)}.")
        if not isinstance(ly, LinearTerm):
            raise TypeError(f"ly must be LinearTerm instance, got {type(ly)}.")
        if not isinstance(ux, LinearTerm):
            raise TypeError(f"ux must be LinearTerm instance, got {type(ux)}.")
        if not isinstance(uy, LinearTerm):
            raise TypeError(f"uy must be LinearTerm instance, got {type(uy)}.")

        return tuple.__new__(cls, (lx, ly, ux, uy))


    #solution_cls = Rect4I

    @classmethod
    def make_placeholder(cls, cursor, attr):
        return cls(
            Variable(cursor.nid, attr, 0).term(),
            Variable(cursor.nid, attr, 1).term(),
            Variable(cursor.nid, attr, 2).term(),
            Variable(cursor.nid, attr, 3).term(),
        )

    @classmethod
    def make_solution(cls, mav, value_of_var):
        values = [value_of_var.get(Variable(mav.nid, mav.attr, subid), 0)
            for subid in range(4)]
        return Rect4I(*values)


    def is_square(self, size=None):
        if size is None:
            return self.width == self.height
        else:
            return (self.width == self.height) & (self.width == size)

@public
class TD4LinearTerm(TD4):
    """LinearTerm version of TD4"""
    __slots__ = ()
    vec_cls = Vec2LinearTerm
    rect_cls = Rect4LinearTerm

    def __rmul__(self, other):
        if isinstance(other, TD4I):
            return TD4LinearTerm(transl=self.vec_cls(coerce_term(other.transl.x), coerce_term(other.transl.y)), d4=other.d4) * self
        else:
            return NotImplemented

    def __mul__(self, other):
        if(isinstance(other, Rect4I)):
            other = Rect4LinearTerm(other.lx, other.ly, other.ux, other.uy)

        return super().__mul__(other)

class Constraint:
    __slots__=()

    def __and__(self, other):
        # Python's 'and' cannot be overloaded, so we overload '&' instead.
        return MultiConstraint((self,)) & other

@dataclass(frozen=True)
class MultiConstraint:
    constraints: tuple[Constraint]

    def __and__(self, other):
        # Python's 'and' cannot be overloaded, so we overload '&' instead.

        if isinstance(other, Constraint):
            return MultiConstraint(self.constraints + (other,))
        elif isinstance(other, MultiConstraint):
            return MultiConstraint(self.constraints + other.constraints)
        else:
            raise TypeError(f"addition not supported for {type(self)} and {type(other)}")


@dataclass(frozen=True, eq=False)
class Inequality(Constraint):
    """term <= 0"""
    term: LinearTerm

    def __eq__(self, other):
        return type(self) == type(other) and self.term.same_as(other.term)

@dataclass(frozen=True, eq=False)
class Equality(Constraint):
    """term == 0"""
    term: LinearTerm

    def __eq__(self, other):
        return type(self) == type(other) and self.term.same_as(other.term)

@public
class SolverError(Exception):
    pass

def constraints_to_Ab(constraints: list[Constraint], n_variables: int, idx_of_var: dict[Variable,int]):
    A = np.zeros((len(constraints), n_variables), dtype=np.float64)
    b = np.zeros(len(constraints), dtype=np.float64)

    for i, e in enumerate(constraints):
        for variable, coefficient in zip(e.term.variables, e.term.coefficients):
            j = idx_of_var[variable]
            A[i, j] = coefficient

        b[i] = -e.term.constant

    return A, b

@public
class Solver:
    def __init__(self, subgraph):
        self.equalities = []
        self.inequalities = []
        self.subgraph = subgraph

    def constrain(self, constraint: Constraint|MultiConstraint):
        if isinstance(constraint, MultiConstraint):
            for elem in constraint.constraints:
                self.constrain(elem)
        elif isinstance(constraint, Equality):
            self.equalities.append(constraint)
        elif isinstance(constraint, Inequality):
            self.inequalities.append(constraint)
        else:
            raise TypeError("constrain() expects Inequality or Equality.")

    def solve(self):
        from scipy.optimize import linprog

        variables = set()
        for e in chain(self.equalities, self.inequalities):
            variables |= set(e.term.variables)
        variables = tuple(variables)
        n_variables = len(variables)
        idx_of_var = {variable: index for index, variable in enumerate(variables)}

        A_eq, b_eq = constraints_to_Ab(self.equalities, n_variables, idx_of_var)
        A_ub, b_ub = constraints_to_Ab(self.inequalities, n_variables, idx_of_var)

        c = np.zeros(n_variables, dtype=np.float64)
        # (c * variables) is minimized. By subtracting each row of A_ub, the
        # speicified 
        for x in A_ub:
            c -= x

        bounds = n_variables*[(None, None)]
        res = linprog(c=c, A_eq=A_eq, b_eq=b_eq, A_ub=A_ub, b_ub=b_ub, bounds=bounds)

        if not res.success:
            raise SolverError(res.message)

        value_of_var = {variable: int(value) for variable, value in zip(variables, res.x)}

        mavs = {variable.mav() for variable in variables}
        for mav in mavs:
            node = self.subgraph.cursor_at(mav.nid, lookup_npath=False)
            #print(self.subgraph.tables())
            #print(node, self.subgraph)
            node.update_byattr(mav.attr, mav.attr.placeholder.make_solution(mav, value_of_var))
