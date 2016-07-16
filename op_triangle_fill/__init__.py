'''
Created on Jul 12, 2016

@author: Patrick
'''
import bpy
import bmesh
from mathutils import Vector

from bpy.props import FloatProperty, BoolProperty
from ..bmesh_fns import edge_loops_from_bmedges, join_bmesh

def relax_bmesh(bme, verts, exclude, iterations = 1, spring_power = .1, quad_power = .1):
    '''
    takes verts
    '''
    for j in range(0,iterations):
        deltas = dict()
        #edges as springs
        for i, bmv0 in enumerate(verts):
            
            if bmv0.index in exclude: continue
            
            lbmeds = bmv0.link_edges
            net_f = Vector((0,0,0))
            
            for bmed in lbmeds:
                bmv1 = bmed.other_vert(bmv0)
                net_f += bmv1.co - bmv0.co
                
            deltas[bmv0.index] = spring_power*net_f  #todo, normalize this to average spring length?
            
        
        #cross braces on faces, try to expand face to square
        for bmf in bme.faces:
            if len(bmf.verts) != 4: continue
            
            dia0 = bmf.verts[2].co - bmf.verts[0].co
            dia1 = bmf.verts[3].co - bmf.verts[1].co
            
            avg_l = .5 * dia0.length + .5 * dia1.length
            
            d0 = .5 * (dia0.length - avg_l)
            d1 = .5 * (dia1.length - avg_l)
            
            dia0.normalize()
            dia1.normalize()
            
            #only expand, no tension
            if bmf.verts[0].index not in exclude:
                deltas[bmf.verts[0].index] += quad_power * d0 * dia0
            if bmf.verts[2].index not in exclude:
                deltas[bmf.verts[2].index] += -quad_power * d0 * dia0
        
            if bmf.verts[1].index not in exclude:
                deltas[bmf.verts[1].index] += quad_power * d1 * dia1
            if bmf.verts[3].index not in exclude:
                deltas[bmf.verts[3].index] += -quad_power * d1 * dia1  
                  
        for i in deltas:
            bme.verts[i].co += deltas[i]
            
            
def collapse_short_edges(bm,boundary_edges, interior_edges,threshold=.5):
    '''
    collapses edges shorter than threshold * average_edge_length
    '''
    ### collapse short edges
    edges_len_average = sum(ed.calc_length() for ed in interior_edges)/len(interior_edges)

    boundary_verts = set()
    for ed in boundary_edges:
        boundary_verts.update([ed.verts[0], ed.verts[1]])
        
    interior_verts = set()
    for ed in interior_edges:
        interior_verts.update([ed.verts[0], ed.verts[1]])
        
    interior_verts.difference_update(boundary_verts)
    bmesh.ops.remove_doubles(bm,verts=list(interior_verts),dist=edges_len_average*threshold)

def average_edge_cuts(bm,edges_boundary, edges_interior, cuts=1):
    ### subdivide long edges
    edges_count = len(edges_boundary)
    shortest_edge = min(edges_boundary, key = lambda x: x.calc_length())
    shortest_l = shortest_edge.calc_length()
    
    edges_len_average = sum(ed.calc_length() for ed in edges_boundary)/edges_count

    spread = edges_len_average/shortest_l
    if spread > 5:
        print('seems to be a large difference in edge lenghts')
        print('going to use 1/2 average edge ength as target instead of min edge')
        target = .5 * edges_len_average
    else:
        target = shortest_l
        
    subdivide_edges = []
    for edge in edges_interior:
        cut_count = int(edge.calc_length()/target)*cuts
        if cut_count < 0:
            cut_count = 0
        if not edge.is_boundary:
            subdivide_edges.append([edge,cut_count])
    for edge in subdivide_edges:
        bmesh.ops.subdivide_edges(bm,edges=[edge[0]],cuts=edge[1]) #perhaps....bisect and triangulate
                       
def triangle_fill_loop(bm, eds):
    geom_dict = bmesh.ops.triangle_fill(bm,edges=eds,use_beauty=True)
    if geom_dict["geom"] == []:
        return False, geom_dict
    else:
        return True, geom_dict

def triangulate(bm,fs):
    new_geom = bmesh.ops.triangulate(bm,faces=fs, ngon_method = 0, quad_method = 1) 
    return new_geom

def smooth_verts(bm, verts_smooth, iters = 10):
    for i in range(iters):
        #bmesh.ops.smooth_vert(bm,verts=smooth_verts,factor=1.0,use_axis_x=True,use_axis_y=True,use_axis_z=True)    
        bmesh.ops.smooth_vert(bm,verts=verts_smooth,factor=1.0,use_axis_x=True,use_axis_y=True,use_axis_z=True)    
   
