# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ordec.core import *

def _iter_triplets(vertices):
    stack = [None]
    try:
        stack.append(next(vertices).pos)
        stack.append(next(vertices).pos)
    except StopIteration:
        raise ValueError("Too few vertices in path (must have at least two).")
    yield stack
    while True:
        try:
            stack.pop(0)
            stack.append(next(vertices).pos)
        except StopIteration:
            break
        yield stack
    stack.append(None)
    yield stack

def _direction(vec: Vec2I):
    if vec.x == 0:
        if vec.y == 0:
            raise ValueError(f"Direction of {vec} undefined.")
        elif vec.y > 0:
            return Vec2I(0, 1)
        else:
            return Vec2I(0, -1)
    elif vec.y == 0:
        if vec.x == 0:
            assert False
        elif vec.x > 0:
            return Vec2I(1, 0)
        else:
            return Vec2I(-1, 0)
    else:
        raise ValueError(f"{vec} is not rectilinear.")

def path_to_poly_vertices(path: LayoutPath):
    if path.width % 2 != 0:
        raise ValueError(f"Path width must be multiple of two (is {path.width}.")
    halfwidth = path.width // 2
    vertices_left = []
    vertices_right = []
    for a, b, c in _iter_triplets(path.vertices):
        if a == None or c == None:
            if a == None:
                # b is first vertex of path
                direction = _direction(c - b)
                if path.endtype == PathEndType.SQUARE:
                    extension = -halfwidth*direction
                else:
                    extension = Vec2I(0, 0)
            else:
                # b is last vertex of path
                direction = _direction(b - a)
                if path.endtype == PathEndType.SQUARE:
                    extension = halfwidth*direction
                else:
                    extension = Vec2I(0, 0)
            normal = Vec2I(direction.y, -direction.x)
            
            #vertices_right.append(b)
            vertices_left.append(b + halfwidth*normal + extension)
            vertices_right.append(b - halfwidth*normal + extension)
        else:
            direction = _direction(c - b) + _direction(b - a)
            abs_direction = Vec2I(abs(direction.x), abs(direction.y))
            if abs_direction == Vec2I(1, 1):
                # 90 degree turn, which is the usual case.
                normal = Vec2I(direction.y, -direction.x)
                vertices_left.append(b + halfwidth*normal)
                vertices_right.append(b - halfwidth*normal)
            elif abs_direction in (Vec2I(0, 2), Vec2I(2, 0)): 
                # 0 degree turn => node b can be dropped
                pass
            else:
                raise ValueError("Unsupported path (Only 90 degree and 0 degree turns permitted.")

    vertices_right.reverse()
    vertices_loop = vertices_left + vertices_right
    return vertices_loop

def paths_to_poly(layout: Layout):
    for old_path in layout.all(LayoutPath):
        vertices_loop = path_to_poly_vertices(old_path)
        new_poly = layout % LayoutPoly(
            layer=old_path.layer,
            vertices=vertices_loop,
            )

        for v in old_path.vertices:
            v.remove()
        old_path.remove()
