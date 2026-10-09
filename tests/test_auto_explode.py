"""Run: blender -b --factory-startup -P tests/test_auto_explode.py"""
import math
import os
import runpy
import sys

import bmesh
import bpy
from mathutils import Euler, Vector

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, REPO)
import auto_explode  # noqa: E402
from auto_explode import core  # noqa: E402

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def fresh():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    return bpy.context.scene


def box(name, size, loc):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    g = bmesh.ops.create_cube(bm, size=1)
    bmesh.ops.scale(bm, vec=size, verts=g["verts"])
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    o.location = loc
    bpy.context.scene.collection.objects.link(o)
    return o


def ranks(objs, **kw):
    parts, axis, step = core.plan(objs, **kw)
    return {p.obj.name: p.side * p.rank for p in parts}, axis, step


def world_z(o):
    bpy.context.view_layer.update()
    return o.matrix_world.translation.z


# A sandwich: board in the middle, layers above and below ------------------
scene = fresh()
board = box("Board", (1, 2, 0.02), (0, 0, 0))
above1 = box("Display", (0.8, 0.8, 0.03), (0, 0, 0.04))
above2 = box("Cover", (1, 2, 0.02), (0, 0, 0.09))
below1 = box("Battery", (0.6, 1, 0.04), (0, 0, -0.05))
below2 = box("Base", (1, 2, 0.02), (0, 0, -0.1))
r, axis, step = ranks([board, above1, above2, below1, below2])
check(tuple(axis) == (0, 0, 1), "auto axis is the thinnest direction (Z)")
check(r == {"Board": 0, "Display": 1, "Cover": 2, "Battery": -1, "Base": -2},
      f"sandwich ranks by what covers what (got {r})")
check(step > 0, "positive layer step")

# Parts side by side don't stack on each other -----------------------------
left = box("Key_L", (0.2, 0.2, 0.05), (-0.3, 0, 0.13))
right = box("Key_R", (0.2, 0.2, 0.06), (0.3, 0, 0.13))
r, _, _ = ranks([board, above1, above2, left, right], anchor=board)
check(r["Key_L"] == r["Key_R"] == 3, f"side-by-side buttons share a layer (got {r})")
check(r["Board"] == 0 and r["Cover"] == 2, "the requested anchor stays put")

# Fasteners leave first and go farthest ------------------------------------
screw = box("Screw_1", (0.05, 0.05, 0.12), (0.4, 0.8, -0.06))
r, _, _ = ranks([board, below1, below2, screw], anchor=board)
check(r["Screw_1"] == -3, f"screw goes one past the outermost bottom layer (got {r})")

# Children ride along; hidden helpers are ignored ---------------------------
chip = box("Chip", (0.1, 0.1, 0.02), (0, 0, 0.02))
chip.parent = board
helper = box("Cutter", (0.3, 0.3, 0.3), (0, 0, 0.09))
helper.hide_render = True
parts, _, _ = core.plan([board, chip, above2, helper])
names = {p.obj.name for p in parts}
check("Chip" not in names and "Cutter" not in names, f"children/hidden helpers aren't parts ({names})")

# Forced axis -------------------------------------------------------------
_, axis, _ = ranks([board, above1], axis="X")
check(tuple(axis) == (1, 0, 0), "forced X axis")

# Animation: loop, order, clear keeps the user's own keys ------------------
scene = fresh()
board = box("Board", (1, 2, 0.02), (0, 0, 0))
disp = box("Display", (0.8, 0.8, 0.03), (0, 0, 0.04))
cover = box("Cover", (1, 2, 0.02), (0, 0, 0.09))
cover.keyframe_insert("rotation_euler", frame=1)  # user's own animation
parts, _, _ = core.plan([board, disp, cover], anchor=board)
end = core.animate(parts, scene, start=1, move=10, stagger=5, hold=20, lead=4)
check(scene.frame_start == 1 and scene.frame_end == end, "scene frame range set")
z0 = world_z(cover)
scene.frame_set(1)
check(abs(world_z(cover) - z0) < 1e-6, "assembled at the first frame")
scene.frame_set(end)
check(abs(world_z(cover) - z0) < 1e-6, "assembled again at the last frame (seamless loop)")
scene.frame_set(4 + 5 + 10 + 10)  # inside the hold
check(world_z(cover) > world_z(disp) > 0.04, "fully exploded during the hold, cover above display")


