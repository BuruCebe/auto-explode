"""Build the demo model: a high-tech remote controller, in its own scene.

Run inside Blender (Scripting tab > Open > Run) or headless:
    blender -b -P examples/remote_controller.py -- out.blend

Real-world size: 170 x 48 x 21 mm. Every part is a separate object with bevels and real
materials; chips are parented to the circuit board so they explode with it.
"""
import math
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

SCENE = "Remote Controller"
MM = 0.001
W, L = 48 * MM, 170 * MM          # width (X), length (Y)
H_BOT, H_TOP = 11 * MM, 9.5 * MM  # shell heights
WALL = 1.6 * MM
TOP_Z = H_BOT + H_TOP             # top surface


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def material(name, color, rough, metal=0.0, emit=None, strength=0.0, coat=0.0, alpha=1.0,
             spec=0.5):
    m = bpy.data.materials.new(name)
    m["remote_demo"] = True
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (*color, 1)
    p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metal
    p.inputs["Coat Weight"].default_value = coat
    p.inputs["Specular IOR Level"].default_value = spec
    if emit:
        p.inputs["Emission Color"].default_value = (*emit, 1)
        p.inputs["Emission Strength"].default_value = strength
    if alpha < 1:
        p.inputs["Alpha"].default_value = alpha
        m.surface_render_method = "BLENDED"
    return m


def new_object(name, build, mat, collection, smooth=True):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    build(bm)
    if all(e.is_manifold for e in bm.edges):  # open shells set their own normals
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    collection.objects.link(obj)
    if mat:
        me.materials.append(mat)
    # Origin at the part's center, so it pivots and explodes sensibly.
    center = sum((Vector(c) for c in obj.bound_box), Vector()) / 8
    me.transform(Matrix.Translation(-center))
    obj.location = center
    me.uv_layers.new()
    if smooth:
        me.shade_smooth()
    return obj


def attach(child, parent):
    """Parent without moving. matrix_world isn't evaluated yet, so use the basis."""
    child.parent = parent
    child.matrix_parent_inverse = parent.matrix_basis.inverted()


def bevel(obj, width, segments=3):
    b = obj.modifiers.new("Bevel", "BEVEL")
    b.width = width
    b.segments = segments
    b.limit_method = "ANGLE"
    b.angle_limit = math.radians(35)
    b.harden_normals = True
    b.use_clamp_overlap = True
    obj.modifiers.new("Weighted Normal", "WEIGHTED_NORMAL").keep_sharp = True


def rounded_box(w, l, h, r, z0, x=0.0, y=0.0, segments=10, open_face=None):
    """Box with rounded vertical corners. open_face: 'TOP' or 'BOTTOM' to leave it open."""
    def build(bm):
        geom = bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=(w, l, h), verts=geom["verts"])
        vertical = [e for e in bm.edges
                    if (e.verts[0].co.xy - e.verts[1].co.xy).length < 1e-9]
        bmesh.ops.bevel(bm, geom=vertical, offset=r, segments=segments,
                        affect="EDGES", profile=0.5)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)  # while still closed
        if open_face:
            sign = 1 if open_face == "TOP" else -1
            face = max(bm.faces, key=lambda f: sign * f.calc_center_median().z)
            bmesh.ops.delete(bm, geom=[face], context="FACES_ONLY")
        bmesh.ops.translate(bm, verts=bm.verts, vec=(x, y, z0 + h / 2))
    return build


def cylinder(r, h, z0, x=0.0, y=0.0, segments=48):
    def build(bm):
        bmesh.ops.create_cone(bm, cap_ends=True, segments=segments, radius1=r, radius2=r,
                              depth=h)
        bmesh.ops.translate(bm, verts=bm.verts, vec=(x, y, z0 + h / 2))
    return build


