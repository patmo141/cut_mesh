'''
Created on Oct 8, 2015

@author: Patrick,  

#TODO Micah Needs to add email and stuff in here
License, copyright all that
This code has an ineresting peidgree
Inspired by contours Patrick Moore for CGCookie
Improved by using some PolyStrips concepts Jon Denning @CGCookie and Taylor University
refreshed again as part of summer practicum by Micah Stewart Summer 2018, Taylor University + Impulse Dental Technologies LLC
reworked again by Patrick Moore, Micah Stewart and Jon Denning Fall 2018 
'''
import time
import math

import bpy
import bmesh
import bgl

from collections import defaultdict
from mathutils import Vector, Matrix, Color, kdtree
from mathutils.bvhtree import BVHTree
from mathutils.geometry import intersect_point_line, intersect_line_plane
from bpy_extras import view3d_utils

from ..bmesh_fns import grow_selection_to_find_face, flood_selection_faces, edge_loops_from_bmedges_old, flood_selection_by_verts, flood_selection_edge_loop, ensure_lookup
from ..cut_algorithms import cross_section_2seeds_ver1, path_between_2_points
from .. import common_drawing
from ..common.rays import get_view_ray_data, ray_cast
from ..common.blender import bversion
from ..common.utils import get_matrices
from ..common.bezier import CubicBezier, CubicBezierSpline
from ..common.shaders import circleShader

