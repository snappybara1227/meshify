bl_info = {
    "name": "Meshify",
    "author": "OpenAI",
    "version": (0, 0, 31),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Meshify",
    "description": "Meshify Adaptive Fix Chains",
    "category": "3D View",
}

import bpy
import bmesh


# =========================================================
# STATE
# =========================================================
_draw_handle = None
meshify_clusters_ngon = []
meshify_clusters_nm = []


# =========================================================
# DETECTION
# =========================================================
def detect_ngons(bm):
    return [f for f in bm.faces if len(f.verts) > 4]


def detect_non_manifold(bm):
    return [e for e in bm.edges if not e.is_manifold]


# =========================================================
# CLUSTERING (UNCHANGED)
# =========================================================
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


# =========================================================
# EXECUTION (ADAPTIVE FIX CHAINS)
# =========================================================

class MESHIFY_OT_fix_ngon_cluster(bpy.types.Operator):
    bl_idname = "meshify.fix_ngon_cluster"
    bl_label = "Fix Ngon Cluster"

    cluster_index: bpy.props.IntProperty()

    def execute(self, context):
        # Only 1 step: triangulate
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
        return {'FINISHED'}


class MESHIFY_OT_fix_nm_cluster(bpy.types.Operator):
    bl_idname = "meshify.fix_nm_cluster"
    bl_label = "Fix Non-Manifold Cluster"

    cluster_index: bpy.props.IntProperty()

    def execute(self, context):
        cluster = meshify_clusters_nm[self.cluster_index]
        cluster_size = len(cluster)

        # -------------------------
        # STEP 1: MERGE (ALWAYS)
        # -------------------------
        bm = bmesh.from_edit_mesh(context.active_object.data)
        bm.edges.ensure_lookup_table()
        bm.verts.ensure_lookup_table()

        verts = set()
        for i in cluster:
            if i < len(bm.edges) and bm.edges[i].is_valid:
                for v in bm.edges[i].verts:
                    verts.add(v)

        if verts:
            bmesh.ops.remove_doubles(bm, verts=list(verts), dist=0.0001)

        bmesh.update_edit_mesh(context.active_object.data)

        # -------------------------
        # STEP 2: FILL (ONLY IF BIG)
        # -------------------------
        if cluster_size > 2:
            bm = bmesh.from_edit_mesh(context.active_object.data)
            bm.edges.ensure_lookup_table()

            edges = [
                bm.edges[i]
                for i in cluster
                if i < len(bm.edges) and bm.edges[i].is_valid
            ]

            if edges:
                bmesh.ops.holes_fill(bm, edges=edges)

            bmesh.update_edit_mesh(context.active_object.data)

        return {'FINISHED'}


# =========================================================
# CORE
# =========================================================
def draw_meshify():
    global meshify_clusters_ngon, meshify_clusters_nm

    if not bpy.context.scene.meshify_enabled:
        return

    obj = bpy.context.active_object
    if not obj or obj.mode != 'EDIT':
        meshify_clusters_ngon = []
        meshify_clusters_nm = []
        return

    bm = bmesh.from_edit_mesh(obj.data)

    ngons = detect_ngons(bm)
    nm_edges = detect_non_manifold(bm)

    meshify_clusters_ngon = cluster_faces(ngons)
    meshify_clusters_nm = cluster_edges(nm_edges)


# =========================================================
# HANDLER
# =========================================================
def add_draw_handler():
    global _draw_handle
    if _draw_handle is None:
        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            draw_meshify, (), 'WINDOW', 'POST_VIEW'
        )


def remove_draw_handler():
    global _draw_handle
    if _draw_handle:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None


def update_meshify_enabled(self, context):
    if self.meshify_enabled:
        add_draw_handler()
    else:
        remove_draw_handler()


# =========================================================
# UI (ADAPTIVE STEP COUNT)
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

        # NGON
        if meshify_clusters_ngon:
            layout.label(text="Ngon Clusters:")
            for i, cluster in enumerate(meshify_clusters_ngon):
                row = layout.row()
                row.label(text=f"Cluster {i} ({len(cluster)} faces)")
                op = row.operator("meshify.fix_ngon_cluster", text="Fix (1 step)")
                op.cluster_index = i

        # NON-MANIFOLD
        if meshify_clusters_nm:
            layout.separator()
            layout.label(text="Non-Manifold Clusters:")

            for i, cluster in enumerate(meshify_clusters_nm):
                steps = 1 if len(cluster) <= 2 else 2

                row = layout.row()
                row.label(text=f"Cluster {i} ({len(cluster)} edges)")
                op = row.operator(
                    "meshify.fix_nm_cluster",
                    text=f"Fix ({steps} step{'s' if steps > 1 else ''})"
                )
                op.cluster_index = i


# =========================================================
# REGISTER
# =========================================================
classes = (
    MESHIFY_PT_main,
    MESHIFY_OT_fix_ngon_cluster,
    MESHIFY_OT_fix_nm_cluster,
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

    for c in reversed(classes):
        bpy.utils.unregister_class(c)

    del bpy.types.Scene.meshify_enabled


if __name__ == "__main__":
    register()