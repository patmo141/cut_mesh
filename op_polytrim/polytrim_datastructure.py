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

class NetworkCutter(object):
    ''' Manages cuts in the InputNetwork '''

    def __init__(self):
        self.cut = False


class PolyLineKnife(object): #NetworkCutter
    '''
    A class which manages user placed points on an object to create a
    poly_line, adapted to the objects surface.
    '''
    def __init__(self,input_net,context, source_ob, ui_type = 'DENSE_POLY'):
        self.input_net = input_net # is network

        self.cyclic = False #R
        
        self.closest_ep = None   #UI  closest free input point (< 2 segs)
        self.snap_element = None    #UI
        self.connect_element = None #UI

         #TODO: (Cutting with new method, very hard)
        self.face_chain = set()

        self.non_man_eds = [ed.index for ed in self.input_net.bme.edges if not ed.is_manifold] #UI? (Network,cutting...)
        self.non_man_ed_loops = edge_loops_from_bmedges_old(self.input_net.bme, self.non_man_eds) #UI? (Network,cutting...)

        self.non_man_points = []        #UI
        self.non_man_bmverts = []       #UI
        for loop in self.non_man_ed_loops:
            self.non_man_points += [self.input_net.source_ob.matrix_world * self.input_net.bme.verts[ind].co for ind in loop]
            self.non_man_bmverts += [self.input_net.bme.verts[ind].index for ind in loop]
        if len(self.non_man_points):
            kd = kdtree.KDTree(len(self.non_man_points))
            for i, v in enumerate(self.non_man_points):
                kd.insert(v, i)
            kd.balance()
            self.kd = kd
        else:
            self.kd = None



        #keep up with these to show user
        self.perimeter_edges = []

    def num_points(self): return self.input_net.num_points
    num_points = property(num_points)


####

## UI

###

    #################
    #### drawing ####

    


class InputPoint(object):  # NetworkNode
    '''
    Representation of an input point
    '''
    def __init__(self, world, local, view, face_ind, seed_geom = None):
        self.world_loc = world
        self.local_loc = local
        self.view = view
        self.face_index = face_ind
        self.segments = []

        #SETTING UP FOR MORE COMPLEX MESH CUTTING    ## SHould this exist in InputPoint??
        self.seed_geom = seed_geom #UNUSED, but will be needed if input point exists on an EDGE or VERT in the source mesh

    def is_endpoint(self):
        if self.seed_geom and self.num_linked_segs > 0: return False  #TODO, better system to delinate edge of mesh
        if self.num_linked_segs < 2: return True # What if self.linked_segs == 2 ??
    def linked_segs(self): return self.segments
    def num_linked_segs(self): return len(self.segments)
    is_endpoint = property(is_endpoint)
    linked_segs = property(linked_segs)
    num_linked_segs = property(num_linked_segs)

    def set_world_loc(self, loc): self.world_loc = loc
    def set_local_loc(self, loc): self.local_loc = loc
    def set_view(self, view): self.view = view
    def set_face_ind(self, face_ind): self.face_index = face_ind

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
class InputSegment(object): #NetworkSegment
    '''
    Representation of a cut between 2 input points
    Equivalent to an "edge" in a mesh connecting to verts
    '''
    def __init__(self, ip0, ip1):
        self.ip0 = ip0
        self.ip1 = ip1
        self.path = []  #list of 3d points for previsualization
        self.bad_segment = False
        ip0.linked_segs.append(self)
        ip1.linked_segs.append(self)

    def linked_points(self): return [self.ip0, self.ip1]
    def is_bad(self): return self.bad_segment
    linked_points = property(linked_points)
    is_bad = property(is_bad)

    def other_point(self, p):
        if p not in self.linked_points: return None
        return self.ip0 if p == self.ip1 else self.ip1

    def detach(self):
        #TODO safety?  Check if in ip0.link_sgements?
        self.ip0.linked_segs.remove(self)
        self.ip1.linked_segs.remove(self)

    def make_path(self, bme, bvh, mx, imx):
        #TODO: Separate this into NetworkCutter.
        # * return either bad segment or other important data.
        f0 = bme.faces[self.ip0.face_index]  #<<--- Current BMFace
        f1 = bme.faces[self.ip1.face_index] #<<--- Next BMFace

        if f0 == f1:
            self.path = [self.ip0.world_loc, self.ip1.world_loc]
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
                self.path = [mx * v for v in vs]
                self.bad_segment = False

            else:  #we failed to find the next face in the face group
                self.bad_segment = True
                self.path = [self.ip0.world_loc, self.ip1.world_loc]
                print('cut failure!!!')

