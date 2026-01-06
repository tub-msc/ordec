# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass
from public import public
from itertools import chain
from abc import ABC, abstractmethod
import numpy as np
from .geoprim import *
from .ordb import Attr, MutableSubgraph
from .geoprim import TD4, Vec2Generic, Rect4Generic
from .rational import *

class ConstrainableAttrPlaceholder(ABC):
    """
    Abstract base class for classes that implement placeholder values
    for ConstrainableAttrs. The placeholder values (i.e. instances of
    ConstrainableAttrPlaceholder subclasses) are returned by ConstrainableAttr
    when the underlying DB value is None.
    """
    __slots__ = ()

    @classmethod
    @abstractmethod
    def make_placeholder(cls, cursor: 'Node', attr: 'ConstrainableAttr'):
        pass

    @classmethod
    @abstractmethod
    def make_solution(cls, mav: 'MissingAttrVal', value_of_var: dict['Variable', int]):
        pass

@public
class ConstrainableAttr(Attr):
    """
    An attribute that can be constrained. When the underlying attribute value
    in the database is None, it is considered undefined / variable. In this
    case, the attribute's read hook returns a placeholder object instead of
    None. When the underlying attribute value in the databse is not None, the
    attribute acts like a regular attribute.
    """
    def __init__(self, type: type, placeholder: ConstrainableAttrPlaceholder, **kwargs):
        super().__init__(type, **kwargs)
        self.placeholder = placeholder

    def read_hook(self, value, cursor):
        if value is None:
            return self.placeholder.make_placeholder(cursor, self)
        return value


@dataclass(frozen=True, eq=True)
class MissingAttrVal:
    subgraph: MutableSubgraph
    nid: int
    attr: ConstrainableAttr

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
    subgraph: MutableSubgraph #: Subgraph to which the variable belongs.
    nid: int #: The nid of the node to which the variable belongs.
    attr: ConstrainableAttr #: The attribute to which the variable belongs.
    subid: int #: Using the subid, multiple variables can be associated with one attribute. For example the subids (0, 1, 2, 3) for (lx, ly, ux, uy) of a constrainable Rect4 attribute.

    def __post_init__(self):
        if not self.subgraph.mutable:
            raise ValueError("Subgraph of Variable must be mutable.")

    def __repr__(self):
        return f"{type(self).__name__}({self})"

    def __str__(self):
        return f"nid{self.nid}.{self.attr.name}.{self.subid}"

    def term(self):
        return LinearTerm((self,), (1.0,), 0.0)

    def mav(self):
        return MissingAttrVal(self.subgraph, self.nid, self.attr)

@dataclass(frozen=True)
class LinearTerm:
    """
    Represents the linear term:
    (sum over n of coefficient_n * variable_n) + constant
    """

    variables: tuple[Variable] #: Tuple of all variables of the term.
    coefficients: tuple[float] #: Tuple of all coefficients of the term, must have the same length as the variables tuple.
    constant: float #: Constant value of the term.

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
        return LessThanOrEqualsZero(self - other)

    def __ge__(self, other):
        return LessThanOrEqualsZero(-(self - other))

    def __eq__(self, other):
        return EqualsZero(self - other)

    def same_as(self, other) -> bool:
        """
        Returns whether self and other is the identical term. Sort of a
        replacement for __eq__, since __eq__ returns EqualsZero objects.
        """
        return type(self) == type(other) \
            and (self.variables == other.variables) \
            and (self.coefficients == other.coefficients) \
            and (self.constant == other.constant)

@public
class Vec2LinearTerm(Vec2Generic, ConstrainableAttrPlaceholder):
    """
    Point in 2D space.

    Attributes:
        x (LinearTerm): x coordinate
        y (LinearTerm): y coordinate
    """

    __slots__ = ()

    def __new__(cls, x: LinearTerm, y: LinearTerm):
        x = coerce_term(x)
        y = coerce_term(y)
        if not (isinstance(x, LinearTerm) and isinstance(y, LinearTerm)):
            raise TypeError(f"x and y must be LinearTerm instances, got {type(x)} and {type(y)}.")
        return tuple.__new__(cls, (x, y))

    @classmethod
    def make_placeholder(cls, cursor, attr):
        return cls(
            Variable(cursor.subgraph, cursor.nid, attr, 0).term(),
            Variable(cursor.subgraph, cursor.nid, attr, 1).term(),
        )

    @classmethod
    def make_solution(cls, mav, value_of_var):
        values = [value_of_var.get(Variable(mav.subgraph, mav.nid, mav.attr, subid), 0)
            for subid in range(2)]
        return Vec2I(*values)

    def transl(self) -> 'TD4LinearTerm':
        return TD4LinearTerm(transl=self)

    def __eq__(self, other):
        if isinstance(other, Vec2Generic):
            other_x = other.x
            other_y = other.y
        elif isinstance(other, tuple) and len(other) == 2:
            other_x, other_y = other
        else:
            raise TypeError("Vec2LinearTerm equation (==) expects Vec2Generic or 2-tuple on right-hand side.")

        return EqualsZero(self.x - other_x) & EqualsZero(self.y - other_y)

