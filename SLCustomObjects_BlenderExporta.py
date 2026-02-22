bl_info = {
    "name":        "Map Exporter — SCP:SL",
    "author":      "aliberat",
    "version":     (1, 0, 0),
    "blender":     (4, 0, 0),
    "location":    "View3D › N-Panel › Map Exporter",
    "description": "Exports every face as a PrimitiveComponent cube for SCP:SL",
    "category":    "Import-Export",
}

import bpy
import json
import math
import os
import time
import bmesh
from mathutils import Vector, Matrix
from bpy.props import (
    StringProperty, BoolProperty, FloatVectorProperty,
    IntProperty, FloatProperty, EnumProperty, PointerProperty,
)
from bpy.types import Operator, Panel, PropertyGroup

ADDON_AUTHOR = "aliberat"
SLCO_EXT     = ".slco"

PRIMITIVE_ITEMS = [
    ("Cube",     "Cube",     "Box"),
    ("Sphere",   "Sphere",   "Sphere"),
    ("Capsule",  "Capsule",  "Capsule"),
    ("Cylinder", "Cylinder", "Cylinder"),
    ("Plane",    "Plane",    "Plane"),
    ("Quad",     "Quad",     "Quad"),
]


def color_to_hex(c):
    r = max(0, min(255, int(c[0] * 255)))
    g = max(0, min(255, int(c[1] * 255)))
    b = max(0, min(255, int(c[2] * 255)))
    a = max(0, min(255, int(c[3] * 255)))
    return f"{r:02X}{g:02X}{b:02X}{a:02X}"


def face_to_unity(face_verts_world, world_normal, thickness):
    """
    Convert one face (world-space verts + normal) into:
      unity_pos   — cube center in Unity coords
      unity_rot   — cube euler angles in Unity (XYZ degrees)
      unity_scale — cube size in Unity (X=width, Y=thickness, Z=height)

    ── ROTATION MATH ──────────────────────────────────────────────────────────
    Blender world frame for the face:
      T  = tangent   (face "right")
      N  = normal    (face "outward")
      B  = bitangent (face "up")
      T × B = N  →  right-handed frame, det = +1

    Axis remap Blender → Unity:  (x, y, z) → (x, z, -y)
      uT, uN, uB = remapped vectors

    After remapping, det([uT|uN|uB]) = –1  (the remap introduces a reflection).
    Fix: negate uB → matrix [uT | uN | -uB],  det = +1  ✓

    Result: cube Y-axis = face normal (thin side faces outward, no gaps/twist).
    """

    vert_avg = sum(face_verts_world, Vector()) / len(face_verts_world)

    # consistent tangent — world Z as reference
    ref = Vector((0.0, 0.0, 1.0))
    if abs(world_normal.dot(ref)) > 0.98:
        ref = Vector((1.0, 0.0, 0.0))
    tangent   = ref.cross(world_normal).normalized()
    bitangent = world_normal.cross(tangent).normalized()
    # verify: tangent × bitangent should equal world_normal (right-handed) ✓

    # bounding-box in face space (gaps appear when you use vert_avg instead of bbox center)
    projs_t = [(v - vert_avg).dot(tangent)   for v in face_verts_world]
    projs_b = [(v - vert_avg).dot(bitangent) for v in face_verts_world]
    t_min, t_max = min(projs_t), max(projs_t)
    b_min, b_max = min(projs_b), max(projs_b)

    width  = max(t_max - t_min, 0.0005)
    height = max(b_max - b_min, 0.0005)

    center = (vert_avg
              + tangent   * ((t_min + t_max) * 0.5)
              + bitangent * ((b_min + b_max) * 0.5))

    # ── position ──────────────────────────────────────────────────────────────
    unity_pos = [round(center.x, 5), round(center.z, 5), round(-center.y, 5)]

    # ── rotation ──────────────────────────────────────────────────────────────
    def b2u(v):
        return Vector((v.x, v.z, -v.y))

    uT =  b2u(tangent)
    uN =  b2u(world_normal)
    uB =  b2u(bitangent)

    # [uT | uN | -uB]  →  det = +1  (proper rotation, no reflection)
    rot = Matrix((
        ( uT.x,  uN.x, -uB.x),
        ( uT.y,  uN.y, -uB.y),
        ( uT.z,  uN.z, -uB.z),
    ))

    q  = rot.to_quaternion().normalized()
    eu = q.to_euler('XYZ')
    unity_rot = [
        round(math.degrees(eu.x), 4),
        round(math.degrees(eu.y), 4),
        round(math.degrees(eu.z), 4),
    ]

    # ── scale ─────────────────────────────────────────────────────────────────
    unity_scale = [round(width, 5), round(thickness, 5), round(height, 5)]

    return unity_pos, unity_rot, unity_scale


