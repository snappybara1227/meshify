bl_info = {
    "name": "Meshify",
    "author": "OpenAI",
    "version": (0, 0, 37),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Meshify",
    "description": "Meshify Undo Fix + Detection Restore",
    "category": "3D View",
}

import bpy
import bmesh
import time


# =========================================================
# STATE
# =========================================================
meshify_clusters_ngon = []
meshify_clusters_nm = []

meshify_confirm_state = {
    "cluster_id": None,
    "timestamp": 0
}

meshify_last_fix = False


# =========================================================
# DETECTION
# =========================================================
def detect_ngons(bm):
    return [f for f in bm.faces if len(f.verts) > 4]


def detect_non_manifold(bm):
    return [e for e in bm.edges if not e.is_manifold]


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
# CLASSIFICATION
# =========================================================
def classify_hole_complexity(size):
    if size <= 4:
        return "SMALL"
    elif size <= 10:
        return "MEDIUM"
    else:
        return "LARGE"


def assign_confidence(cluster_type, complexity=None):
    if cluster_type == "HOLE":
        if complexity == "SMALL":
            return "HIGH"
        elif complexity == "MEDIUM":
            return "MEDIUM"
        else:
            return "LOW"

    if cluster_type == "NGON":
        return "MEDIUM"

    return "LOW"


def classify_nm_cluster(bm, cluster):
    boundary_edges = []

    for i in cluster:
        if i >= len(bm.edges):
            continue

        e = bm.edges[i]
        if not e.is_valid:
            continue

        if e.is_boundary:
            boundary_edges.append(i)

    if len(boundary_edges) == len(cluster):
        size = len(boundary_edges)
        complexity = classify_hole_complexity(size)
        confidence = assign_confidence("HOLE", complexity)

        return {
            "type": "HOLE",
            "complexity": complexity,
            "confidence": confidence,
            "indices": cluster
        }

    return {
        "type": "OTHER",
        "confidence": "LOW",
        "indices": cluster
    }


# =========================================================
# CONFIRMATION
# =========================================================
def require_confirmation(cluster_id):
    global meshify_confirm_state
    now = time.time()

    if meshify_confirm_state["cluster_id"] == cluster_id:
        if now - meshify_confirm_state["timestamp"] < 2:
            meshify_confirm_state["cluster_id"] = None
            return True

    meshify_confirm_state["cluster_id"] = cluster_id
    meshify_confirm_state["timestamp"] = now
    return False


# =========================================================
# EXECUTION (UNCHANGED)
# =========================================================
class MESHIFY_OT_fix_nm_cluster(bpy.types.Operator):
    bl_idname = "meshify.fix_nm_cluster"
    bl_label = "Fix Non-Manifold Cluster"
    bl_options = {'REGISTER', 'UNDO'}

    cluster_index: bpy.props.IntProperty()

    def execute(self, context):
        global meshify_last_fix

        cluster_data = meshify_clusters_nm[self.cluster_index]
        confidence = cluster_data.get("confidence", "LOW")

        if confidence == "LOW":
            if not require_confirmation(self.cluster_index):
                self.report({'WARNING'}, "⚠ Click again to confirm")
                return {'CANCELLED'}

        bpy.ops.ed.undo_push(message="Meshify Fix")

        bm = bmesh.from_edit_mesh(context.active_object.data)
        bm.edges.ensure_lookup_table()

        cluster = cluster_data["indices"]

        edges = [
            bm.edges[i]
            for i in cluster
            if i < len(bm.edges) and bm.edges[i].is_valid
        ]

        if edges:
            bmesh.ops.holes_fill(bm, edges=edges)

        bmesh.update_edit_mesh(context.active_object.data)

        meshify_last_fix = True
        return {'FINISHED'}


class MESHIFY_OT_fix_ngon_cluster(bpy.types.Operator):
    bl_idname = "meshify.fix_ngon_cluster"
    bl_label = "Fix Ngon Cluster"
    bl_options = {'REGISTER', 'UNDO'}

    cluster_index: bpy.props.IntProperty()

    def execute(self, context):
        global meshify_last_fix

        bpy.ops.ed.undo_push(message="Meshify Fix")

        bm = bmesh.from_edit_mesh(context.active_object.data)
        bm.faces.ensure_lookup_table()

        cluster = meshify_clusters_ngon[self.cluster_index]

        faces = [
            bm.faces[i]
            for i in cluster
            if i < len(bm.faces)
            and bm.faces[i].is_valid
            and len(bm.faces[i].verts) > 4
        ]

        if faces:
            bmesh.ops.triangulate(bm, faces=faces)

        bmesh.update_edit_mesh(context.active_object.data)

        meshify_last_fix = True
        return {'FINISHED'}


class MESHIFY_OT_undo_last(bpy.types.Operator):
    bl_idname = "meshify.undo_last"
    bl_label = "Undo Last Fix"

    def execute(self, context):
        global meshify_last_fix

        if meshify_last_fix:
            bpy.ops.ed.undo()
            meshify_last_fix = False

        return {'FINISHED'}


# =========================================================
# 🔥 FIX: DETECTION PIPELINE RUNS HERE
# =========================================================
def run_detection(context):
    global meshify_clusters_ngon, meshify_clusters_nm

    obj = context.active_object
    if not obj or obj.mode != 'EDIT':
        meshify_clusters_ngon = []
        meshify_clusters_nm = []
        return

    bm = bmesh.from_edit_mesh(obj.data)

    ngons = detect_ngons(bm)
    nm_edges = detect_non_manifold(bm)

    meshify_clusters_ngon = cluster_faces(ngons)
    meshify_clusters_nm = [classify_nm_cluster(bm, c) for c in cluster_edges(nm_edges)]


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

        # 🔥 CRITICAL FIX: run detection EVERY DRAW
        run_detection(context)

        layout.operator("meshify.undo_last", text="Undo Last Fix")

        if meshify_clusters_nm:
            layout.label(text="Non-Manifold Clusters:")
            for i, c in enumerate(meshify_clusters_nm):
                confidence = c.get("confidence", "LOW")
                row = layout.row()
                row.label(text=f"Hole [{confidence}]")
                op = row.operator("meshify.fix_nm_cluster", text="Fix")
                op.cluster_index = i

        if meshify_clusters_ngon:
            layout.separator()
            layout.label(text="Ngon Clusters:")
            for i, cluster in enumerate(meshify_clusters_ngon):
                row = layout.row()
                row.label(text="Ngon [MEDIUM]")
                op = row.operator("meshify.fix_ngon_cluster", text="Fix")
                op.cluster_index = i


# =========================================================
# REGISTER
# =========================================================
classes = (
    MESHIFY_PT_main,
    MESHIFY_OT_fix_nm_cluster,
    MESHIFY_OT_fix_ngon_cluster,
    MESHIFY_OT_undo_last,
)

def register():
    bpy.types.Scene.meshify_enabled = bpy.props.BoolProperty(
        name="Enable Meshify",
        default=False,
    )

    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)

    del bpy.types.Scene.meshify_enabled


if __name__ == "__main__":
    register()