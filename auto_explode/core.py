"""Plan and animate an exploded view.

The idea: pick an explode axis (by default the assembly's thinnest direction, which is how
most products are stacked). One part is the anchor and stays put: the active object if it's
one of the parts, otherwise the part nearest the middle. Every
other part goes to the side it sits on, and gets a *rank*: one more than the highest-ranked
part it covers. A top shell covers the screen module, which covers the circuit board, so the
shell must travel farther than the screen. Outer parts leave first and come back last.
Fasteners (screws, bolts, ...) are pulled out before anything else.

Parts parented to another selected part ride along with it, so chips stay on their board.
"""

import re
from dataclasses import dataclass, field

import bpy
from mathutils import Vector

FASTENER = re.compile(r"(screw|bolt|nut|rivet|fastener|washer)", re.I)
TAG = "auto_explode_offset"


@dataclass
class Part:
    obj: object
    lo: Vector
    hi: Vector
    t: float = 0.0          # center position along the axis, relative to the assembly
    side: int = 0           # +1 / -1, 0 for the anchor
    rank: int = 0           # 0 = anchor; higher = farther out
    fastener: bool = False
    offset: Vector = field(default_factory=lambda: Vector((0, 0, 0)))


# --------------------------------------------------------------------------
# Geometry helpers
# --------------------------------------------------------------------------

def _ancestors(obj):
    p = obj.parent
    while p is not None:
        yield p
        p = p.parent


def _descendants(obj):
    for child in obj.children:
        yield child
        yield from _descendants(child)


def _renders(obj):
    return obj.type in {"MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES"} and not obj.hide_render


def _bounds(objs):
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    if not pts:
        return None
    lo = Vector(min(p[i] for p in pts) for i in range(3))
    hi = Vector(max(p[i] for p in pts) for i in range(3))
    return lo, hi


def roots(objects):
    """Selected objects that don't have a selected ancestor."""
    chosen = set(objects)
    return [o for o in objects if not any(a in chosen for a in _ancestors(o))]


def pick_axis(lo, hi, axis="AUTO"):
    if axis in ("X", "Y", "Z"):
        return Vector([1.0 if c == axis else 0.0 for c in "XYZ"])
    size = hi - lo
    i = min(range(3), key=lambda k: size[k])
    return Vector([1.0 if k == i else 0.0 for k in range(3)])


def _footprints_overlap(a, b, axis, tol):
    """Do the two parts overlap when seen down the axis?"""
    for k in range(3):
        if axis[k] > 0.5:
            continue
        if min(a.hi[k], b.hi[k]) - max(a.lo[k], b.lo[k]) <= tol:
            return False
    return True


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------