def optimize_mesh(me, angle_deg):
    """
    1. Merge triangles into quads where possible.
    2. Dissolve edges between faces whose normals differ < angle_deg.
       → flat surfaces become ONE big face → ONE cube, no seams.
    """
    bm = bmesh.new()
    bm.from_mesh(me)

    bmesh.ops.join_triangles(
        bm,
        faces=bm.faces,
        angle_face_threshold=math.radians(0.5),
        angle_shape_threshold=math.radians(40.0),
    )
    bmesh.ops.dissolve_limit(
        bm,
        angle_limit=math.radians(angle_deg),
        verts=bm.verts,
        edges=bm.edges,
    )

    bm.to_mesh(me)
    bm.free()


# ── property groups ────────────────────────────────────────────────────────────

class SLCOObjectProps(PropertyGroup):
    enabled:        BoolProperty(name="Include in Export", default=True)
    override_color: BoolProperty(name="Override Color",   default=False)
    color:          FloatVectorProperty(name="Color", subtype='COLOR', size=4,
                        min=0.0, max=1.0, default=(1.0, 1.0, 1.0, 1.0))
    collidable:     BoolProperty(name="Collidable", default=True)
    visible:        BoolProperty(name="Visible",    default=True)
    custom_name:    StringProperty(name="Custom Name", default="")


class SLCOSceneProps(PropertyGroup):
    primitive_type: EnumProperty(name="Primitive Type", items=PRIMITIVE_ITEMS, default="Cube")
    global_color:   FloatVectorProperty(name="Default Color", subtype='COLOR', size=4,
                        min=0.0, max=1.0, default=(1.0, 1.0, 1.0, 1.0))
    global_collidable:    BoolProperty(name="Collidable", default=True)
    global_visible:       BoolProperty(name="Visible",    default=True)
    export_selected_only: BoolProperty(name="Selected Only", default=True)
    skip_hidden:          BoolProperty(name="Skip Hidden",   default=True)
    write_log:            BoolProperty(name="Write Log",     default=True)
    search_filter:        StringProperty(name="Search",      default="")
    last_export_count:    IntProperty(default=0)
    last_export_time:     StringProperty(default="")

    face_thickness: FloatProperty(
        name="Face Thickness",
        description="Cube depth along face normal. 0.01 is smoothest.",
        default=0.01,
        min=0.001, max=2.0, precision=3,
    )
    dissolve_angle: FloatProperty(
        name="Merge Angle (deg)",
        description=(
            "Faces with normals closer than this are merged into ONE cube.\n"
            "0.5 = only perfectly flat surfaces merge (recommended)\n"
            "5   = gently curved surfaces also merge\n"
            "15  = aggressive, very blocky result"
        ),
        default=0.5,
        min=0.0, max=45.0, precision=1,
    )
    do_optimize: BoolProperty(
        name="Merge flat faces",
        description="Flat surfaces become ONE cube instead of many. Always enable this.",
        default=True,
    )


def gather_objects(context):
    sp  = context.scene.slco_scene
    src = context.selected_objects if sp.export_selected_only else context.scene.objects
    out = [o for o in src if o.type == 'MESH']
    if sp.skip_hidden:
        out = [o for o in out if not o.hide_viewport]
    return out


# ── operators ──────────────────────────────────────────────────────────────────

class SLCO_OT_ApplyScale(Operator):
    bl_idname = "slco.apply_scale"
    bl_label  = "Apply Scale"
    def execute(self, context):
        meshes = [o for o in context.selected_objects if o.type == 'MESH']
        if not meshes:
            self.report({'WARNING'}, "No mesh selected."); return {'CANCELLED'}
        old = context.view_layer.objects.active
        for o in meshes:
            context.view_layer.objects.active = o
            bpy.ops.object.transform_apply(scale=True, location=False, rotation=False)
        context.view_layer.objects.active = old
        self.report({'INFO'}, f"Applied scale on {len(meshes)} object(s).")
        return {'FINISHED'}


