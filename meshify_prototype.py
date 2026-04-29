bl_info = {
    "name": "Meshify",
    "author": "OpenAI",
    "version": (0, 0, 33),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Meshify",
    "description": "Meshify Hole Complexity Classification",
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
# DETECTION (UNCHANGED)
# =========================================================
def detect_ngons(bm):
    return [f for f in bm.faces if len(f.verts) > 4]


def detect_non_manifold(bm):
    return [e for e in bm.edges if not e.is_manifold]


# =========================================================
# CLUSTERING (UNCHANGED)
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
# HOLE COMPLEXITY CLASSIFICATION (NEW)
# =========================================================
def classify_hole_complexity(cluster_size):
    if cluster_size <= 4:
        return "SMALL"
    elif cluster_size <= 10:
        return "MEDIUM"
    else:
        return "LARGE"


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

    # If all edges are boundary → treat as hole
    if len(boundary_edges) == len(cluster):
        size = len(boundary_edges)
        complexity = classify_hole_complexity(size)

        return {
            "type": "HOLE",
            "complexity": complexity,
            "size": size
        }

    return {
        "type": "OTHER",
        "complexity": None,
        "size": len(cluster)
    }


# =========================================================
# EXECUTION (UPDATED LOGIC)
# =========================================================
class MESHIFY_OT_fix_nm_cluster(bpy.types.Operator):
    bl_idname = "meshify.fix_nm_cluster"
    bl_label = "Fix Non-Manifold Cluster"

    cluster_index: bpy.props.IntProperty()

    def execute(self, context):
        cluster_data = meshify_clusters_nm[self.cluster_index]
        cluster = cluster_data["indices"]
        ctype = cluster_data["type"]
        complexity = cluster_data.get("complexity")

        # HOLE LOGIC ONLY (refined)
        if ctype == "HOLE":
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


class MESHIFY_OT_fix_ngon_cluster(bpy.types.Operator):
    bl_idname = "meshify.fix_ngon_cluster"
    bl_label = "Fix Ngon Cluster"

    cluster_index: bpy.props.IntProperty()

    def execute(self, context):
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

    raw_nm = cluster_edges(nm_edges)

    typed = []
    for cluster in raw_nm:
        data = classify_nm_cluster(bm, cluster)
        data["indices"] = cluster
        typed.append(data)

    meshify_clusters_nm = typed


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
# UI (UPDATED LABELS)
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

        if meshify_clusters_nm:
            layout.label(text="Non-Manifold Clusters:")

            for i, c in enumerate(meshify_clusters_nm):
                cluster = c["indices"]
                ctype = c["type"]

                if ctype == "HOLE":
                    comp = c["complexity"]

                    if comp == "SMALL":
                        label = "Small Hole"
                        warning = ""
                    elif comp == "MEDIUM":
                        label = "Medium Hole"
                        warning = ""
                    else:
                        label = "Large Hole"
                        warning = " ⚠"

                    row = layout.row()
                    row.label(text=f"{label} ({len(cluster)} edges){warning}")

                    op = row.operator(
                        "meshify.fix_nm_cluster",
                        text="Fix (1 step)"
                    )
                    op.cluster_index = i


# =========================================================
# REGISTER
# =========================================================
classes = (
    MESHIFY_PT_main,
    MESHIFY_OT_fix_nm_cluster,
    MESHIFY_OT_fix_ngon_cluster,
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