# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
import numpy as np
import copy
import warnings
warnings.filterwarnings('ignore')

from scipy.optimize import LinearConstraint, milp


class Geo:
    """
    Imporant: Currently, all vars must be added before constraints are added.
    """

    def __init__(self):
        self.vars = []
        self.constraints = []
        self.objs = []

    def constrain(self, terms: list['Term']):
        for term in terms:
            if not isinstance(term, Term):
                raise TypeError("Constraint must be Term.")
            self.constraints.append(term)

    def solve(self):
        A = np.array([t.coeffs for t in self.constraints])
        b_u = np.array([-t.scalar for t in self.constraints])
        b_l = np.full_like(b_u, np.iinfo(b_u.dtype).min) # was: -np.inf

        objective = np.zeros((len(self.vars),), dtype=int)
        # Construct the constraints
        constrs = LinearConstraint(A, b_l, b_u)
        # All vars must be integers not continuous
        integrality = np.ones_like(objective)
        res = milp(c=objective, constraints=constrs, integrality=integrality)
        for var, res_val in zip(self.vars, res.x):
            var.value = res_val

    def svg(self):
        """outputs 50x50 units, origin in lower left point"""
        svg_list = []
        svg_list.append('<svg width="500" height="500" xmlns="http://www.w3.org/2000/svg">')
        svg_list.append(
            '<defs><pattern id="grid" width="1" height="1" patternUnits="userSpaceOnUse"><path d="M 1 0 L 0 0 0 1" fill="none" stroke="lightblue" stroke-width="0.2"/></pattern></defs>')
        svg_list.append('<g transform="translate(0 500) scale(10.0 -10.0)">')
        svg_list.append('<rect width="100%" height="100%" fill="url(#grid)" />')
        for o in self.objs:
            svg_list.append(o.svg())
        svg_list.append('</g>')
        svg_list.append('</svg>')
        return "\n".join(svg_list)


class Var:
    def __init__(self, geo):
        self.geo = geo
        self.idx = len(self.geo.vars)
        self.geo.vars.append(self)
        self.value = None

    def __repr__(self):
        if self.value == None:
            return f"v{self.idx}"
        else:
            return f"v{self.idx} = {self.value}"

    def __eq__(self, other):
        return self.term() == other

    def __ge__(self, other):
        return self.term() >= other

    def __le__(self, other):
        return self.term() <= other

    def __add__(self, other):
        return self.term() + other

    def __sub__(self, other):
        return self.term() - other

    def __neg__(self):
        return -self.term()

    def term(self):
        return Term(self.geo, self)


class Term:
    """Represents a term, possibly to be optimized to be less than or equal to zero."""

    def __init__(self, geo: Geo, var: Var = None):
        self.geo = geo
        self.coeffs = np.zeros((len(geo.vars),), dtype=int)
        self.scalar = 0
        if var:
            self.coeffs[var.idx] = 1

    def __repr__(self):
        return f"Term({self.coeffs} + {self.scalar})"

    def __sub__(self, other):
        return self + (-other)

    def __add__(self, other):
        if isinstance(other, (Var, Term)):
            if isinstance(other, Var):
                other = other.term()
            new = Term(geo=self.geo)
            new.coeffs = self.coeffs + other.coeffs
            new.scalar = self.scalar + other.scalar
            return new
        elif isinstance(other, int):
            new = Term(geo=self.geo)
            new = copy.copy(self)
            new.scalar += other
            return new
        else:
            raise TypeError("Unsupported Term addition")

    def __neg__(self):
        new = copy.copy(self)
        # new.coeffs *= -1
        new.coeffs = -new.coeffs
        # new.scalar *= -1
        new.scalar = -new.scalar
        return new

    def __le__(self, other):
        return [(self - other)]

    def __ge__(self, other):
        return [-(self - other)]

    def __eq__(self, other):
        l = (self <= other)
        g = (self >= other)
        return l + g


class Rect:
    def __init__(self, geo):
        self.geo = geo
        self.top = Var(geo)
        self.bottom = Var(geo)
        self.left = Var(geo)
        self.right = Var(geo)

        geo.objs.append(self)

    @property
    def width(self):
        return self.right - self.left

    @property
    def height(self):
        return self.top - self.bottom

    def __repr__(self):
        return f"Rect({self.top}, {self.bottom}, {self.left}, {self.right})"

    def svg(self):
        w = self.right.value - self.left.value
        h = self.top.value - self.bottom.value
        x = self.left.value
        y = self.bottom.value
        return f'<rect width="{w}" height="{h}" x="{x}" y="{y}" fill="blue" />'