class SLCO_OT_ApplyAll(Operator):
    bl_idname = "slco.apply_all"
    bl_label  = "Apply All Transforms"
    def execute(self, context):
        meshes = [o for o in context.selected_objects if o.type == 'MESH']
        if not meshes:
            self.report({'WARNING'}, "No mesh selected."); return {'CANCELLED'}
        old = context.view_layer.objects.active
        for o in meshes:
            context.view_layer.objects.active = o
            bpy.ops.object.transform_apply(scale=True, location=True, rotation=True)
        context.view_layer.objects.active = old
        self.report({'INFO'}, f"Applied all transforms on {len(meshes)} object(s).")
        return {'FINISHED'}


class SLCO_OT_SelectAllMeshes(Operator):
    bl_idname = "slco.select_all_meshes"
    bl_label  = "Select All Meshes"
    def execute(self, context):
        bpy.ops.object.select_all(action='DESELECT')
        for o in context.scene.objects:
            if o.type == 'MESH':
                o.select_set(True)
        self.report({'INFO'}, "All mesh objects selected.")
        return {'FINISHED'}


class SLCO_OT_EnableAll(Operator):
    bl_idname = "slco.enable_all";  bl_label = "Enable All"
    def execute(self, context):
        for o in context.scene.objects:
            if o.type == 'MESH': o.slco_obj.enabled = True
        return {'FINISHED'}


class SLCO_OT_DisableAll(Operator):
    bl_idname = "slco.disable_all"; bl_label = "Disable All"
    def execute(self, context):
        for o in context.scene.objects:
            if o.type == 'MESH': o.slco_obj.enabled = False
        return {'FINISHED'}


class SLCO_OT_PreviewCount(Operator):
    bl_idname    = "slco.preview_count"
    bl_label     = "Preview Cube Count"
    bl_description = "Show how many cubes will be generated with current settings"
    def execute(self, context):
        sp      = context.scene.slco_scene
        objects = [o for o in gather_objects(context) if o.slco_obj.enabled]
        if not objects:
            self.report({'WARNING'}, "No objects selected."); return {'CANCELLED'}
        total = 0
        for obj in objects:
            depsgraph = context.evaluated_depsgraph_get()
            eval_obj  = obj.evaluated_get(depsgraph)
            me        = eval_obj.to_mesh()
            if sp.do_optimize:
                optimize_mesh(me, sp.dissolve_angle)
            total += len(me.polygons)
            eval_obj.to_mesh_clear()
        lvl = 'INFO' if total < 2000 else 'WARNING'
        self.report({lvl}, f"With current settings: {total} cubes will be exported.")
        return {'FINISHED'}


