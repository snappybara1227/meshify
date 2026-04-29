bl_info = {
    "name": "Meshify",
    "author": "OpenAI",
    "version": (0, 0, 40),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Meshify",
    "category": "3D View",
}

import bpy
import bmesh
import random  # 🔥 NEW

# =========================================================
# STATE
# =========================================================
meshify_nm_clusters = []
meshify_ngon_clusters = []
meshify_last_message = ""
meshify_last_operation = ""
meshify_last_result = ""
meshify_selected_strategy = ""
meshify_selected_context = ""

# 🔥 EXPLORATION RATE
meshify_exploration_rate = 0.2

meshify_memory = {
    "non_manifold": {
        "small": "fill",
        "medium": "fill",
        "large": "fill"
    },
    "ngon": {
        "small": "triangulate",
        "medium": "triangulate",
        "large": "triangulate"
    }
}

meshify_memory_updated = "No"

# =========================================================
# CONTEXT
# =========================================================
def get_context(size):
    if size <= 4:
        return "small"
    elif size <= 8:
        return "medium"
    else:
        return "large"

# =========================================================
# DETECTION
# =========================================================
def detect_non_manifold(bm):
    return [e for e in bm.edges if not e.is_manifold]

def detect_ngons(bm):
    return [f for f in bm.faces if len(f.verts) > 4]

# =========================================================
# CLUSTERING
# =========================================================
def cluster_edges(edges):
    visited = set()
    clusters = []
    edge_set = set(e.index for e in edges)

    for e in edges:
        if e.index in visited:
            continue

        stack = [e]
        cluster = []

        while stack:
            cur = stack.pop()
            if cur.index in visited:
                continue

            visited.add(cur.index)
            cluster.append(cur.index)

            for v in cur.verts:
                for ne in v.link_edges:
                    if ne.index in edge_set and ne.index not in visited:
                        stack.append(ne)

        clusters.append(cluster)

    return clusters


def cluster_faces(faces):
    visited = set()
    clusters = []
    face_set = set(f.index for f in faces)

    for f in faces:
        if f.index in visited:
            continue

        stack = [f]
        cluster = []

        while stack:
            cur = stack.pop()
            if cur.index in visited:
                continue

            visited.add(cur.index)
            cluster.append(cur.index)

            for e in cur.edges:
                for nf in e.link_faces:
                    if nf.index in face_set and nf.index not in visited:
                        stack.append(nf)

        clusters.append(cluster)

    return clusters

# =========================================================
# DETECTION PIPELINE
# =========================================================
def run_detection(context):
    global meshify_nm_clusters, meshify_ngon_clusters

    obj = context.active_object

    if not obj or obj.mode != 'EDIT':
        meshify_nm_clusters = []
        meshify_ngon_clusters = []
        return

    bm = bmesh.from_edit_mesh(obj.data)

    meshify_nm_clusters = cluster_edges(detect_non_manifold(bm))
    meshify_ngon_clusters = cluster_faces(detect_ngons(bm))

# =========================================================
# STRATEGY SELECTION (EXPLORE vs EXPLOIT)
# =========================================================
def select_strategy(problem_type, context):
    global meshify_selected_strategy

    if problem_type == "non_manifold":
        strategy_list = ["fill", "merge"]
        default = "fill"
    else:
        strategy_list = ["triangulate"]
        default = "triangulate"

    # SAFETY
    if not strategy_list:
        strategy = default
        meshify_selected_strategy = strategy + " (default)"
        return strategy

    # 🔥 EPSILON-GREEDY STYLE
    if random.random() < meshify_exploration_rate:
        strategy = random.choice(strategy_list)
        meshify_selected_strategy = strategy + " (explore)"
    else:
        strategy = meshify_memory.get(problem_type, {}).get(context, default)
        meshify_selected_strategy = strategy + " (memory)"

    return strategy

# =========================================================
# EXECUTION
# =========================================================
class MESHIFY_OT_fix_nm_cluster(bpy.types.Operator):
    bl_idname = "meshify.fix_nm_cluster"
    bl_label = "Fix"
    bl_options = {'REGISTER', 'UNDO'}

    cluster_index: bpy.props.IntProperty()

    def execute(self, context):
        global meshify_last_message, meshify_last_operation
        global meshify_last_result, meshify_memory_updated, meshify_selected_context

        if self.cluster_index >= len(meshify_nm_clusters):
            return {'CANCELLED'}

        cluster = meshify_nm_clusters[self.cluster_index]
        context_type = get_context(len(cluster))
        meshify_selected_context = context_type

        strategy = select_strategy("non_manifold", context_type)

        # BEFORE
        run_detection(context)
        nm_before = len(meshify_nm_clusters)

        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)

        bm.edges.ensure_lookup_table()
        edges = [bm.edges[i] for i in cluster if i < len(bm.edges)]

        if strategy == "fill":
            if edges:
                bmesh.ops.holes_fill(bm, edges=edges)

        elif strategy == "merge":
            if edges:
                verts = set(v for e in edges for v in e.verts)
                bmesh.ops.remove_doubles(bm, verts=list(verts), dist=0.0001)

        bmesh.update_edit_mesh(obj.data)

        # AFTER
        run_detection(context)
        nm_after = len(meshify_nm_clusters)

        improvement = nm_after < nm_before

        if improvement:
            meshify_last_message = "✔ Fix improved mesh"
            meshify_last_result = "improved"
            meshify_memory.setdefault("non_manifold", {})[context_type] = strategy
            meshify_memory_updated = "Yes"
        else:
            meshify_last_message = "⚠ No improvement"
            meshify_last_result = "no improvement"
            meshify_memory_updated = "No"

        meshify_last_operation = strategy

        return {'FINISHED'}


