from dataclasses import dataclass
from public import public
from itertools import chain
from .geoprim import *
from .rational import *

class MissingAttrVal:
    __slots__=('nid', 'attr')

    def __init__(self, cursor, attr):
        self.nid = cursor.nid
        self.attr = attr

    def __repr__(self):
        return f"{type(self).__name__}(nid{self.nid}.{self.attr.name})"

    def __hash__(self):
        return hash((self.nid, self.attr))

    def __eq__(self, other):
        if type(other) == type(self):
            return self.nid == other.nid and self.attr == other.attr
        else:
            return False

    def __bool__(self):
        # Some level of compatibility with None:
        return False

    def solution_value(self, value_of_var):
        values = [value_of_var[variable] for variable in self.variables()]
        return self.solution_cls(*values)

class MissingRect4(MissingAttrVal):
    __slots__=()

    solution_cls = Rect4I

    def variables(self):
        return (
            Variable(self, 0),
            Variable(self, 1),
            Variable(self, 2),
            Variable(self, 3),
            )

    @property
    def lx(self):
        return Variable(self, 0).term()

    @property
    def ly(self):
        return Variable(self, 1).term()

    @property
    def ux(self):
        return Variable(self, 2).term()

    @property
    def uy(self):
        return Variable(self, 3).term()

    @property
    def cx(self):
        return 0.5*self.lx + 0.5*self.ux

    @property
    def cy(self):
        return 0.5*self.ly + 0.5*self.uy

    @property
    def width(self):
        return self.ux - self.lx

    @property
    def height(self):
        return self.uy - self.ly

class MissingVec2(MissingAttrVal):
    __slots__=()

    solution_cls = Vec2I

    def variables(self):
        return (
            Variable(self, 0),
            Variable(self, 1),
            )

    @property
    def x(self):
        return Variable(self, 0).term()

    @property
    def y(self):
        return Variable(self, 1).term()

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
    mav: MissingAttrVal
    subid: int

    def __repr__(self):
        return f"{type(self).__name__}({self})"

    def __str__(self):
        return f"nid{self.mav.nid}.{self.mav.attr.name}.{self.subid}"

    def term(self):
        return LinearTerm((self,), (1.0,), 0.0)

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

    def __sub__(self, other):
        other = coerce_term(other)
        return self + (-other)

    def __le__(self, other):
        return Inequality(self - other)

    def __ge__(self, other):
        return Inequality(other - self)

    def __eq__(self, other):
        return Equality(self - other)

@dataclass(frozen=True)
class Inequality:
    """term <= 0"""
    term: LinearTerm

@dataclass(frozen=True)
class Equality:
    """term == 0"""
    term: LinearTerm

@public
class SolverError(Exception):
    pass

@public
class Solver:
    def __init__(self, subgraph):
        self.equalities = []
        self.inequalities = []
        self.subgraph = subgraph

    def constrain(self, constraint: Inequality|Equality):
        if isinstance(constraint, Equality):
            self.equalities.append(constraint)
        elif isinstance(constraint, Inequality):
            self.inequalities.append(constraint)
        else:
            raise TypeError("constrain() expects Inequality or Equality.")

    def solve(self):
        from scipy.optimize import linprog
        import numpy as np

        variables = set()
        for e in chain(self.equalities, self.inequalities):
            variables |= set(e.term.variables)
        variables = tuple(variables)
        n_variables = len(variables)
        idx_of_var = {variable: index for index, variable in enumerate(variables)}

        A_eq = np.zeros((len(self.equalities), n_variables), dtype=np.float64)
        b_eq = np.zeros(len(self.equalities), dtype=np.float64)

        for i, e in enumerate(self.equalities):
            for variable, coefficient in zip(e.term.variables, e.term.coefficients):
                j = idx_of_var[variable]
                A_eq[i, j] = coefficient

            b_eq[i] = -e.term.constant

        c = np.zeros(n_variables, dtype=np.float64)

        bounds = n_variables*[(None, None)]
        res = linprog(c=c, A_eq=A_eq, b_eq=b_eq, bounds=bounds)

        if not res.success:
            raise SolverError(res.message)

        value_of_var = {variable: int(value) for variable, value in zip(variables, res.x)}

        mavs = {variable.mav for variable in variables}
        for mav in mavs:
            node = self.subgraph.cursor_at(mav.nid, lookup_npath=False)
            node.update_byattr(mav.attr, mav.solution_value(value_of_var))
