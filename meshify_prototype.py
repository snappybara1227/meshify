bl_info = {
    "name": "Meshify",
    "author": "OpenAI",
    "version": (0, 0, 40),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Meshify",
    "description": "Meshify Adaptive Strategy Switching",
    "category": "3D View",
}

import bpy
import bmesh


# =========================================================
# STATE
# =========================================================
meshify_clusters_ngon = []
meshify_clusters_nm = []
meshify_last_result = None
meshify_last_message = ""


# =========================================================
# DETECTION
# =========================================================
def detect_ngons(bm):
    return [f for f in bm.faces if len(f.verts) > 4]


def detect_non_manifold(bm):
    return [e for e in bm.edges if not e.is_manifold]


def count_issues(bm):
    nm = len([e for e in bm.edges if not e.is_manifold])
    ng = len([f for f in bm.faces if len(f.verts) > 4])
    return nm, ng


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
# CLASSIFICATION (unchanged simplified)
# =========================================================
def classify_nm_cluster(bm, cluster):
    size = len(cluster)

    if size <= 4:
        confidence = "HIGH"
    elif size <= 10:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    return {
        "type": "Hole",
        "confidence": confidence,
        "size": size,
        "indices": cluster
    }


# =========================================================
# EXECUTION WITH ADAPTIVE STRATEGY
# =========================================================
class MESHIFY_OT_fix_nm_cluster(bpy.types.Operator):
    bl_idname = "meshify.fix_nm_cluster"
    bl_label = "Fix Non-Manifold Cluster"
    bl_options = {'REGISTER', 'UNDO'}

    cluster_index: bpy.props.IntProperty()

    def execute(self, context):
        global meshify_last_result, meshify_last_message

        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)

        before_nm, before_ng = count_issues(bm)

        bpy.ops.ed.undo_push(message="Meshify Fix")

        cluster = meshify_clusters_nm[self.cluster_index]["indices"]

        # -------------------------
        # PRIMARY: MERGE + FILL
        # -------------------------
        bm.edges.ensure_lookup_table()
        bm.verts.ensure_lookup_table()

        verts = set()
        for i in cluster:
            if i < len(bm.edges) and bm.edges[i].is_valid:
                for v in bm.edges[i].verts:
                    verts.add(v)

        if verts:
            bmesh.ops.remove_doubles(bm, verts=list(verts), dist=0.0001)

        edges = [bm.edges[i] for i in cluster if i < len(bm.edges) and bm.edges[i].is_valid]

        if edges:
            bmesh.ops.holes_fill(bm, edges=edges)

        bmesh.update_edit_mesh(obj.data)

        # -------------------------
        # EVALUATE PRIMARY
        # -------------------------
        bm = bmesh.from_edit_mesh(obj.data)
        after_nm, after_ng = count_issues(bm)

        if (after_nm + after_ng) < (before_nm + before_ng):
            meshify_last_result = "SUCCESS"
            meshify_last_message = "✔ Primary fix worked"
            return {'FINISHED'}

        # -------------------------
        # FALLBACK: FILL ONLY
        # -------------------------
        meshify_last_message = "⚠ Primary failed → using fallback"

        bpy.ops.ed.undo_push(message="Meshify Fallback")

        bm = bmesh.from_edit_mesh(obj.data)
        bm.edges.ensure_lookup_table()

        edges = [bm.edges[i] for i in cluster if i < len(bm.edges) and bm.edges[i].is_valid]

        if edges:
            bmesh.ops.holes_fill(bm, edges=edges)

        bmesh.update_edit_mesh(obj.data)

        # -------------------------
        # EVALUATE FALLBACK
        # -------------------------
        bm = bmesh.from_edit_mesh(obj.data)
        final_nm, final_ng = count_issues(bm)

        if (final_nm + final_ng) < (before_nm + before_ng):
            meshify_last_result = "SUCCESS"
        else:
            meshify_last_result = "WARNING"
            meshify_last_message = "⚠ Fallback failed → unresolved"

        return {'FINISHED'}


class MESHIFY_OT_fix_ngon_cluster(bpy.types.Operator):
    bl_idname = "meshify.fix_ngon_cluster"
    bl_label = "Fix Ngon Cluster"
    bl_options = {'REGISTER', 'UNDO'}

    cluster_index: bpy.props.IntProperty()

    def execute(self, context):
        global meshify_last_result, meshify_last_message

        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)

        before_nm, before_ng = count_issues(bm)

        bpy.ops.ed.undo_push(message="Meshify Fix")

        # PRIMARY: TRIANGULATE
        bm.faces.ensure_lookup_table()

        cluster = meshify_clusters_ngon[self.cluster_index]

        faces = [bm.faces[i] for i in cluster if i < len(bm.faces) and bm.faces[i].is_valid]

        if faces:
            bmesh.ops.triangulate(bm, faces=faces)

        bmesh.update_edit_mesh(obj.data)

        # EVALUATE
        bm = bmesh.from_edit_mesh(obj.data)
        after_nm, after_ng = count_issues(bm)

        if (after_nm + after_ng) < (before_nm + before_ng):
            meshify_last_result = "SUCCESS"
            meshify_last_message = "✔ Primary fix worked"
            return {'FINISHED'}

        # FALLBACK: TRIANGULATE + MERGE
        meshify_last_message = "⚠ Primary failed → using fallback"

        bpy.ops.ed.undo_push(message="Meshify Fallback")

        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()

        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)

        bmesh.update_edit_mesh(obj.data)

        bm = bmesh.from_edit_mesh(obj.data)
        final_nm, final_ng = count_issues(bm)

        if (final_nm + final_ng) < (before_nm + before_ng):
            meshify_last_result = "SUCCESS"
        else:
            meshify_last_result = "WARNING"
            meshify_last_message = "⚠ Fallback failed → unresolved"

        return {'FINISHED'}


class MESHIFY_OT_undo_last(bpy.types.Operator):
    bl_idname = "meshify.undo_last"
    bl_label = "Undo Last Fix"

    def execute(self, context):
        bpy.ops.ed.undo()
        return {'FINISHED'}


# =========================================================
# DETECTION PIPELINE
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

        run_detection(context)

        layout.operator("meshify.undo_last")

        # MESSAGE
        if meshify_last_message:
            layout.label(text=meshify_last_message)

        layout.separator()

        # NM
        if meshify_clusters_nm:
            layout.label(text="Non-Manifold:")
            for i, c in enumerate(meshify_clusters_nm):
                row = layout.row()
                row.label(text=f"Hole ({c['size']} edges) [{c['confidence']}]")
                op = row.operator("meshify.fix_nm_cluster", text="Fix")
                op.cluster_index = i

        # NGON
        if meshify_clusters_ngon:
            layout.separator()
            layout.label(text="Ngons:")
            for i, cluster in enumerate(meshify_clusters_ngon):
                row = layout.row()
                row.label(text=f"Ngon ({len(cluster)} faces) [MEDIUM]")
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