bl_info = {
    "name": "Meshify",
    "author": "OpenAI",
    "version": (0, 0, 16),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Meshify",
    "description": "Meshify with multi-layer visualization + suggestions",
    "category": "3D View",
}

import bpy
import gpu
import bmesh
from gpu_extras.batch import batch_for_shader


# ---------------------------
# GLOBAL STATE
# ---------------------------
_draw_handle = None
meshify_suggestions = set()
DISTORTION_RATIO_THRESHOLD = 1.5


# ---------------------------
# DRAW CALLBACK
# ---------------------------
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

    # reset suggestions every frame
    meshify_suggestions = set()

    # ---------------------------
    # NON-MANIFOLD EDGES
    # ---------------------------
    nm_lines = []
    for e in bm.edges:
        if not e.is_manifold:
            v1 = world @ e.verts[0].co
            v2 = world @ e.verts[1].co
            nm_lines.append((v1.x, v1.y, v1.z))
            nm_lines.append((v2.x, v2.y, v2.z))
            meshify_suggestions.add("Non-manifold → Merge by distance / Fill hole")

    # ---------------------------
    # NGON FACES
    # ---------------------------
    ngon_tris = []
    for f in bm.faces:
        if len(f.verts) > 4:
            verts = [world @ v.co for v in f.verts]
            for i in range(1, len(verts) - 1):
                ngon_tris.append(verts[0])
                ngon_tris.append(verts[i])
                ngon_tris.append(verts[i + 1])
            meshify_suggestions.add("Ngon → Triangulate or subdivide")

    # ---------------------------
    # VALENCE VERTICES
    # ---------------------------
    valence_lines = []
    for v in bm.verts:
        valence = len(v.link_edges)  # connectivity info :contentReference[oaicite:0]{index=0}

        if valence != 4:
            co = world @ v.co
            scale = max(obj.dimensions) * 0.02 if max(obj.dimensions) > 0 else 0.05

            valence_lines.extend([
                (co.x - scale, co.y, co.z),
                (co.x + scale, co.y, co.z),
                (co.x, co.y - scale, co.z),
                (co.x, co.y + scale, co.z),
            ])
            meshify_suggestions.add("Bad valence → Adjust edge flow")

    # ---------------------------
    # FACE DISTORTION
    # ---------------------------
    distortion_tris = []
    for f in bm.faces:
        lengths = [e.calc_length() for e in f.edges]
        if not lengths:
            continue

        max_len = max(lengths)
        min_len = min(lengths)
        if min_len == 0:
            continue

        ratio = max_len / min_len
        if ratio > DISTORTION_RATIO_THRESHOLD:
            verts = [world @ v.co for v in f.verts]
            for i in range(1, len(verts) - 1):
                distortion_tris.append(verts[0])
                distortion_tris.append(verts[i])
                distortion_tris.append(verts[i + 1])
            meshify_suggestions.add("Distortion → Even edge spacing")

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')

    # ---------------------------
    # DRAW ALL LAYERS
    # ---------------------------

    # Distortion (blue tint)
    if distortion_tris:
        batch = batch_for_shader(shader, 'TRIS', {"pos": distortion_tris})
        shader.bind()
        shader.uniform_float("color", (0.2, 0.6, 1.0, 0.3))
        batch.draw(shader)

    # Ngon (orange)
    if ngon_tris:
        batch = batch_for_shader(shader, 'TRIS', {"pos": ngon_tris})
        shader.bind()
        shader.uniform_float("color", (1.0, 0.5, 0.1, 0.35))
        batch.draw(shader)

    # Non-manifold (red)
    if nm_lines:
        batch = batch_for_shader(shader, 'LINES', {"pos": nm_lines})
        shader.bind()
        shader.uniform_float("color", (1.0, 0.0, 0.0, 1.0))
        gpu.state.line_width_set(4.0)
        batch.draw(shader)

    # Valence (yellow)
    if valence_lines:
        batch = batch_for_shader(shader, 'LINES', {"pos": valence_lines})
        shader.bind()
        shader.uniform_float("color", (1.0, 1.0, 0.2, 1.0))
        gpu.state.line_width_set(2.0)
        batch.draw(shader)

    gpu.state.line_width_set(1.0)


# ---------------------------
# HANDLER CONTROL
# ---------------------------
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
    except Exception:
        pass

    _draw_handle = None


# ---------------------------
# TOGGLE
# ---------------------------
def update_meshify_enabled(self, context):
    if self.meshify_enabled:
        add_draw_handler()
    else:
        remove_draw_handler()

    if context and context.window and context.window.screen:
        for area in context.window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


# ---------------------------
# UI PANEL
# ---------------------------
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
            for s in sorted(meshify_suggestions):
                layout.label(text=f"- {s}")


# ---------------------------
# REGISTRATION
# ---------------------------
classes = (
    MESHIFY_PT_main,
)


def register_props():
    bpy.types.Scene.meshify_enabled = bpy.props.BoolProperty(
        name="Enable Meshify",
        default=False,
        update=update_meshify_enabled,
    )


def unregister_props():
    if hasattr(bpy.types.Scene, "meshify_enabled"):
        del bpy.types.Scene.meshify_enabled


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