def get_pos_with_constraints(constraints, instances, ext):
    """
    Information which we need to calculate the position:
        - instance list (keyword (if instance not port), type)
        - constrain (first_input, second_input, offset)
        --> if a input is a tuple with multiple entries, it is a child of a instance not a port
    How to calculate the positions:
        - First setup everything in their own column (for loop)
        - Maybe reserve the first column for ports and put them there in rows
            --> Then look at the constraints, if there is one above each other
                pop from column and place below/above it
            --> if left or right just swap in the column section
    :param constraints: the constraints from the parsing
    :param instances: instances with (name, type, size)
    :param ext: external cells as refs
    :returns instance_positions: dict of instances with their position
    """
    G = Geo()
    # maps names to geo elements
    geo_mapping = dict()

    # Return if there are no constraint
    if len(constraints) == 0:
        return {}

    # Add instances to geo field
    for name, instance_type in instances.items():
        if instance_type is None:
            geo_mapping[name] = Rect(G)
        else:
            # Get symbol size from lib and add rect to geo instance
            sub_cell_symbol = ext[instance_type[1]]().symbol
            geo_mapping[name] = (Rect(G), sub_cell_symbol)

    # calculate sizes --> add constraints for width and height
    for name, instance_type in instances.items():
        if instance_type is None:
            G.constrain(geo_mapping[name].height == 1)
            G.constrain(geo_mapping[name].width == 1)
        else:
            sub_cell_symbol = geo_mapping[name][1]
            positions = sub_cell_symbol.outline
            width = positions.ux - positions.lx
            height = positions.uy - positions.ly
            G.constrain(geo_mapping[name][0].height == int(height))
            G.constrain(geo_mapping[name][0].width == int(width))

    # Add the constraints and calculate the final positions afterward
    for name, constraint in constraints:
        first_port = constraint[0]
        second_port = constraint[1]
        offset = constraint[2]

        # Check if it is a port connection
        if instances[first_port] is None:
            lhs = geo_mapping[first_port]
        else:
            first_instance = geo_mapping[first_port]
            lhs, first_symbol_ref = first_instance
            # port_pos_x = getattr(first_symbol_ref, first_port[1]).pos.x
            # port_pos_y = getattr(first_symbol_ref, first_port[1]).pos.y

        if instances[second_port] is None:
            rhs = geo_mapping[second_port]
        else:
            second_instance = geo_mapping[second_port]
            rhs, second_symbol_ref = second_instance
            # port_pos_x = getattr(second_symbol_ref, second_port[1]).pos.x
            # port_pos_y = getattr(second_symbol_ref, second_port[1]).pos.y

        if name == "left":
            # 1.right + offset = 2.left
            G.constrain(lhs.right + int(offset) <= rhs.left)
        elif name == "right":
            # 1.left - offset = 2.right
            G.constrain(lhs.left - int(offset) >= rhs.right)
        elif name == "above":
            # 1.bottom - offset = 2.top
            G.constrain(lhs.bottom - int(offset) >= rhs.top)
        elif name == "below":
            # 1.top + offset = 2.bottom
            G.constrain(lhs.top + int(offset) <= rhs.bottom)

    # Solve the lgs
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', r'All-NaN (slice|axis) encountered')
    G.solve()

    # get return values and return
    name_pos_dict = dict()
    for name, geo_instance in geo_mapping.items():
        if type(geo_instance) == tuple:
            geo = geo_instance[0]
        else:
            geo = geo_instance
        offset = 2
        name_pos_dict[name] = (int(geo.left.value) + offset,
                               int(geo.bottom.value) + offset)

    #with open("out.svg", "w") as f:
    #    f.write(G.svg())

    return name_pos_dict

def Test():
    G = Geo()

    # A and B are horizontal bars
    pd = Rect(G)
    pu = Rect(G)
    vdd = Rect(G)
    vss = Rect(G)
    a = Rect(G)
    y = Rect(G)

    G.constrain(pd.width == 4)
    G.constrain(pd.height == 4)

    G.constrain(pu.width == 4)
    G.constrain(pu.height == 4)

    G.constrain(vdd.width == 1)
    G.constrain(vdd.height == 1)

    G.constrain(vss.width == 1)
    G.constrain(vss.height == 1)

    G.constrain(a.width == 1)
    G.constrain(a.height == 1)

    G.constrain(y.width == 1)
    G.constrain(y.height == 1)

    G.constrain(vdd.bottom - 2 == pu.top)
    G.constrain(pu.bottom - 3 == pd.top)
    G.constrain(a.bottom - 1 == pd.top)
    G.constrain(y.bottom -1 == pd.top)
    G.constrain(a.right + 2 == pd.left)
    G.constrain(a.right + 2 == pu.left)
    G.constrain(y.left - 2 == pd.right)
    G.constrain(vss.top + 2 == pd.bottom)

    G.solve()

    with open("out.svg", "w") as f:
        f.write(G.svg())


if __name__ == "__main__":
    Test()
