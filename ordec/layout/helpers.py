# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from ..core import *

def poly_orientation(vertices: list[Vec2I]):
    """
    Returns either 'cw' or 'ccw'.
    Warning: Does not work for complex (i.e. self-intersecting) polygons!
    """

    # See https://en.wikipedia.org/wiki/Curve_orientation#Orientation_of_a_simple_polygon
    B_idx = 0
    B = vertices[0]
    for v_idx, v in enumerate(vertices):
        if (v.x < B.x) or ((v.x == B.x) and (v.y < B.y)):
            B_idx = v_idx
            B = v
    A = vertices[(B_idx - 1) % len(vertices)]
    C = vertices[(B_idx + 1) % len(vertices)]

    det = (B.x-A.x)*(C.y-A.y) - (C.x-A.x)*(B.y-A.y)
    if (A == B) or (B == C) or (det == 0):
        raise ValueError("Invalid polygon.")
    if det < 0:
        return 'cw'
    else:
        return 'ccw'

def iter_triplets(vertices):
    """
    Iterates through iterable 'vertices' in triplets
    (predecessor, current, successor). Each vertex is returned exactly once
    as 'current'. For the first element, 'predecessor' is None; for the last
    element, 'successor' is None.

    This function is meant for traversing the vertices of a LayoutPath.
    Thus, the iterable must return at least two elements.
    """
    it = iter(vertices)

    try:
        frame = [None, next(it), next(it)]
    except StopIteration:
        raise ValueError("Too few vertices in path (must have at least two).")
    yield frame
    while True:
        frame.pop(0)
        try:
            frame.append(next(it))
        except StopIteration:
            break
        yield frame
    frame.append(None)
    yield frame

def rectilinear_direction(vec: Vec2I) -> Vec2I:
    """
    The input vector must be zero in one coordinate and non-zero in the other
    coordinate (rectilinear). The function returns the matching unit vectors,
    which is either Vec2I(1, 0), Vec2I(-1, 0), Vec2I(0, 1) or Vec2I(0, -1).
    """
    if vec.x == 0:
        if vec.y > 0:
            return Vec2I(0, 1)
        elif vec.y < 0:
            return Vec2I(0, -1)
    elif vec.y == 0:
        if vec.x > 0:
            return Vec2I(1, 0)
        elif vec.x < 0:
            return Vec2I(-1, 0)
        assert False
    raise ValueError(f"{vec} is not rectilinear.")

def path_to_poly_vertices(path: LayoutPath) -> list[Vec2I]:
    """
    Calculates the outline / stroke expansion of the given LayoutPath.
    """
    if path.width % 2 != 0:
        raise ValueError(f"Path width must be multiple of two (is {path.width}.")
    halfwidth = path.width // 2
    outline = []
    for pred, cur, succ in iter_triplets(path.vertices()):
        extension = Vec2I(0, 0)
        if pred == None:
            # cur is first vertex of path
            direction = rectilinear_direction(succ - cur)
            if path.endtype == PathEndType.SQUARE:
                extension = -halfwidth*direction
        elif succ == None:
            # cur is last vertex of path
            direction = rectilinear_direction(cur - pred)
            if path.endtype == PathEndType.SQUARE:
                extension = halfwidth*direction
        else:
            # cur has both a predecessor and a successor
            direction = rectilinear_direction(succ - cur) + rectilinear_direction(cur - pred)
            abs_direction = Vec2I(abs(direction.x), abs(direction.y))
            if abs_direction in (Vec2I(0, 2), Vec2I(2, 0)): 
                # 0 degree turn => node b can be dropped
                continue
            if abs_direction != Vec2I(1, 1):
                raise ValueError("Unsupported path (Only 90 degree and 0 degree turns permitted.")
            # else: 90 degree turn, which is the usual case.
        normal = Vec2I(direction.y, -direction.x)
        outline.append(cur + halfwidth*normal + extension)
        outline.insert(0, cur - halfwidth*normal + extension)
            
    return outline

def paths_to_poly(layout: Layout):
    """
    For the given Layout, removes all LayoutPath objects and replaces them by
    geometrically equivalent LayoutPoly objects.
    """
    for old_path in layout.all(LayoutPath):
        vertices_loop = path_to_poly_vertices(old_path)
        new_poly = layout % LayoutPoly(
            layer=old_path.layer,
            vertices=vertices_loop,
            )

        old_path.remove()