def ring(r_out, r_in, h, z0, x=0.0, y=0.0, segments=64):
    def build(bm):
        outer = bmesh.ops.create_circle(bm, cap_ends=False, segments=segments, radius=r_out)
        inner = bmesh.ops.create_circle(bm, cap_ends=False, segments=segments, radius=r_in)
        edges = [e for e in bm.edges]
        bmesh.ops.bridge_loops(bm, edges=edges)
        ext = bmesh.ops.extrude_face_region(bm, geom=list(bm.faces))
        bmesh.ops.translate(bm, verts=[v for v in ext["geom"] if isinstance(v, bmesh.types.BMVert)],
                            vec=(0, 0, h))
        bmesh.ops.translate(bm, verts=bm.verts, vec=(x, y, z0))
    return build


# --------------------------------------------------------------------------
# Scene
# --------------------------------------------------------------------------

def _remove_previous():
    """Delete what an earlier run created, so names stay clean on rebuild."""
    for name in ("Remote", "Studio Lights"):
        coll = bpy.data.collections.get(name)
        if coll is None:
            continue
        for obj in list(coll.all_objects):
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if data is not None and data.users == 0:
                if isinstance(data, bpy.types.Mesh):
                    bpy.data.meshes.remove(data)
                elif isinstance(data, bpy.types.Light):
                    bpy.data.lights.remove(data)
        bpy.data.collections.remove(coll)
    cam = bpy.data.objects.get("Remote_Camera")
    if cam is not None:
        bpy.data.objects.remove(cam, do_unlink=True)
    # Materials and worlds from the last run, now unused: rebuild them from scratch.
    for m in [m for m in bpy.data.materials if m.users == 0 and m.get("remote_demo")]:
        bpy.data.materials.remove(m)


