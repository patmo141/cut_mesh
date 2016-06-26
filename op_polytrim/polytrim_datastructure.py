'''
Created on Oct 8, 2015

@author: Patrick
'''
import time

import bpy
import bmesh
from mathutils import Vector, Matrix, kdtree
from mathutils.bvhtree import BVHTree
from mathutils.geometry import intersect_point_line, intersect_line_plane
from bpy_extras import view3d_utils

from ..bmesh_fns import grow_selection_to_find_face, flood_selection_faces, edge_loops_from_bmedges, flood_selection_by_verts
from ..cut_algorithms import cross_section_2seeds_ver1, path_between_2_points
from .. import common_drawing
from ..common_utilities import bversion

class PolyLineKnife(object):
    '''
    A class which manages user placed points on an object to create a
    poly_line, adapted to the objects surface.
    '''
    def __init__(self,context, cut_object, ui_type = 'DENSE_POLY'):   
        self.cut_ob = cut_object
        self.bme = bmesh.new()
        self.bme.from_mesh(cut_object.data)
        self.bme.verts.ensure_lookup_table()
        self.bme.edges.ensure_lookup_table()
        self.bme.faces.ensure_lookup_table()
        
        non_tris = [f for f in self.bme.faces if len(f.verts) > 3]
        #if len(non_tris):
            #geom = bmesh.ops.connect_verts_concave(self.bme, non_tris)
            #self.bme.verts.ensure_lookup_table()
            #self.bme.edges.ensure_lookup_table()
            #self.bme.faces.ensure_lookup_table()
        
        self.bvh = BVHTree.FromBMesh(self.bme)
        
        self.cyclic = False
        self.start_edge = None
        self.end_edge = None
        
        self.pts = []
        self.cut_pts = []  #local points
        self.normals = []
        
        self.face_map = []  #all the faces that user drawn poly line fall upon
        self.face_changes = [] #the indices where the next point lies on a different face
        self.face_groups = dict()  #maps bmesh face index to all the points in user drawn polyline which fall upon it
        self.new_ed_face_map = dict()  #maps face index in bmesh to new edges created by bisecting
        
        self.ed_map = []  #existing edges in bmesh crossed by cut line
        self.new_cos = []  #location of crosses
        
        
        self.non_man_eds = [ed.index for ed in self.bme.edges if not ed.is_manifold]
        self.non_man_ed_loops = edge_loops_from_bmedges(self.bme, self.non_man_eds)
        
        #print(self.non_man_ed_loops)
        self.non_man_points = []
        self.non_man_bmverts = []
        for loop in self.non_man_ed_loops:
            self.non_man_points += [self.cut_ob.matrix_world * self.bme.verts[ind].co for ind in loop]
            self.non_man_bmverts += [self.bme.verts[ind].index for ind in loop]
        if len(self.non_man_points):  
            kd = kdtree.KDTree(len(self.non_man_points))
            for i, v in enumerate(self.non_man_points):
                kd.insert(v, i)
                
            kd.balance()            
            self.kd = kd
        else:
            self.kd = None
            
        self.face_chain = set()  #all faces crossed by the cut curve
        if ui_type not in {'SPARSE_POLY','DENSE_POLY', 'BEZIER'}:
            self.ui_type = 'SPARSE_POLY'
        else:
            self.ui_type = ui_type
                
        self.selected = -1
        self.hovered = [None, -1]
        
        self.grab_undo_loc = None
        self.start_edge_undo = None
        self.end_edge_undo = None
        
        self.mouse = (None, None)
        
        #keep up with these to show user
        self.bad_segments = []
        self.split = False
        self.face_seed = None
    
    def reset_vars(self):
        '''
        TODOD, parallel workflow will make this obsolete
        '''
        self.cyclic = False  #for cuts entirely within the mesh
        self.start_edge = None #for cuts ending on non man edges
        self.end_edge = None  #for cuts ending on non man edges
        
        self.pts = []  #world points
        self.cut_pts = []  #local points
        self.normals = []
        self.face_map = []
        self.face_changes = []
        self.new_cos = []
        self.ed_map = []
        
        self.face_chain = set()  #all faces crossed by the cut curve
                
        self.selected = -1
        self.hovered = [None, -1]
        
        self.grab_undo_loc = None
        self.mouse = (None, None)
        
        #keep up with these to show user
        self.bad_segments = []
        self.face_seed = None
        
    def grab_initiate(self):
        if self.selected != -1:
            self.grab_undo_loc = self.pts[self.selected]
            self.start_edge_undo = self.start_edge
            self.end_edge_undo = self.end_edge
            return True
        else:
            return False
       
    def grab_mouse_move(self,context,x,y):
        region = context.region
        rv3d = context.region_data
        coord = x, y
        view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        ray_target = ray_origin + (view_vector * 1000)

        mx = self.cut_ob.matrix_world
        imx = mx.inverted()

        if bversion() < '002.077.000':
            loc, no, face_ind = self.cut_ob.ray_cast(imx * ray_origin, imx * ray_target)
            if face_ind == -1: 
                self.grab_cancel()
                return
        else:
            res, loc, no, face_ind = self.cut_ob.ray_cast(imx * ray_origin, imx * ray_target - imx * ray_origin)
        
            if not res:
                self.grab_cancel()
                return
            
        #check if first or end point and it's a non man edge!   
        if self.selected == 0 and self.start_edge or self.selected == (len(self.pts) -1) and self.end_edge:
        
            co3d, index, dist = self.kd.find(mx * loc)

            #get the actual non man vert from original list
            close_bmvert = self.bme.verts[self.non_man_bmverts[index]] #stupid mapping, unreadable, terrible, fix this, because can't keep a list of actual bmverts
            close_eds = [ed for ed in close_bmvert.link_edges if not ed.is_manifold]
            loc3d_reg2D = view3d_utils.location_3d_to_region_2d
            
            if len(close_eds) != 2:
                self.grab_cancel()
                return
                
            bm0 = close_eds[0].other_vert(close_bmvert)
            bm1 = close_eds[1].other_vert(close_bmvert)
        
            a0 = bm0.co
            b   = close_bmvert.co
            a1  = bm1.co 
            
            inter_0, d0 = intersect_point_line(loc, a0, b)
            inter_1, d1 = intersect_point_line(loc, a1, b)
            
            screen_0 = loc3d_reg2D(region, rv3d, mx * inter_0)
            screen_1 = loc3d_reg2D(region, rv3d, mx * inter_1)
            screen_v = loc3d_reg2D(region, rv3d, mx * b)
            
            screen_d0 = (self.mouse - screen_0).length
            screen_d1 = (self.mouse - screen_1).length
            screen_dv = (self.mouse - screen_v).length
            
            if 0 < d0 <= 1 and screen_d0 < 60:
                ed, pt = close_eds[0], inter_0
                
            elif 0 < d1 <= 1 and screen_d1 < 60:
                ed, pt = close_eds[1], inter_1
                
            elif screen_dv < 60:
                if abs(d0) < abs(d1):
                    ed, pt = close_eds[0], b
                    
                else:
                    ed, pt = close_eds[1], b
                    
            else:
                self.grab_cancel()
                return
            
            if self.selected == 0:
                self.start_edge = ed
            else:
                self.end_edge = ed
            
            self.pts[self.selected] = mx * pt
            self.cut_pts[self.selected] = pt
            self.normals[self.selected] = view_vector
            self.face_map[self.selected] = ed.link_faces[0].index             
        else:
            self.pts[self.selected] = mx * loc
            self.cut_pts[self.selected] = loc
            self.normals[self.selected] = view_vector
            self.face_map[self.selected] = face_ind
        
    def grab_cancel(self):
        self.pts[self.selected] = self.grab_undo_loc
        self.start_edge = self.start_edge_undo
        self.end_edge = self.end_edge_undo
        return
    
    def grab_confirm(self):
        self.grab_undo_loc = None
        self.start_edge_undo = None
        self.end_edge_undo = None
        return
               
    def click_add_point(self,context,x,y):
        '''
        x,y = event.mouse_region_x, event.mouse_region_y
        
        this will add a point into the bezier curve or
        close the curve into a cyclic curve
        '''
        region = context.region
        rv3d = context.region_data
        coord = x, y
        view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        ray_target = ray_origin + (view_vector * 1000)
        mx = self.cut_ob.matrix_world
        imx = mx.inverted()
    
        if bversion() < '002.077.000':
            loc, no, face_ind = self.cut_ob.ray_cast(imx * ray_origin, imx * ray_target)
            if face_ind == -1: 
                self.selected = -1
                return
        else:
            res, loc, no, face_ind = self.cut_ob.ray_cast(imx * ray_origin, imx * ray_target - imx * ray_origin)
        
            if not res:
                self.selected = -1
                return
            
        if self.hovered[0] and 'NON_MAN' in self.hovered[0]:
            
            if self.cyclic:
                self.selected = -1
                return
            
            ed, wrld_loc = self.hovered[1]
            
            if len(self.pts) == 0:
                self.start_edge = ed
            elif len(self.pts) and not self.start_edge:
                self.selected = -1
                return
            elif len(self.pts) and self.start_edge:
                self.end_edge = ed
                
            self.pts += [wrld_loc] 
            self.cut_pts += [imx * wrld_loc]
            #self.cut_pts += [loc]
            self.face_map += [ed.link_faces[0].index]
            self.normals += [view_vector]
            self.selected = len(self.pts) -1
        
        if self.hovered[0] == None and not self.end_edge:  #adding in a new point at end
            self.pts += [mx * loc]
            self.cut_pts += [loc]
            #self.normals += [no]
            self.normals += [view_vector] #try this, because fase normals are difficult
            self.face_map += [face_ind]
            self.selected = len(self.pts) -1
                
        if self.hovered[0] == 'POINT':
            self.selected = self.hovered[1]
            if self.hovered[1] == 0 and not self.start_edge:  #clicked on first bpt, close loop
                self.cyclic = self.cyclic == False
            return
         
        elif self.hovered[0] == 'EDGE':  #cut in a new point
            self.pts.insert(self.hovered[1]+1, mx * loc)
            self.cut_pts.insert(self.hovered[1]+1, loc)
            self.normals.insert(self.hovered[1]+1, view_vector)
            self.face_map.insert(self.hovered[1]+1, face_ind)
            self.selected = self.hovered[1] + 1
            return
    
    def click_delete_point(self, mode = 'mouse'):
        if mode == 'mouse':
            if not self.hovered[0] == 'POINT': return
            self.pts.pop(self.hovered[1])
            self.cut_pts.pop(self.hovered[1])
            self.normals.pop(self.hovered[1])
            self.face_map.pop(self.hovered[1])
        
        else:
            if self.selected == -1: return
            self.pts.pop(self.selected)
            self.cut_pts.pop(self.selected)
            self.normals.pop(self.selected)
            self.face_map.pop(self.selected)

    
    def hover_non_man(self,context,x,y):
        region = context.region
        rv3d = context.region_data
        coord = x, y
        self.mouse = Vector((x, y))
        
        loc3d_reg2D = view3d_utils.location_3d_to_region_2d
        
        view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        ray_target = ray_origin + (view_vector * 1000)
        mx = self.cut_ob.matrix_world
        imx = mx.inverted()
        if bversion() < '002.077.000':
            loc, no, face_ind = self.cut_ob.ray_cast(imx * ray_origin, imx * ray_target)
            
        else:
            res, loc, no, face_ind = self.cut_ob.ray_cast(imx * ray_origin, imx * ray_target - imx * ray_origin)
        
         
        
        if len(self.non_man_points):
            co3d, index, dist = self.kd.find(mx * loc)

            #get the actual non man vert from original list
            close_bmvert = self.bme.verts[self.non_man_bmverts[index]] #stupid mapping, unreadable, terrible, fix this, because can't keep a list of actual bmverts
            close_eds = [ed for ed in close_bmvert.link_edges if not ed.is_manifold]
            if len(close_eds) == 2:
                bm0 = close_eds[0].other_vert(close_bmvert)
                bm1 = close_eds[1].other_vert(close_bmvert)
            
                a0 = bm0.co
                b   = close_bmvert.co
                a1  = bm1.co 
                
                inter_0, d0 = intersect_point_line(loc, a0, b)
                inter_1, d1 = intersect_point_line(loc, a1, b)
                
                screen_0 = loc3d_reg2D(region, rv3d, mx * inter_0)
                screen_1 = loc3d_reg2D(region, rv3d, mx * inter_1)
                screen_v = loc3d_reg2D(region, rv3d, mx * b)
                
                if not screen_0 and screen_1 and screen_v:
                    return
                screen_d0 = (self.mouse - screen_0).length
                screen_d1 = (self.mouse - screen_1).length
                screen_dv = (self.mouse - screen_v).length
                
                if 0 < d0 <= 1 and screen_d0 < 30:
                    self.hovered = ['NON_MAN_ED', (close_eds[0], mx*inter_0)]
                    return
                elif 0 < d1 <= 1 and screen_d1 < 30:
                    self.hovered = ['NON_MAN_ED', (close_eds[1], mx*inter_1)]
                    return
                elif screen_dv < 30:
                    if abs(d0) < abs(d1):
                        self.hovered = ['NON_MAN_VERT', (close_eds[0], mx*b)]
                        return
                    else:
                        self.hovered = ['NON_MAN_VERT', (close_eds[1], mx*b)]
                        return
                    
    def hover(self,context,x,y):
        '''
        hovering happens in mixed 3d and screen space, 20 pixels thresh for points, 30 for edges
        40 for non_man
        '''
        region = context.region
        rv3d = context.region_data
        coord = x, y
        self.mouse = Vector((x, y))
        
        loc3d_reg2D = view3d_utils.location_3d_to_region_2d
        
        
        view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        ray_target = ray_origin + (view_vector * 1000)
        mx = self.cut_ob.matrix_world
        imx = mx.inverted()
        #loc, no, face_ind = self.cut_ob.ray_cast(imx * ray_origin, imx * ray_target)
        
        
        if len(self.pts) == 0:
            self.hovered = [None, -1]
            self.hover_non_man(context, x, y)
            return

        def dist(v):
            diff = v - Vector((x,y))
            return diff.length
        
        
        screen_pts =  [loc3d_reg2D(context.region, context.space_data.region_3d, pt) for pt in self.pts]
        closest_point = min(screen_pts, key = dist)
        
        if (closest_point - Vector((x,y))).length  < 20:
            self.hovered = ['POINT',screen_pts.index(closest_point)]
            return

        if len(self.pts) < 2: 
            self.hovered = [None, -1]
            return
                    
        for i in range(0,len(self.pts)):   
            a  = loc3d_reg2D(context.region, context.space_data.region_3d,self.pts[i])
            next = (i + 1) % len(self.pts)
            b = loc3d_reg2D(context.region, context.space_data.region_3d,self.pts[next])
            
            if b == 0 and not self.cyclic:
                self.hovered = [None, -1]
                return
            
            if a and b:
                intersect = intersect_point_line(Vector((x,y)).to_3d(), a.to_3d(),b.to_3d()) 
                if intersect:
                    dist = (intersect[0].to_2d() - Vector((x,y))).length_squared
                    bound = intersect[1]
                    if (dist < 400) and (bound < 1) and (bound > 0):
                        self.hovered = ['EDGE',i]
                        return
                    
        self.hovered = [None, -1]
        self.hover_non_man(context, x, y)  #todo, optimize because double ray cast per mouse move!
          
    def snap_poly_line(self):
        '''
        only needed if processing an outside mesh
        '''
        locs = []
        self.face_map = []
        #self.normals = [] for now, leave normals from view direction
        self.face_changes = []
        self.face_groups = dict()
        
        mx = self.cut_ob.matrix_world
        imx = mx.inverted()
        
        last_face_ind = None
        for i, v in enumerate(self.pts):
            if bversion() < '002.077.000':
                loc, no, ind, d = self.bvh.find(imx * v)
            else:
                loc, no, ind, d = self.bvh.find_nearest(imx * v)
                
            self.face_map.append(ind)
            locs.append(loc)
            
            if i == 0:
                last_face_ind = ind
                group = [i]
                print('first face group index')
                print((ind,group))
                
            if ind != last_face_ind: #we have found a new face
                self.face_changes.append(i-1)
                
                if last_face_ind not in self.face_groups: #previous face has not been mapped before
                    self.face_groups[last_face_ind] = group
                    last_face_ind = ind
                    group = [i]
                else:
                    print('group already in dictionary')
                    exising_group = self.face_groups[last_face_ind]
                    if 0 not in exising_group:
                        print('LOOKS LIKE WE CROSSED SAME FACE MULTIPLE TIMES')
                        print('YOUR PROGRAMMER IS NOT SMART ENOUGH FOR THIS')
                    self.face_groups[last_face_ind] = group + exising_group #we have wrapped, add this group to the old
            
            else:
                if i != 0:
                    group += [i]
            #double check for the last point
            if i == len(self.pts) - 1:  #
                if ind != self.face_map[0]:  #we didn't click on the same face we started on
                    
                    if self.cyclic:
                        self.face_changes.append(i)
                        
                        
                    if ind not in self.face_groups:
                        print('final group not added to dictionary yet')
                        print((ind, group))
                        self.face_groups[ind] = group
                    
                    else:
                        print('group already in dictionary')
                        exising_group = self.face_groups[ind]
                        if 0 not in exising_group:
                            print('LOOKS LIKE WE CROSSED SAME FACE MULTIPLE TIMES')
                            print('YOUR PROGRAMMER IS NOT SMART ENOUGH FOR THIS')
                        self.face_groups[ind] = group + exising_group
                        
                else:
                    print('group already in dictionary')
                    exising_group = self.face_groups[ind]
                    if 0 not in exising_group:
                        print('LOOKS LIKE WE CROSSED SAME FACE MULTIPLE TIMES')
                        print('YOUR PROGRAMMER IS NOT SMART ENOUGH FOR THIS')
                    self.face_groups[ind] = group + exising_group
                              
        self.cut_pts = locs
        
        #clean up face groups if necessary
        #TODO, get smarter about not adding in these
        if not self.cyclic:
            
            
            
            if self.start_edge:
                s_ind = self.start_edge.link_faces[0].index
                if s_ind in self.face_groups:
                    v_group = self.face_groups[s_ind]
                    if len(v_group) == 1:
                        print('remove first face from face groups')
                        del self.face_groups[s_ind]
                    elif len(v_group) > 1:
                        print('remove first vert from first face group')
                        v_group.pop(0)
                        self.face_groups[s_ind] = v_group
            if self.end_edge:
                e_ind = self.end_edge.link_faces[0].index        
                if e_ind in self.face_groups:
                    v_group = self.face_groups[e_ind]
                    if len(v_group) == 1:
                        print('remove last face from face groups')
                        del self.face_groups[e_ind]
                    elif len(v_group) > 1:
                        print('remove last vert from last face group')
                        v_group.pop()
                        self.face_groups[e_ind] = v_group
        
        print('FACE GROUPS')
        print(self.face_groups)
 
    def preprocess_points(self):
        '''
        '''
        #self.normals = [] for now, leave normals from view direction
        self.face_changes = []
        self.face_groups = dict()
        last_face_ind = None
        for i, v in enumerate(self.pts):
            
            if i == 0:
                last_face_ind = self.face_map[i]
                group = [i]
                print('first face group index')
                print((self.face_map[i],group))
                
            if self.face_map[i] != last_face_ind: #we have found a new face
                self.face_changes.append(i-1)
                
                if last_face_ind not in self.face_groups: #previous face has not been mapped before
                    self.face_groups[last_face_ind] = group
                    last_face_ind = self.face_map[i]
                    group = [i]
                else:
                    print('group already in dictionary')
                    exising_group = self.face_groups[last_face_ind]
                    if 0 not in exising_group:
                        print('LOOKS LIKE WE CROSSED SAME FACE MULTIPLE TIMES')
                        print('YOUR PROGRAMMER IS NOT SMART ENOUGH FOR THIS')
                    self.face_groups[last_face_ind] = group + exising_group #we have wrapped, add this group to the old
            
            else:
                if i != 0:
                    group += [i]
            #double check for the last point
            if i == len(self.pts) - 1:  #
                if self.face_map[i] != self.face_map[0]:  #we didn't click on the same face we started on
                    
                    if self.cyclic:
                        self.face_changes.append(i)
                        
                        
                    if self.face_map[i] not in self.face_groups:
                        print('final group not added to dictionary yet')
                        print((self.face_map[i], group))
                        self.face_groups[self.face_map[i]] = group
                    
                    else:
                        print('group already in dictionary')
                        exising_group = self.face_groups[self.face_map[i]]
                        if 0 not in exising_group:
                            print('LOOKS LIKE WE CROSSED SAME FACE MULTIPLE TIMES')
                            print('YOUR PROGRAMMER IS NOT SMART ENOUGH FOR THIS')
                        self.face_groups[self.face_map[i]] = group + exising_group
                        
                else:
                    print('group already in dictionary')
                    exising_group = self.face_groups[self.face_map[i]]
                    if 0 not in exising_group:
                        print('LOOKS LIKE WE CROSSED SAME FACE MULTIPLE TIMES')
                        print('YOUR PROGRAMMER IS NOT SMART ENOUGH FOR THIS')
                    self.face_groups[self.face_map[i]] = group + exising_group
        
        #clean up face groups if necessary
        #TODO, get smarter about not adding in these
        if not self.cyclic:
            s_ind = self.start_edge.link_faces[0].index
            e_ind = self.end_edge.link_faces[0].index
            
            if s_ind in self.face_groups:
                v_group = self.face_groups[s_ind]
                if len(v_group) == 1:
                    print('remove first face from face groups')
                    del self.face_groups[s_ind]
                elif len(v_group) > 1:
                    print('remove first vert from first face group')
                    v_group.pop(0)
                    self.face_groups[s_ind] = v_group
                    
            if e_ind in self.face_groups:
                v_group = self.face_groups[e_ind]
                if len(v_group) == 1:
                    print('remove last face from face groups')
                    del self.face_groups[e_ind]
                elif len(v_group) > 1:
                    print('remove last vert from last face group')
                    v_group.pop()
                    self.face_groups[e_ind] = v_group
        
        print('FACE GROUPS')
        print(self.face_groups)
               
    def click_seed_select(self, context, x, y):
        
        region = context.region
        rv3d = context.region_data
        coord = x, y
        view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        ray_target = ray_origin + (view_vector * 1000)
        mx = self.cut_ob.matrix_world
        imx = mx.inverted()

        if bversion() < '002.077.000':
            loc, no, face_ind = self.cut_ob.ray_cast(imx * ray_origin, imx * ray_target)
            
        else:
            res, loc, no, face_ind = self.cut_ob.ray_cast(imx * ray_origin, imx * ray_target - imx * ray_origin)
        
            
        if face_ind != -1:
            self.face_seed = face_ind
            print('face selected!!')
            return True
            
        else:
            self.face_seed = None
            print('face not selected')
            return False
                     
    def make_cut(self):
        if self.split: return #already did this, no going back!
        mx = self.cut_ob.matrix_world
        imx = mx.inverted()
        print('\n')
        print('BEGIN CUT ON POLYLINE')
        
        self.new_cos = []
        self.ed_map = []
        
        self.face_chain = set()
        self.preprocess_points()
        self.bad_segments = []
        
        self.new_ed_face_map = dict()
        
        #print('there are %i cut points' % len(self.cut_pts))
        #print('there are %i face changes' % len(self.face_changes))

        for m, ind in enumerate(self.face_changes):

            print('m, IND')
            print((m,ind))
            
            if m == 0 and not self.cyclic:
                self.ed_map += [self.start_edge]
                #self.new_cos += [imx * self.cut_pts[0]]
                self.new_cos += [self.cut_pts[0]]
                
                
                #self.new_ed_face_map[0] = self.start_edge.link_faces[0].index
                
                #print('not cyclic...come back to me')
                #continue
            
            #n_p1 = (m + 1) % len(self.face_changes)
            #ind_p1 = self.face_changes[n_p1]

            n_p1 = (ind + 1) % len(self.cut_pts)
            ind_p1 = self.face_map[n_p1]
            #print('walk on edge pair %i, %i' % (m, n_p1))
            #print('original faces in mesh %i, %i' % (self.face_map[ind], self.face_map[ind_p1]))
            
            if n_p1 == 0 and not self.cyclic:
                print('not cyclic, we are done here')
                break
            
            
            f0 = self.bme.faces[self.face_map[ind]]
            #f1 = self.bme.faces[self.face_map[ind_p1]]
            f1 = self.bme.faces[self.face_map[n_p1]]
            
            no0 = self.normals[ind]
            #no1 = self.normals[ind_p1]
            no1 = self.normals[n_p1]
            
            surf_no = imx.to_3x3() * no0.lerp(no1, 0.5)  #must be a better way.
            
            #normal method 1
            #e_vec = self.cut_pts[ind_p1] - self.cut_pts[ind]
            e_vec = self.cut_pts[n_p1] - self.cut_pts[ind]
            
            #normal method 2
            #v0 = self.cut_pts[ind] - self.cut_pts[ind-1]
            #v0.normalize()
            #v1 = self.cut_pts[ind + 1] - self.cut_pts[ind]
            #v1.normalize()
            
            #ang = v0.angle(v1, 0)
            #if ang > 1 * math.pi/180:
            #    curve_no = v0.cross(v1)
            #    cut_no = e_vec.cross(curve_no)
                
            #else: #method 2 using surface normal
            cut_no = e_vec.cross(surf_no)
                
            #cut_pt = .5*self.cut_pts[ind_p1] + 0.5*self.cut_pts[ind]
            cut_pt = .5*self.cut_pts[n_p1] + 0.5*self.cut_pts[ind]
    
            #find the shared edge
            cross_ed = None
            for ed in f0.edges:
                if f1 in ed.link_faces:
                    cross_ed = ed
                    break
                
            #if no shared edge, need to cut across to the next face    
            if not cross_ed:
                if self.face_changes.index(ind) != 0:
                    p_face = self.bme.faces[self.face_map[ind-1]]
                else:
                    p_face = None
                
                vs = []
                epp = .0000000001
                use_limit = True
                attempts = 0
                while epp < .0001 and not len(vs) and attempts <= 5:
                    attempts += 1
                    vs, eds, eds_crossed, faces_crossed, error = path_between_2_points(self.bme, 
                                                             self.bvh,                                         
                                                             #self.cut_pts[ind], self.cut_pts[ind_p1],
                                                             self.cut_pts[ind], self.cut_pts[n_p1], 
                                                             max_tests = 10000, debug = True, 
                                                             prev_face = p_face,
                                                             use_limit = use_limit)
                    if len(vs) and error == 'LIMIT_SET':
                        vs = []
                        use_limit = False
                        print('Limit was too limiting, relaxing that consideration')
                        
                    elif len(vs) == 0 and error == 'EPSILON':
                        print('Epsilon was too small, relaxing epsilon')
                        epp *= 10
                    elif len(vs) == 0 and error:
                        print("too bad, couldn't adjust")
                        break
                
                if not len(vs):
                    print('\n')
                    print('CUTTING METHOD')
                    
                    vs = []
                    epp = .00000001
                    use_limit = True
                    attempts = 0
                    while epp < .0001 and not len(vs) and attempts <= 10:
                        attempts += 1
                        vs, eds, eds_crossed, faces_crossed, error = cross_section_2seeds_ver1(self.bme,
                                                        cut_pt, cut_no, 
                                                        f0.index,self.cut_pts[ind],
                                                        #f1.index, self.cut_pts[ind_p1],
                                                        f1.index, self.cut_pts[n_p1],
                                                        max_tests = 10000, debug = True, prev_face = p_face,
                                                        epsilon = epp)
                        if len(vs) and error == 'LIMIT_SET':
                            vs = []
                            use_limit = False
                        elif len(vs) == 0 and error == 'EPSILON':
                            epp *= 10
                        elif len(vs) == 0 and error:
                            print('too bad, couldnt adjust')
                            break
                        
                if len(vs):
                    #do this before we add in any points
                    if len(self.new_cos) > 1:
                        self.new_ed_face_map[len(self.new_cos)-1] = self.face_map[ind]
                        
                    elif len(self.new_cos) == 1 and m ==1 and not self.cyclic:
                        self.new_ed_face_map[len(self.new_cos)-1] = self.face_map[ind]
                    for v,ed in zip(vs,eds_crossed):
                        self.new_cos.append(v)
                        self.ed_map.append(ed)
                       
                    self.face_chain.update(faces_crossed)
                        
                    if ind == len(self.face_changes) - 1 and self.cyclic:
                        print('This is the loop closing segment.  %i' % len(vs))
                else:
                    self.bad_segments.append(ind)
                    print('cut failure!!!')
                
                if ((not self.cyclic) and
                    m == (len(self.face_changes) - 1) and
                    self.end_edge.link_faces[0].index == f1.index
                    ):
                
                    print('end to the non manifold edge while walking multiple faces')
                    self.ed_map += [self.end_edge]
                    self.new_cos += [self.cut_pts[-1]]
                    self.new_ed_face_map[len(self.new_cos)-2] = f1.index
                
                continue
            
            p0 = cross_ed.verts[0].co
            p1 = cross_ed.verts[1].co
            v = intersect_line_plane(p0,p1,cut_pt,cut_no)
            if v:
                self.new_cos.append(v)
                self.ed_map.append(cross_ed)
                if len(self.new_cos) > 1:
                    self.new_ed_face_map[len(self.new_cos)-2] = self.face_map[ind]
            
            if ((not self.cyclic) and
                m == (len(self.face_changes) - 1) and
                self.end_edge.link_faces[0].index == f1.index
                ):
                
                print('end to the non manifold edge jumping single face')
                self.ed_map += [self.end_edge]
                self.new_cos += [self.cut_pts[-1]]
                self.new_ed_face_map[len(self.new_cos)-2] = f1.index
                          
    def calc_ed_pcts(self):
        '''
        not used utnil bmesh.ops uses the percentage index
        '''
        if not len(self.ed_map) and len(self.new_cos): return
        
        for v, ed in zip(self.new_cos, self.ed_map):
            
            v0 = ed.verts[0].co
            v1 = ed.verts[1].co
            
            ed_vec = v1 - v0
            L = ed_vec.length
            
            cut_vec = v - v0
            l = cut_vec.length
            
            pct = l/L
            
    def find_select_inner_faces(self):
        if not self.face_seed: return
        if len(self.bad_segments): return
        f0 = self.bme.faces[self.face_seed]
        inner_faces = flood_selection_by_verts(self.bme, set(), f0, max_iters=1000)
        
        for f in self.bme.faces:
            f.select_set(False)
        for f in inner_faces:
            f.select_set(True)
                 
    def confirm_cut_to_mesh(self):
        
        if len(self.bad_segments): return  #can't do this with bad segments!!
        
        if self.split: return #already split! no going back
        new_verts = []
        new_bmverts = []
        new_edges = []
        
        self.calc_ed_pcts()
        ed_set = set(self.ed_map)
        if len(self.ed_map) != len(set(self.ed_map)):  #doubles in ed dictionary
            
            print('doubles in the edges crossed!!')
            print('ideally, this will turn  the face into an ngon for simplicity sake')
            seen = set()
            new_eds = []
            new_cos = []
            removals = []

            for i, ed in enumerate(self.ed_map):
                if ed not in seen and not seen.add(ed):
                    new_eds += [ed]
                    new_cos += [self.new_cos[i]]
                else:
                    removals.append(ed.index)
            
            print('these are the edge indices wich were removed to be only cut once ')
            print(removals)
            
            self.ed_map = new_eds
            self.new_cos = new_cos
            
            
        start = time.time()
        print('bisecting edges')
        geom =  bmesh.ops.bisect_edges(self.bme, edges = self.ed_map,cuts = 1,edge_percents = {})
        new_bmverts = [ele for ele in geom['geom_split'] if isinstance(ele, bmesh.types.BMVert)]

        #assigne new verts their locations
        for v, co in zip(new_bmverts, self.new_cos):
            v.co = co
        
        finish = time.time()
        print('Took %f seconds' % (finish-start))
        start = finish
        ed_geom = bmesh.ops.connect_verts(self.bme, verts = new_bmverts, faces_exclude = [], check_degenerate = False)
        new_edges = ed_geom['edges']
        if self.cyclic:
            new_edges.reverse()
            new_edges = new_edges[1:] + [new_edges[0]]
            
        finish = time.time()
        print('took %f seconds' % (finish-start))
        
        start = finish
        
        print('subdividing edges which need subdivision')
        
       
        self.bme.verts.ensure_lookup_table()
        self.bme.edges.ensure_lookup_table()
        
        
        print('subdividing new edges where needed')
        newer_edges = []
        unchanged_edges = []
        for i, edge in enumerate(new_edges):
            if i in self.new_ed_face_map:
                print('%i is in the new ed face map' % i)
                face_ind = self.new_ed_face_map[i]
                print('edge %i is cross face %i' % (i, face_ind))
                if face_ind not in self.face_groups:
                    print('unfortunately, it is not in the face groups')
                    unchanged_edges += [edge]
                    continue
                #these are the user polyine vertex indices
                vert_inds = self.face_groups[face_ind]
                
                if len(vert_inds):
                    print('there are %i user drawn poly points on the face' % len(vert_inds))
                    geom =  bmesh.ops.bisect_edges(self.bme, edges = [edge],cuts = len(vert_inds),edge_percents = {})
                    new_bmverts = [ele for ele in geom['geom_split'] if isinstance(ele, bmesh.types.BMVert)]
                    newer_edges += [ele for ele in geom['geom_split'] if isinstance(ele, bmesh.types.BMEdge)]
                    #for n, bv in enumerate(new_bmverts):
                    #    bv.co = self.cut_pts[vert_inds[n]]
        
                    self.bme.verts.ensure_lookup_table()
                    self.bme.edges.ensure_lookup_table()
                    
            else:
                #print('%i edge crosses a face in the walking algo, unchanged' % i)
                unchanged_edges += [edge]
        
        print('splitting old edges')
        self.bme.verts.ensure_lookup_table()
        self.bme.edges.ensure_lookup_table() 
        bmesh.ops.split_edges(self.bme, edges = unchanged_edges, verts = [], use_verts = False)
        
        print('splitting newer edges')
        self.bme.verts.ensure_lookup_table()
        self.bme.edges.ensure_lookup_table() 
        bmesh.ops.split_edges(self.bme, edges = newer_edges, verts = [], use_verts = False) 
        
        self.bme.verts.ensure_lookup_table()
        self.bme.edges.ensure_lookup_table()
        self.bme.faces.ensure_lookup_table()
        finish = time.time()
        print('took %f seconds' % (finish-start))
        self.split = True
        
    def split_geometry(self):
        if not (self.split and self.face_seed): return
        
        self.find_select_inner_faces()
        
        self.bme.to_mesh(self.cut_ob.data)
        bpy.ops.object.mode_set(mode ='EDIT')
        bpy.ops.mesh.separate(type = 'SELECTED')
        bpy.ops.object.mode_set(mode = 'OBJECT')
        
        #EXPENSIVE!!
        #self.bme = bmesh.new()
        #self.bme.from_mesh(self.cut_ob.data)
        #self.bme.verts.ensure_lookup_table()
        #self.bme.edges.ensure_lookup_table()
        #self.bme.faces.ensure_lookup_table()
        #self.bvh = BVHTree.FromBMesh(self.bme)
        #self.reset_vars()
          
    def replace_segment(self,start,end,new_locs):
        #http://stackoverflow.com/questions/497426/deleting-multiple-elements-from-a-list
        print('replace')
        return
                
    def draw(self,context):
        
        
        if self.hovered[0] in {'NON_MAN_ED', 'NON_MAN_VERT'}:
            ed, pt = self.hovered[1]
            common_drawing.draw_3d_points(context,[pt], 6, color = (.3,1,.3,1))
                    
        if len(self.pts) == 0: return
        
        if self.cyclic and len(self.pts):
            common_drawing.draw_polyline_from_3dpoints(context, self.pts + [self.pts[0]], (.1,.2,1,.8), 2, 'GL_LINE_STRIP')
        
        else:
            common_drawing.draw_polyline_from_3dpoints(context, self.pts, (.1,.2,1,.8), 2, 'GL_LINE')
        
        if self.ui_type != 'DENSE_POLY':    
            common_drawing.draw_3d_points(context,self.pts, 3)
            common_drawing.draw_3d_points(context,[self.pts[0]], 8, color = (1,1,0,1))
            
        else:
            common_drawing.draw_3d_points(context,self.pts, 4, color = (1,1,1,1)) 
            common_drawing.draw_3d_points(context,[self.pts[0]], 4, color = (1,1,0,1))
        
        
        if self.selected != -1 and len(self.pts) >= self.selected + 1:
            common_drawing.draw_3d_points(context,[self.pts[self.selected]], 8, color = (0,1,1,1))
                
        if self.hovered[0] == 'POINT':
            common_drawing.draw_3d_points(context,[self.pts[self.hovered[1]]], 8, color = (0,1,0,1))
     
        elif self.hovered[0] == 'EDGE':
            loc3d_reg2D = view3d_utils.location_3d_to_region_2d
            a = loc3d_reg2D(context.region, context.space_data.region_3d, self.pts[self.hovered[1]])
            next = (self.hovered[1] + 1) % len(self.pts)
            b = loc3d_reg2D(context.region, context.space_data.region_3d, self.pts[next])
            common_drawing.draw_polyline_from_points(context, [a,self.mouse, b], (0,.2,.2,.5), 2,"GL_LINE_STRIP")  

        if self.face_seed:
            #TODO direct bmesh face drawing util
            vs = self.bme.faces[self.face_seed].verts
            common_drawing.draw_3d_points(context,[self.cut_ob.matrix_world * v.co for v in vs], 4, color = (1,1,.1,1))
            
            
        if len(self.new_cos):
            if self.split: 
                color = (.1, .1, .8, 1)
            else: 
                color = (.2,.5,.2,1)
            common_drawing.draw_3d_points(context,[self.cut_ob.matrix_world * v for v in self.new_cos], 6, color = color)
        if len(self.bad_segments):
            for ind in self.bad_segments:
                m = self.face_changes.index(ind)
                m_p1 = (m + 1) % len(self.face_changes)
                ind_p1 = self.face_changes[m_p1]
                common_drawing.draw_polyline_from_3dpoints(context, [self.pts[ind], self.pts[ind_p1]], (1,.1,.1,1), 4, 'GL_LINE')


class PolyCutPoint(object):
    
    def __init__(self,co):
        self.co = co
        
        self.no = None
        self.face = None
        self.face_region = set()
        
    def find_closest_non_manifold(self):
        return None
    
class NonManifoldEndpoint(object):
    
    def __init__(self,co, ed):
        if len(ed.link_faces) != 1:
            return None
        
        self.co = co
        self.ed = ed
        self.face = ed.link_faces[0]
        
    
        
        
        
        