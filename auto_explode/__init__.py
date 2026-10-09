"""Auto Explode: one-click exploded views and assembly animations."""

import bpy
from bpy.props import EnumProperty, FloatProperty, IntProperty, PointerProperty

from . import core


class ExplodeSettings(bpy.types.PropertyGroup):
    axis: EnumProperty(
        name="Axis", default="AUTO",
        items=[("AUTO", "Auto", "The assembly's thinnest direction (how most products stack)"),
               ("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")])
    spacing: FloatProperty(
        name="Spacing", default=1.0, min=0.1, soft_max=4.0,
        description="Gap between layers, relative to the assembly's thickness")
    amount: FloatProperty(
        name="Amount", default=1.0, min=0.0, max=1.0, subtype="FACTOR",
        description="How far apart the static exploded pose is")
    move: IntProperty(name="Move Frames", default=24, min=2,
                      description="Frames each part takes to travel")
    stagger: IntProperty(name="Stagger", default=6, min=0,
                         description="Frames between one layer starting and the next")
    hold: IntProperty(name="Hold", default=30, min=0,
                      description="Frames to hold the fully exploded view")


def _parts(context):
    s = context.scene.auto_explode
    objs = [o for o in context.selected_objects]
    return core.plan(objs, s.axis, s.spacing, anchor=context.active_object)


class AUTO_EXPLODE_OT_animate(bpy.types.Operator):
    bl_idname = "auto_explode.animate"
    bl_label = "Animate Explode"
    bl_description = ("Keyframe the selection flying apart layer by layer, holding, and "
                      "reassembling. Loops seamlessly")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return len(context.selected_objects) >= 2 and context.mode == "OBJECT"

    def execute(self, context):
        s = context.scene.auto_explode
        parts, _, _ = _parts(context)
        if len(parts) < 2:
            self.report({"ERROR"}, "Select at least two visible parts")
            return {"CANCELLED"}
        end = core.animate(parts, context.scene, start=context.scene.frame_start,
                           move=s.move, stagger=s.stagger, hold=s.hold)
        layers = max(p.rank for p in parts)
        self.report({"INFO"}, f"{len(parts)} parts in {layers} layers, frames "
                              f"{context.scene.frame_start}-{end}")
        return {"FINISHED"}


class AUTO_EXPLODE_OT_pose(bpy.types.Operator):
    bl_idname = "auto_explode.pose"
    bl_label = "Explode Pose"
    bl_description = "Spread the selection apart without keyframes, for still renders"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return len(context.selected_objects) >= 2 and context.mode == "OBJECT"

    def execute(self, context):
        parts, _, _ = _parts(context)
        core.pose(parts, context.scene.auto_explode.amount)
        return {"FINISHED"}


class AUTO_EXPLODE_OT_clear(bpy.types.Operator):
    bl_idname = "auto_explode.clear"
    bl_label = "Reassemble"
    bl_description = ("Remove Auto Explode's offsets and keyframes from the scene. Your own "
                      "animation is left alone")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        n = core.clear(context.scene.objects)
        self.report({"INFO"}, f"Reassembled {n} part(s)")
        return {"FINISHED"}


class VIEW3D_PT_auto_explode(bpy.types.Panel):
    bl_label = "Auto Explode"
    bl_idname = "VIEW3D_PT_auto_explode"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Explode"

    def draw(self, context):
        layout = self.layout
        s = context.scene.auto_explode
        layout.use_property_split = True
        layout.use_property_decorate = False

        if len(context.selected_objects) < 2:
            layout.label(text="Select the parts of an assembly.", icon="INFO")
        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("auto_explode.animate", icon="RENDER_ANIMATION")
        row = col.row(align=True)
        row.operator("auto_explode.pose", icon="FULLSCREEN_ENTER")
        row.operator("auto_explode.clear", icon="FULLSCREEN_EXIT")

        layout.prop(s, "axis", expand=True)
        layout.prop(s, "spacing")
        layout.prop(s, "amount")
        col = layout.column(align=True)
        col.prop(s, "move")
        col.prop(s, "stagger")
        col.prop(s, "hold")
        col = layout.column(align=True)
        col.label(text="The active object stays put.", icon="PINNED")
        col.label(text="Parented parts move together.", icon="LINKED")


classes = (
    ExplodeSettings,
    AUTO_EXPLODE_OT_animate,
    AUTO_EXPLODE_OT_pose,
    AUTO_EXPLODE_OT_clear,
    VIEW3D_PT_auto_explode,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.auto_explode = PointerProperty(type=ExplodeSettings)


def unregister():
    del bpy.types.Scene.auto_explode
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