class MESHIFY_OT_fix_ngon_cluster(bpy.types.Operator):
    bl_idname = "meshify.fix_ngon_cluster"
    bl_label = "Fix"
    bl_options = {'REGISTER', 'UNDO'}

    cluster_index: bpy.props.IntProperty()

    def execute(self, context):
        global meshify_last_message, meshify_last_operation
        global meshify_last_result, meshify_memory_updated, meshify_selected_context

        if self.cluster_index >= len(meshify_ngon_clusters):
            return {'CANCELLED'}

        cluster = meshify_ngon_clusters[self.cluster_index]
        context_type = get_context(len(cluster))
        meshify_selected_context = context_type

        strategy = select_strategy("ngon", context_type)

        # BEFORE
        run_detection(context)
        ngon_before = len(meshify_ngon_clusters)

        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)

        bm.faces.ensure_lookup_table()
        faces = [bm.faces[i] for i in cluster if i < len(bm.faces)]

        if strategy == "triangulate":
            if faces:
                bmesh.ops.triangulate(bm, faces=faces)

        bmesh.update_edit_mesh(obj.data)

        # AFTER
        run_detection(context)
        ngon_after = len(meshify_ngon_clusters)

        improvement = ngon_after < ngon_before

        if improvement:
            meshify_last_message = "✔ Fix improved mesh"
            meshify_last_result = "improved"
            meshify_memory.setdefault("ngon", {})[context_type] = strategy
            meshify_memory_updated = "Yes"
        else:
            meshify_last_message = "⚠ No improvement"
            meshify_last_result = "no improvement"
            meshify_memory_updated = "No"

        meshify_last_operation = strategy

        return {'FINISHED'}


class MESHIFY_OT_undo(bpy.types.Operator):
    bl_idname = "meshify.undo"
    bl_label = "Undo Last Fix"

    def execute(self, context):
        global meshify_last_operation, meshify_last_message
        global meshify_last_result, meshify_memory_updated

        bpy.ops.ed.undo()

        meshify_last_operation = "undo"
        meshify_last_message = "↩ Undo"
        meshify_last_result = ""
        meshify_memory_updated = "No"

        return {'FINISHED'}

# =========================================================
# UI
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

        if not context.scene.meshify_enabled:
            return

        run_detection(context)

        layout.operator("meshify.undo")

        if meshify_last_message:
            layout.label(text=meshify_last_message)

        layout.separator()

        layout.label(text="Non-Manifold:")
        for i, cluster in enumerate(meshify_nm_clusters):
            row = layout.row()
            row.label(text=f"Hole ({len(cluster)} edges)")
            op = row.operator("meshify.fix_nm_cluster", text="Fix")
            op.cluster_index = i

        layout.separator()
        layout.label(text="Ngons:")
        for i, cluster in enumerate(meshify_ngon_clusters):
            row = layout.row()
            row.label(text=f"Ngon ({len(cluster)} face)")
            op = row.operator("meshify.fix_ngon_cluster", text="Fix")
            op.cluster_index = i

        layout.separator()
        layout.label(text="--- DEV ---")
        layout.label(text=f"Context: {meshify_selected_context}")
        layout.label(text=f"Selected strategy: {meshify_selected_strategy}")
        layout.label(text=f"Last result: {meshify_last_result}")
        layout.label(text=f"Memory updated: {meshify_memory_updated}")
        layout.label(text=f"Memory NM: {meshify_memory['non_manifold']}")
        layout.label(text=f"Memory Ngon: {meshify_memory['ngon']}")

# =========================================================
# REGISTER
# =========================================================
classes = (
    MESHIFY_PT_main,
    MESHIFY_OT_fix_nm_cluster,
    MESHIFY_OT_fix_ngon_cluster,
    MESHIFY_OT_undo,
)

def register():
    bpy.types.Scene.meshify_enabled = bpy.props.BoolProperty(default=False)

    for c in classes:
        bpy.utils.register_class(c)

def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)

    del bpy.types.Scene.meshify_enabled


if __name__ == "__main__":
    register()