def build():
    _remove_previous()
    scene = bpy.data.scenes.get(SCENE)
    if scene is not None:
        bpy.data.scenes.remove(scene)
    for w in [w for w in bpy.data.worlds if w.users == 0 and w.name.startswith("Studio Dark")]:
        bpy.data.worlds.remove(w)
    scene = bpy.data.scenes.new(SCENE)
    if bpy.context.window is not None:
        bpy.context.window.scene = scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.unit_settings.length_unit = "MILLIMETERS"

    root = bpy.data.collections.new("Remote")
    scene.collection.children.link(root)

    # Materials ------------------------------------------------------------
    alu = material("Anodized_Aluminum_Space_Gray", (0.11, 0.115, 0.125), 0.3, metal=1.0)
    soft = material("Soft_Touch_Polymer", (0.018, 0.019, 0.022), 0.85, spec=0.2)
    steel = material("Machined_Aluminum", (0.62, 0.63, 0.66), 0.22, metal=1.0)
    glow = material("Backlight_Cyan", (0.02, 0.05, 0.06), 0.3,
                    emit=(0.1, 0.85, 1.0), strength=6.0)
    glass = material("Gorilla_Glass", (0.01, 0.012, 0.015), 0.04, coat=1.0, alpha=0.35)
    pcb = material("PCB_Matte_Green", (0.01, 0.07, 0.035), 0.45, coat=0.4)
    chip = material("IC_Epoxy", (0.012, 0.012, 0.014), 0.38)
    shield = material("Tin_Shield_Can", (0.7, 0.71, 0.72), 0.3, metal=1.0)
    gold = material("Gold_Contacts", (1.0, 0.72, 0.32), 0.25, metal=1.0)
    cell = material("LiPo_Foil", (0.32, 0.36, 0.42), 0.35, metal=0.7)
    rubber = material("Rubber_Feet", (0.025, 0.025, 0.025), 0.9, spec=0.2)
    screw_m = material("Black_Oxide_Steel", (0.05, 0.05, 0.055), 0.35, metal=1.0)
    ir = material("IR_Lens_Smoked", (0.25, 0.015, 0.02), 0.08, coat=1.0)

    # Display: emissive UI under the glass ---------------------------------
    disp = material("OLED_Display_UI", (0.0, 0.0, 0.0), 0.5)
    nt = disp.node_tree
    p = nt.nodes["Principled BSDF"]
    tc = nt.nodes.new("ShaderNodeTexCoord")
    grad = nt.nodes.new("ShaderNodeTexGradient")
    grad.gradient_type = "SPHERICAL"
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (55, 55, 55)
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.wave_type = "RINGS"
    wave.inputs["Scale"].default_value = 160
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.0, 0.0, 0.0, 1)
    ramp.color_ramp.elements[1].position = 0.6
    ramp.color_ramp.elements[1].color = (0.08, 0.75, 1.0, 1)
    mix = nt.nodes.new("ShaderNodeMath")
    mix.operation = "MULTIPLY"
    nt.links.new(tc.outputs["Object"], mapping.inputs["Vector"])
    nt.links.new(mapping.outputs["Vector"], grad.inputs["Vector"])
    nt.links.new(tc.outputs["Object"], wave.inputs["Vector"])
    nt.links.new(grad.outputs["Fac"], mix.inputs[0])
    nt.links.new(wave.outputs["Fac"], mix.inputs[1])
    nt.links.new(mix.outputs["Value"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], p.inputs["Emission Color"])
    p.inputs["Emission Strength"].default_value = 4.0

    # Layout (Y runs along the remote, +Y is the front end) ----------------
    SCREEN_Y, DPAD_Y, ROW_Y, PILL_Y, LED_Y = 50 * MM, 0.0, -30 * MM, -52 * MM, 77 * MM
    screen_w, screen_l = 36 * MM, 34 * MM
    small_r = 4.2 * MM
    row_x = (-12 * MM, 0.0, 12 * MM)

    # Shells -------------------------------------------------------------
    bottom = new_object("Bottom_Shell", rounded_box(W, L, H_BOT, 9 * MM, 0.0, open_face="TOP"),
                        soft, root)
    s = bottom.modifiers.new("Solidify", "SOLIDIFY")
    s.thickness, s.offset, s.use_even_offset = WALL, -1, True
    bevel(bottom, 0.7 * MM)

    top = new_object("Top_Shell", rounded_box(W, L, H_TOP, 9 * MM, H_BOT, open_face="BOTTOM"),
                     alu, root)
    s = top.modifiers.new("Solidify", "SOLIDIFY")
    s.thickness, s.offset, s.use_even_offset = WALL, -1, True

    def cutters(bm):
        z0, h = H_BOT, H_TOP + 2 * MM
        bmesh.ops.create_cone(bm, cap_ends=True, segments=64, radius1=14.6 * MM,
                              radius2=14.6 * MM, depth=h,
                              matrix=Matrix.Translation((0, DPAD_Y, z0 + h / 2)))
        for x in row_x:
            bmesh.ops.create_cone(bm, cap_ends=True, segments=48, radius1=small_r + 0.4 * MM,
                                  radius2=small_r + 0.4 * MM, depth=h,
                                  matrix=Matrix.Translation((x, ROW_Y, z0 + h / 2)))
        for x in (-9 * MM, 9 * MM):
            g = bmesh.ops.create_cube(bm, size=1.0)
            bmesh.ops.scale(bm, vec=(11.6 * MM, 5.4 * MM, h), verts=g["verts"])
            bmesh.ops.translate(bm, vec=(x, PILL_Y, z0 + h / 2), verts=g["verts"])
        g = bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=(screen_w - 2 * MM, screen_l - 2 * MM, h), verts=g["verts"])
        bmesh.ops.translate(bm, vec=(0, SCREEN_Y, z0 + h / 2), verts=g["verts"])

    cut = new_object("Top_Shell_Cutters", cutters, None, root, smooth=False)
    attach(cut, top)
    cut.hide_render = True
    cut.hide_viewport = True
    cut.display_type = "WIRE"
    boolean = top.modifiers.new("Holes", "BOOLEAN")
    boolean.operation, boolean.object, boolean.solver = "DIFFERENCE", cut, "EXACT"
    bevel(top, 0.6 * MM)

    # Top details --------------------------------------------------------
    g = new_object("Screen_Glass", rounded_box(screen_w, screen_l, 0.8 * MM, 3 * MM, TOP_Z,
                                               y=SCREEN_Y), glass, root)
    bevel(g, 0.25 * MM, 2)
    d = new_object("OLED_Display", rounded_box(screen_w - 3 * MM, screen_l - 3 * MM, 1.4 * MM,
                                               2 * MM, TOP_Z - 2.6 * MM, y=SCREEN_Y), disp, root)
    bevel(d, 0.2 * MM, 2)

    dpad = new_object("DPad_Ring", ring(14 * MM, 8.6 * MM, 4.2 * MM, TOP_Z - 2.8 * MM, y=DPAD_Y),
                      steel, root)
    bevel(dpad, 0.5 * MM)
    halo = new_object("DPad_Backlight", ring(8.6 * MM, 8.0 * MM, 3.6 * MM, TOP_Z - 2.8 * MM,
                                            y=DPAD_Y), glow, root)
    attach(halo, dpad)
    ok = new_object("OK_Button", cylinder(7.6 * MM, 4.4 * MM, TOP_Z - 2.8 * MM, y=DPAD_Y, segments=64),
                    steel, root)
    bevel(ok, 0.6 * MM)
    for i, x in enumerate(row_x):
        b = new_object(f"Function_Button_{i + 1}", cylinder(small_r, 4.0 * MM, TOP_Z - 2.8 * MM,
                                                           x=x, y=ROW_Y), alu, root)
        bevel(b, 0.5 * MM)
    for name, x in (("Volume_Down", -9 * MM), ("Volume_Up", 9 * MM)):
        b = new_object(name, rounded_box(10.8 * MM, 4.6 * MM, 4.0 * MM, 2.2 * MM, TOP_Z - 2.8 * MM,
                                         x=x, y=PILL_Y), steel, root)
        bevel(b, 0.5 * MM)
    led = new_object("Status_LED_Strip", rounded_box(20 * MM, 1.6 * MM, 0.6 * MM, 0.7 * MM, TOP_Z,
                                                     y=LED_Y), glow, root)
    bevel(led, 0.15 * MM, 2)

    def dome(bm):
        bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=3.2 * MM)
        bmesh.ops.translate(bm, verts=bm.verts, vec=(0, L / 2 - 1.5 * MM, H_BOT + 1.5 * MM))
    new_object("IR_Lens", dome, ir, root)

    # Internals ----------------------------------------------------------
    board = new_object("Circuit_Board", rounded_box(W - 7 * MM, L - 14 * MM, 1.2 * MM, 6 * MM,
                                                    8.6 * MM), pcb, root)
    bevel(board, 0.2 * MM, 2)
    board_top = 9.8 * MM

    def on_board(name, builder, mat_):
        o = new_object(name, builder, mat_, root)
        attach(o, board)
        bevel(o, 0.15 * MM, 2)
        return o

    on_board("MCU", rounded_box(9 * MM, 9 * MM, 1.1 * MM, 0.6 * MM, board_top, y=-18 * MM, segments=3),
             chip)
    on_board("RF_Shield", rounded_box(18 * MM, 22 * MM, 2.2 * MM, 1.2 * MM, board_top, y=20 * MM,
                                      segments=4), shield)
    on_board("Flash_Memory", rounded_box(6 * MM, 4 * MM, 0.9 * MM, 0.3 * MM, board_top, x=-10 * MM,
                                         y=-40 * MM, segments=2), chip)
    on_board("Power_IC", rounded_box(5 * MM, 5 * MM, 0.9 * MM, 0.3 * MM, board_top, x=10 * MM,
                                     y=-40 * MM, segments=2), chip)
    for i, (x, y) in enumerate(((-14 * MM, -5 * MM), (-14 * MM, 3 * MM), (14 * MM, -5 * MM),
                                (14 * MM, 3 * MM))):
        on_board(f"Capacitor_{i + 1}", cylinder(1.0 * MM, 1.6 * MM, board_top, x=x, y=y,
                                                segments=24), shield)
    for i, (x, y) in enumerate([(0, DPAD_Y)] + [(x, ROW_Y) for x in row_x]):
        on_board(f"Dome_Contact_{i + 1}", cylinder(3.0 * MM, 0.3 * MM, board_top, x=x, y=y,
                                                   segments=32), gold)

    battery = new_object("LiPo_Battery", rounded_box(32 * MM, 64 * MM, 4.4 * MM, 2.5 * MM, 2.2 * MM,
                                                     y=-22 * MM), cell, root)
    bevel(battery, 0.8 * MM)

    # Fasteners and feet -------------------------------------------------
    for i, (x, y) in enumerate(((-16.5, -70), (16.5, -70), (-16.5, 70), (16.5, 70))):
        def screw(bm, x=x * MM, y=y * MM):
            bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=1.9 * MM,
                                  radius2=1.9 * MM, depth=1.0 * MM,
                                  matrix=Matrix.Translation((x, y, 0.5 * MM)))
            bmesh.ops.create_cone(bm, cap_ends=True, segments=24, radius1=0.95 * MM,
                                  radius2=0.95 * MM, depth=6 * MM,  # stops below the board
                                  matrix=Matrix.Translation((x, y, 1.0 * MM + 3.0 * MM)))
        sc = new_object(f"Screw_{i + 1}", screw, screw_m, root)
        bevel(sc, 0.2 * MM, 2)
    for i, y in enumerate((-62 * MM, 62 * MM)):
        f = new_object(f"Rubber_Foot_{i + 1}", rounded_box(34 * MM, 10 * MM, 1.0 * MM, 4 * MM,
                                                          -1.0 * MM, y=y), rubber, root)
        bevel(f, 0.4 * MM, 3)

    # Camera, lights, world, render -------------------------------------
    target = Vector((0, 0, 10 * MM))
    cam = bpy.data.objects.new("Remote_Camera", bpy.data.cameras.new("Remote_Camera"))
    scene.collection.objects.link(cam)
    cam.data.lens = 70
    cam.data.clip_start = 1 * MM
    cam.location = (0.24, -0.27, 0.2)
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam

    lights = bpy.data.collections.new("Studio Lights")
    scene.collection.children.link(lights)
    for name, loc, power, size, color in (
            ("Key", (-0.25, -0.2, 0.3), 14, 0.25, (1.0, 0.96, 0.9)),
            ("Fill", (0.3, -0.15, 0.12), 3, 0.4, (0.85, 0.92, 1.0)),
            ("Rim", (0.05, 0.35, 0.22), 14, 0.15, (0.6, 0.9, 1.0))):
        lamp = bpy.data.lights.new(name, "AREA")
        lamp.energy, lamp.size, lamp.color = power, size, color
        o = bpy.data.objects.new(name + " Light", lamp)
        o.location = loc
        o.rotation_euler = (target - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        lights.objects.link(o)

    world = bpy.data.worlds.new("Studio Dark")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    sky = world.node_tree.nodes.new("ShaderNodeTexGradient")
    coord = world.node_tree.nodes.new("ShaderNodeTexCoord")
    ramp = world.node_tree.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.004, 0.005, 0.007, 1)
    ramp.color_ramp.elements[1].color = (0.03, 0.04, 0.055, 1)
    world.node_tree.links.new(coord.outputs["Window"], sky.inputs["Vector"])
    world.node_tree.links.new(sky.outputs["Fac"], ramp.inputs["Fac"])
    world.node_tree.links.new(ramp.outputs["Color"], bg.inputs["Color"])
    scene.world = world

    eevee = next(i.identifier for i in
                 bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items
                 if i.identifier.startswith("BLENDER_EEVEE"))
    scene.render.engine = eevee
    scene.eevee.taa_render_samples = 64
    if hasattr(scene.eevee, "use_raytracing"):
        scene.eevee.use_raytracing = True
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Punchy" if "AgX - Punchy" in [
        i.identifier for i in scene.view_settings.bl_rna.properties["look"].enum_items] else "None"
    scene.render.resolution_x, scene.render.resolution_y = 1600, 1000
    scene.render.fps = 30
    return scene


if __name__ == "__main__":
    build()
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if argv:
        bpy.ops.wm.save_as_mainfile(filepath=argv[0])