@public
class Rect4LinearTerm(Rect4Generic, ConstrainableAttrPlaceholder):
    __slots__=()
    vector_cls = Vec2LinearTerm

    def __new__(cls, lx: LinearTerm, ly: LinearTerm, ux: LinearTerm, uy: LinearTerm):
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

    @classmethod
    def make_placeholder(cls, cursor, attr):
        return cls(
            Variable(cursor.subgraph, cursor.nid, attr, 0).term(),
            Variable(cursor.subgraph, cursor.nid, attr, 1).term(),
            Variable(cursor.subgraph, cursor.nid, attr, 2).term(),
            Variable(cursor.subgraph, cursor.nid, attr, 3).term(),
        )

    @classmethod
    def make_solution(cls, mav, value_of_var):
        values = [value_of_var.get(Variable(mav.subgraph, mav.nid, mav.attr, subid), 0)
            for subid in range(4)]
        return Rect4I(*values)

    def is_square(self, size=None):
        if size is None:
            return self.width == self.height
        else:
            return (self.width == self.height) & (self.width == size)

    def __eq__(self, other):
        if isinstance(other, Rect4Generic):
            other_lx = other.lx
            other_ly = other.ly
            other_ux = other.ux
            other_uy = other.uy
        elif isinstance(other, tuple) and len(other) == 4:
            other_lx, other_ly, other_ux, other_uy = other
        else:
            raise TypeError("Rect4LinearTerm equation (==) expects Rect4Generic or 4-tuple on right-hand side.")

        return EqualsZero(self.lx - other_lx) \
            & EqualsZero(self.ly - other_ly) \
            & EqualsZero(self.ux - other_ux) \
            & EqualsZero(self.uy - other_uy)

    def contains(self, other) -> 'MultiConstraint':
        """
        Sadly, Python's 'in' operator coerces to booleans, so we cannt use it for our purpose here.
        """
        if isinstance(other, Rect4Generic):
            other_lx = other.lx
            other_ly = other.ly
            other_ux = other.ux
            other_uy = other.uy
        elif isinstance(other, tuple) and len(other) == 4:
            other_lx, other_ly, other_ux, other_uy = other
        else:
            raise TypeError("Rect4LinearTerm.contains expects Rect4Generic or 4-tuple on right-hand side.")

        return LessThanOrEqualsZero(self.lx - other_lx) & \
            LessThanOrEqualsZero(self.ly - other_ly) & \
            LessThanOrEqualsZero(other_ux - self.ux) & \
            LessThanOrEqualsZero(other_uy - self.uy)


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
class LessThanOrEqualsZero(Constraint):
    """Inequality constraint of the form: term <= 0"""
    term: LinearTerm #: Constrained term.

    def __eq__(self, other):
        # To compare constraints, Term.same_as must be used rather than Term.__eq__.
        # This comparison is very strict (e.g., a + b is not the same_as b + a).
        return type(self) == type(other) and self.term.same_as(other.term)

@dataclass(frozen=True, eq=False)
class EqualsZero(Constraint):
    """Equality constraint of the form: term == 0"""
    term: LinearTerm #: Constrained term.

    def __eq__(self, other):
        # To compare constraints, Term.same_as must be used rather than Term.__eq__.
        # This comparison is very strict (e.g., a + b is not the same_as b + a).
        return type(self) == type(other) and self.term.same_as(other.term)

@public
class SolverError(Exception):
    pass

@dataclass
class AmbiguityInfo:
    """
    Information about solution ambiguity when multiple optimal solutions exist.

    This object is only created when the solution is NOT unique, indicating
    missing constraints that leave degrees of freedom.
    """
    n_variables: int #: Total number of variables in the problem
    constraint_rank: int #: Rank of the active constraint matrix
    degrees_of_freedom: int #: Number of remaining unconstrained degrees of freedom
    #: Null space basis vectors. Each column represents a direction
    #: in which the solution can vary while remaining optimal.
    null_space: np.ndarray

    def describe_freedom(self, variables: tuple[Variable]) -> str:
        """
        Generate a human-readable description of the degrees of freedom
        (i.e. which variables are underconstrained).
        """
        lines = [f"{self.degrees_of_freedom} degree(s) of freedom remaining:"]

        for i in range(self.null_space.shape[1]):
            vec = self.null_space[:, i]
            # Find variables with significant coefficients in this null space vector
            significant = [(var, coef) for var, coef in zip(variables, vec) if abs(coef) > 1e-6]

            if significant:
                terms = [f"{coef:.3f}*{var}" for var, coef in significant]
                lines.append(f"  Direction {i+1}: {' + '.join(terms)} can vary freely.")

        return '\n'.join(lines)

