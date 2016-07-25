'''
Created on Jul 12, 2016

@author: Patrick
'''
import math

import bpy
import bmesh
from mathutils import Vector

from bpy.props import FloatProperty, BoolProperty, IntProperty
from ..bmesh_fns import edge_loops_from_bmedges, join_bmesh
from ..common_utilities import sort_objects_by_angles, delta_angles

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
    
    
    iter_max = IntProperty(default = 5, name = 'Max Iterations')
    
    def triangulate_fill(self,bme,edges, max_iters):
        
        ed_loops = edge_loops_from_bmedges(bme, edges, ret = {'VERTS','EDGES'})
        
        for vs, eds in zip(ed_loops['VERTS'], ed_loops['EDGES']):
            if vs[0] != vs[-1]: 
                print('not a closed loop')
                continue
            bme.verts.ensure_lookup_table()
            bme.edges.ensure_lookup_table()
            bme.faces.ensure_lookup_table()
            
            
            def calc_angle(v, report = False):
                #use link edges and non_man eds
                eds_non_man = [ed for ed in v.link_edges if not ed.is_manifold]
                eds_all = [ed for ed in v.link_edges]
                
                #shift list to start with a non manifold edge if needed
                base_ind = eds_all.index(eds_non_man[0])
                eds_all = eds_all[base_ind:] + eds_all[:base_ind]
                
                #vector representation of edges
                eds_vecs = [ed.other_vert(v).co - v.co for ed in eds_all]
                
                if len(eds_non_man) != 2:
                    print("more than 2 non manifold edges, loop self intersects or there is a dangling edge")
                    return 2 * math.pi, None, None
                
                va = eds_non_man[0].other_vert(v)
                vb = eds_non_man[1].other_vert(v)
                
                Va = va.co - v.co
                Vb = vb.co - v.co
                
                angle = Va.angle(Vb)
                
                #check for connectivity
                if len(eds_all) == 2:
                    if any([ed.other_vert(va) == vb for ed in vb.link_edges]):
                        #already a tri over here
                        print('va and vb connect')
                        return 2 * math.pi, None, None
                
                    elif any([f in eds[0].link_faces for f in eds[1].link_faces]):
                        print('va and vb share face')
                        return 2 * math.pi, None, None
                    
                    else: #completely regular situation
                        
                        if Vb.cross(Va).dot(v.normal) < 0:
                            print('keep normals consistent reverse')
                            return angle, vb, va
                        else:
                            
                            return angle, va, vb
                
                elif len(eds_all) > 2:
                    #sort edges ccw by normal, starting at eds_nm[0]
                    eds_sorted = sort_objects_by_angles(v.normal, eds_all, eds_vecs)
                    vecs_sorted = [ed.other_vert(v).co - v.co for ed in v.link_edges]
                    deltas = delta_angles(v.normal, vecs_sorted)
                    ed1_ind = eds_sorted.index(eds_non_man[1])
                    
                    delta_forward = sum(deltas[:ed1_ind])
                    delta_reverse = sum(deltas[ed1_ind:])
                    
                    if ed1_ind == len(eds_all) - 1:
                        
                        if report:
                            print('ed_nm1 is last in the loop')

                        if delta_reverse > math.pi:
                            
                            if report:
                                print('delta revers >180 so ret 2pi - angle')
                            return 2*math.pi - angle, va, vb
                        
                        else:
                            if report:
                                print('delta revers <180 so ret angle')
                            return angle, va, vb  
                        
                    elif ed1_ind == 1:
                        if report:
                            print('ed_nm1 is index 1 in the loop')
                            
                        if delta_forward > math.pi:
                            if report:
                                print('delta forward > 180 so ret 2pi - angle')
                            return 2*math.pi - angle, va, vb
                        else:
                            if report:
                                print('delta revers < 180 so ret angle')
                            return angle, vb, va  #notice reverse Va, Vb to mainatin normals
                        
                        
                    else:
                        print('BIG PROBLEM IN ANALYZING THIS VERTEX')
                        #big problems....edges on both sides
                return angle, va, vb
                
            #initiate the front and calc angles
            angles = {}
            neighbors = {}
            verts = [bme.verts[i] for i in vs]
            for v in verts:
                ang, va, vb = calc_angle(v)
                angles[v] = ang
                neighbors[v] = (va, vb)
            front = set(verts)   
            iters = 0 
            while len(front) > 4 and iters < max_iters:
                iters += 1
                print('      ')
                print('   #################   ')
                print('this is the %i iteration' % iters)
                
                v_small = min(front, key = angles.get)
                smallest_angle = angles[v_small]
                
                print('the smallest v is %i' % v_small.index)
                print('the smallest angle is %f' % smallest_angle)
                
                va, vb = neighbors[v_small]
                
                vec_a = va.co - v_small.co
                vec_b = vb.co - v_small.co
                
                Ra, Rb = vec_a.length, vec_b.length
                
                R_13 = .67*Ra + .33*Rb
                R_12 = .5*Ra + .5*Rb
                R_23 = .33*Ra + .67*Rb
                
                print((R_13, R_12, R_23))
                
                vec_a.normalize()
                vec_b.normalize()
                v_13 = vec_a.lerp(vec_b, .33) #todo, verify lerp
                v_12 = vec_a.lerp(vec_b, .5)
                v_23 = vec_a.lerp(vec_b, .67)
                
                v_13.normalize()
                v_12.normalize()
                v_23.normalize()
                
                if smallest_angle < math.pi/180 * 75:
                    print(' < 75 degrees situation')
                    try:
                        f = bme.faces.new((vb, v_small, va))
                        f.normal_update()
                    except ValueError:
                        print('concavity with face on back side')
                        angles[v_small] = 2*math.pi
                
                    #Remove v from the front
                    front.remove(v_small)
                    angles.pop(v_small, None)
                    neighbors.pop(v_small, None)
                    
                    #update angles and neigbors of va and vb
                    va.normal_update()
                    ang, v_na, v_nb = calc_angle(va)
                    angles[va] = ang
                    neighbors[va] = (v_na, v_nb)
    
                    vb.normal_update()
                    ang, v_na, v_nb = calc_angle(vb)
                    angles[vb] = ang
                    neighbors[vb] = (v_na, v_nb)
                                        
                elif smallest_angle < math.pi/180 * 135:
                    print('75 to 135 degrees situation')
                    v_new_co = v_small.co + R_12 * v_12
                    
                    v_new = bme.verts.new(v_new_co)
                    #bme.faces.new((va, v_small, v_new))
                    #bme.faces.new((v_new, v_small, vb))
                    
                    f1 = bme.faces.new((v_new, v_small, va))
                    f2 = bme.faces.new((vb, v_small, v_new))
                    
                    f1.normal_update()
                    f2.normal_update()
                    
                    
                    front.add(v_new)
                    front.remove(v_small)
                    angles.pop(v_small, None)
                    neighbors.pop(v_small, None)
                    
                    v_new.normal_update()
                    ang, v_na, v_nb = calc_angle(v_new)
                    angles[v_new] = ang
                    neighbors[v_new] = (v_na, v_nb)
                    v_new.select_set(True)
                    
                    va.normal_update()
                    ang, v_na, v_nb = calc_angle(va)
                    angles[va] = ang
                    neighbors[va] = (v_na, v_nb)
    
                    print('previous angle for vb is %f' % angles[vb])
                    vb.normal_update()
                    ang, v_na, v_nb = calc_angle(vb, report = True)
                    angles[vb] = ang
                    neighbors[vb] = (v_na, v_nb)
                    vb.select_set(True)
                    print('new angle for vb is %f' % ang)
                    
                else:
                    print('> 135 degrees situation')
                    v_new_coa = v_small.co + R_13 * v_13
                    v_new_cob = v_small.co + R_23 * v_23
                    
                    v_new_a = bme.verts.new(v_new_coa)
                    v_new_b = bme.verts.new(v_new_cob)
                    
                    #bme.faces.new((va, v_small, v_new_a))
                    #bme.faces.new((v_new_a, v_small, v_new_b))
                    #bme.faces.new((v_new_b, v_small, vb))
                    
                    f1 = bme.faces.new((v_new_a, v_small, va))
                    f2 = bme.faces.new((v_new_b, v_small, v_new_a))
                    f3 = bme.faces.new((vb, v_small, v_new_b))
                    
                    f1.normal_update()
                    f2.normal_update()
                    f3.normal_update()
                    
                    #update the 2 newly created verts
                    front.update([v_new_a, v_new_b])
                    front.remove(v_small)
                    angles.pop(v_small, None)
                    neighbors.pop(v_small, None)
            
                    v_new_a.normal_update()
                    ang, v_na, v_nb = calc_angle(v_new_a)
                    angles[v_new_a] = ang
                    neighbors[v_new_a] = (v_na, v_nb)
    
                    v_new_b.normal_update()
                    ang, v_na, v_nb = calc_angle(v_new_b)
                    angles[v_new_b] = ang
                    neighbors[v_new_b] = (v_na, v_nb)
                    
                    #update the information on the neighbors
                    va.normal_update()
                    ang, v_na, v_nb = calc_angle(va)
                    angles[va] = ang
                    neighbors[va] = (v_na, v_nb)
    
                    vb.normal_update()
                    ang, v_na, v_nb = calc_angle(vb)
                    angles[vb] = ang
                    neighbors[vb] = (v_na, v_nb)
    
    def invoke(self, context, event): 
        return context.window_manager.invoke_props_dialog(self, width=300) 
    
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
        self.triangulate_fill(bme, eds, self.iter_max)
        bme.select_flush(True)
        bmesh.update_edit_mesh(obj.data)
        bpy.ops.ed.undo_push(message="Triangle Fill")
        return{'FINISHED'}