class PolyLineKnife(object):
    '''
    A class which manages user placed points on an object to create a
    poly_line, adapted to the objects surface.
    '''
    def __init__(self,context, cut_object, ui_type = 'DENSE_POLY'):
        self.source_ob = cut_object
        self.bme = bmesh.new()
        self.bme.from_mesh(cut_object.data)
        ensure_lookup(self.bme)
        self.bvh = BVHTree.FromBMesh(self.bme)
        self.mx, self.imx = get_matrices(self.source_ob)

        self.input_points = InputPointMap()

        self.cyclic = False
        self.selected = -1
        self.hovered = [None, -1]
        self.snap_element = None
        self.start_edge = None
        self.connect_element = None
        self.end_edge = None
        self.face_changes = []
        self.face_groups = dict()
        self.face_chain = set()

        self.new_ed_face_map = dict()  #maps face index in bmesh to new edges created by bisecting
        self.ed_cross_map = EdgeIntersectionMap()
        self.non_man_eds = [ed.index for ed in self.bme.edges if not ed.is_manifold]
        self.non_man_ed_loops = edge_loops_from_bmedges_old(self.bme, self.non_man_eds)
        self.non_man_points = []
        self.non_man_bmverts = []
        for loop in self.non_man_ed_loops:
            self.non_man_points += [self.source_ob.matrix_world * self.bme.verts[ind].co for ind in loop]
            self.non_man_bmverts += [self.bme.verts[ind].index for ind in loop]
        if len(self.non_man_points):
            kd = kdtree.KDTree(len(self.non_man_points))
            for i, v in enumerate(self.non_man_points):
                kd.insert(v, i)
            kd.balance()
            self.kd = kd
        else:
            self.kd = None

        if ui_type not in {'SPARSE_POLY','DENSE_POLY', 'BEZIER'}:
            self.ui_type = 'SPARSE_POLY'
        else:
            self.ui_type = ui_type

        self.grab_point = None
        self.grab_undo_loc = None
        self.start_edge_undo = None
        self.end_edge_undo = None

        #keep up with these to show user
        self.bad_segments = []
        self.split = False
        self.perimeter_edges = []
        self.inner_faces = []
        self.face_seed = None

    def has_points(self): return self.input_points.num_points > 0
    def num_points(self): return self.input_points.num_points
    has_points = property(has_points)
    num_points = property(num_points)

    #################################
    #### polyline data structure ####

    def reset_vars(self):
        '''
        Resets variables..
        TODOD, parallel workflow will make this obsolete
        '''
        self.cyclic = False  #for cuts entirely within the mesh
        self.start_edge = None #for cuts ending on non man edges
        self.end_edge = None  #for cuts ending on non man edges

        self.input_points = InputPointMap()

        self.face_changes = []
        self.ed_cross_map = EdgeIntersectionMap()

        self.face_chain = set()  #all faces crossed by the cut curve

        self.selected = None
        self.hovered = [None, -1]

        self.grab_undo_loc = None

        #keep up with these to show user
        self.bad_segments = []
        self.face_seed = None

    def toggle_cyclic(self): self.cyclic = self.cyclic == False

    def click_add_point(self,context,mouse_loc):
        '''
        this will add a point into the trim line
        close the curve into a cyclic curve
        
        #Need to get smarter about closing the loop
        '''
        def none_selected(): self.selected = None # use in self.ray_cast()
        
        view_vector, ray_origin, ray_target= get_view_ray_data(context,mouse_loc)
        loc, no, face_ind = ray_cast(self.source_ob, self.imx, ray_origin, ray_target, none_selected)
        if loc == None: return

        if self.hovered[0] and 'NON_MAN' in self.hovered[0]:
            
            
            bmed, wrld_loc = self.hovered[1] # hovered[1] is tuple (BMesh Element, location?)
            ip1 = self.closest_endpoint(wrld_loc)
            
            
            self.input_points.add(wrld_loc, self.imx * wrld_loc, view_vector, bmed.link_faces[0].index)
            self.selected = self.input_points.points[-1]
            self.selected.seed_geom = bmed

            if ip1:
                seg = InputSegment(self.selected, ip1)
                self.input_points.segments.append(seg)
                seg.pre_vis_cut(self.bme, self.bvh, self.mx, self.imx)
        
        elif (self.hovered[0] == None) and (self.snap_element == None):  #adding in a new point at end, may need to specify closest unlinked vs append and do some previs
            print('adding in a point')
            closest_endpoint = self.closest_endpoint(self.mx * loc)
            print(closest_endpoint)

            self.input_points.add(self.mx * loc, loc, view_vector, face_ind)
            self.selected = self.input_points.points[-1]

            if closest_endpoint:
                seg = InputSegment(closest_endpoint, self.selected)
                self.input_points.segments.append(seg)
                seg.pre_vis_cut(self.bme, self.bvh, self.mx, self.imx)

        elif self.hovered[0] == None and self.snap_element != None:  #adding in a new point at end, may need to specify closest unlinked vs append and do some previs
            
            print('This is the close loop scenario')
            closest_endpoints = self.closest_endpoints(self.snap_element.world_loc, 2)
            
            print('these are the 2 closest endpoints, one should be snap element itself')
            print(closest_endpoints)
            if closest_endpoints == None:
                #we are not quite hovered but in snap territory
                return
            
            if len(closest_endpoints) != 2:
                print('len of closest endpoints not 2')
                return
            
            
            seg = InputSegment(closest_endpoints[0], closest_endpoints[1])
            self.input_points.segments.append(seg)
            seg.pre_vis_cut(self.bme, self.bvh, self.mx, self.imx)
            
        elif self.hovered[0] == 'POINT':
            self.selected = self.hovered[1]

        elif self.hovered[0] == 'EDGE':  #TODO, actually make InputSegment as hovered
            
            #this looks like a TOOLs kind of operation
            point = InputPoint(self.mx * loc, loc, view_vector, face_ind)
            old_seg = self.hovered[1]
            new_seg0, new_seg1 = old_seg.insert_point(point)
            new_seg0.pre_vis_cut(self.bme, self.bvh, self.mx, self.imx)
            new_seg1.pre_vis_cut(self.bme, self.bvh, self.mx, self.imx)
            self.input_points.segments += [new_seg0, new_seg1]
            self.input_points.points.append(point)
            self.input_points.segments.remove(old_seg)
            self.selected = point

    
    def closest_endpoints(self, pt3d, n_points):
        #in our application, at most there will be 100 endpoints?
        #no need for accel structure here
        n_points = max(0, n_points)
        
        endpoints = [ip for ip in self.input_points.points if ip.is_endpoint] #TODO self.endpoints?
        
        if len(endpoints) == 0: return None
        n_points = min(n_points, len(endpoints))
        
        
        def dist3d(point):
            return (point.world_loc - pt3d).length
        
        endpoints.sort(key = dist3d)
        
        return endpoints[0:n_points+1]
    
    def closest_endpoint(self, pt3d):
         
        def dist3d(point):
            return (point.world_loc - pt3d).length
        
        endpoints = [ip for ip in self.input_points.points if ip.is_endpoint] 
        if len(endpoints) == 0: return None
        
        return min(endpoints, key = dist3d)
    
    
    def interpolate_input_point_pair(self, p0, p1, factor):
        '''
        will return a linear interpolation of this point with other
        needs to be at this level, because snapping to the source object is critical
        
        '''
        assert factor >= 0.0
        assert factor <= 1.0
        
        new_pt = p0.duplicate()
        
        new_pt.set_world_loc(factor * p0.world_loc + (1-factor)*p1.world_loc)
        new_pt.set_local_loc(factor * p0.local_loc + (1-factor)*p1.local_loc)
        new_pt.view = factor * p0.view + (1-factor) * p1.view
        new_pt.view.normalize()
        
        #need to snap it and find face index
        loc, no, ind, d = self.bvh.find_nearest(new_pt.local_loc)
        
        #view stays the same
        new_pt.set_face_ind(ind)
        new_pt.set_local_loc(loc)
        new_pt.set_world_loc(self.mx * loc)
    
        return new_pt
        
        
    def re_tesselate_segment(self, ip_start, ip_end, tesselation_mode = 'LINEAR', clamp_existings = True):
        '''
        High level function which allows re-tesselation of segments with various options
        
        Eg:  Linear, error_based, step_sized, CubicSpline
        '''
        
        return None
    
    def linear_re_tesselate_segment(self, ip_start, ip_end, res):
        '''
        ip_start - InputPoint
        ip_end = InputPoint
        res - Float (target distance step between points)
        
        
        re tesesselates all segments between ip_start and ip_end
        
        will preserve the original input points, and only add new input points
        between them as necessary
        
        It is important that ip_start to ip_end indicates the direction desired
        for the segment to be re_tesselated.
        
        for example if ip_start is at index 5 and ip_end is at index 2.
        Input points 5,6,7...N, 0,1 2. will be retesselated
        
        However if ip_start is at index 2 and ip_end is at index 5
        InputPoints 2,3,4,5 will be re_tesslated
        
        re_teseselate(ip5, ip2) will not be same as re_tesslate(ip2, ip5)
        
        '''
        assert ip_start in self.input_points.points
        assert ip_end in self.input_points.points
        
        ind_start = self.input_points.points.index(ip_start)
        ind_end = self.input_points.points.index(ip_end)
        
        print('Am I considered cyclic yet?')
        print(self.cyclic)
        print(ind_start, ind_end)
        
        if ind_start > ind_end and self.cyclic:
            points = self.input_points.points[ind_start:] + self.input_points.points[:ind_end]
            
        elif ind_start > ind_end and not self.cyclic:
            ind_start, ind_end = ind_end, ind_start
            points = self.input_points.points[ind_start:ind_end+1]  #need to get the last point
        else:
            points = self.input_points.points[ind_start:ind_end+1]  #need to get the last point
        
        
        new_points = []
        for i in range(0, len(points) - 1):
            L = (points[i+1].world_loc - points[i].world_loc).length
            n_steps = math.floor(L/res)
            
            if n_steps == 0: #don't loose points at closer resolution
                new_points += [points[i].duplicate()]
                
            for n in range(n_steps):
                factor = n/n_steps
                new_points += [self.interpolate_input_point_pair(points[i+1], points[i], factor)]
                
        new_points += [points[-1]]  #get the final point on there
        
        
        if ind_start > ind_end and self.cyclic:  #crosses over the "start" of the cyclic
            self.input_points.points = new_points + self.input_points.points[ind_end:ind_start]  #self.input_points.points[ind_start:] + self.input_points.points[:ind_end]
        
        elif ind_start < ind_end and self.cyclic:
            
            self.input_points.points = self.input_points.points[0:ind_start] + new_points + self.input_points.points[ind_end:]
                
        else:
            self.input_points.points = self.input_points.points[0:ind_start] + new_points + self.input_points.points[ind_end:]
        
        self.selected = None   
          
        
    def click_delete_point(self, mode = 'mouse'):
        '''
        removes point from the trim line
        '''
        if mode == 'mouse':
            if self.hovered[0] != 'POINT': 
                print('hovered is not a point')
                print(self.hovered[0])
                return

            self.input_points.remove(self.hovered[1])

            if not self.hovered[1].is_endpoint:
                last_seg1, last_seg2 = self.hovered[1].link_segments
                ip1 = last_seg1.other_point(self.hovered[1])
                ip2 = last_seg2.other_point(self.hovered[1])
                new_seg = InputSegment(ip1, ip2)
                self.input_points.segments.append(new_seg)
                new_seg.pre_vis_cut(self.bme, self.bvh, self.mx, self.imx)

            if self.input_points.is_empty or self.selected == self.hovered[1]:
                self.selected = None

        else: #hard delete with x key
            if not self.selected: return
            self.input_points.remove(self.selected, disconnect= True)

        #if self.ed_cross_map.is_used:
        #    self.make_cut()

    def grab_initiate(self):
        '''
        sets variables necessary for grabbing functionality
        '''
        if self.selected and isinstance(self.selected, InputPoint):
            #print("Point:",self.selected))
            #print("Grab Point:", self.grab_point)
            
            self.grab_point = self.selected.duplicate()
            
            return True
        else:
            return False

    def grab_mouse_move(self,context,mouse_loc):
        '''
        sets variables depending on where cursor is moved
        '''
        region = context.region
        rv3d = context.region_data
        # ray tracing
        view_vector, ray_origin, ray_target= get_view_ray_data(context, mouse_loc)
        loc, no, face_ind = ray_cast(self.source_ob, self.imx, ray_origin, ray_target, None)
        if face_ind == -1: return

        # check to see if the start_edge or end_edge points are selected
        #Shouldn't this be checking the grab_point?  which shoudl keep seed_geom in duplicate?
        if isinstance(self.selected, InputPoint) and self.selected.seed_geom != None:

            #check the 3d mouse location vs non manifold verts
            co3d, index, dist = self.kd.find(self.mx * loc)

            #get the actual non man vert from original list
            close_bmvert = self.bme.verts[self.non_man_bmverts[index]] #stupid mapping, unreadable, terrible, fix this, because can't keep a list of actual bmverts?  why not?  #undo caching?
            close_eds = [ed for ed in close_bmvert.link_edges if not ed.is_manifold]
            loc3d_reg2D = view3d_utils.location_3d_to_region_2d

            if len(close_eds) != 2: return

            bm0 = close_eds[0].other_vert(close_bmvert)
            bm1 = close_eds[1].other_vert(close_bmvert)

            a0 = bm0.co
            b   = close_bmvert.co
            a1  = bm1.co

            inter_0, d0 = intersect_point_line(loc, a0, b)
            inter_1, d1 = intersect_point_line(loc, a1, b)

            screen_0 = loc3d_reg2D(region, rv3d, self.mx * inter_0)
            screen_1 = loc3d_reg2D(region, rv3d, self.mx * inter_1)
            screen_v = loc3d_reg2D(region, rv3d, self.mx * b)

            screen_d0 = (Vector((mouse_loc)) - screen_0).length
            screen_d1 = (Vector((mouse_loc)) - screen_1).length
            screen_dv = (Vector((mouse_loc)) - screen_v).length

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
                return

            self.grab_point.set_values(self.mx * pt, pt, view_vector, ed.link_faces[0].index)
            self.grab_point.seed_geom = ed
        else:
            self.grab_point.set_values(self.mx * loc, loc, view_vector, face_ind)
            
    def grab_cancel(self):
        '''
        returns variables to their status before grab was initiated
        '''
        #we have not touched the oringal point!
        self.grab_point = None
        return

    def grab_confirm(self, context):
        '''
        sets new variables based on new location
        '''
        
        self.selected.world_loc = self.grab_point.world_loc
        self.selected.local_loc = self.grab_point.local_loc
        self.selected.view = self.grab_point.view
        self.selected.seed_geom = self.grab_point.seed_geom
        self.selected.face_index = self.grab_point.face_index
        
        
        for seg in self.selected.link_segments:
            seg.pre_vis_cut(self.bme, self.bvh, self.mx, self.imx)
            
        self.grab_point = None
        
        return

    def add_sketch_points(self, hovered_start, sketch_points, view_vector):
        '''
        rebuilds the list of input points depending on the sketch
        '''
        hover_start = hovered_start[1]
        hovered_end = self.hovered
        hover_end = hovered_end[1]

        # ending on non manifold edge/vert
        if hovered_end[0] and "NON_MAN" in hovered_end[0]:
            self.input_points.points += sketch_points.points
            self.input_points.add(hovered_end[1][1], None, view_vector, None)
            self.end_edge = hovered_end[1][0]

        # starting on non manifold edge/vert
        elif hovered_start[0] and "NON_MAN" in hovered_start[0]:
            self.input_points.points += sketch_points.points
            self.start_edge = hovered_start[1][0]

        #User is not connecting back to polyline
        elif hovered_end[0] != 'POINT':
            # Do nothing if...
            if self.cyclic or self.end_edge: pass

             # starting at last point
            elif hover_start == self.num_points - 1:
                self.input_points.points += sketch_points.points

            # starting at origin point
            elif hover_start == 0:
                # origin point is start edge
                if self.start_edge:
                    self.input_points.points = [self.input_points.points[0]] + sketch_points.points
                else:
                    self.input_points.points = sketch_points.points[::-1] + self.input_points.points

            # starting in the middle
            else:  #if the last hovered was not the endpoint of the polyline, need to trim and append
                self.input_points.points = self.input_points.points[:hover_start + 1] + sketch_points.points

        # User initiaiated and terminated the sketch on the line.
        else:
            # if start and stop sketch point is same, don't do anything, unless their is only 1 point.
            if hover_end == hover_start:
                if self.num_points == 1:
                    self.input_points.points += sketch_points.points
                    self.cyclic = True

            elif self.cyclic:
                # figure out ammount of points between hover_end and hover_start on both sides XXX: Works, but maybe complicated?
                last_point_index = self.num_points - 1
                num_between = abs(hover_end - hover_start) - 1
                if hover_start < hover_end:  num_between_thru_origin = (last_point_index - hover_end) + hover_start
                else: num_between_thru_origin = (last_point_index - hover_start) + hover_end

                # path through origin point is shorter so cut them out points on those segments/points
                if num_between_thru_origin <= num_between:
                    if hover_start > hover_end:
                        self.input_points.points = self.input_points.points[hover_end: hover_start] + sketch_points.points
                    else:
                        self.input_points.points = sketch_points.points + (self.input_points.points[hover_start: hover_end])[::-1]

                # path not passing through origin point is shorter so cut points on this path
                else:
                    if hover_start > hover_end:
                        self.input_points.points = self.input_points.points[0: hover_end] + sketch_points.points[::-1] + self.input_points.points[hover_start:]

                    else:
                        self.input_points.points = self.input_points.points[:hover_start] + sketch_points.points + self.input_points.points[hover_end:]

            else:
                #drawing "upstream" relative to self.input_points indexing (towards index 0)
                if hover_start > hover_end:
                    # connecting the ends
                    if hover_end == 0 and hover_start == self.num_points - 1:
                        if self.start_edge:
                            self.input_points.points = [self.input_points.points[0]] + sketch_points.points[::-1] + self.input_points.points[hover_start:]
                        else:
                            self.input_points.points += sketch_points.points
                            self.cyclic = True

                    # add sketch points in
                    else:
                        self.input_points.points = self.input_points.points[:hover_end + 1] + sketch_points.points[::-1] + self.input_points.points[hover_start:]

                #drawing "downstream" relative to self.input_points indexing (away from index 0)
                else:
                    # making cyclic
                    if hover_end == self.num_points - 1 and hover_start == 0:
                        if self.start_edge:
                            self.input_points.points = [self.input_points.points[0]] + sketch_points.points + self.input_points.points[hover_end:]
                        else:
                            self.input_points.points += sketch_points.points[::-1]
                            self.cyclic = True

                    # when no points are out
                    elif hover_end == 0:
                        self.input_points.points = self.input_points.points[:1] + sketch_points.points
                        self.cyclic = True
                    # adding sketch points in

                    else:
                        self.input_points.points = self.input_points.points[:hover_start + 1] + sketch_points.points + self.input_points.points[hover_end:]

    def snap_poly_line(self):
        '''
        only needed if processing an outside mesh
        '''
        locs = []
        self.face_changes = []
        self.face_groups = dict()


        last_face_ind = None
        for i, point in enumerate(self.input_points):
            world_loc = point.world_loc
            if bversion() < '002.077.000':
                loc, no, ind, d = self.bvh.find(self.imx * world_loc)
            else:
                loc, no, ind, d = self.bvh.find_nearest(self.imx * world_loc)

            self.input_points.get(i).set_face_ind(ind)
            self.input_points.get(i).set_local_loc(loc)

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
                        print('LOOKS LIKE WE CLICKED SAME FACE MULTIPLE TIMES')
                        print('YOUR PROGRAMMER IS NOT SMART ENOUGH FOR THIS')
                        #TODO....GENERATE SOME ERROR
                        #TODO....REMOVE SELF INTERSECTIONS IN ORIGINAL PATH

                    self.face_groups[last_face_ind] = group + exising_group #we have wrapped, add this group to the old

            else:
                if i != 0:
                    group += [i]
            #double check for the last point
            if i == self.num_points - 1:  #
                if ind != self.input_points.get(0).face_index:  #we didn't click on the same face we started on
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

    ###########################
    #### cutting algorithm ####

    def make_cut(self, ind = None):
        '''
        makes cutting path by walking algorithm
        '''
        if self.split: return #already did this, no going back!
        print('\n','BEGIN CUT ON POLYLINE')

        self.ed_cross_map = EdgeIntersectionMap()
        self.face_chain = set()
        self.preprocess_points()
        self.bad_segments = []
        self.new_ed_face_map = dict()

        # iteration for each input point that changes a face
        for m, ind in enumerate(self.face_changes):
            pnt = self.input_points.points[ind]
            nxt_ind = (ind + 1) % self.num_points
            nxt_pnt = self.input_points.points[nxt_ind]
            ind_p1 = nxt_pnt.face_index #the face in the cut object which the next cut point falls upon

            if m == 0 and not self.cyclic:
                self.ed_cross_map.add(self.start_edge, self.input_points.points[0].local_loc)

            if nxt_ind == 0 and not self.cyclic:
                print('not cyclic, we are done here')
                break

            f0 = self.bme.faces[pnt.face_index]  #<<--- Current BMFace
            self.face_chain.add(f0)

            f1 = self.bme.faces[nxt_pnt.face_index] #<<--- Next BMFace

            ###########################
            ## Define the cutting plane for this segment#
            ############################

            surf_no = self.imx.to_3x3() * pnt.view.lerp(nxt_pnt.view, 0.5)  #must be a better way.
            e_vec = nxt_pnt.local_loc - pnt.local_loc
            #define
            cut_no = e_vec.cross(surf_no)
            #cut_pt = .5*self.cut_pts[ind_p1] + 0.5*self.cut_pts[ind]
            cut_pt = .5 * nxt_pnt.local_loc + 0.5 * pnt.local_loc

            #find the shared edge,, check for adjacent faces for this cut segment
            cross_ed = None
            for ed in f0.edges:
                if f1 in ed.link_faces:
                    cross_ed = ed
                    self.face_chain.add(f1)
                    break

            #if no shared edge, need to cut across to the next face
            if not cross_ed:
                if self.face_changes.index(ind) != 0:
                    p_face = self.bme.faces[self.input_points.points[ind-1].face_index]  #previous face to try and be smart about the direction we are going to walk
                else:
                    p_face = None

                vs = []
                epp = .0000000001
                use_limit = True
                attempts = 0
                while epp < .0001 and not len(vs) and attempts <= 5:
                    attempts += 1
                    vs, eds, eds_crossed, faces_crossed, error = path_between_2_points(
                        self.bme,
                        self.bvh,
                        pnt.local_loc, nxt_pnt.local_loc,
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
                        print('too bad, couldnt adjust due to ' + error)
                        print(p_face)
                        print(f0)
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
                        vs, eds, eds_crossed, faces_crossed, error = cross_section_2seeds_ver1(
                            self.bme,
                            cut_pt, cut_no,
                            f0.index,pnt.local_loc,
                            #f1.index, self.cut_pts[ind_p1],
                            f1.index, nxt_pnt.local_loc,
                            max_tests = 10000, debug = True, prev_face = p_face,
                            epsilon = epp)
                        if len(vs) and error == 'LIMIT_SET':
                            vs = []
                            use_limit = False
                        elif len(vs) == 0 and error == 'EPSILON':
                            epp *= 10
                        elif len(vs) == 0 and error:
                            print('too bad, couldnt adjust due to ' + error)
                            print(p_face)
                            print(f0)
                            break

                if len(vs):
                    #do this before we add in any points
                    if self.ed_cross_map.count > 1:
                        self.new_ed_face_map[self.ed_cross_map.count-1] = pnt.face_index
                    elif self.ed_cross_map.count == 1 and m ==1 and not self.cyclic:
                        self.new_ed_face_map[self.ed_cross_map.count-1] = pnt.face_index
                    for v,ed in zip(vs,eds_crossed):
                        self.ed_cross_map.add(ed, v)

                    print('crossed %i faces' % len(faces_crossed))
                    self.face_chain.update(faces_crossed)

                    if ind == len(self.face_changes) - 1 and self.cyclic:
                        print('This is the loop closing segment.  %i' % len(vs))


                else:  #we failed to find the next face in the face group
                    self.bad_segments.append(ind)
                    print('cut failure!!!')

                if ((not self.cyclic) and
                    m == (len(self.face_changes) - 1) and
                    self.end_edge.link_faces[0].index == f1.index
                    ):

                    print('end to the non manifold edge while walking multiple faces')
                    self.ed_cross_map.add(self.end_edge, self.input_points.points[-1].local_loc)
                    self.new_ed_face_map[self.ed_cross_map.count-2] = f1.index

                continue

            p0 = cross_ed.verts[0].co
            p1 = cross_ed.verts[1].co
            v = intersect_line_plane(p0,p1,cut_pt,cut_no)
            if v:
                self.ed_cross_map.add(cross_ed,v)
                if self.ed_cross_map.count > 1:
                    self.new_ed_face_map[self.ed_cross_map.count-2] = pnt.face_index

            if ((not self.cyclic) and
                m == (len(self.face_changes) - 1) and
                self.end_edge.link_faces[0].index == f1.index
                ):

                print('end to the non manifold edge jumping single face')

                self.new_ed_face_map[self.ed_cross_map.count-2] = f1.index

    def preprocess_points(self):
        '''
        fills data strucutures based on trim line and groups input points with polygons in the cut object
         * accomodate for high density cutting on low density geometry
        '''
        if not self.cyclic and not (self.start_edge != None and self.end_edge != None):
            print('not ready!')
            return
        self.face_changes = []
        self.face_groups = dict()
        last_face_ind = None

        # Loop through each input point
        for i, pnt in enumerate(self.input_points):
            v = pnt.world_loc
            # if loop is on first input point
            if i == 0:
                last_face_ind = pnt.face_index
                group = [i]
                print('first face group index')
                print((pnt.face_index, group))

            # if we have found a new face
            if pnt.face_index != last_face_ind:
                self.face_changes.append(i-1) #this index in cut points, represents an input point that is on a face which has not been evaluted previously
                #Face changes might better be described as edge crossings

                if last_face_ind not in self.face_groups: #previous face has not been mapped before
                    self.face_groups[last_face_ind] = group
                    last_face_ind = pnt.face_index
                    group = [i]
                else:
                    print('group already in dictionary')
                    exising_group = self.face_groups[last_face_ind]
                    if 0 not in exising_group:
                        print('LOOKS LIKE WE CLICKED ON SAME FACE MULTIPLE TIMES')
                        print('YOUR PROGRAMMER IS NOT SMART ENOUGH FOR THIS')
                        print('THEREFORE SOME VERTS MAY NOT BE ACCOUNTED FOR...')


                    else:
                        self.face_groups[last_face_ind] = group + exising_group #we have wrapped, add this group to the old

            else:
                if i != 0:
                    group += [i]
            #double check for the last point
            if i == self.num_points - 1:  #
                if pnt.face_index != self.input_points.points[0].face_index:  #we didn't click on the same face we started on
                    if self.cyclic:
                        self.face_changes.append(i)

                    if pnt.face_index not in self.face_groups:
                        self.face_groups[pnt.face_index] = group

                    else:
                        #print('group already in dictionary')
                        exising_group = self.face_groups[pnt.face_index]
                        if 0 not in exising_group:
                            print('LOOKS LIKE WE CROSSED SAME FACE MULTIPLE TIMES')
                            print('YOUR PROGRAMMER IS NOT SMART ENOUGH FOR THIS')
                        else:
                            self.face_groups[pnt.face_index] = group + exising_group

                else:
                    #print('group already in dictionary')
                    exising_group = self.face_groups[pnt.face_index]
                    if 0 not in exising_group:
                        print('LOOKS LIKE WE CROSSED SAME FACE MULTIPLE TIMES')
                        print('YOUR PROGRAMMER IS NOT SMART ENOUGH FOR THIS')
                    else:
                        self.face_groups[pnt.face_index] = group + exising_group

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

    def click_seed_select(self, context, mouse_loc):
        '''
        finds the selected face and returns a status
        '''
        # ray casting
        view_vector, ray_origin, ray_target= get_view_ray_data(context, mouse_loc)
        loc, no, face_ind = ray_cast(self.source_ob, self.imx, ray_origin, ray_target, None)

        if face_ind != -1:
            if face_ind not in [f.index for f in self.face_chain]:
                self.face_seed = self.bme.faces[face_ind]
                print('face selected!!')
                return 1
            else:
                print('face too close to boundary')
                return -1
        else:
            self.face_seed = None
            print('face not selected')
            return 0

    def confirm_cut_to_mesh(self):
        if len(self.bad_segments): return  #can't do this with bad segments!!

        if self.split: return #already split! no going back

        self.calc_ed_pcts()

        if self.ed_cross_map.has_multiple_crossed_edges:  #doubles in ed dictionary

            print('doubles in the edges crossed!!')
            print('ideally, this will turn  the face into an ngon for simplicity sake')
            seen = set()
            new_eds = []
            new_cos = []
            removals = []

            for i, ed in enumerate(self.ed_cross_map.get_edges()):
                if ed not in seen and not seen.add(ed):
                    new_eds += [ed]
                    new_cos += [self.ed_cross_map.get_loc(i)]
                else:
                    removals.append(ed.index)

            print('these are the edge indices which were removed to be only cut once ')
            print(removals)

            self.ed_cross_map.add_list(new_eds, new_cos)

        for v in self.bme.verts:
            v.select_set(False)
        for ed in self.bme.edges:
            ed.select_set(False)
        for f in self.bme.faces:
            f.select_set(False)

        start = time.time()
        print('bisecting edges')
        geom =  bmesh.ops.bisect_edges(self.bme, edges = self.ed_cross_map.get_edges(),cuts = 1,edge_percents = {})
        new_bmverts = [ele for ele in geom['geom_split'] if isinstance(ele, bmesh.types.BMVert)]

        #assigned new verts their locations
        for v, co in zip(new_bmverts, self.ed_cross_map.get_locs()):
            v.co = co
            #v.select_set(True)

        finish = time.time()
        print('Took %f seconds to bisect edges' % (finish-start))
        start = finish

        ##########################################################
        ########## Connect all the newly crated verts ############
        ed_geom = bmesh.ops.connect_verts(self.bme, verts = new_bmverts, faces_exclude = [], check_degenerate = False)
        new_edges = ed_geom['edges']
        if self.cyclic:
            new_edges.reverse()
            new_edges = new_edges[1:] + [new_edges[0]]


        finish = time.time()
        print('took %f seconds to connect the verts and %i new edges were created' % ((finish-start), len(new_edges)))
        start = finish

        self.bme.verts.ensure_lookup_table()
        self.bme.edges.ensure_lookup_table()

        ########################################################
        ###### The user clicked points need subdivision ########
        newer_edges = []
        unchanged_edges = []

        bisect_eds = []
        bisect_pts = []
        for i, edge in enumerate(new_edges):
            if i in self.new_ed_face_map:
                #print('%i is in the new ed face map' % i)
                face_ind = self.new_ed_face_map[i]
                #print('edge %i is cross face %i' % (i, face_ind))
                if face_ind not in self.face_groups:
                    print('unfortunately, it is not in the face groups')
                    unchanged_edges += [edge]
                    continue
                #these are the user polyine vertex indices
                vert_inds = self.face_groups[face_ind]

                if len(vert_inds):
                    if len(vert_inds) > 1:
                        print('there are %i user drawn poly points on the face' % len(vert_inds))

                    bisect_eds += [edge]
                    bisect_pts += [self.input_points.points[vert_inds[0]].local_loc]  #TODO, this only allows for a single point per face

                    #geom =  bmesh.ops.bisect_edges(self.bme, edges = [edge],cuts = len(vert_inds),edge_percents = {})
                    #new_bmverts = [ele for ele in geom['geom_split'] if isinstance(ele, bmesh.types.BMVert)]
                    #newer_edges += [ele for ele in geom['geom_split'] if isinstance(ele, bmesh.types.BMEdge)]

                    #if len(vert_inds) == 1:
                    #    new_bmverts[0].co = self.cut_pts[vert_inds[0]]
                else:
                    print('#################################')
                    print('there are not user drawn points...what do we do!?')
                    print('so this may not be gettings split')
                    print('#################################')

            else:
                #print('%i edge crosses a face in the walking algo, unchanged' % i)
                unchanged_edges += [edge]

        geom =  bmesh.ops.bisect_edges(self.bme, edges = bisect_eds,cuts = len(vert_inds),edge_percents = {})
        new_bmverts = [ele for ele in geom['geom_split'] if isinstance(ele, bmesh.types.BMVert)]
        newer_edges += [ele for ele in geom['geom_split'] if isinstance(ele, bmesh.types.BMEdge)]

        print('Len of new bmverts %i and len of expected verts %i' % (len(bisect_pts), len(new_bmverts)))
        for v, loc in zip(new_bmverts, bisect_pts):
            v.co = loc

        finish = time.time()
        print('Took %f seconds to bisect %i multipoint edges' % ((finish-start), len(newer_edges)))
        print('Leaving %i unchanged edges' % len(unchanged_edges))
        start = finish

        for ed in new_edges:
            ed.select_set(True)

        for ed in newer_edges:
            ed.select_set(True)



        face_boundary = set()
        for ed in new_edges:
            face_boundary.update(list(ed.link_faces))
        for ed in newer_edges:
            face_boundary.update(list(ed.link_faces))

        self.bme.verts.ensure_lookup_table()
        self.bme.edges.ensure_lookup_table()
        self.bme.faces.ensure_lookup_table()

        self.perimeter_edges = list(set(new_edges) | set(newer_edges))
        finish = time.time()
        #print('took %f seconds' % (finish-start))
        self.split = True

    def confirm_cut_to_mesh_no_ops(self):

        if len(self.bad_segments): return 
        if self.split: return 

        for v in self.bme.verts:
            v.select_set(False)
        for ed in self.bme.edges:
            ed.select_set(False)
        for f in self.bme.faces:
            f.select_set(False)

        start = time.time()

        self.perimeter_edges = []

        #Create new vertices and put them in data structure
        new_vert_ed_map = {}
        ed_list = self.ed_cross_map.get_edges()
        new_bmverts = [self.bme.verts.new(co) for co in self.ed_cross_map.get_locs()]
        for bmed, bmvert in zip(ed_list, new_bmverts):
            if bmed not in new_vert_ed_map:
                new_vert_ed_map[bmed] = [bmvert]
            else:
                print('Ed crossed multiple times.')
                new_vert_ed_map[bmed] += [bmvert]


        print('took %f seconds to create %i new verts and map them to edges' % (time.time()-start, len(new_bmverts)))
        finish = time.time()

        #SPLIT ALL THE CROSSED FACES
        fast_ed_map = set(ed_list)
        del_faces = []
        new_faces = []

        print('len of face chain %i' % len(self.face_chain))
        errors = []
        for bmface in self.face_chain:
            eds_crossed = [ed for ed in bmface.edges if ed in fast_ed_map]

            #scenario 1: it was simply crossed by cut plane. contains no input points
            if bmface.index not in self.face_groups and len(eds_crossed) == 2:
                if any([len(new_vert_ed_map[ed]) > 1 for ed in eds_crossed]):
                    print('2 edges with some double crossed! skipping this face')
                    errors += [(bmface, 'DOUBLE CROSS')]
                    continue

                ed0 = min(eds_crossed, key = ed_list.index)

                if ed0 == eds_crossed[0]:
                    ed1 = eds_crossed[1]
                else:
                    ed1 = eds_crossed[0]

                for v in ed0.verts:
                    new_face_verts = [new_vert_ed_map[ed0][0]]
                    next_v = ed0.other_vert(v)
                    next_ed = [ed for ed in next_v.link_edges if ed in bmface.edges and ed != ed0][0] #TODO, what if None?

                    iters = 0  #safety for now, no 100 vert NGONS allowed!
                    while next_ed != None and iters < 100:
                        iters += 1
                        if next_ed == ed1:
                            new_face_verts += [next_v]
                            new_face_verts += [new_vert_ed_map[ed1][0]]
                            break
                        else:
                            new_face_verts += [next_v]
                            next_v = next_ed.other_vert(next_v)
                            next_ed = [ed for ed in next_v.link_edges if ed in bmface.edges and ed != next_ed][0]


                    new_faces += [self.bme.faces.new(tuple(new_face_verts))]

                #put the new edge into perimeter edges
                for ed in new_faces[-1].edges:
                    if new_vert_ed_map[ed0][0] in ed.verts and new_vert_ed_map[ed1][0] in ed.verts:
                        self.perimeter_edges += [ed]

                del_faces += [bmface]

            #scenario 2: face crossed by cut plane and contains at least 1 input point
            elif bmface.index in self.face_groups and len(eds_crossed) == 2:

                sorted_eds_crossed = sorted(eds_crossed, key = ed_list.index)
                ed0 = sorted_eds_crossed[0]
                ed1 = sorted_eds_crossed[1]


                #make the new verts corresponding to the user click on bmface
                inner_vert_cos = [self.input_points.points[i].local_loc for i in self.face_groups[bmface.index]]
                inner_verts = [self.bme.verts.new(co) for co in inner_vert_cos]

                if ed_list.index(ed0) != 0:
                    inner_verts.reverse()

                for v in ed0.verts:
                    new_face_verts = inner_verts + [new_vert_ed_map[ed0][0]]
                    next_v = ed0.other_vert(v)
                    next_ed = [ed for ed in next_v.link_edges if ed in bmface.edges and ed != ed0][0]

                    iters = 0  #safety for now, no 100 vert NGONS allowed!
                    while next_ed != None and iters < 100:
                        iters += 1
                        if next_ed == ed1:
                            new_face_verts += [next_v]
                            new_face_verts += [new_vert_ed_map[ed1][0]]

                            break
                        else:
                            new_face_verts += [next_v]
                            next_v = next_ed.other_vert(next_v)
                            next_ed = [ed for ed in next_v.link_edges if ed in bmface.edges and ed != next_ed][0]


                    new_faces += [self.bme.faces.new(tuple(new_face_verts))]

                vert_chain = [new_vert_ed_map[ed1][0]] + inner_verts + [new_vert_ed_map[ed0][0]]

                eds = new_faces[-1].edges
                for i, v in enumerate(vert_chain):
                    if i == len(vert_chain) -1: continue
                    for ed in eds:
                        if ed.other_vert(v) == vert_chain[i+1]:
                            self.perimeter_edges += [ed]
                            break

                del_faces += [bmface]

            #scenario 3: face crossed on only one edge and contains input points
            elif bmface.index in self.face_groups and len(eds_crossed) == 1:

                print('ONE EDGE CROSSED TWICE?')

                ed0 = eds_crossed[0]

                #make the new verts corresponding to the user click on bmface
                inner_vert_cos = [self.input_points.points[i].local_loc for i in self.face_groups[bmface.index]]
                inner_verts = [self.bme.verts.new(co) for co in inner_vert_cos]

                #A new face made entirely out of new verts
                if eds_crossed.index(ed0) == 0:
                    print('first multi face reverse')
                    inner_verts.reverse()
                    new_face_verts = [new_vert_ed_map[ed0][1]] + inner_verts + [new_vert_ed_map[ed0][0]]
                    loc = new_vert_ed_map[ed0][0].co
                else:
                    new_face_verts = [new_vert_ed_map[ed0][0]] + inner_verts + [new_vert_ed_map[ed0][1]]
                    loc = new_vert_ed_map[ed0][1].co

                vert_chain = new_face_verts  #hang on to these for later
                new_faces += [self.bme.faces.new(tuple(new_face_verts))]

                #The old face, with new verts inserted
                v_next = min(ed0.verts, key = lambda x: (x.co - loc).length)
                v_end = ed0.other_vert(v_next)

                next_ed = [ed for ed in v_next.link_edges if ed in bmface.edges and ed != ed0][0]
                iters = 0
                while next_ed != None and iters < 100:
                    iters += 1
                    if next_ed == ed0:
                        new_face_verts += [v_end]
                        break

                    else:
                        new_face_verts += [v_next]
                        v_next = next_ed.other_vert(v_next)
                        next_ed = [ed for ed in v_next.link_edges if ed in bmface.edges and ed != next_ed][0]

                if iters > 10:
                    print('This may have iterated out.  %i' % iters)
                    errors += [(bmface, 'TWO CROSS AND ITERATIONS')]

                new_faces += [self.bme.faces.new(tuple(new_face_verts))]

                eds = new_faces[-1].edges
                for i, v in enumerate(vert_chain):
                    if i == len(vert_chain) - 1: continue
                    for ed in eds:
                        if ed.other_vert(v) == vert_chain[i+1]:
                            self.perimeter_edges += [ed]
                            break

                del_faces += [bmface]

            else:
                print('\n')
                print('THIS SCENARIO MAY NOT  ACCOUNTED FOR YET')

                print('There are %i eds crossed' % len(eds_crossed))
                print('BMFace index %i' % bmface.index)
                print('These are the face groups')
                print(self.face_groups)

                if bmface.index in self.face_groups:
                    print('cant cross face twice and have user point on it...ignoring user clicked points')
                    errors += [(bmface, 'CLICK AND DOUBLE CROSS')]
                    continue

                sorted_eds_crossed = sorted(eds_crossed, key = ed_list.index)
                ed0 = sorted_eds_crossed[0]
                ed1 = sorted_eds_crossed[1]
                ed2 = sorted_eds_crossed[2]
                corners = set([v for v in bmface.verts])

                if len(new_vert_ed_map[ed0]) == 2:
                    vs = new_vert_ed_map[ed0]
                    vs.reverse()
                    new_vert_ed_map[ed0] = vs
                    #change order
                    ed0, ed1, ed2 = ed2, ed0, ed1


                for v in ed0.verts:
                    corners.remove(v)
                    new_face_verts = [new_vert_ed_map[ed0][0], v]
                    next_ed = [ed for ed in v.link_edges if ed in bmface.edges and ed != ed0][0]
                    v_next = v
                    while next_ed:

                        if next_ed in sorted_eds_crossed:
                            if len(new_vert_ed_map[next_ed]) > 1:
                                loc = v_next.co
                                #choose the intersection closest to the corner vertex
                                v_last = min(new_vert_ed_map[next_ed], key = lambda x: (x.co - loc).length)
                                new_face_verts += [v_last]
                            else:
                                new_face_verts += [new_vert_ed_map[next_ed][0]]

                                if next_ed == ed1:
                                    print('THIS IS THE PROBLEM!  ALREDY DONE')

                                v_next = next_ed.other_vert(v_next)
                                next_ed = [ed for ed in v_next.link_edges if ed in bmface.edges and ed != next_ed][0]
                                while next_ed != ed1:
                                    v_next = next_ed.other_vert(v_next)
                                    next_ed = [ed for ed in v_next.link_edges if ed in bmface.edges and ed != next_ed][0]

                                vs = sorted(new_vert_ed_map[ed1], key = lambda x: (x.co - v_next.co).length)
                                new_face_verts += vs

                            if len(new_face_verts) != len(set(new_face_verts)):
                                print("ERRROR, multiple verts")
                                print(new_face_verts)

                                print('There are %i verts in vs %i' % (len(vs),bmface.index))
                                print(vs)

                                print('attempting a dumb hack')
                                new_face_verts.pop()
                                errors += [(bmface, 'MULTIPLE VERTS')]


                            new_faces += [self.bme.faces.new(tuple(new_face_verts))]
                            break

                        v_next = next_ed.other_vert(v_next)
                        next_ed = [ed for ed in v_next.link_edges if ed in bmface.edges and ed != next_ed][0]
                        new_face_verts += [v_next]
                        corners.remove(v_next)

                for ed in new_faces[-1].edges:
                    if ed.other_vert(new_vert_ed_map[ed0][0]) == new_vert_ed_map[ed1][0]:
                        self.perimeter_edges += [ed]
                        print('succesfully added edge?')
                        break
                #final corner
                print('There shouldnt be too many left in corners %i' % len(corners))
                v0 = [v for v in corners if v in ed2.verts][0]
                vf = min(new_vert_ed_map[ed1], key = lambda x: (x.co - v0.co).length)
                new_face_verts = [new_vert_ed_map[ed2][0], v0, vf]
                new_faces += [self.bme.faces.new(tuple(new_face_verts))]

                for ed in new_faces[-1].edges:
                    if ed.other_vert(new_vert_ed_map[ed1][1]) == new_vert_ed_map[ed2][0]:
                        self.perimeter_edges += [ed]
                        print('succesffully added edge?')
                        break

                del_faces += [bmface]


        print('took %f seconds to split the faces' % (time.time() - finish))
        finish = time.time()

        ensure_lookup(self.bme)

        for bmface, msg in errors:
            print('Error on this face %i' % bmface.index)
            bmface.select_set(True)

        bmesh.ops.delete(self.bme, geom = del_faces, context = 5)

        ensure_lookup(self.bme)

        self.bme.normal_update()

        #normal est
        to_test = set(new_faces)
        iters = 0
        while len(to_test) and iters < 10:
            iters += 1
            print('test round %i' % iters)
            to_remove = []
            for test_f in to_test:
                link_faces = []
                for ed in test_f.edges:
                    if len(ed.link_faces) > 1:
                        for f in ed.link_faces:
                            if f not in to_test:
                                link_faces += [f]
                if len(link_faces)== 0:
                    continue

                if test_f.normal.dot(link_faces[0].normal) < 0:
                    print('NEEDS FLIP')
                    test_f.normal_flip()
                else:
                    print('DOESNT NEED FLIP')
                to_remove += [test_f]
            to_test.difference_update(to_remove)
        #bmesh.ops.recalc_face_normals(self.bme, faces = new_faces)

        ensure_lookup(self.bme)

        #ngons = [f for f in new_faces if len(f.verts) > 4]
        #bmesh.ops.triangulate(self.bme, faces = ngons)

        for ed in self.perimeter_edges:
            ed.select_set(True)


        finish = time.time()
        print('took %f seconds' % (finish-start))
        self.split = True

    def calc_ed_pcts(self):
        '''
        not used until bmesh.ops uses the percentage index
        '''
        if not self.ed_cross_map.count: return

        ed_list = self.ed_cross_map.get_edges()
        loc_list = self.ed_cross_map.get_locs()
        for v, ed in zip(loc_list, ed_list):

            v0 = ed.verts[0].co
            v1 = ed.verts[1].co

            ed_vec = v1 - v0
            L = ed_vec.length

            cut_vec = v - v0
            l = cut_vec.length

            pct = l/L

    def split_geometry(self, context, mode = 'DUPLICATE'):
        '''
        takes the cut path and finalizes depending on user preference.
         * mode:  Enum in {'KNIFE','DUPLICATE', 'DELETE', 'SPLIT', 'SEPARATE'}
        '''
        #if not (self.split and self.face_seed): return

        start = time.time()
        self.find_select_inner_faces()

        ensure_lookup(self.bme)

        #bmesh.ops.recalc_face_normals(self.bme, faces = self.bme.faces)
        #bmesh.ops.recalc_face_normals(self.bme, faces = self.bme.faces)

        if mode == 'KNIFE':
            ''' just confirms the new cut edges to the mesh, no separation '''
            self.bme.to_mesh(self.source_ob.data)

        elif mode == 'SEPARATE':
            ''' separates into 2 split objects '''
            if not (self.split and self.face_seed): return
            output_bme = bmesh.new()

            verts = set()
            vert_lookup = {}
            for f in self.inner_faces:
                verts.update([v for v in f.verts])

            vert_list = list(verts)
            new_bmverts = []
            for i, v in enumerate(vert_list):
                vert_lookup[v.index] = i
                new_bmverts += [output_bme.verts.new(v.co)]

            for f in self.inner_faces:
                f_ind_tuple = [vert_lookup[v.index] for v in f.verts]
                f_vert_tuple = [new_bmverts[i] for i in f_ind_tuple]
                output_bme.faces.new(tuple(f_vert_tuple))

            new_data = bpy.data.meshes.new(self.source_ob.name + ' trimmed') 
            new_ob =   bpy.data.objects.new(self.source_ob.name + ' trimmed', new_data)
            new_ob.matrix_world = self.source_ob.matrix_world
            output_bme.to_mesh(new_data)
            context.scene.objects.link(new_ob)

            # Get material
            mat = bpy.data.materials.get("Polytrim Material")
            if mat is None:
                # create material
                mat = bpy.data.materials.new(name="Polytrim Material")
                mat.diffuse_color = Color((0.1, .5, .8))
            # Assign it to object
            if new_ob.data.materials:
                # assign to 1st material slot
                new_ob.data.materials[0] = mat
            else:
                # no slots
                new_ob.data.materials.append(mat)

            bmesh.ops.delete(self.bme, geom = self.inner_faces, context = 5)
            self.bme.to_mesh(self.source_ob.data)

        elif mode == 'DELETE':
            ''' deletes selection from source object '''
            self.find_select_inner_faces()

            gdict = bmesh.ops.split_edges(self.bme, edges = self.perimeter_edges, verts = [], use_verts = False) 
            #this dictionary is bad...just empy stuff

            ensure_lookup(self.bme)

            #bmesh.ops.delete(self.bme, geom = self.inner_faces, context = 5)
            bmesh.ops.delete(self.bme, geom = self.inner_faces, context = 5)

            self.bme.to_mesh(self.source_ob.data)
            self.bme.free()

        elif mode == 'DUPLICATE':
            '''
            creates a new object with the selected portion
            of original but leavs the original object un-touched
            '''
            if not (self.split and self.face_seed): return
            output_bme = bmesh.new()

            verts = set()
            vert_lookup = {}
            for f in self.inner_faces:
                verts.update([v for v in f.verts])

            vert_list = list(verts)
            new_bmverts = []
            for i, v in enumerate(vert_list):
                vert_lookup[v.index] = i
                new_bmverts += [output_bme.verts.new(v.co)]

            for f in self.inner_faces:
                f_ind_tuple = [vert_lookup[v.index] for v in f.verts]
                f_vert_tuple = [new_bmverts[i] for i in f_ind_tuple]
                output_bme.faces.new(tuple(f_vert_tuple))

            new_data = bpy.data.meshes.new(self.source_ob.name + ' trimmed')
            new_ob =   bpy.data.objects.new(self.source_ob.name + ' trimmed', new_data)
            new_ob.matrix_world = self.source_ob.matrix_world
            output_bme.to_mesh(new_data)
            context.scene.objects.link(new_ob)

            # Get material
            mat = bpy.data.materials.get("Polytrim Material")
            if mat is None:
                # create material
                mat = bpy.data.materials.new(name="Polytrim Material")
                mat.diffuse_color = Color((0.1, .5, .8))
            # Assign it to object
            if new_ob.data.materials:
                # assign to 1st material slot
                new_ob.data.materials[0] = mat
            else:
                # no slots
                new_ob.data.materials.append(mat)

            #bmesh.ops.delete(self.bme, geom = self.inner_faces, context = 5)
            #self.bme.to_mesh(self.source_ob.data)
            self.bme.free()


        #store the cut as an object
        cut_bme = bmesh.new()
        cut_me = bpy.data.meshes.new('polyknife_stroke')
        cut_ob = bpy.data.objects.new('polyknife_stroke', cut_me)

        bmvs = [cut_bme.verts.new(pnt.local_loc) for pnt in self.input_points]
        for v0, v1 in zip(bmvs[:-1], bmvs[1:]):
            cut_bme.edges.new((v0,v1))

        if self.cyclic:
            cut_bme.edges.new((bmvs[-1], bmvs[0]))
        cut_bme.to_mesh(cut_me)
        context.scene.objects.link(cut_ob)
        cut_ob.show_x_ray = True
        cut_ob.location = self.source_ob.location

    def find_select_inner_faces(self):
        '''
        finds faces that are on side of user selected seed
        '''
        if not self.face_seed: return
        if self.bad_segments: return
        f0 = self.face_seed
        #inner_faces = flood_selection_by_verts(self.bme, set(), f0, max_iters=1000)
        inner_faces = flood_selection_edge_loop(self.bme, self.perimeter_edges, f0, max_iters = 20000)

        if len(inner_faces) == len(self.bme.faces):
            print('region growing selected entire mesh!')
            self.inner_faces = []
        else:
            self.inner_faces = list(inner_faces)

        for f in self.bme.faces:
            f.select_set(False)
        #for f in inner_faces:
        #    f.select_set(True)

        print('Found %i faces in the region' % len(inner_faces))

    #################
    #### drawing ####

    def draw(self,context,mouse_loc):
        '''
        2d drawing
        '''
        green  = (.3,1,.3,1)
        red = (1,.1,.1,1)
        orange = (1,.8,.2,1)
        yellow = (1,1,.1,1)
        cyan = (0,1,1,1)
        navy_opaque = (0,.2,.2,.5)
        blue_opaque = (0,0,1,.2)

        loc3d_reg2D = view3d_utils.location_3d_to_region_2d

        ## Hovered Non-manifold Edge or Vert
        if self.hovered[0] in {'NON_MAN_ED', 'NON_MAN_VERT'}:
            ed, pt = self.hovered[1]
            common_drawing.draw_3d_points(context,[pt], 6, green)

        if  self.input_points.is_empty: return
        # Bad Segments
        #TODO - This section is very confusing and hard to wrap the mind around. making it more intuitive would be very helpful
        for bad_ind in self.bad_segments:
            face_chng_ind = self.face_changes.index(bad_ind)
            next_face_chng_ind = (face_chng_ind + 1) % len(self.face_changes)
            bad_ind_2 = self.face_changes[next_face_chng_ind]
            if bad_ind_2 == 0 and not self.cyclic: bad_ind_2 = self.num_points - 1 # If the bad index 2 is 0 this is an error and needs to be changed to the last point's index
            print("HEY:", self.input_points.get(bad_ind).world_loc, self.input_points.get(bad_ind_2).world_loc)
            common_drawing.draw_polyline_from_3dpoints(context, [self.input_points.get(bad_ind).world_loc, self.input_points.get(bad_ind_2).world_loc], red, 4, 'GL_LINE')

        ## Origin Point
        common_drawing.draw_3d_points(context,[self.input_points.get(0).world_loc], 8, orange)

        ## Selected Point
        if self.selected and isinstance(self.selected, InputPoint):
            common_drawing.draw_3d_points(context,[self.selected.world_loc], 8, cyan)

        ## Hovered Point
        if self.hovered[0] == 'POINT':
            common_drawing.draw_3d_points(context,[self.hovered[1].world_loc], 8, color = (0,1,0,1))
        # Insertion Lines (for adding in a point to edge)
        elif self.hovered[0] == 'EDGE':
            seg = self.hovered[1]
            a = loc3d_reg2D(context.region, context.space_data.region_3d, seg.ip0.world_loc)
            b = loc3d_reg2D(context.region, context.space_data.region_3d, seg.ip1.world_loc)
            if a and b:
                common_drawing.draw_polyline_from_points(context, [a,mouse_loc, b], navy_opaque, 2,"GL_LINE_STRIP")

        # Insertion Lines (for adding closing loop)
        elif self.snap_element != None and self.connect_element != None:
            a = loc3d_reg2D(context.region, context.space_data.region_3d, self.connect_element.world_loc)
            b = loc3d_reg2D(context.region, context.space_data.region_3d, self.snap_element.world_loc)
            if a and b:
                common_drawing.draw_polyline_from_points(context, [a, b], navy_opaque, 2,"GL_LINE_STRIP")
                
                
        # Grab Location Dot and Lines XXX:This part is gross..
        if self.grab_point:
            # Dot
            common_drawing.draw_3d_points(context,[self.grab_point.world_loc], 5, blue_opaque)
            # Lines
            
            point_orig = self.selected  #had to be selected to be grabbed
            
            other_locs = [seg.other_point(point_orig).world_loc for seg in point_orig.link_segments]
            
            for pt_3d in other_locs:
                other_loc = loc3d_reg2D(context.region, context.space_data.region_3d, pt_3d)
                grab_loc = loc3d_reg2D(context.region, context.space_data.region_3d, self.grab_point.world_loc)
                if other_loc and grab_loc:
                    common_drawing.draw_polyline_from_points(context, [grab_loc, other_loc], blue_opaque, 4,"GL_LINE_STRIP")
                
                

        # Face Seed Vertices
        if self.face_seed:
            #TODO direct bmesh face drawing util
            vs = self.face_seed.verts
            common_drawing.draw_3d_points(context,[self.source_ob.matrix_world * v.co for v in vs], 4, yellow)

    def draw3d(self,context,special=None):
        '''
        3d drawing
         * ADAPTED FROM POLYSTRIPS John Denning @CGCookie and Taylor University
        '''
        
        if self.input_points.is_empty: return

        # when polyline select mode is enabled..
        if special:
            if special == "lite": color = (1,1,1,.5)
            elif special == "extra-lite": color = (1,1,1,.2)
            elif special == "green": color = (.3,1,.3,1)

            #common_drawing.draw3d_points(context, self.input_points.world_locs, color, 2)
            if self.cyclic:
                common_drawing.draw3d_polyline(context, self.input_points.world_locs + [self.input_points.world_locs[0]], color, 2,"GL_LINE_STRIP")
            else:
                common_drawing.draw3d_polyline(context, self.input_points.world_locs, color, 2,"GL_LINE_STRIP")

            return

        blue = (.1,.1,.8,1)
        blue2 = (.1,.2,1,.8)
        green = (.2,.5,.2,1)
        orange = (1,.8,.2,1)

        region,r3d = context.region,context.space_data.region_3d
        view_dir = r3d.view_rotation * Vector((0,0,-1))
        view_loc = r3d.view_location - view_dir * r3d.view_distance
        if r3d.view_perspective == 'ORTHO': view_loc -= view_dir * 1000.0

        bgl.glEnable(bgl.GL_POINT_SMOOTH)
        bgl.glDepthRange(0.0, 1.0)
        bgl.glEnable(bgl.GL_DEPTH_TEST)

        def set_depthrange(near=0.0, far=1.0, points=None):
            if points and len(points) and view_loc:
                d2 = min((view_loc-p).length_squared for p in points)
                d = math.sqrt(d2)
                d2 /= 10.0
                near = near / d2
                far = 1.0 - ((1.0 - far) / d2)
            if r3d.view_perspective == 'ORTHO':
                far *= 0.9999
            near = max(0.0, min(1.0, near))
            far = max(near, min(1.0, far))
            bgl.glDepthRange(near, far)
            #bgl.glDepthRange(0.0, 0.5)

        # draws points
        def draw3d_points(context, points, color, size):
            if len(points) == 0: return
            bgl.glColor4f(*color)
            bgl.glPointSize(size)
            set_depthrange(0.0, 0.997, points)
            bgl.glBegin(bgl.GL_POINTS)
            for coord in points: bgl.glVertex3f(*coord)
            bgl.glEnd()
            bgl.glPointSize(1.0)

        # draws polylines.
        def draw3d_polyline(context, points, color, thickness, LINE_TYPE, zfar=0.997):
            if len(points) == 0: return
            if LINE_TYPE == "GL_LINE_STIPPLE":
                bgl.glLineStipple(4, 0x5555)  #play with this later
                bgl.glEnable(bgl.GL_LINE_STIPPLE)
            bgl.glEnable(bgl.GL_BLEND)
            bgl.glColor4f(*color)
            bgl.glLineWidth(thickness)
            set_depthrange(0.0, zfar, points)
            bgl.glBegin(bgl.GL_LINE_STRIP)
            for coord in points: bgl.glVertex3f(*coord)
            bgl.glEnd()
            bgl.glLineWidth(1)
            if LINE_TYPE == "GL_LINE_STIPPLE":
                bgl.glDisable(bgl.GL_LINE_STIPPLE)
                bgl.glEnable(bgl.GL_BLEND)  # back to uninterrupted lines

        bgl.glLineWidth(1)  # Why are these two lines down here?
        bgl.glDepthRange(0.0, 1.0)

        # Preview Polylines
        if self.ed_cross_map.count:
            if self.split:
                color = blue
            else:
                color = green
            draw3d_polyline(context,[self.source_ob.matrix_world * v for v in self.ed_cross_map.get_locs()], color, 5, 'GL_LINE_STRIP')
        
        
        # Polylines...InputSegments
        else:
            for seg in self.input_points.segments:
                if seg.bad_segment:
                    draw3d_polyline(context, [seg.ip0.world_loc, seg.ip1.world_loc],  orange, 2, 'GL_LINE_STRIP' )
                elif len(seg.pre_vis_data) >= 2:
                    draw3d_polyline(context, seg.pre_vis_data,  blue, 2, 'GL_LINE_STRIP' )
                else:
                    draw3d_polyline(context, [seg.ip0.world_loc, seg.ip1.world_loc],  blue2, 2, 'GL_LINE_STRIP' )
     
            #if self.cyclic:
            #    draw3d_polyline(context, self.input_points.world_locs + [self.input_points.world_locs[0]],  blue2, 2, 'GL_LINE_STRIP' )
            #else:
            #    draw3d_polyline(context, self.input_points.world_locs ,  blue2, 2, 'GL_LINE' )
        #Points
        #draw3d_points(context, [self.input_points.world_locs[0]], orange, 10)
        if self.num_points > 1:
            draw3d_points(context, self.input_points.world_locs[1:], blue, 6)

        bgl.glLineWidth(1)     
                
        
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthRange(0.0, 1.0)
        bgl.glDepthMask(bgl.GL_TRUE)



class InputPoint(object):
    '''
    Representation of an input point
    '''
    def __init__(self, world, local, view, face_ind, seed_geom = None):
        self.world_loc = world
        self.local_loc = local
        self.view = view
        self.face_index = face_ind
        self.link_segments = []

        #SETTING UP FOR MORE COMPLEX MESH CUTTING
        self.seed_geom = seed_geom #UNUSED, but will be needed if input point exists on an EDGE or VERT in the source mesh

    def is_endpoint(self):
        if self.seed_geom and len(self.link_segments) > 0: return False  #TODO, better system to delinate edge of mesh
        if len(self.link_segments) < 2: return True # What if self.link_segments == 2 ??
    is_endpoint = property(is_endpoint)

    def set_world_loc(self, loc): self.world_loc = loc
    def set_local_loc(self, loc): self.local_loc = loc
    def set_view(self, view): self.view = view
    def set_face_ind(self, face_ind): self.face_index = face_ind

    def are_connected(self, point):   
        '''
        takes another input point, and returns InputSegment if they are connected
        returns False if they are not connected
        '''
        for seg in self.link_segments:
            if seg.other_point(self) == point:
                return seg
            
        return False

    def set_values(self, world, local, view, face_ind):
        self.world_loc = world
        self.local_loc = local
        self.view = view
        self.face_index = face_ind
    #note, does not duplicate connectivity data
    def duplicate(self): return InputPoint(self.world_loc, self.local_loc, self.view, self.face_index)

    def print_data(self): # for debugging
        print('\n', "POINT DATA", '\n')
        print("world location:", self.world_loc, '\n')
        print("local location:", self.local_loc, '\n')
        print("view direction:", self.view, '\n')
        print("face index:", self.face_index, '\n')

##########################################
#Input Segment ToDos
#TODO - method to clean segments with unused Input Points

##########################################
class InputSegment(object):
    '''
    Representation of a cut between 2 input points
    Equivalent to an "edge" in a mesh connecting to verts
    '''
    def __init__(self, ip0, ip1):
        self.input_points = [ip0, ip1]
        self.ip0 = ip0
        self.ip1 = ip1
        
        ip0.link_segments.append(self)
        ip1.link_segments.append(self)
        
        self.pre_vis_data = []  #list of 3d points for previsualization
        self.bad_segment = False
        
    def other_point(self, ip):
        if ip not in self.input_points: return None
        return self.ip0 if ip == self.ip1 else self.ip1
    

    def insert_point(self, point):
        seg0 = InputSegment(self.ip0, point)
        seg1 = InputSegment(point, self.ip1)
        
        
        self.ip0.link_segments.remove(self)
        self.ip1.link_segments.remove(self)
        return seg0, seg1
    
    def detach(self):
        #TODO safety?  Check if in ip0.link_sgements?
        self.ip0.link_segments.remove(self)
        self.ip1.link_segments.remove(self)
        
    def closes_point_3d_linear(self, pt3d):
        '''
        will return the closest point on a straigh line segment
        drawn between the two input points
       
        If the 3D point is not within the infinite cylinder defined
        by 2 infinite disks placed at each input point and orthogonal
        to the vector between them, will return None
       
       
       
        A_pt3d              B_pt3d
          .                    .
          |                    |              
          |                    |              
          |                    |               
          |       ip0._________x_________.ip1   
         
         
         A_pt3d will return None, None.  B_pt3d will return 3d location at orthogonal intersection and the distance
         
         else, will return a tupple (location of intersection, %along line from ip0 to ip1
         
         happens in the world coordinates
       
        ''' 


        intersect3d = intersect_point_line(pt3d, self.ip0.world_loc, self.ip1.world_loc)

        if intersect3d == None: return (None, None)

        dist3d = (intersect3d[0] - pt3d).length

        if  (intersect3d[1] < 1) and (intersect3d[1] > 0):
            return (intersect3d[0], dist3d)

        return (None, None)

    def pre_vis_cut(self, bme, bvh, mx, imx):
        f0 = bme.faces[self.ip0.face_index]  #<<--- Current BMFace
        f1 = bme.faces[self.ip1.face_index] #<<--- Next BMFace

        if f0 == f1:
            self.pre_vis_data = [self.ip0.world_loc, self.ip1.world_loc]
            self.bad_segment = False
            return

        ###########################
        ## Define the cutting plane for this segment#
        ############################

        surf_no = imx.to_3x3() * self.ip0.view.lerp(self.ip1.view, 0.5)  #must be a better way.
        e_vec = self.ip1.local_loc - self.ip0.local_loc
        #define
        cut_no = e_vec.cross(surf_no)
        #cut_pt = .5*self.cut_pts[ind_p1] + 0.5*self.cut_pts[ind]
        cut_pt = .5 * self.ip0.local_loc + 0.5 * self.ip1.local_loc

        #find the shared edge,, check for adjacent faces for this cut segment
        cross_ed = None
        for ed in f0.edges:
            if f1 in ed.link_faces:
                cross_ed = ed
                self.face_chain.add(f1)
                break

        #if no shared edge, need to cut across to the next face
        if not cross_ed:
            p_face = None

            vs = []
            epp = .0000000001
            use_limit = True
            attempts = 0
            while epp < .0001 and not len(vs) and attempts <= 5:
                attempts += 1
                vs, eds, eds_crossed, faces_crossed, error = path_between_2_points(
                    bme,
                    bvh,
                    self.ip0.local_loc, self.ip1.local_loc,
                    max_tests = 1000, debug = True,
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
                    print('too bad, couldnt adjust due to ' + error)
                    print(p_face)
                    print(f0)
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
                    vs, eds, eds_crossed, faces_crossed, error = cross_section_2seeds_ver1(
                        bme,
                        cut_pt, cut_no,
                        f0.index,self.ip0.local_loc,
                        #f1.index, self.cut_pts[ind_p1],
                        f1.index, self.ip1.local_loc,
                        max_tests = 10000, debug = True, prev_face = p_face,
                        epsilon = epp)
                    if len(vs) and error == 'LIMIT_SET':
                        vs = []
                        use_limit = False
                    elif len(vs) == 0 and error == 'EPSILON':
                        epp *= 10
                    elif len(vs) == 0 and error:
                        print('too bad, couldnt adjust due to ' + error)
                        print(p_face)
                        print(f0)
                        break

            if len(vs):
                print('crossed %i faces' % len(faces_crossed))
                self.face_chain = (faces_crossed)
                self.pre_vis_data = [mx * v for v in vs]
                self.bad_segment = False

            else:  #we failed to find the next face in the face group
                self.bad_segment = True
                self.pre_vis_data = [self.ip0.world_loc, self.ip1.world_loc]
                print('cut failure!!!')

class InputPointMap(object):
    '''
    Data structure that stores a set of InputPoints that are
    connected with InputSegments.
    
    InputPoints store a mapping to the source mesh.
    InputPoints and Input segments, analogous to Verts and Edges
    
    Collection of all InputPoints and Input Segments
     * works with InputPoint objects
    '''
    def __init__(self):
        self.points = []
        self.segments = []  #order not important, but maintain order in this list for indexing?

    def __iter__(self):
        for p in self.points:
            yield p

    def is_empty(self): return len(self.points) == 0
    def num_points(self): return len(self.points)
    is_empty = property(is_empty)
    num_points = property(num_points)

    def world_locs(self): return [p.world_loc for p in self.points]
    def local_locs(self): return [p.local_loc for p in self.points]
    def views(self): return [p.view for p in self.points]
    def face_indices(self): return [p.face_index for p in self.points]
    world_locs = property(world_locs)
    local_locs = property(local_locs)
    view = property(views)
    face_indices = property(face_indices)

    def get(self, start, end=None):
        if end: return self.points[start:end] #end is excluded in slice
        else: return self.points[start]

    def add(self, world=None, local=None, view=None, face_ind=None, p=None):
        point = p
        if not point: point = InputPoint(world, local, view, face_ind)
        
        #now handled at a higher level
        #if len(self.points) > 0:
        #    last_point = self.points[-1]
        #    new_segment = InputSegment(last_point, point)
        #    self.segments.append(new_segment)
        self.points.append(point)

    def add_multiple(self, world=None, local=None, view=None, face_ind=None, points=None):
        if points: 
            #removing this method, and using the "add" to generate connectivity
            #self.points += points
            for p in points:
                self.add(p)  #less efficient but handles the segment generation
        else:
            for i in range(len(world)):
                self.add(world[i], local[i], view[i], face_ind[i])

    def insert(self, insert_ind, world, local, view, face_ind):  #this method will be moved to the InputSegment class later
        point = InputPoint(world, local, view, face_ind)
        point_ahead = self.points[insert_ind]
        
        if insert_ind != 0:
            
            point_behind = self.points[insert_ind- 1]
            old_seg = point_behind.are_connected(point_ahead)
            if old_seg:
                self.segments.remove(old_seg)
                
            new_seg0 = InputSegment(point_behind, point)
            new_seg1 = InputSegment(point, point_ahead)
            self.segments += [new_seg0, new_seg1]
            
        #TODO more generic "node" treatment of InputPoint
        #this assumes there are no T o X or junctions higher than genus 2
        
        self.points.insert(insert_ind, point)

    def replace(self, ind, point):
        if isinstance(ind, InputPoint):
            old_p = ind
        else:
            old_p = self.points[ind]
        other_points = [seg.other_point(old_p) for seg in old_p.link_segments]

        for seg in old_p.link_segments:
            if seg in self.segments:
                self.segments.remove(seg)

        if isinstance(ind, int):
            self.points[ind] = point
        else:
            if old_p in self.points:
                self.points.remove(old_p)
            self.points.append(point)

        for p1 in other_points:
            if p1 == None: continue
            seg = InputSegment(point, p1)
            self.segments.append(seg)

    def pop(self, ind=-1):
        point = self.points[ind]
        connected_points = [seg.other_point(point) for seg in point.link_segments]
        
        if len(connected_points) == 2: #maintain connectivity
            new_segment = InputSegment(connected_points[0], connected_points[1])    
            self.segments.append(new_segment)
            
        for seg in point.link_segments:   
            self.segments.remove(seg)
            
        self.points.remove(point)

    def remove(self, point, disconnect = True):
        if point not in self.points: return False

        connected_points = [seg.other_point(point) for seg in point.link_segments]

        if len(connected_points) == 2 and not disconnect: #maintain connectivity
            new_segment = InputSegment(connected_points[0], connected_points[1])
            self.segments.append(new_segment)

        for seg in point.link_segments:
            self.segments.remove(seg)
            seg.other_point(point).link_segments.remove(seg)

        self.points.remove(point)
        return True

    def duplicate(self):
        new = InputPointMap()
        new.points = self.points
        new.segments = self.segments
        return new

class EdgeIntersectionMap(object):
    '''
    Map of edge crossings by trim line and necessary methods
    '''
    def __init__(self):
        self.edge_list = []
        self.loc_list = []
        self.count = 0
        self.is_used = False
        self.has_multiple_crossed_edges = False

    def get_edge(self, index): return self.edge_list[index]
    def get_edges(self): return self.edge_list
    def get_loc(self, index): return self.loc_list[index]
    def get_locs(self): return self.loc_list

    def add(self, edge, loc):
        if edge in self.edge_list: self.has_multiple_crossed_edges = True
        self.edge_list.append(edge)
        self.loc_list.append(loc)
        self.count += 1
        self.is_used = True

    def add_list(self, edges, locs):
        for i, ed in enumerate(edges):
            self.add(ed, locs[i])