def check_solution_uniqueness(res, A_eq, A_ub, b_ub, n_variables) -> AmbiguityInfo | None:
    """
    Check if the linear programming solution is unique using rank analysis.

    Builds the active constraint matrix (equality constraints plus inequality
    constraints with zero slack) and computes its rank. If the rank equals
    the number of variables, the solution is unique and None is returned.
    Otherwise, computes the null space to identify directions of freedom and
    returns an AmbiguityInfo object.

    Args:
        res: Result from scipy.optimize.linprog
        A_eq: Equality constraint matrix
        A_ub: Inequality constraint matrix
        b_ub: Inequality constraint bounds
        n_variables: Number of variables

    Returns:
        None if solution is unique, AmbiguityInfo if solution has degrees of freedom
    """
    from scipy.linalg import null_space

    # Build active constraint matrix
    active_parts = []

    # Equality constraints are always active
    if A_eq.size > 0:
        active_parts.append(A_eq)

    # Find inequality constraints that are active (slack ≈ 0)
    if A_ub.size > 0:
        slack = b_ub - A_ub @ res.x
        tolerance = 1e-7
        active_mask = np.abs(slack) < tolerance

        if np.any(active_mask):
            active_parts.append(A_ub[active_mask])

    # Build active constraint matrix
    if active_parts:
        active_matrix = np.vstack(active_parts)
    else:
        # No active constraints - completely unconstrained
        active_matrix = np.zeros((0, n_variables), dtype=np.float64)

    if active_matrix.shape[0] == 0:
        # No constraints - completely unconstrained
        return AmbiguityInfo(
            n_variables=n_variables,
            constraint_rank=0,
            degrees_of_freedom=n_variables,
            null_space=np.eye(n_variables)
        )

    # Compute rank of active constraints
    rank = np.linalg.matrix_rank(active_matrix, tol=1e-10)
    dof = max(0, n_variables - rank)
    if dof == 0:
        return None # Solution is unique!

    # Solution is not unique!
    return AmbiguityInfo(
        n_variables=n_variables,
        constraint_rank=rank,
        degrees_of_freedom=dof,
        null_space=null_space(active_matrix, rcond=1e-10)
    )

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
    """
    Collects and solves constraints for a set of :class:`ConstrainableAttr`
    attributes of specified subgraph.
    """
    def __init__(self, subgraph: 'SubgraphRoot'):
        self.equalities = []
        self.inequalities = []
        self.subgraph = subgraph

    def constrain(self, constraint: Constraint|MultiConstraint):
        """Add constraint that must be satisfied by the solution."""
        if isinstance(constraint, MultiConstraint):
            for elem in constraint.constraints:
                self.constrain(elem)
        elif isinstance(constraint, EqualsZero):
            self.equalities.append(constraint)
        elif isinstance(constraint, LessThanOrEqualsZero):
            self.inequalities.append(constraint)
        else:
            raise TypeError("constrain() expects LessThanOrEqualsZero or EqualsZero.")

    def solve(self, allow_ambiguous: bool=False):
        """
        Using linear programming, calculates a solution that satisfies all
        specified constraints. The solution values are then written to all
        affected :class:`ConstrainableAttr` attributes.

        Args:
            allow_ambiguous: If False (default), checks that the solution is unique.
                Raises SolverError if multiple optimal solutions exist,
                indicating missing constraints. If True, skips uniqueness
                checking and allows ambiguous solutions.

        Raises:
            SolverError: If the LP solver fails, or if allow_ambiguous=False and
                the solution is not unique (has degrees of freedom).
        """

        from scipy.optimize import linprog

        variables = set()
        for e in chain(self.equalities, self.inequalities):
            variables |= set(e.term.variables)

        for v in variables:
            if v.subgraph != self.subgraph.subgraph:
                raise SolverError(f"Solver found Variables of unexpected subgraph {v.subgraph}.")

        variables = tuple(variables)
        n_variables = len(variables)
        idx_of_var = {variable: index for index, variable in enumerate(variables)}

        A_eq, b_eq = constraints_to_Ab(self.equalities, n_variables, idx_of_var)
        A_ub, b_ub = constraints_to_Ab(self.inequalities, n_variables, idx_of_var)

        c = np.zeros(n_variables, dtype=np.float64)
        # (c * variables) is minimized. By subtracting each row of A_ub, the
        # speicified inequalities are optimized towards equality. Each
        # inequality is given the same weight in this process.
        for x in A_ub:
            c -= x

        bounds = n_variables*[(None, None)]
        res = linprog(c=c, A_eq=A_eq, b_eq=b_eq, A_ub=A_ub, b_ub=b_ub, bounds=bounds)

        if not res.success:
            raise SolverError(res.message)

        # Check solution uniqueness unless explicitly allowed to be ambiguous
        if not allow_ambiguous:
            ambiguity_info = check_solution_uniqueness(res, A_eq, A_ub, b_ub, n_variables)

            if ambiguity_info is not None:
                raise SolverError(
                    f"System is underconstrained; solution is ambiguous.\n"
                    + ambiguity_info.describe_freedom(variables))

        value_of_var = {variable: int(value) for variable, value in zip(variables, res.x)}

        mavs = {variable.mav() for variable in variables}
        for mav in mavs:
            node = self.subgraph.cursor_at(mav.nid, lookup_npath=False)
            #print(self.subgraph.tables())
            #print(node, self.subgraph)
            node.update_byattr(mav.attr, mav.attr.placeholder.make_solution(mav, value_of_var))