class InputNetwork(object): #InputNetwork
    '''
    Data structure that stores a set of InputPoints that are
    connected with InputSegments.

    InputPoints store a mapping to the source mesh.
    InputPoints and Input segments, analogous to Verts and Edges

    Collection of all InputPoints and Input Segments
    '''
    def __init__(self, source_ob, ui_type="DENSE_POLY"):
        self.source_ob = source_ob
        self.bme = bmesh.new()
        self.bme.from_mesh(self.source_ob.data)
        ensure_lookup(self.bme)
        self.bvh = BVHTree.FromBMesh(self.bme)
        self.mx, self.imx = get_matrices(self.source_ob)
        if ui_type not in {'SPARSE_POLY','DENSE_POLY', 'BEZIER'}:
            self.ui_type = 'SPARSE_POLY'
        else:
            self.ui_type = ui_type

        self.points = []
        self.segments = []  #order not important, but maintain order in this list for indexing?

    def is_empty(self): return (not(self.points or self.segments))
    def num_points(self): return len(self.points)
    def num_segs(self): return len(self.segments)
    is_empty = property(is_empty)
    num_points = property(num_points)
    num_segs = property(num_segs)

    def point_world_locs(self): return [p.world_loc for p in self.points]
    def point_local_locs(self): return [p.local_loc for p in self.points]
    def point_views(self): return [p.view for p in self.points]
    def point_face_indices(self): return [p.face_index for p in self.points]
    point_world_locs = property(point_world_locs)
    point_local_locs = property(point_local_locs)
    point_views = property(point_views)
    point_face_indices = property(point_face_indices)

    def create_point(self, world_loc, local_loc, view, face_ind):
        ''' create an InputPoint '''
        self.points.append(InputPoint(world_loc, local_loc, view, face_ind))
        return self.points[-1]

    def connect_points(self, p1, p2, make_path=True):
        ''' connect 2 points with a segment '''
        self.segments.append(InputSegment(p1, p2))
        if make_path: self.segments[-1].make_path(self.bme, self.bvh, self.mx, self.imx)

    def disconnect_points(self, p1, p2):
        seg = self.are_connected(p1, p2)
        if seg:
            self.segments.remove(seg)
            p1.linked_segs.remove(seg)
            p2.linked_segs.remove(seg)

    def are_connected(self, p1, p2):
        ''' Sees if 2 points are connected, returns connecting segment if True '''
        for seg in p1.linked_segs:
            if seg.other_point(p1) == p2:
                return seg
        return False

    def connected_points(self, p):
        return [seg.other_point(p) for seg in p.linked_segs]

    def insert_point(self, new_p, seg):
        p1 = seg.ip0
        p2 = seg.ip1
        self.disconnect_points(p1,p2)
        self.connect_points(p1, new_p)
        self.connect_points(p2, new_p)

    def remove_point(self, point):
        connected_points = self.connected_points(point)
        for cp in connected_points:
            self.disconnect_points(cp, point)

        if len(connected_points) == 2:
            self.connect_points(connected_points[0], connected_points[1])

        self.points.remove(point)

    def duplicate(self):
        new = InputNetwork(self.source_ob)
        new.points = self.points
        new.segments = self.segments
        return new
