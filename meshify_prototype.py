bl_info = {
    "name": "Meshify",
    "author": "OpenAI",
    "version": (0, 0, 33),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Meshify",
    "category": "3D View",
}

import bpy
import bmesh

# =========================================================
# STATE
# =========================================================
meshify_nm_clusters = []
meshify_ngon_clusters = []
meshify_last_message = ""
meshify_last_operation = ""

meshify_memory = {
    "non_manifold": "fill",
    "ngon": "triangulate"
}

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
# EXECUTION (SAFE LAYER ADDED)
# =========================================================
class MESHIFY_OT_fix_nm_cluster(bpy.types.Operator):
    bl_idname = "meshify.fix_nm_cluster"
    bl_label = "Fix"
    bl_options = {'REGISTER', 'UNDO'}

    cluster_index: bpy.props.IntProperty()

    def execute(self, context):
        global meshify_last_message, meshify_last_operation, meshify_memory

        # ✅ INDEX SAFETY
        if self.cluster_index >= len(meshify_nm_clusters):
            return {'CANCELLED'}

        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)

        cluster = meshify_nm_clusters[self.cluster_index]

        bm.edges.ensure_lookup_table()
        edges = [bm.edges[i] for i in cluster if i < len(bm.edges)]

        if edges:
            bmesh.ops.holes_fill(bm, edges=edges)

        bmesh.update_edit_mesh(obj.data)

        # ✅ REFRESH DETECTION
        run_detection(context)

        meshify_last_message = "✔ Fix applied"
        meshify_last_operation = "fill"
        meshify_memory["non_manifold"] = "fill"

        return {'FINISHED'}


class MESHIFY_OT_fix_ngon_cluster(bpy.types.Operator):
    bl_idname = "meshify.fix_ngon_cluster"
    bl_label = "Fix"
    bl_options = {'REGISTER', 'UNDO'}

    cluster_index: bpy.props.IntProperty()

    def execute(self, context):
        global meshify_last_message, meshify_last_operation, meshify_memory

        # ✅ INDEX SAFETY
        if self.cluster_index >= len(meshify_ngon_clusters):
            return {'CANCELLED'}

        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)

        cluster = meshify_ngon_clusters[self.cluster_index]

        bm.faces.ensure_lookup_table()
        faces = [bm.faces[i] for i in cluster if i < len(bm.faces)]

        if faces:
            bmesh.ops.triangulate(bm, faces=faces)

        bmesh.update_edit_mesh(obj.data)

        # ✅ REFRESH DETECTION
        run_detection(context)

        meshify_last_message = "✔ Fix applied"
        meshify_last_operation = "triangulate"
        meshify_memory["ngon"] = "triangulate"

        return {'FINISHED'}


class MESHIFY_OT_undo(bpy.types.Operator):
    bl_idname = "meshify.undo"
    bl_label = "Undo Last Fix"

    def execute(self, context):
        global meshify_last_operation, meshify_last_message

        bpy.ops.ed.undo()

        # ✅ UNDO STATE FIX
        meshify_last_operation = "undo"
        meshify_last_message = "↩ Undo"

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

        # NM
        layout.label(text="Non-Manifold:")
        for i, cluster in enumerate(meshify_nm_clusters):
            row = layout.row()
            row.label(text=f"Hole ({len(cluster)} edges)")
            op = row.operator("meshify.fix_nm_cluster", text="Fix")
            op.cluster_index = i

        # NGON
        layout.separator()
        layout.label(text="Ngons:")
        for i, cluster in enumerate(meshify_ngon_clusters):
            row = layout.row()
            row.label(text=f"Ngon ({len(cluster)} face)")
            op = row.operator("meshify.fix_ngon_cluster", text="Fix")
            op.cluster_index = i

        # DEV
        layout.separator()
        layout.label(text="--- DEV ---")
        layout.label(text=f"NM clusters: {len(meshify_nm_clusters)}")
        layout.label(text=f"Ngon clusters: {len(meshify_ngon_clusters)}")
        layout.label(text=f"Last operation: {meshify_last_operation}")
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