class SLCO_OT_Export(Operator):
    bl_idname    = "slco.export"
    bl_label     = "Export (.slco)"
    bl_description = "Export faces as PrimitiveComponent cubes for SCP:SL"

    filepath: StringProperty(subtype="FILE_PATH")

    def invoke(self, context, event):
        base = os.path.splitext(bpy.data.filepath)[0] if bpy.data.filepath else "untitled"
        self.filepath = base + SLCO_EXT
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        sp      = context.scene.slco_scene
        objects = [o for o in gather_objects(context) if o.slco_obj.enabled]
        if not objects:
            self.report({'ERROR'}, "No objects to export!"); return {'CANCELLED'}

        export_list = []
        log_lines   = [
            "SCP:SL Map Export Log",
            f"Made by {ADDON_AUTHOR}",
            f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Optimize={sp.do_optimize}  MergeAngle={sp.dissolve_angle}  Thickness={sp.face_thickness}",
            "",
        ]
        total_cubes = 0

        for obj in objects:
            depsgraph = context.evaluated_depsgraph_get()
            eval_obj  = obj.evaluated_get(depsgraph)
            me        = eval_obj.to_mesh()

            if sp.do_optimize:
                optimize_mesh(me, sp.dissolve_angle)

            world     = obj.matrix_world
            rot3      = world.to_3x3()
            op        = obj.slco_obj
            raw_color = op.color if op.override_color else sp.global_color
            color_hex = color_to_hex(raw_color)
            base_name = op.custom_name.strip() or obj.name

            for fi, face in enumerate(me.polygons):
                world_verts  = [world @ me.vertices[vi].co for vi in face.vertices]
                world_normal = (rot3 @ face.normal).normalized()

                pos, rot, scl = face_to_unity(world_verts, world_normal, sp.face_thickness)

                export_list.append({
                    "name":       f"{base_name}_f{fi}",
                    "primitive":  sp.primitive_type,
                    "color":      color_hex,
                    "collidable": op.collidable,
                    "visible":    op.visible,
                    "position":   pos,
                    "rotation":   rot,
                    "scale":      scl,
                })

            count = len(me.polygons)
            eval_obj.to_mesh_clear()
            total_cubes += count
            log_lines.append(f"{obj.name}: {count} cubes")

        export_data = {
            "author":       ADDON_AUTHOR,
            "tool":         "Map Exporter — SCP:SL",
            "export_time":  time.strftime('%Y-%m-%d %H:%M:%S'),
            "blender_file": bpy.data.filepath or "unsaved",
            "object_count": len(export_list),
            "objects":      export_list,
        }

        fp = self.filepath if self.filepath.endswith(SLCO_EXT) else self.filepath + SLCO_EXT
        with open(fp, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        if sp.write_log:
            with open(fp.replace(SLCO_EXT, "_export.log"), 'w') as lf:
                lf.write('\n'.join(log_lines))

        sp.last_export_count = total_cubes
        sp.last_export_time  = time.strftime('%H:%M:%S')
        self.report({'INFO'}, f"Exported {total_cubes} cubes → {os.path.basename(fp)}")
        return {'FINISHED'}


# ── panels ─────────────────────────────────────────────────────────────────────

class SLCO_PT_Main(Panel):
    bl_label = "Map Exporter"; bl_idname = "SLCO_PT_main"
    bl_space_type = 'VIEW_3D'; bl_region_type = 'UI'; bl_category = "Map Exporter"
    def draw(self, context):
        box = self.layout.box()
        box.label(text="SCP:SL Map Exporter", icon='EXPORT')
        box.label(text=f"Made by {ADDON_AUTHOR}", icon='USER')


class SLCO_PT_Settings(Panel):
    bl_label = "Settings"; bl_idname = "SLCO_PT_settings"
    bl_space_type = 'VIEW_3D'; bl_region_type = 'UI'
    bl_category = "Map Exporter"; bl_parent_id = "SLCO_PT_main"

    def draw(self, context):
        layout = self.layout
        sp     = context.scene.slco_scene

        layout.label(text="Primitive Type:", icon='MESH_CUBE')
        layout.prop(sp, "primitive_type", text="")

        layout.separator(factor=0.4)
        layout.label(text="Color:", icon='COLOR')
        layout.prop(sp, "global_color", text="")

        layout.separator(factor=0.4)
        row = layout.row(align=True)
        row.prop(sp, "global_collidable", text="Collidable", toggle=True, icon='PHYSICS')
        row.prop(sp, "global_visible",    text="Visible",    toggle=True, icon='HIDE_OFF')

        layout.separator(factor=0.6)
        layout.label(text="Face Thickness:", icon='FACE_MAPS')
        layout.prop(sp, "face_thickness", text="(0.01 = smoothest)")

        layout.separator(factor=0.6)
        box = layout.box()
        box.label(text="Flat Surface Optimization", icon='MOD_DECIM')
        box.prop(sp, "do_optimize", text="Merge flat faces into one cube")
        col = box.column()
        col.enabled = sp.do_optimize
        col.prop(sp, "dissolve_angle", text="Merge Angle")
        if sp.do_optimize:
            if   sp.dissolve_angle < 1.0:  box.label(text="Only perfect flat surfaces",    icon='CHECKMARK')
            elif sp.dissolve_angle <= 5.0: box.label(text="Good for most meshes",          icon='CHECKMARK')
            else:                          box.label(text="Aggressive — blocky result",    icon='ERROR')

        layout.separator(factor=0.4)
        layout.operator("slco.preview_count", text="Preview Cube Count", icon='HIDE_OFF')

        layout.separator(factor=0.4)
        layout.prop(sp, "export_selected_only", text="Selected Only")
        layout.prop(sp, "skip_hidden",           text="Skip Hidden")
        layout.prop(sp, "write_log",             text="Write Log")


class SLCO_PT_Fix(Panel):
    bl_label = "Fix Transforms"; bl_idname = "SLCO_PT_fix"
    bl_space_type = 'VIEW_3D'; bl_region_type = 'UI'
    bl_category = "Map Exporter"; bl_parent_id = "SLCO_PT_main"
    def draw(self, context):
        layout = self.layout
        layout.operator("slco.apply_scale", text="Apply Scale",          icon='FULLSCREEN_ENTER')
        layout.operator("slco.apply_all",   text="Apply All Transforms", icon='CHECKMARK')
        layout.separator(factor=0.4)
        layout.operator("slco.select_all_meshes", text="Select All Meshes", icon='RESTRICT_SELECT_OFF')


class SLCO_PT_ObjectList(Panel):
    bl_label = "Object List"; bl_idname = "SLCO_PT_objlist"
    bl_space_type = 'VIEW_3D'; bl_region_type = 'UI'
    bl_category = "Map Exporter"; bl_parent_id = "SLCO_PT_main"

    def draw(self, context):
        layout = self.layout
        sp     = context.scene.slco_scene
        row    = layout.row(align=True)
        row.prop(sp, "search_filter", text="", icon='VIEWZOOM')
        row.operator("slco.enable_all",  text="", icon='CHECKMARK')
        row.operator("slco.disable_all", text="", icon='X')
        layout.separator(factor=0.3)

        candidates = gather_objects(context)
        search     = sp.search_filter.lower()
        shown = excluded = 0

        for obj in candidates:
            if search and search not in obj.name.lower():
                continue
            op  = obj.slco_obj
            box = layout.box()
            col = box.column(align=True)
            row = col.row(align=True)
            row.prop(op, "enabled", text="", icon='CHECKMARK' if op.enabled else 'PANEL_CLOSE')
            row.label(text=obj.name, icon='MESH_DATA')
            if not op.enabled:
                excluded += 1
                col.label(text="Excluded", icon='PANEL_CLOSE'); continue
            shown += 1
            col.label(text=f"Faces: {len(obj.data.polygons)}", icon='FACE_MAPS')
            row2 = col.row(align=True)
            row2.prop(op, "override_color", text="Color Override", toggle=True)
            if op.override_color:
                col.prop(op, "color", text="")
            col.prop(op, "collidable",  text="Collidable")
            col.prop(op, "visible",     text="Visible")
            col.prop(op, "custom_name", text="Custom Name")

        if not candidates:
            layout.label(text="No mesh objects found.", icon='INFO')
        else:
            layout.label(text=f"{shown} included  |  {excluded} excluded", icon='INFO')


class SLCO_PT_Export(Panel):
    bl_label = "Export"; bl_idname = "SLCO_PT_export"
    bl_space_type = 'VIEW_3D'; bl_region_type = 'UI'
    bl_category = "Map Exporter"; bl_parent_id = "SLCO_PT_main"
    def draw(self, context):
        layout = self.layout
        sp     = context.scene.slco_scene
        cands  = [o for o in gather_objects(context) if o.slco_obj.enabled]
        if cands:
            layout.label(text=f"{len(cands)} object(s) ready", icon='CHECKMARK')
        else:
            layout.label(text="Nothing to export.", icon='ERROR')
        row = layout.row()
        row.scale_y = 2.2
        row.operator("slco.export", text="EXPORT  (.slco)", icon='EXPORT')
        if sp.last_export_count > 0:
            box = layout.box()
            box.label(text=f"Last: {sp.last_export_count} cubes at {sp.last_export_time}", icon='TIME')


classes = [
    SLCOObjectProps, SLCOSceneProps,
    SLCO_OT_ApplyScale, SLCO_OT_ApplyAll, SLCO_OT_SelectAllMeshes,
    SLCO_OT_EnableAll, SLCO_OT_DisableAll, SLCO_OT_PreviewCount, SLCO_OT_Export,
    SLCO_PT_Main, SLCO_PT_Settings, SLCO_PT_Fix, SLCO_PT_ObjectList, SLCO_PT_Export,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.slco_obj  = PointerProperty(type=SLCOObjectProps)
    bpy.types.Scene.slco_scene = PointerProperty(type=SLCOSceneProps)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Object.slco_obj
    del bpy.types.Scene.slco_scene

if __name__ == "__main__":
    register()
