'''
Created on Oct 8, 2015

@author: Patrick
'''
import time
import math

import bpy
import bmesh
import bgl

from mathutils import Vector, Matrix, Color, kdtree
from mathutils.bvhtree import BVHTree
from mathutils.geometry import intersect_point_line, intersect_line_plane
from bpy_extras import view3d_utils

from ..bmesh_fns import grow_selection_to_find_face, flood_selection_faces, edge_loops_from_bmedges_old, flood_selection_by_verts, flood_selection_edge_loop
from ..cut_algorithms import cross_section_2seeds_ver1, path_between_2_points
from .. import common_drawing
from ..common_utilities import bversion

class PolyLineKnife(object):
    '''
    A class which manages user placed points on an object to create a
    poly_line, adapted to the objects surface.
    '''

    ## Initializing
    def __init__(self,context, cut_object, ui_type = 'DENSE_POLY'):
        # object variable setup
        self.cut_ob = cut_object
        self.bme = bmesh.new()
        self.bme.from_mesh(cut_object.data)
        self.ensure_lookup()
        self.bvh = BVHTree.FromBMesh(self.bme)

        # polyline properties
        self.cyclic = False
        self.selected = -1
        self.hovered = [None, -1]

        # polyline variables
        self.points_data = [] # List of dictionaries, each dict contains point data: world loc, local loc, view direction, face index, and normal
        self.start_edge = None
        self.end_edge = None
        self.face_changes = [] #the indices where the next point lies on a different face
        self.face_groups = dict()   #maps bmesh face index to all the points in user drawn polyline which fall upon it
        self.new_ed_face_map = dict()  #maps face index in bmesh to new edges created by bisecting

        #TODO: Put new_cos and ed_map in same data structure
        self.ed_map = []  #existing edges in bmesh crossed by cut line.  list of type BMEdge
        self.new_cos = []  #location of crosses.  list of tyep Vector().  Does not include user clicked noew positions
        self.face_chain = set()  #all faces crossed by the cut curve. set of type BMFace

        self.non_man_eds = [ed.index for ed in self.bme.edges if not ed.is_manifold]
        self.non_man_ed_loops = edge_loops_from_bmedges_old(self.bme, self.non_man_eds)

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


        if ui_type not in {'SPARSE_POLY','DENSE_POLY', 'BEZIER'}:
            self.ui_type = 'SPARSE_POLY'
        else:
            self.ui_type = ui_type

        self.grab_point = None
        self.grab_undo_loc = None
        self.start_edge_undo = None
        self.end_edge_undo = None

        self.mouse = (None, None)

        #keep up with these to show user
        self.bad_segments = []
        self.split = False
        self.perimeter_edges = []
        self.inner_faces = []
        self.face_seed = None

    ## Resets datastructures
    def reset_vars(self):
        '''
        TODOD, parallel workflow will make this obsolete
        '''
        self.cyclic = False  #for cuts entirely within the mesh
        self.start_edge = None #for cuts ending on non man edges
        self.end_edge = None  #for cuts ending on non man edges

        self.points_data = []

        self.face_changes = []
        self.new_cos = [] #TODO: Put new_cos and ed_map in same data structure
        self.ed_map = []

        self.face_chain = set()  #all faces crossed by the cut curve

        self.selected = -1
        self.hovered = [None, -1]

        self.grab_undo_loc = None
        self.mouse = (None, None)

        #keep up with these to show user
        self.bad_segments = []
        self.face_seed = None


    ## ****************************************
    ## ****** POLYLINE/POINT MANIPULATION *****
    ## ****************************************

    ## Add's a point to the trim line.
    def click_add_point(self,context,x,y):
        '''
        x,y = event.mouse_region_x, event.mouse_region_y

        this will add a point into the bezier curve or
        close the curve into a cyclic curve
        '''
        mx, imx = self.get_matrices()
        # ray tracing
        def none_selected(): self.selected = -1 # use in self.ray_cast()
        view_vector, ray_origin, ray_target= self.get_view_ray_data(context, (x, y))
        loc, no, face_ind = self.ray_cast(imx, ray_origin, ray_target, none_selected)
        if loc == None: return

        # if user is currently hovering over non man edge
        if self.hovered[0] and 'NON_MAN' in self.hovered[0]:
            # unselect if it's cyclic and non manifold
            if self.cyclic:
                self.selected = -1
                return

            ed, wrld_loc = self.hovered[1] # hovered[1] is tuple

            if len(self.points_data) == 0:
                self.start_edge = ed

            elif len(self.points_data) and not self.start_edge:
                self.selected = -1
                return

            elif len(self.points_data) and self.start_edge:
                self.end_edge = ed

            self.points_data += [{
                "world_location": wrld_loc,
                "local_location": imx * wrld_loc,
                "view_direction": view_vector,
                "face_index": ed.link_faces[0].index
            }]
            self.selected = len(self.points_data) -1

        # Add point information to datastructures if nothing is being hovered over
        if self.hovered[0] == None and not self.end_edge:  #adding in a new point at end
            self.points_data += [{
                "world_location":mx * loc,
                "local_location": loc,
                "view_direction": view_vector,
                "face_index": face_ind
            }]  #Store data for the click
            self.selected = len(self.points_data) -1

        # If you click point, set it's index to 'selected'
        if self.hovered[0] == 'POINT':
            self.selected = self.hovered[1]
            return

        # If an edge is clicked, cut in a new point
        elif self.hovered[0] == 'EDGE':
            self.points_data.insert(self.hovered[1]+1, {
                "world_location":mx * loc,
                "local_location": loc,
                "view_direction": view_vector,
                "face_index": face_ind
            })
            self.selected = self.hovered[1] + 1

            if len(self.new_cos):
                self.make_cut()
            return

    ## Delete's a point from the trim line.
    def click_delete_point(self, mode = 'mouse'):
        if mode == 'mouse':
            if self.hovered[0] != 'POINT': return

            if self.selected >= self.hovered[1]: self.selected -= 1

            self.points_data.pop(self.hovered[1])

            if not self.num_points():
                self.selected = -1
                self.start_edge = None

            # some kinds of deletes make cyclic false again
            if self.num_points() <= 2 or self.hovered[1] == 0: self.cyclic = False

            if self.end_edge and self.hovered[1] == self.num_points(): #notice not -1 because we popped
                print('deteted last non man edge')
                self.end_edge = None
                self.new_cos = []
                self.selected = -1
                return
        else:
            if self.selected == -1: return
            self.points_data.pop(self.selected)

        if len(self.new_cos):
            self.make_cut()

    ## Initiates a grab if point is selected
    def grab_initiate(self):
        if self.selected != -1:
            self.grab_point = self.points_data[self.selected]
            self.grab_undo_loc = self.points_data[self.selected]["world_location"]
            self.start_edge_undo = self.start_edge
            self.end_edge_undo = self.end_edge
            return True
        else:
            return False

    def grab_mouse_move(self,context,x,y):
        region = context.region
        rv3d = context.region_data
        mx, imx = self.get_matrices()
        # ray tracing
        view_vector, ray_origin, ray_target= self.get_view_ray_data(context, (x, y))
        loc, no, face_ind = self.ray_cast(imx, ray_origin, ray_target, self.grab_cancel)
        if loc == None: return

        #check if first or end point and it's a non man edge!
        if self.selected == 0 and self.start_edge or self.selected == (len(self.points_data) -1) and self.end_edge:

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

            self.grab_point = {
                "world_location": mx * pt,
                "local_location": pt,
                "view_direction": view_vector,
                "face_index": ed.link_faces[0].index
            }
        else:
            self.grab_point = {
                "world_location": mx * loc,
                "local_location": loc,
                "view_direction": view_vector,
                "face_index": face_ind
            }

    def grab_cancel(self):
        self.points_data[self.selected]["world_location"] = self.grab_undo_loc
        self.start_edge = self.start_edge_undo
        self.end_edge = self.end_edge_undo
        self.grab_point = None
        return

    def grab_confirm(self, context, x, y):
        if self.grab_point:
            self.points_data[self.selected] = self.grab_point
            self.grab_point = None
        self.grab_undo_loc = None
        self.start_edge_undo = None
        self.end_edge_undo = None
        return

    ## Makes the sketch and rebuilds the list of input points depending on the sketch
    def make_sketch(self, hovered_start, sketch_data, view_vector):
        hover_start = hovered_start[1]
        hovered_end = self.hovered
        hover_end = hovered_end[1]
        view_vectors = [view_vector]*len(sketch_data)

        # ending on non manifold edge/vert
        if hovered_end[0] and "NON_MAN" in hovered_end[0]:
            self.points_data += sketch_data + [{"world_location": hovered_end[1][1], "view_direction": view_vector}]
            self.end_edge = hovered_end[1][0]

        # starting on non manifold edge/vert
        elif hovered_start[0] and "NON_MAN" in hovered_start[0]:
            self.points_data += sketch_data
            self.start_edge = hovered_start[1][0]

        #User is not connecting back to polyline
        elif hovered_end[0] != 'POINT':
            # Do nothing if...
            if self.cyclic or self.end_edge: pass

             # starting at last point
            elif hover_start == len(self.points_data) - 1:
                self.points_data += sketch_data

            # starting at origin point
            elif hover_start == 0:
                # origin point is start edge
                if self.start_edge:
                    self.points_data = [self.points_data[0]] + sketch_data
                else:
                    self.points_data = sketch_data[::-1] + self.points_data[:]

            # starting in the middle
            else:  #if the last hovered was not the endpoint of the polyline, need to trim and append
                self.points_data = self.points_data[:hover_start] + sketch_data

        # User initiaiated and terminated the sketch on the line.
        else:
            # if start and stop sketch point is same, don't do anything, unless their is only 1 point.
            if hover_end == hover_start:
                if len(self.points_data) == 1:
                    self.points_data += sketch_data
                    self.cyclic = True
            elif self.cyclic:
                # figure out ammount of points between hover_end and hover_start on both sides
                last_point_index = len(self.points_data) - 1
                num_between = abs(hover_end - hover_start) - 1
                if hover_start < hover_end:  num_between_thru_origin = (last_point_index - hover_end) + hover_start
                else: num_between_thru_origin = (last_point_index - hover_start) + hover_end

                # path through origin point is shorter so cut them out points on those segments/points
                if num_between_thru_origin <= num_between:
                    if hover_start > hover_end:
                        self.points_data = self.points_data[hover_end:hover_start] + sketch_data
                    else:
                        self.points_data = sketch_data + self.points_data[hover_end:hover_start:-1]

                # path not passing through origin point is shorter so cut points on this path
                else:
                    if hover_start > hover_end:
                        self.points_data = self.points_data[:hover_end] + sketch_data[::-1] + self.points_data[hover_start:]
                    else:
                        self.points_data = self.points_data[:hover_start] + sketch_data + self.points_data[hover_end:]
            else:
                #drawing "upstream" relative to self.points_data indexing (towards index 0)
                if hover_start > hover_end:
                    # connecting the ends
                    if hover_end == 0 and hover_start == len(self.points_data) - 1:
                        if self.start_edge:
                            self.points_data = [self.points_data[0]] + sketch_data[::-1] + [self.points_data[hover_start]]
                        else:
                            self.points_data += sketch_data
                            self.cyclic = True

                    # add sketch points in
                    else:
                        self.points_data = self.points_data[:hover_end + 1] + sketch_data[::-1] + self.points_data[hover_start:]

                #drawing "downstream" relative to self.points_data indexing (away from index 0)
                else:
                    # making cyclic
                    if hover_end == self.num_points() - 1 and hover_start == 0:
                        if self.start_edge:
                            self.points_data = [self.points_data[0]] + sketch_data + [self.points_data[hover_end]]
                        else:
                            self.points_data += sketch_data[::-1]
                            self.cyclic = True

                    # when no points are out
                    elif hover_end == 0:
                        self.points_data = self.points_data[:1] + sketch_data
                        self.cyclic = True
                    # adding sketch points in

                    else:
                        self.points_data = self.points_data[:hover_start + 1] + sketch_data + self.points_data[hover_end:]


    ## ********************
    ## ****** HOVER *****
    ## ********************

    ## gets information of where mouse is hovering over
    def hover(self,context,x,y):
        '''
        hovering happens in mixed 3d and screen space, 20 pixels thresh for points, 30 for edges
        40 for non_man
        '''
        mx, imx = self.get_matrices()
        self.mouse = Vector((x, y))
        loc3d_reg2D = view3d_utils.location_3d_to_region_2d
        # ray tracing
        view_vector, ray_origin, ray_target = self.get_view_ray_data(context, (x,y))
        loc, no, face_ind = self.ray_cast(imx, ray_origin, ray_target, None)

        # if no input points...
        if len(self.points_data) == 0:
            self.hovered = [None, -1]
            self.hover_non_man(context, x, y)
            return

       # find length between vertex and mouse
        def dist(v):
            if v == None:
                print('v off screen')
                return 100000000
            diff = v - self.mouse
            return diff.length


        def dist3d(v3):
            if v3 == None:
                return 100000000
            delt = v3 - self.cut_ob.matrix_world * loc
            return delt.length

        world_locs = [d['world_location'] for d in self.points_data]
        closest_3d_point = min(world_locs, key = dist3d)
        point_screen_dist = dist(loc3d_reg2D(context.region, context.space_data.region_3d, closest_3d_point))

        # If an input point is less than 20(some unit) away, stop and set hovered to the input point
        if point_screen_dist  < 20:
            def find(lst, key, value):
                for i, dic in enumerate(lst):
                    if dic[key] == value:
                        return i
                return -1

            self.hovered = ['POINT', find(self.points_data, "world_location", closest_3d_point)]
            return

        # If there is 1 input point, stop and set hovered to None
        if len(self.points_data) < 2:
            self.hovered = [None, -1]
            return

        ## ?? What is happening here
        line_inters3d = []
        for i in range(len(self.points_data)):
            nexti = (i + 1) % len(self.points_data)
            if next == 0 and not self.cyclic:
                self.hovered = [None, -1]
                return


            intersect3d = intersect_point_line(self.cut_ob.matrix_world * loc, self.points_data[i]["world_location"], self.points_data[nexti]["world_location"])

            if intersect3d != None:
                dist3d = (intersect3d[0] - loc).length
                bound3d = intersect3d[1]
                if  (bound3d < 1) and (bound3d > 0):
                    line_inters3d += [dist3d]
                    #print('intersect line3d success')
                else:
                    line_inters3d += [1000000]
            else:
                line_inters3d += [1000000]

        ## ?? And here
        i = line_inters3d.index(min(line_inters3d))
        nexti = (i + 1) % len(self.points_data)

        ## ?? And here
        a  = loc3d_reg2D(context.region, context.space_data.region_3d,self.points_data[i]["world_location"])
        b = loc3d_reg2D(context.region, context.space_data.region_3d,self.points_data[nexti]["world_location"])

        ## ?? and here, obviously, its stopping and setting hovered to EDGE, but how?
        if a and b:
            intersect = intersect_point_line(Vector((x,y)).to_3d(), a.to_3d(),b.to_3d())
            dist = (intersect[0].to_2d() - Vector((x,y))).length_squared
            bound = intersect[1]
            if (dist < 400) and (bound < 1) and (bound > 0):
                self.hovered = ['EDGE', i]
                return

        ## Multiple points, but not hovering over edge or point.
        self.hovered = [None, -1]

        if self.start_edge != None:
            self.hover_non_man(context, x, y)  #todo, optimize because double ray cast per mouse move!

    def hover_non_man(self,context,x,y):
        region = context.region
        rv3d = context.region_data
        mx, imx = self.get_matrices()
        # ray casting
        view_vector, ray_origin, ray_target= self.get_view_ray_data(context, (x, y))
        loc, no, face_ind = self.ray_cast(imx, ray_origin, ray_target, None)

        self.mouse = Vector((x, y))
        loc3d_reg2D = view3d_utils.location_3d_to_region_2d
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

                if screen_0 and screen_1 and screen_v:
                    screen_d0 = (self.mouse - screen_0).length
                    screen_d1 = (self.mouse - screen_1).length
                    screen_dv = (self.mouse - screen_v).length

                    if 0 < d0 <= 1 and screen_d0 < 20:
                        self.hovered = ['NON_MAN_ED', (close_eds[0], mx*inter_0)]
                        return
                    elif 0 < d1 <= 1 and screen_d1 < 20:
                        self.hovered = ['NON_MAN_ED', (close_eds[1], mx*inter_1)]
                        return
                    elif screen_dv < 20:
                        if abs(d0) < abs(d1):
                            self.hovered = ['NON_MAN_VERT', (close_eds[0], mx*b)]
                            return
                        else:
                            self.hovered = ['NON_MAN_VERT', (close_eds[1], mx*b)]
                            return


    ## *************************
    ## ***** Cut Preview *****
    ## *************************

    ## Fills data strucutures based on trim line and groups input points with polygons in the cut object
    def preprocess_points(self):
        '''
        Accomodate for high density cutting on low density geometry
        '''
        if not self.cyclic and not (self.start_edge != None and self.end_edge != None):
            print('not ready!')
            return
        self.face_changes = []
        self.face_groups = dict()
        last_face_ind = None

        # Loop through each input point
        for i, dct in enumerate(self.points_data):
            v = dct["world_location"]
            # if loop is on first input point
            if i == 0:
                last_face_ind = self.points_data[i]["face_index"]
                group = [i]
                print('first face group index')
                print((self.points_data[i]["face_index"],group))

            # if we have found a new face
            if self.points_data[i]["face_index"] != last_face_ind:
                self.face_changes.append(i-1) #this index in cut points, represents an input point that is on a face which has not been evaluted previously
                #Face changes might better be described as edge crossings

                if last_face_ind not in self.face_groups: #previous face has not been mapped before
                    self.face_groups[last_face_ind] = group
                    last_face_ind = self.points_data[i]["face_index"]
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
            if i == len(self.points_data) - 1:  #
                if self.points_data[i]["face_index"] != self.points_data[0]["face_index"]:  #we didn't click on the same face we started on
                    if self.cyclic:
                        self.face_changes.append(i)

                    if self.points_data[i]["face_index"] not in self.face_groups:
                        self.face_groups[self.points_data[i]["face_index"]] = group

                    else:
                        #print('group already in dictionary')
                        exising_group = self.face_groups[self.points_data[i]["face_index"]]
                        if 0 not in exising_group:
                            print('LOOKS LIKE WE CROSSED SAME FACE MULTIPLE TIMES')
                            print('YOUR PROGRAMMER IS NOT SMART ENOUGH FOR THIS')
                        else:
                            self.face_groups[self.points_data[i]["face_index"]] = group + exising_group

                else:
                    #print('group already in dictionary')
                    exising_group = self.face_groups[self.points_data[i]["face_index"]]
                    if 0 not in exising_group:
                        print('LOOKS LIKE WE CROSSED SAME FACE MULTIPLE TIMES')
                        print('YOUR PROGRAMMER IS NOT SMART ENOUGH FOR THIS')
                    else:
                        self.face_groups[self.points_data[i]["face_index"]] = group + exising_group

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

    # Finds the selected face and returns a status
    def click_seed_select(self, context, x, y):
        mx, imx = self.get_matrices()

        # ray casting
        view_vector, ray_origin, ray_target= self.get_view_ray_data(context, (x, y))
        loc, no, face_ind = self.ray_cast(imx, ray_origin, ray_target, None)

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

    def preview_region(self):
        if self.face_seed == None:
            return

        #face_set = flood_selection_faces(self.bme, self.face_chain, self.face_seed, max_iters = 5000)
        #self.prev_region = [f.calc_center_median() for f in face_set]

    # makes cutting path
    def make_cut(self):
        if self.split: return #already did this, no going back!
        mx, imx = self.get_matrices()
        print('\n')
        print('BEGIN CUT ON POLYLINE')

        self.new_cos = []  #New coordinates created by intersections of mesh edges with cut segments
        self.ed_map = []  #smarter thing to do might be edge_map = {}  edge_map[ed] = co. Can't cross an edge twice because dictionary reqires


        self.face_chain = set()
        self.preprocess_points()  #put things into different data strucutures and grouping input points with polygons in the cut object
        self.bad_segments = []

        self.new_ed_face_map = dict()

        #print('there are %i cut points' % len(self.cut_pts))
        #print('there are %i face changes' % len(self.face_changes))

        # iteration for each input point that changes a face
        for m, ind in enumerate(self.face_changes):


            ## first time through and non-manifold edge cut
            if m == 0 and not self.cyclic:
                self.ed_map += [self.start_edge]
                #self.new_cos += [imx * self.cut_pts[0]]
                self.new_cos += [self.points_data[0]["local_location"]]

                #self.new_ed_face_map[0] = self.start_edge.link_faces[0].index

                #print('not cyclic...come back to me')
                #continue

            #n_p1 = (m + 1) % len(self.face_changes)
            #ind_p1 = self.face_changes[n_p1]

            n_p1 = (ind + 1) % len(self.points_data)  #The index of the next cut_pt (input point)
            ind_p1 = self.points_data[n_p1]["face_index"]  #the face in the cut object which the next cut point falls upon

            n_m1 = (ind - 1)
            ind_m1 = self.points_data[n_m1]["face_index"]
            #print('walk on edge pair %i, %i' % (m, n_p1))
            #print('original faces in mesh %i, %i' % (self.face_map[ind], self.face_map[ind_p1]))

            if n_p1 == 0 and not self.cyclic:
                print('not cyclic, we are done here')
                break

            f0 = self.bme.faces[self.points_data[ind]["face_index"]]  #<<--- Current BMFace
            self.face_chain.add(f0)

            f1 = self.bme.faces[self.points_data[n_p1]["face_index"]] #<<--- Next BMFace

            ###########################
            ## Define the cutting plane for this segment#
            ############################

            no0 = self.points_data[ind]["view_direction"]  #direction the user was looking when adding current point
            no1 = self.points_data[n_p1]["view_direction"]  #direction the user was looking when adding next point
            surf_no = imx.to_3x3() * no0.lerp(no1, 0.5)  #must be a better way.

            e_vec = self.points_data[n_p1]["local_location"] - self.points_data[ind]["local_location"]

            #define
            cut_no = e_vec.cross(surf_no)

            #cut_pt = .5*self.cut_pts[ind_p1] + 0.5*self.cut_pts[ind]
            cut_pt = .5*self.points_data[n_p1]["local_location"] + 0.5*self.points_data[ind]["local_location"]

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
                    p_face = self.bme.faces[self.points_data[ind-1]["face_index"]]  #previous face to try and be smart about the direction we are going to walk
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
                        #self.cut_pts[ind], self.cut_pts[ind_p1],
                        self.points_data[ind]["local_location"], self.points_data[n_p1]["local_location"],
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
                            f0.index,self.points_data[ind]["local_location"],
                            #f1.index, self.cut_pts[ind_p1],
                            f1.index, self.points_data[n_p1]["local_location"],
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
                    if len(self.new_cos) > 1:
                        self.new_ed_face_map[len(self.new_cos)-1] = self.points_data[ind]["face_index"]
                    elif len(self.new_cos) == 1 and m ==1 and not self.cyclic:
                        self.new_ed_face_map[len(self.new_cos)-1] = self.points_data[ind]["face_index"]
                    for v,ed in zip(vs,eds_crossed):
                        self.new_cos.append(v)
                        self.ed_map.append(ed)

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
                    self.ed_map += [self.end_edge]
                    self.new_cos += [self.points_data[-1]["local_location"]]
                    self.new_ed_face_map[len(self.new_cos)-2] = f1.index

                continue

            p0 = cross_ed.verts[0].co
            p1 = cross_ed.verts[1].co
            v = intersect_line_plane(p0,p1,cut_pt,cut_no)
            if v:
                self.new_cos.append(v)
                self.ed_map.append(cross_ed)
                if len(self.new_cos) > 1:
                    self.new_ed_face_map[len(self.new_cos)-2] = self.points_data[ind]["face_index"]

            if ((not self.cyclic) and
                m == (len(self.face_changes) - 1) and
                self.end_edge.link_faces[0].index == f1.index
                ):

                print('end to the non manifold edge jumping single face')
                self.ed_map += [self.end_edge]
                self.new_cos += [self.points_data[-1]["local_location"]]
                self.new_ed_face_map[len(self.new_cos)-2] = f1.index

    def smart_make_cut(self):
        if len(self.new_cos) == 0:
            print('havent made initial cut yet')
            self.make_cut()

        old_fcs = self.face_changes
        old_fgs = self.face_groups

        self.preprocess_points()


    ## ********************
    ## ****** OTHER *****
    ## ********************

    def confirm_cut_to_mesh(self):

        if len(self.bad_segments): return  #can't do this with bad segments!!

        if self.split: return #already split! no going back

        self.calc_ed_pcts()

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

            print('these are the edge indices which were removed to be only cut once ')
            print(removals)

            self.ed_map = new_eds
            self.new_cos = new_cos

        for v in self.bme.verts:
            v.select_set(False)
        for ed in self.bme.edges:
            ed.select_set(False)
        for f in self.bme.faces:
            f.select_set(False)

        start = time.time()
        print('bisecting edges')
        geom =  bmesh.ops.bisect_edges(self.bme, edges = self.ed_map,cuts = 1,edge_percents = {})
        new_bmverts = [ele for ele in geom['geom_split'] if isinstance(ele, bmesh.types.BMVert)]

        #assigned new verts their locations
        for v, co in zip(new_bmverts, self.new_cos):
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
                    bisect_pts += [self.points_data[vert_inds[0]]["local_location"]]  #TODO, this only allows for a single point per face

                    #geom =  bmesh.ops.bisect_edges(self.bme, edges = [edge],cuts = len(vert_inds),edge_percents = {})
                    #new_bmverts = [ele for ele in geom['geom_split'] if isinstance(ele, bmesh.types.BMVert)]
                    #newer_edges += [ele for ele in geom['geom_split'] if isinstance(ele, bmesh.types.BMEdge)]

                    #if len(vert_inds) == 1:
                    #    new_bmverts[0].co = self.cut_pts[vert_inds[0]]

                    #self.bme.verts.ensure_lookup_table()
                    #self.bme.edges.ensure_lookup_table()
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

        if len(self.bad_segments): return  #can't do this with bad segments!!

        if self.split: return #already split! no going back

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
        new_bmverts = [self.bme.verts.new(co) for co in self.new_cos]
        for bmed, bmvert in zip(self.ed_map, new_bmverts):
            if bmed not in new_vert_ed_map:
                new_vert_ed_map[bmed] = [bmvert]
            else:
                print('Ed crossed multiple times.')
                new_vert_ed_map[bmed] += [bmvert]


        print('took %f seconds to create %i new verts and map them to edges' % (time.time()-start, len(new_bmverts)))
        finish = time.time()

        #SPLIT ALL THE CROSSED FACES
        fast_ed_map = set(self.ed_map)
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

                ed0 = min(eds_crossed, key = self.ed_map.index)

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

                sorted_eds_crossed = sorted(eds_crossed, key = self.ed_map.index)
                ed0 = sorted_eds_crossed[0]
                ed1 = sorted_eds_crossed[1]


                #make the new verts corresponding to the user click on bmface
                inner_vert_cos = [self.points_data[i]["local_location"] for i in self.face_groups[bmface.index]]
                inner_verts = [self.bme.verts.new(co) for co in inner_vert_cos]

                if self.ed_map.index(ed0) != 0:
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
                inner_vert_cos = [self.points_data[i]["local_location"] for i in self.face_groups[bmface.index]]
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

                sorted_eds_crossed = sorted(eds_crossed, key = self.ed_map.index)
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

        self.ensure_lookup()

        for bmface, msg in errors:
            print('Error on this face %i' % bmface.index)
            bmface.select_set(True)

        bmesh.ops.delete(self.bme, geom = del_faces, context = 5)

        self.ensure_lookup()

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

        self.ensure_lookup()

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
        if not len(self.ed_map) and len(self.new_cos): return

        for v, ed in zip(self.new_cos, self.ed_map):

            v0 = ed.verts[0].co
            v1 = ed.verts[1].co

            ed_vec = v1 - v0
            L = ed_vec.length

            cut_vec = v - v0
            l = cut_vec.length

            pct = l/L

    def preview_mesh(self, context):

        self.find_select_inner_faces()
        context.tool_settings.mesh_select_mode = (False, True, False)
        self.bme.to_mesh(self.cut_ob.data)

        #store the cut!
        cut_bme = bmesh.new()
        cut_me = bpy.data.meshes.new('polyknife_stroke')
        cut_ob = bpy.data.objects.new('polyknife_stroke', cut_me)
        cut_ob.hide = True
        bmvs = [cut_bme.verts.new(dct["local_location"]) for dct in self.points_data]
        for v0, v1 in zip(bmvs[:-1], bmvs[1:]):
            cut_bme.edges.new((v0,v1))

        if self.cyclic:
            cut_bme.edges.new((bmvs[-1], bmvs[0]))
        cut_bme.to_mesh(cut_me)
        context.scene.objects.link(cut_ob)
        cut_ob.show_x_ray = True

    def split_geometry(self, context, mode = 'DUPLICATE'):
        '''
        mode:  Enum in {'KNIFE','DUPLICATE', 'DELETE', 'SPLIT', 'SEPARATE'}
        '''
        #if not (self.split and self.face_seed): return

        start = time.time()
        self.find_select_inner_faces()

        self.ensure_lookup()

        #bmesh.ops.recalc_face_normals(self.bme, faces = self.bme.faces)
        #bmesh.ops.recalc_face_normals(self.bme, faces = self.bme.faces)

        if mode == 'KNIFE':
            '''
            this mode just confirms the new cut edges to the mesh
            does not separate them
            '''

            self.bme.to_mesh(self.cut_ob.data)

        if mode == 'SEPARATE':
            '''
            separates the selected portion into a new object
            leaving hole in original object
            this is destructive
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

            new_data = bpy.data.meshes.new(self.cut_ob.name + ' trimmed') 
            new_ob =   bpy.data.objects.new(self.cut_ob.name + ' trimmed', new_data)
            new_ob.matrix_world = self.cut_ob.matrix_world
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
            self.bme.to_mesh(self.cut_ob.data)



        elif mode == 'DELETE':
            '''
            deletes the selected region of mesh
            This is destructive method
            '''
            print('DELETING THE INNER GEOM')
            self.find_select_inner_faces()

            gdict = bmesh.ops.split_edges(self.bme, edges = self.perimeter_edges, verts = [], use_verts = False) 
            #this dictionary is bad...just empy stuff

            self.ensure_lookup()

            #bmesh.ops.delete(self.bme, geom = self.inner_faces, context = 5)
            bmesh.ops.delete(self.bme, geom = self.inner_faces, context = 5)

            self.bme.to_mesh(self.cut_ob.data)
            self.bme.free()


        elif mode == 'SPLIT':
            '''
            splits the mesh, leaving 2 separate pieces in the original object
            This is destructive method
            '''
            if not self.split: return
            #print('There are %i perimeter edges' % len(self.perimeter_edges))

            #old_eds = set([e for e in self.bme.edges])
            #gdict = bmesh.ops.split_edges(self.bme, edges = self.perimeter_edges, verts = [], use_verts = False)
            #this dictionary is bad...just empy stuff

            #self.ensure_lookup()

            #current_edges = set([e for e in self.bme.edges])
            #new_edges = current_edges - old_eds
            #for ed in new_edges:
            #    ed.select_set(True)
            #print('There are %i new edges' % len(new_edges))

            self.bme.to_mesh(self.cut_ob.data)


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

            new_data = bpy.data.meshes.new(self.cut_ob.name + ' trimmed')
            new_ob =   bpy.data.objects.new(self.cut_ob.name + ' trimmed', new_data)
            new_ob.matrix_world = self.cut_ob.matrix_world
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
            #self.bme.to_mesh(self.cut_ob.data)
            self.bme.free()


        #store the cut as an object
        cut_bme = bmesh.new()
        cut_me = bpy.data.meshes.new('polyknife_stroke')
        cut_ob = bpy.data.objects.new('polyknife_stroke', cut_me)

        bmvs = [cut_bme.verts.new(dct["local_location"]) for dct in self.points_data]
        for v0, v1 in zip(bmvs[:-1], bmvs[1:]):
            cut_bme.edges.new((v0,v1))

        if self.cyclic:
            cut_bme.edges.new((bmvs[-1], bmvs[0]))
        cut_bme.to_mesh(cut_me)
        context.scene.objects.link(cut_ob)
        cut_ob.show_x_ray = True
        cut_ob.location = self.cut_ob.location

    def find_select_inner_faces(self):
        if not self.face_seed: return
        if len(self.bad_segments): return
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

    def replace_segment(self,start,end,new_locs):
        #http://stackoverflow.com/questions/497426/deleting-multiple-elements-from-a-list
        print('replace')
        return

    def snap_poly_line(self):
        '''
        only needed if processing an outside mesh
        '''
        locs = []
        self.face_changes = []
        self.face_groups = dict()

        mx, imx = self.get_matrices()

        last_face_ind = None
        for i, dct in enumerate(self.points_data):
            v = dct["world_location"]
            if bversion() < '002.077.000':
                loc, no, ind, d = self.bvh.find(imx * v)
            else:
                loc, no, ind, d = self.bvh.find_nearest(imx * v)

            self.points_data[i]["face_index"] = ind
            self.points_data[i]["local_location"] = loc

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
            if i == len(self.points_data) - 1:  #
                if ind != self.points_data[0]["face_index"]:  #we didn't click on the same face we started on
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


    ## ******************************
    ## ****** HELPER FUNCTIONS *****
    ## ******************************

    # calls bmesh's ensure lookup table functions
    def ensure_lookup(self):
        self.bme.verts.ensure_lookup_table()
        self.bme.edges.ensure_lookup_table()
        self.bme.faces.ensure_lookup_table()

    # get info to use later with ray_cast
    def get_view_ray_data(self, context, coord):
        view_vector = view3d_utils.region_2d_to_vector_3d(context.region, context.region_data, coord)
        ray_origin = view3d_utils.region_2d_to_origin_3d(context.region, context.region_data, coord)
        ray_target = ray_origin + (view_vector * 1000)
        return [view_vector, ray_origin, ray_target]

    # cast rays and get info based on blender version
    def ray_cast(self, imx, ray_origin, ray_target, also_do_this):
        if bversion() < '002.077.000':
            loc, no, face_ind = self.cut_ob.ray_cast(imx * ray_origin, imx * ray_target)
            if face_ind == -1:
                if also_do_this:
                    also_do_this()
                    return [None, None, None]
                else:
                    pass
        else:
            res, loc, no, face_ind = self.cut_ob.ray_cast(imx * ray_origin, imx * ray_target - imx * ray_origin)
            if not res:
                if also_do_this:
                    also_do_this()
                    return [None, None, None]
                else:
                    pass

        return [loc, no, face_ind]

    ## get the world matrix and inverse for the object
    def get_matrices(self):
        mx = self.cut_ob.matrix_world
        imx = mx.inverted()
        return [mx, imx]

    ## toggles self.cyclic
    def toggle_cyclic(self):
        if self.cyclic: self.cyclic = False
        else: self.cyclic = True

    # returns length of points_data
    def num_points(self):
        return len(self.points_data)


    ## *************************
    ## ****** DRAWING/UI *****
    ## *************************

    ## 2D drawing
    def draw(self,context):

        ## Hovered Non-manifold Edge or Vert
        if self.hovered[0] in {'NON_MAN_ED', 'NON_MAN_VERT'}:
            ed, pt = self.hovered[1]
            common_drawing.draw_3d_points(context,[pt], 6, color = (.3,1,.3,1))

        if  not self.points_data: return

        # Bad Segments
        #TODO - This section is very confusing and hard to wrap the mind around. making it more intuitive would be very helpful
        for bad_ind in self.bad_segments:
            face_chng_ind = self.face_changes.index(bad_ind)
            next_face_chng_ind = (face_chng_ind + 1) % len(self.face_changes)
            bad_ind_2 = self.face_changes[next_face_chng_ind]
            if bad_ind_2 == 0 and not self.cyclic: bad_ind_2 = len(self.points_data) - 1 # If the bad index 2 is 0 this is an error and needs to be changed to the last point's index
            common_drawing.draw_polyline_from_3dpoints(context, [self.points_data[bad_ind]["world_location"], self.points_data[bad_ind_2]["world_location"]], (1,.1,.1,1), 4, 'GL_LINE')

        ## Origin Point
        if self.points_data[0]:
            common_drawing.draw_3d_points(context,[self.points_data[0]["world_location"]], 8, (1,.8,.2,1))

        ## Selected Point
        if self.selected != -1 and len(self.points_data) >= self.selected + 1:
            common_drawing.draw_3d_points(context,[self.points_data[self.selected]["world_location"]], 8, color = (0,1,1,1))

        ## Hovered Point
        if self.hovered[0] == 'POINT':
            common_drawing.draw_3d_points(context,[self.points_data[self.hovered[1]]["world_location"]], 8, color = (0,1,0,1))
        # Insertion Lines (for adding in a point to edge)
        elif self.hovered[0] == 'EDGE':
            loc3d_reg2D = view3d_utils.location_3d_to_region_2d
            a = loc3d_reg2D(context.region, context.space_data.region_3d, self.points_data[self.hovered[1]]["world_location"])
            next = (self.hovered[1] + 1) % len(self.points_data)
            b = loc3d_reg2D(context.region, context.space_data.region_3d, self.points_data[next]["world_location"])
            common_drawing.draw_polyline_from_points(context, [a,self.mouse, b], (0,.2,.2,.5), 2,"GL_LINE_STRIP")

        # Grab Location Dot and Lines
        if self.grab_point:
            loc3d_reg2D = view3d_utils.location_3d_to_region_2d
            color = (0,0,1,.2)
            common_drawing.draw_3d_points(context,[self.grab_point["world_location"]], 5, color)
            # find index of grab point in points data
            for i in range(self.num_points()):
                if self.points_data[i]["world_location"] == self.grab_undo_loc:
                    grab_point_ind = i
                    break
            low_ind = grab_point_ind - 1
            high_ind = (grab_point_ind + 1) % self.num_points()
            low_loc = loc3d_reg2D(context.region, context.space_data.region_3d, self.points_data[low_ind]["world_location"])
            grab_loc = loc3d_reg2D(context.region, context.space_data.region_3d, self.grab_point["world_location"])
            high_loc = loc3d_reg2D(context.region, context.space_data.region_3d, self.points_data[high_ind]["world_location"])
            if self.num_points() == 1:
                pass
            elif self.selected == 0 and not self.cyclic:
                common_drawing.draw_polyline_from_points(context, [grab_loc, high_loc], color, 4,"GL_LINE_STRIP")
            elif self.selected == self.num_points() - 1 and not self.cyclic:
                common_drawing.draw_polyline_from_points(context, [low_loc, grab_loc], color, 4,"GL_LINE_STRIP")
            else:
                common_drawing.draw_polyline_from_points(context, [low_loc, grab_loc, high_loc], color, 4,"GL_LINE_STRIP")

        # Face Seed Vertices
        if self.face_seed:
            #TODO direct bmesh face drawing util
            vs = self.face_seed.verts
            common_drawing.draw_3d_points(context,[self.cut_ob.matrix_world * v.co for v in vs], 4, color = (1,1,.1,1))

    ## 3D drawing
    def draw3d(self,context):
        #ADAPTED FROM POLYSTRIPS John Denning @CGCookie and Taylor University
        if not self.points_data: return

        region,r3d = context.region,context.space_data.region_3d
        view_dir = r3d.view_rotation * Vector((0,0,-1))
        view_loc = r3d.view_location - view_dir * r3d.view_distance
        if r3d.view_perspective == 'ORTHO': view_loc -= view_dir * 1000.0

        bgl.glEnable(bgl.GL_POINT_SMOOTH)
        bgl.glDepthRange(0.0, 1.0)
        bgl.glEnable(bgl.GL_DEPTH_TEST)

        world_locs = [d['world_location'] for d in self.points_data]

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
        if len(self.new_cos):
            if self.split:
                color = (.1, .1, .8, 1)
            else:
                color = (.2,.5,.2,1)
            draw3d_polyline(context,[self.cut_ob.matrix_world * v for v in self.new_cos], color, 5, 'GL_LINE_STRIP')
        # Polylines
        else:
            if self.cyclic and len(self.points_data):
                draw3d_polyline(context, world_locs + [world_locs[0]],  (.1,.2,1,.8), 2, 'GL_LINE_STRIP' )
            else:
                draw3d_polyline(context, world_locs,  (.1,.2,1,.8),2, 'GL_LINE' )

        # Origin Point
        draw3d_points(context, [world_locs[0]], (1,.8,.2,1), 10)

        # Points
        if len(self.points_data) > 1:
            draw3d_points(context, world_locs[1:], (.2, .2, .8, 1), 6)

        bgl.glLineWidth(1)
        bgl.glDepthRange(0.0, 1.0)




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





