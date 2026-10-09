"""Render the README stills and GIF frames from the demo remote.

    blender -b --factory-startup -P docs/images/render.py [-- quick]
    python docs/images/compose.py

Builds the remote with examples/remote_controller.py, runs Auto Explode on it exactly as
the Animate button does, then renders. Fails if the explode plan isn't the expected stack.
"""
import math
import os
import runpy
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
RAW = os.path.join(HERE, "_raw")
sys.path.insert(0, REPO)
from auto_explode import core  # noqa: E402

QUICK = "quick" in sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else False
os.makedirs(RAW, exist_ok=True)

scene = runpy.run_path(os.path.join(REPO, "examples", "remote_controller.py"),
                       run_name="remote_builder")["build"]()
bpy.context.window_manager  # noqa: B018  (keep context alive in background)
parts_objs = [o for o in bpy.data.collections["Remote"].all_objects if not o.hide_render]
parts, axis, step = core.plan(parts_objs, anchor=bpy.data.objects["Circuit_Board"])
ranks = {p.obj.name: p.side * p.rank for p in parts}
assert ranks["Circuit_Board"] == 0 and ranks["Top_Shell"] == 2 and ranks["Screw_1"] == -4, ranks
end = core.animate(parts, scene)
PEAK = 70  # fully exploded, inside the hold
cam = scene.camera
target0 = Vector((0, 0, 0.01))
view_dir = (cam.location - target0).normalized()


def bounds_at(frame):
    scene.frame_set(frame)
    deps = bpy.context.evaluated_depsgraph_get()
    pts = []
    for o in parts_objs:
        if o.type != "MESH":
            continue
        ev = o.evaluated_get(deps)
        pts += [ev.matrix_world @ Vector(c) for c in ev.bound_box]
    lo = Vector(min(p[i] for p in pts) for i in range(3))
    hi = Vector(max(p[i] for p in pts) for i in range(3))
    return lo, hi


def frame_camera(lo, hi, direction, margin=1.0, lens=None):
    """Point the camera along `direction` at the box, close enough to fill the frame."""
    if lens:
        cam.data.lens = lens
    center = (lo + hi) / 2
    radius = (hi - lo).length / 2
    r = scene.render
    aspect = r.resolution_x / r.resolution_y
    half_w = math.atan(cam.data.sensor_width / 2 / cam.data.lens)
    half_h = math.atan(math.tan(half_w) / aspect)
    dist = radius / math.sin(min(half_w, half_h)) * margin
    cam.location = center + direction.normalized() * dist
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
    return center, dist


def render_still(path, frame, w, h, samples):
    scene.frame_set(frame)
    scene.render.resolution_x, scene.render.resolution_y = w, h
    scene.eevee.taa_render_samples = samples
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def render_frames(folder, frames, w, h, samples, per_frame=None):
    os.makedirs(folder, exist_ok=True)
    for i, f in enumerate(frames):
        if per_frame:
            per_frame(i, f)
        render_still(os.path.join(folder, f"{i:04d}.png"), f, w, h, samples)


S_HI, S_LO = (16, 8) if QUICK else (96, 32)
step_f = 4 if QUICK else 2

# Stills -------------------------------------------------------------------
scene.render.resolution_x, scene.render.resolution_y = 1600, 1000
lo, hi = bounds_at(1)
frame_camera(lo, hi, view_dir, margin=0.78)
render_still(os.path.join(RAW, "hero_assembled.png"), 1, 1600, 1000, S_HI)
lo, hi = bounds_at(PEAK)
frame_camera(lo, hi, view_dir, margin=0.95)
render_still(os.path.join(RAW, "hero_exploded.png"), PEAK, 1600, 1000, S_HI)

# Animation, product angle (camera framed on the exploded extent) ----------
frames = list(range(scene.frame_start, end, step_f))
scene.render.resolution_x, scene.render.resolution_y = 800, 500
frame_camera(lo, hi, view_dir, margin=0.95)
render_frames(os.path.join(RAW, "anim_main"), frames, 800, 500, S_LO)

# Animation, side view: the stack order reads best from here ----------------
side_dir = Vector((1.0, -0.12, 0.16))
frame_camera(lo, hi, side_dir, margin=0.8, lens=85)
render_frames(os.path.join(RAW, "anim_side"), frames, 800, 500, S_LO)

# Orbit around the exploded pose -------------------------------------------
center, dist = frame_camera(lo, hi, view_dir, margin=0.95, lens=70)
n = 24 if QUICK else 60
elev = math.asin(view_dir.normalized().z)
start_az = math.atan2(view_dir.y, view_dir.x)


def orbit(i, f):
    az = start_az + 2 * math.pi * i / n
    d = Vector((math.cos(az) * math.cos(elev), math.sin(az) * math.cos(elev), math.sin(elev)))
    cam.location = center + d * dist
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()


render_frames(os.path.join(RAW, "anim_orbit"), [PEAK] * n, 800, 500, S_LO, per_frame=orbit)

with open(os.path.join(RAW, "plan.txt"), "w", encoding="utf-8") as fh:
    for name, r in sorted(ranks.items(), key=lambda kv: kv[1]):
        fh.write(f"{r:+d} {name}\n")
print("RENDER_OK", len(frames), "frames per animation")