def plan(objects, axis="AUTO", spacing=1.0, anchor=None):
    """Work out where every part goes. Returns (parts, axis_vector, step)."""
    # World matrices are stale for objects a script has just created or moved.
    bpy.context.view_layer.update()
    parts = []
    for obj in roots(objects):
        members = [o for o in (obj, *_descendants(obj)) if _renders(o)]
        if not members:
            continue  # hidden helpers (boolean cutters, empties) ride with their parent
        lo, hi = _bounds(members)
        parts.append(Part(obj, lo, hi, fastener=bool(FASTENER.search(obj.name))))
    if len(parts) < 2:
        return parts, Vector((0, 0, 1)), 0.0

    lo = Vector(min(p.lo[i] for p in parts) for i in range(3))
    hi = Vector(max(p.hi[i] for p in parts) for i in range(3))
    a = pick_axis(lo, hi, axis)
    center = (lo + hi) / 2
    extent = (hi - lo).dot(a)
    size = (hi - lo).length
    eps = extent * 0.02
    step = extent * 0.9 * spacing

    for p in parts:
        p.t = ((p.lo + p.hi) / 2 - center).dot(a)

    # Anchor: the requested part, else the non-fastener nearest the middle (ties: bigger).
    chosen = next((p for p in parts if anchor is not None and p.obj == anchor), None)
    candidates = [p for p in parts if not p.fastener] or parts
    anchor = chosen or min(candidates, key=lambda p: (round(abs(p.t) / max(eps, 1e-9)),
                                                      -(p.hi - p.lo).length))
    for p in parts:
        if p is not anchor:
            p.side = 1 if p.t >= anchor.t else -1  # above or below the anchor

    def outer(p):  # how far out the part reaches on its own side
        return p.hi.dot(a) if p.side > 0 else -p.lo.dot(a)

    memo = {}

    def rank(p):
        if p is anchor:
            return 0
        if id(p) in memo:
            return memo[id(p)]
        memo[id(p)] = 1  # guard; the relation below is strictly ordered, so no cycles
        inner = [q for q in parts
                 if q is not p and not q.fastener
                 and (q is anchor or q.side == p.side)
                 and outer(q) < outer(p) - eps
                 and _footprints_overlap(p, q, a, size * 0.005)]
        memo[id(p)] = 1 + max((rank(q) for q in inner), default=0)
        return memo[id(p)]

    for p in parts:
        if not p.fastener:
            p.rank = rank(p)
    for side in (1, -1):
        top = max((p.rank for p in parts if p.side == side and not p.fastener), default=0)
        for p in parts:
            if p.fastener and p.side == side:
                p.rank = top + 1  # screws come out first and end up farthest out
    for p in parts:
        p.offset = a * (p.side * p.rank * step)
    return parts, a, step


# --------------------------------------------------------------------------
# Applying
# --------------------------------------------------------------------------

def _local(obj, world_vec):
    """World-space offset -> the space delta_location lives in (the parent's)."""
    if obj.parent is None:
        return world_vec.copy()
    basis = obj.parent.matrix_world @ obj.matrix_parent_inverse
    return basis.to_3x3().inverted() @ world_vec


def _fcurve_holders(action):
    """Containers of F-curves, for both legacy and slotted (4.4+) actions."""
    if hasattr(action, "layers"):
        return [bag.fcurves for layer in action.layers for strip in layer.strips
                for bag in strip.channelbags]
    return [action.fcurves]


def clear(objects):
    """Remove Auto Explode's offsets and keyframes. Other animation is left alone."""
    n = 0
    for obj in objects:
        if TAG not in obj:
            continue
        ad = obj.animation_data
        if ad and ad.action:
            for holder in _fcurve_holders(ad.action):
                for fc in [fc for fc in holder if fc.data_path == "delta_location"]:
                    holder.remove(fc)
        obj.delta_location = (0, 0, 0)
        del obj[TAG]
        n += 1
    return n


def pose(parts, amount=1.0):
    """Static exploded pose, no keyframes (for stills)."""
    clear([p.obj for p in parts])
    for p in parts:
        if p.rank:
            p.obj.delta_location = _local(p.obj, p.offset * amount)
            p.obj[TAG] = tuple(p.offset)


def animate(parts, scene, start=1, move=24, stagger=6, hold=30, lead=12):
    """Keyframe explode -> hold -> reassemble, as a seamless loop. Returns the last frame."""
    clear([p.obj for p in parts])
    moving = [p for p in parts if p.rank]
    if not moving:
        return start
    top = max(p.rank for p in moving)
    out_done = start + lead + (top - 1) * stagger + move
    back_start = out_done + hold
    end = back_start + (top - 1) * stagger + move + lead

    for p in moving:
        zero, full = Vector((0, 0, 0)), _local(p.obj, p.offset)
        leave = start + lead + (top - p.rank) * stagger   # outermost first
        ret = back_start + (p.rank - 1) * stagger         # innermost first
        for frame, value in ((leave, zero), (leave + move, full),
                             (ret, full), (ret + move, zero)):
            p.obj.delta_location = value
            p.obj.keyframe_insert("delta_location", frame=frame)
        p.obj.delta_location = zero
        p.obj[TAG] = tuple(p.offset)

    scene.frame_start, scene.frame_end = start, end
    return end