def first_key(o):
    fcs = [fc for h in core._fcurve_holders(o.animation_data.action) for fc in h
           if fc.data_path == "delta_location"]
    return min(k.co.x for fc in fcs for k in fc.keyframe_points if k.co.y != 0) if fcs else None


check(first_key(cover) < first_key(disp), "outer part starts moving before the inner one")
check(core.clear([board, disp, cover]) == 2, "clear reports the moved parts")
holders = core._fcurve_holders(cover.animation_data.action)
paths = {fc.data_path for h in holders for fc in h}
check("delta_location" not in paths and "rotation_euler" in paths,
      f"clear removes only Auto Explode's keys ({paths})")

# Static pose under a rotated parent lands in the right world place ---------
scene = fresh()
pivot = bpy.data.objects.new("Pivot", None)
scene.collection.objects.link(pivot)
pivot.rotation_euler = Euler((0, math.radians(90), 0))
base = box("Base", (1, 2, 0.02), (0, 0, 0))
lid = box("Lid", (1, 2, 0.02), (0, 0, 0.1))
lid.parent = pivot
bpy.context.view_layer.update()
lid.matrix_parent_inverse = pivot.matrix_world.inverted()
bpy.context.view_layer.update()
before = lid.matrix_world.translation.copy()
parts, _, _ = core.plan([base, lid])
core.pose(parts, 1.0)
bpy.context.view_layer.update()
moved = lid.matrix_world.translation - before
want = next(p.offset for p in parts if p.obj is lid)
check((moved - want).length < 1e-6, f"offset is in world space under a rotated parent ({moved})")

# Operators through the UI path -------------------------------------------
scene = fresh()
auto_explode.register()
objs = [box(n, (1, 2, 0.02), (0, 0, z)) for n, z in (("A", 0), ("B", 0.06), ("C", -0.06))]
for o in objs:
    o.select_set(True)
bpy.context.view_layer.objects.active = objs[0]
check(bpy.ops.auto_explode.animate() == {"FINISHED"}, "Animate operator")
scene.frame_set(scene.frame_start + 12 + 24 + 5)
bpy.context.view_layer.update()
check(objs[0].matrix_world.translation.length < 1e-9 and
      objs[1].matrix_world.translation.z > 0.06, "active object is the anchor in the operator")
check(bpy.ops.auto_explode.pose() == {"FINISHED"}, "Explode Pose operator")
check(bpy.ops.auto_explode.clear() == {"FINISHED"}, "Reassemble operator")
check(all(o.delta_location.length == 0 for o in objs), "reassembled")
auto_explode.unregister()

# The demo remote explodes in the expected order ---------------------------
fresh()
runpy.run_path(os.path.join(REPO, "examples", "remote_controller.py"), run_name="x")["build"]()
remote = [o for o in bpy.data.collections["Remote"].all_objects if not o.hide_render]
r, _, _ = ranks(remote)
check(r["Circuit_Board"] == 0 and r["Top_Shell"] == 2 and r["Bottom_Shell"] == -2
      and r["Screen_Glass"] == 3 and r["Screw_1"] == -4 and r["LiPo_Battery"] == -1,
      "remote: board anchors, shells and screws in order")
check("MCU" not in r, "remote: chips ride on the board")

print(f"\n{'ALL OK' if not failures else f'{len(failures)} FAILED'}")
sys.exit(1 if failures else 0)
