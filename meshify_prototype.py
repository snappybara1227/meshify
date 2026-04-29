bl_info = {
    "name": "Meshify",
    "author": "OpenAI",
    "version": (0, 0, 23),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Meshify",
    "description": "Meshify with Proper Enable/Disable Control",
    "category": "3D View",
}

import bpy
import bmesh

# =========================================================
# STATE
# =========================================================
_draw_handle = None
meshify_suggestions = set()

# context flags
meshify_has_non_manifold = False
meshify_has_ngon = False


# =========================================================
# DETECTION
# =========================================================
def detect_non_manifold(bm):
    return [e for e in bm.edges if not e.is_manifold]


def detect_ngons(bm):
    return [f for f in bm.faces if len(f.verts) > 4]


# =========================================================
# SUGGESTIONS
# =========================================================
def build_suggestions(nm, ng):
    s = set()
    if nm:
        s.add("Non-manifold → Merge by distance / Fill hole")
    if ng:
        s.add("Ngon → Triangulate")
    return s


# =========================================================
# EXECUTION (unchanged)
# =========================================================
class MESHIFY_OT_fill_holes(bpy.types.Operator):
    bl_idname = "meshify.fill_holes"
    bl_label = "Fill Holes"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        bm = bmesh.from_edit_mesh(context.active_object.data)
        edges = [e for e in bm.edges if e.is_boundary]
        bmesh.ops.holes_fill(bm, edges=edges)
        bmesh.update_edit_mesh(context.active_object.data)
        return {'FINISHED'}


class MESHIFY_OT_merge_distance(bpy.types.Operator):
    bl_idname = "meshify.merge_distance"
    bl_label = "Merge by Distance ⚠"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        bm = bmesh.from_edit_mesh(context.active_object.data)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)
        bmesh.update_edit_mesh(context.active_object.data)
        return {'FINISHED'}


class MESHIFY_OT_triangulate(bpy.types.Operator):
    bl_idname = "meshify.triangulate"
    bl_label = "Triangulate ⚠"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        bm = bmesh.from_edit_mesh(context.active_object.data)
        faces = [f for f in bm.faces if len(f.verts) > 4]
        bmesh.ops.triangulate(bm, faces=faces)
        bmesh.update_edit_mesh(context.active_object.data)
        return {'FINISHED'}


# =========================================================
# CORE LOOP (NOW GUARDED)
# =========================================================
def draw_meshify():
    global meshify_suggestions
    global meshify_has_non_manifold, meshify_has_ngon

    context = bpy.context

    # 🚨 HARD STOP
    if not context.scene.meshify_enabled:
        return

    obj = context.active_object
    if not obj or obj.mode != 'EDIT':
        meshify_suggestions = set()
        meshify_has_non_manifold = False
        meshify_has_ngon = False
        return

    bm = bmesh.from_edit_mesh(obj.data)

    nm = detect_non_manifold(bm)
    ng = detect_ngons(bm)

    meshify_suggestions = build_suggestions(nm, ng)

    meshify_has_non_manifold = bool(nm)
    meshify_has_ngon = bool(ng)


# =========================================================
# HANDLER CONTROL (CRITICAL FIX)
# =========================================================
def add_draw_handler():
    global _draw_handle
    if _draw_handle is None:
        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            draw_meshify, (), 'WINDOW', 'POST_VIEW'
        )


def remove_draw_handler():
    global _draw_handle
    if _draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None


def clear_meshify_state():
    global meshify_suggestions
    global meshify_has_non_manifold, meshify_has_ngon

    meshify_suggestions = set()
    meshify_has_non_manifold = False
    meshify_has_ngon = False


def update_meshify_enabled(self, context):
    if self.meshify_enabled:
        add_draw_handler()
    else:
        # 🔥 CRITICAL FIXES
        remove_draw_handler()
        clear_meshify_state()


# =========================================================
# UI (NOW GUARDED)
# =========================================================
class MESHIFY_PT_main(bpy.types.Panel):
    bl_label = "Meshify"
    bl_idname = "MESHIFY_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Meshify"

    def draw(self, context):
        layout = self.layout

        layout.prop(context.scene, "meshify_enabled")

        # 🚨 HARD UI STOP
        if not context.scene.meshify_enabled:
            return

        layout.label(text="Suggestions:")

        if not meshify_suggestions:
            layout.label(text="No issues detected")
            return

        for s in meshify_suggestions:
            layout.label(text=s)

        # context-aware buttons
        if meshify_has_non_manifold:
            layout.operator("meshify.fill_holes")
            layout.operator("meshify.merge_distance")

        if meshify_has_ngon:
            layout.operator("meshify.triangulate")


# =========================================================
# REGISTER
# =========================================================
classes = (
    MESHIFY_PT_main,
    MESHIFY_OT_fill_holes,
    MESHIFY_OT_merge_distance,
    MESHIFY_OT_triangulate,
)


def register():
    bpy.types.Scene.meshify_enabled = bpy.props.BoolProperty(
        name="Enable Meshify",
        default=False,
        update=update_meshify_enabled,
    )

    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    remove_draw_handler()
    clear_meshify_state()

    for c in reversed(classes):
        bpy.utils.unregister_class(c)

    del bpy.types.Scene.meshify_enabled


if __name__ == "__main__":
    register()