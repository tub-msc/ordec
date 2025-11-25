# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from itertools import chain
from typing import Iterable
from public import public

from ..core import *

@public
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
        if pred is None:
            # cur is first vertex of path
            direction = rectilinear_direction(succ - cur)
            if path.endtype == PathEndType.SQUARE:
                extension = -halfwidth*direction
        elif succ is None:
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

@public
def expand_paths(layout: Layout):
    """
    For the given Layout, replaces all LayoutPath instances by geometrically
    equivalent LayoutPoly instances.
    """
    for path in layout.all(LayoutPath):
        path.replace(LayoutPoly(
            layer=path.layer,
            vertices=path_to_poly_vertices(path),
            ))

def rpoly_to_poly_vertices(rpoly: LayoutRectPoly) -> Iterable[Vec2I]:
    start_direction = rpoly.start_direction
    it = iter(rpoly.vertices())
    last = next(it)
    for pos in chain(it, (last,)):
        if start_direction == RectDirection.HORIZONTAL:
            yield Vec2I(pos.x, last.y)
        else:
            yield Vec2I(last.x, pos.y)
        yield pos
        last = pos

@public
def expand_rectpolys(layout: Layout):
    """
    For the given Layout, replaces all LayoutRectPoly instances by geometrically
    equivalent LayoutPoly instances.
    """
    for rpoly in layout.all(LayoutRectPoly):
        rpoly.replace(LayoutPoly(
            layer=rpoly.layer,
            vertices=rpoly_to_poly_vertices(rpoly)
            ))

def rpath_to_path_vertices(rpath: LayoutRectPath) -> Iterable[Vec2I]:
    start_direction = rpath.start_direction
    it = iter(rpath.vertices())
    pos0 = next(it)
    yield pos0
    last = pos0
    for pos in it:
        if start_direction == RectDirection.HORIZONTAL:
            intermediate = Vec2I(pos.x, last.y)
        else:
            intermediate = Vec2I(last.x, pos.y)
        if intermediate != pos and intermediate != last:
            yield intermediate
        yield pos
        last = pos

@public
def expand_rectpaths(layout: Layout):
    """
    For the given Layout, replaces all LayoutRectPath instances by geometrically
    equivalent LayoutPath instances.
    """
    for rpath in layout.all(LayoutRectPath):
        rpath.replace(LayoutPath(
            layer=rpath.layer,
            vertices=rpath_to_path_vertices(rpath),
            endtype=rpath.endtype,
            width=rpath.width,
            ))

@public
def expand_rects(layout: Layout):
    """
    For the given Layout, replaces all LayoutRect instances by geometrically
    equivalent LayoutPoly instances.
    """

    for rect in layout.all(LayoutRect):
        r = rect.rect
        rect.replace(LayoutPoly(
            layer=rect.layer,
            vertices=[
                Vec2I(r.lx, r.ly),
                Vec2I(r.ux, r.ly),
                Vec2I(r.ux, r.uy),
                Vec2I(r.lx, r.uy),
            ]
            ))

@public
def expand_geom(layout: Layout):
    """
    Replaces all LayoutRectPath, LayoutRectPoly, LayoutRect and LayoutPath
    instances by equivalent LayoutPoly instances.
    """
    expand_rectpolys(layout)
    expand_rectpaths(layout)
    expand_rects(layout)
    expand_paths(layout)

def flatten_instance(dst: Layout, src: Layout, tran: TD4I, first_level: bool):
    # At the first level, src is dst and mutable. We need to process only the
    # LayoutInstances and LayoutInstanceArarys and remove them.
    # At all subsequent levels, src is not dst. The processed LayoutInstances
    # and LayoutInstanceArrays should no longer be removed. (They cannot be
    # removed, since src is frozen.)

    assert first_level == (dst is src)

    for src_e in src.all(LayoutInstance):
        sub_tran = tran * src_e.loc_transform()
        flatten_instance(dst, src_e.ref, sub_tran, False)
        if first_level:
            src_e.remove()

    for src_e in src.all(LayoutInstanceArray):
        for col in range(src_e.cols):
            for row in range(src_e.rows):
                sub_tran = tran \
                    * (col*src_e.vec_col).transl() \
                    * (row*src_e.vec_row).transl() \
                    * src_e.loc_transform()
                flatten_instance(dst, src_e.ref, sub_tran, False)
        if first_level:
            src_e.remove()


    if first_level:
        return
    # Furthermore, for each layout below the first level, the geometric elements
    # must be transformed and copied to the destination layout (dst).

    def transform_vertex_loop(vertices):
        ret = [tran * v for v in vertices]
        if tran.det() < 0:
            ret.reverse() # to preserve ccw orientation
        return ret

    for src_e in src.all(LayoutPoly):
        dst % LayoutPoly(
            layer=src_e.layer,
            vertices=transform_vertex_loop(src_e.vertices()),
        )

    for src_e in src.all(LayoutPath):
        dst % LayoutPath(
            layer=src_e.layer,
            width=src_e.width,
            endtype=src_e.endtype,
            vertices=[tran * v for v in src_e.vertices()],
        )

    for src_e in src.all(LayoutRectPoly):
        dst % LayoutRectPoly(
            layer=src_e.layer,
            start_direction=src_e.start_direction,
            vertices=transform_vertex_loop(src_e.vertices()),
        )
    
    for src_e in src.all(LayoutRectPath):
        dst % LayoutRectPath(
            layer=src_e.layer,
            start_direction=src_e.start_direction,
            width=src_e.width,
            endtype=src_e.endtype,
            vertices=[tran * v for v in src_e.vertices()],
        )

    for src_e in src.all(LayoutRect):
        dst % LayoutRect(
            layer=src_e.layer,
            rect=tran * src_e.rect,
        )

    for src_e in src.all(LayoutLabel):
        dst % LayoutLabel(
            layer=src_e.layer,
            pos=tran * src_e.pos,
            text=src_e.text,
        )

@public
def flatten(layout: Layout):
    flatten_instance(layout, layout, TD4I(), True)

@public
def expand_instancearrays(layout: Layout):
    """
    For the given Layout, replaces all LayoutInstanceArrays by geometrically
    equivalent LayoutInstances.
    """
    for ainst in layout.all(LayoutInstanceArray):
        for col in range(ainst.cols):
            for row in range(ainst.rows):
                layout % LayoutInstance(
                    pos=ainst.pos + row*ainst.vec_row + col*ainst.vec_col,
                    orientation=ainst.orientation,
                    ref=ainst.ref,
                )
        ainst.remove()


@public
def expand_pins(layout: Layout):
    """
    For a given layout, removes LayoutPin objects and adds according LayoutPoly
    and LayoutLabel instances.

    Expects that all LayoutRect and LayoutRectPoly objects have already been
    expanded into LayoutPoly objects (e.g. through expand_geom).
    """
    # TODO: Add "Directory" type argument for generating labels
    for pin in layout.all(LayoutPin):
        if not isinstance(pin.ref, LayoutPoly):
            raise Exception(f"expand_pins expects LayoutPoly instead of {type(pin.ref)}. Run expand_geom() ahead of time!")

        vertices = pin.ref.vertices()

        center = sum(vertices, start=Vec2I(0, 0)) // len(vertices)

        pinlayer = pin.ref.layer.pinlayer()

        layout % LayoutPoly(
            layer=pinlayer,
            vertices=vertices,
            )
        layout % LayoutLabel(
            layer=pinlayer,
            pos=center,
            text=pin.pin.full_path_str(), # TODO: Do a Directory lookup here!
            )

        print(pin.ref)
        pin.remove()