def clean_verts(bm, interior_faces):
    ### find corrupted faces
    faces = []     
    for face in interior_faces:
        i = 0
        for edge in face.edges:
            if not edge.is_manifold:
                i += 1
        if i == len(face.edges):
            faces.append(face)
    print('deleting %i lonely faces' % len(faces))                 
    bmesh.ops.delete(bm,geom=faces,context=5)

    edges = []
    for face in bm.faces:
        i = 0
        for vert in face.verts:
            if not vert.is_manifold and not vert.is_boundary:
                i+=1
        if i == len(face.verts):
            for edge in face.edges:
                if edge not in edges:
                    edges.append(edge)
    print('collapsing %i loose or otherwise strange edges' % len(edges))
    bmesh.ops.collapse(bm,edges=edges)
            
    verts = []
    for vert in bm.verts:
        if len(vert.link_edges) in [3,4] and not vert.is_boundary:
            verts.append(vert)
            
    print('dissolving %i weird verts after collapsing edges' % len(verts))
    bmesh.ops.dissolve_verts(bm,verts=verts)

    
class TriangleFill(bpy.types.Operator):
    bl_idname = "object.triangle_fill"
    bl_label = "Triangle Fill Hole"
    bl_options = {'REGISTER', 'UNDO'}
    
    
    

    def triangulate_fill(self,bme,edges):
        
        ed_loops = edge_loops_from_bmedges(bme, edges, ret = {'VERTS','EDGES'})
        
        bme_patches = []
        for vs, eds in zip(ed_loops['VERTS'], ed_loops['EDGES']):
            if vs[0] != vs[-1]: 
                print('not a closed loop')
                continue
            bme.verts.ensure_lookup_table()
            bme.edges.ensure_lookup_table()
            bme.faces.ensure_lookup_table()
            
            hole_edges = [bme.edges[i] for i in eds]
            perimeter_verts = set([bme.verts[i] for i in vs[0:-1]])
            
            
            bme_patches += [bmesh.new()]
            bme_patch = bme_patches[-1]
            ######################

            
            vert_lookup = {}
            vert_list = list(perimeter_verts)
            new_bmverts = []
            for i, v in enumerate(vert_list):
                vert_lookup[v.index] = i
                new_bmverts += [bme_patch.verts.new(v.co)]
            
            patch_hole_edges = []    
            for ed in hole_edges:
                ed_ind_tuple = [vert_lookup[v.index] for v in ed.verts]
                ed_vert_tuple = [new_bmverts[i] for i in ed_ind_tuple]
                patch_hole_edges += [bme_patch.edges.new(tuple(ed_vert_tuple))]
            
            
            ######################
            fill_ok, geom_dict = triangle_fill_loop(bme_patch,patch_hole_edges)
            if fill_ok:
                
                new_faces = [ele for ele in geom_dict['geom'] if isinstance(ele, bmesh.types.BMFace)]
                new_edges = [ele for ele in geom_dict['geom'] if isinstance(ele, bmesh.types.BMEdge)]
                new_verts = [ele for ele in geom_dict['geom'] if isinstance(ele, bmesh.types.BMVert)]
                
                average_edge_cuts(bme_patch, patch_hole_edges, new_edges, cuts =1)
                triangle_geom = triangulate(bme_patch,new_faces)
                
                perim_edges = [ed for ed in bme_patch.edges if not ed.is_manifold]
                interior_edges = [ed for ed in bme_patch.edges if ed.is_manifold]
                interior_verts = [v for v in bme_patch.verts if not v.is_boundary] 
                smooth_verts(bme_patch,interior_verts)
                
                collapse_short_edges(bme_patch, perim_edges, interior_edges, threshold = .9)
                
                
                interior_verts = [v for v in bme_patch.verts if not v.is_boundary] 
                print('%i interior verts' % len(interior_verts))
                smooth_verts(bme_patch,interior_verts)
                
                
                clean_verts(bme_patch, bme_patch.faces)
                
                interior_verts = [v for v in bme_patch.verts if not v.is_boundary] 
                print('%i interior verts' % len(interior_verts))
                smooth_verts(bme_patch,interior_verts)
                
                triangulate(bme_patch, bme_patch.faces)
                interior_verts = [v for v in bme_patch.verts if not v.is_boundary]
                smooth_verts(bme_patch, interior_verts)
                
                #bm.verts.index_update()
                #bmesh.update_edit_mesh(obj.data) 
                #bmesh.ops.recalc_face_normals(bm,faces=bm.faces)
                #bmesh.update_edit_mesh(obj.data)
                
                #join the patch back into original bmesh
                #perim_map = {}
                
        for i, bme_patch in enumerate(bme_patches):
            
            print('merging %i patch into bmesh' % i)
            print('it as % i verts and %i faces' % (len(bme_patch.verts), len(bme_patch.faces)))
 
            join_bmesh(bme_patch, bme, {})
            bme_patch.free()
            bme.verts.ensure_lookup_table()
            bme.edges.ensure_lookup_table()
            bme.faces.ensure_lookup_table()        
                    
        bmesh.ops.recalc_face_normals(bme,faces=bme.faces)                
        return fill_ok
    

    
    def execute(self,context):
        obj = context.active_object
        
        if context.mode != 'EDIT_MESH':
            print('No Edit mode...EDIT MESH?')
            print(context.mode)
            return {'CANCELLED'}
        
        bme = bmesh.from_edit_mesh(obj.data)
        eds = [e.index for e in bme.edges if e.select]
        for ed in bme.edges:
            ed.select_set(False)
        self.triangulate_fill(bme, eds)
        bmesh.update_edit_mesh(obj.data)
        bpy.ops.ed.undo_push(message="Triangle Fill")
        return{'FINISHED'}