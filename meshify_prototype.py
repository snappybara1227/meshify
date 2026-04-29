bl_info = {
    "name": "Meshify",
    "author": "OpenAI",
    "version": (0, 0, 20),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Meshify",
    "description": "Meshify with Execution Engine (Non-manifold fix)",
    "category": "3D View",
}

import bpy
import gpu
import bmesh
from gpu_extras.batch import batch_for_shader


# =========================================================
# 1. STATE LAYER
# =========================================================
_draw_handle = None
meshify_suggestions = set()
DISTORTION_RATIO_THRESHOLD = 1.5


def register_props():
    bpy.types.Scene.meshify_enabled = bpy.props.BoolProperty(
        name="Enable Meshify",
        default=False,
        update=update_meshify_enabled,
    )


def unregister_props():
    if hasattr(bpy.types.Scene, "meshify_enabled"):
        del bpy.types.Scene.meshify_enabled


# =========================================================
# 2. DETECTION ENGINE
# =========================================================
def detect_non_manifold(bm):
    return [e for e in bm.edges if not e.is_manifold]


def detect_ngons(bm):
    return [f for f in bm.faces if len(f.verts) > 4]


def detect_bad_valence(bm):
    return [v for v in bm.verts if len(v.link_edges) != 4]


def detect_distortion(bm):
    bad_faces = []
    for f in bm.faces:
        lengths = [e.calc_length() for e in f.edges]
        if not lengths:
            continue
        max_len = max(lengths)
        min_len = min(lengths)
        if min_len == 0:
            continue
        if (max_len / min_len) > DISTORTION_RATIO_THRESHOLD:
            bad_faces.append(f)
    return bad_faces


# =========================================================
# 3. SUGGESTION ENGINE
# =========================================================
def build_suggestions(nm, ngons, valence, distortion):
    suggestions = set()

    if nm:
        suggestions.add("Non-manifold → Merge by distance / Fill hole")
    if ngons:
        suggestions.add("Ngon → Triangulate or subdivide")
    if valence:
        suggestions.add("Bad valence → Adjust edge flow")
    if distortion:
        suggestions.add("Distortion → Even edge spacing")

    return suggestions


# =========================================================
# 4. SAFETY ENGINE
# =========================================================
def classify_suggestion(s):
    if "Non-manifold" in s:
        if "Fill hole" in s:
            return "SAFE"
        return "CAUTION"
    if "Ngon" in s:
        return "CAUTION"
    if "Bad valence" in s:
        return "RISK"
    if "Distortion" in s:
        return "CAUTION"
    return "SAFE"


# =========================================================
# 5. RANKING ENGINE
# =========================================================
def rank_suggestions(suggestions):
    def priority(s):
        if "Non-manifold" in s:
            return 0
        if "Ngon" in s:
            return 1
        if "Bad valence" in s:
            return 2
        if "Distortion" in s:
            return 3
        return 99

    return sorted(suggestions, key=priority)


# =========================================================
# 6. EXECUTION ENGINE (NEW)
# =========================================================
class MESHIFY_OT_fix_non_manifold(bpy.types.Operator):
    bl_idname = "meshify.fix_non_manifold"
    bl_label = "Apply Fix (Fill Holes)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object

        if obj is None or obj.type != 'MESH' or obj.mode != 'EDIT':
            return {'CANCELLED'}

        bm = bmesh.from_edit_mesh(obj.data)

        # Find boundary edges (holes)
        boundary_edges = [e for e in bm.edges if e.is_boundary]

        if not boundary_edges:
            self.report({'INFO'}, "No holes to fill")
            return {'CANCELLED'}

        # Fill holes safely
        bmesh.ops.holes_fill(bm, edges=boundary_edges)

        bmesh.update_edit_mesh(obj.data)
        return {'FINISHED'}


# =========================================================
# 7. DRAW ENGINE
# =========================================================
def draw_meshify():
    global meshify_suggestions

    obj = bpy.context.active_object
    if obj is None or obj.type != 'MESH' or obj.mode != 'EDIT':
        meshify_suggestions = set()
        return

    bm = bmesh.from_edit_mesh(obj.data)
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()

    world = obj.matrix_world

    nm_edges = detect_non_manifold(bm)
    ngon_faces = detect_ngons(bm)
    valence_verts = detect_bad_valence(bm)
    distortion_faces = detect_distortion(bm)

    meshify_suggestions = build_suggestions(
        nm_edges, ngon_faces, valence_verts, distortion_faces
    )

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')

    # Non-manifold
    lines = []
    for e in nm_edges:
        v1 = world @ e.verts[0].co
        v2 = world @ e.verts[1].co
        lines.extend([(v1.x, v1.y, v1.z), (v2.x, v2.y, v2.z)])

    if lines:
        batch = batch_for_shader(shader, 'LINES', {"pos": lines})
        shader.bind()
        shader.uniform_float("color", (1.0, 0.0, 0.0, 1.0))
        gpu.state.line_width_set(4.0)
        batch.draw(shader)

    gpu.state.line_width_set(1.0)


# =========================================================
# HANDLER CONTROL
# =========================================================
def add_draw_handler():
    global _draw_handle
    if _draw_handle is not None:
        return

    _draw_handle = bpy.types.SpaceView3D.draw_handler_add(
        draw_meshify, (), 'WINDOW', 'POST_VIEW'
    )


def remove_draw_handler():
    global _draw_handle
    if _draw_handle is None:
        return

    try:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
    except:
        pass

    _draw_handle = None


def update_meshify_enabled(self, context):
    if self.meshify_enabled:
        add_draw_handler()
    else:
        remove_draw_handler()


# =========================================================
# 8. UI LAYER
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
        layout.separator()

        layout.label(text="Suggestions:")

        if not meshify_suggestions:
            layout.label(text="No issues detected")
        else:
            ranked = rank_suggestions(meshify_suggestions)

            for i, s in enumerate(ranked, 1):
                safety = classify_suggestion(s)
                layout.label(text=f"{i}. [{safety}] {s}")

            layout.separator()

            # EXECUTION BUTTON (SAFE ONLY)
            for s in ranked:
                if classify_suggestion(s) == "SAFE" and "Non-manifold" in s:
                    layout.operator(
                        "meshify.fix_non_manifold",
                        text="Apply Fix (Fill Hole)"
                    )
                    break


# =========================================================
# REGISTRATION
# =========================================================
classes = (
    MESHIFY_PT_main,
    MESHIFY_OT_fix_non_manifold,
)


def register():
    register_props()
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    remove_draw_handler()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    unregister_props()


if __name__ == "__main__":
    register()