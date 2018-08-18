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
from ..cut_algorithms import cross_section_2seeds_ver1, path_between_2_points, path_between_2_points_clean
from .. import common_drawing
from ..common.rays import get_view_ray_data, ray_cast
from ..common.blender import bversion
from ..common.utils import get_matrices
from ..common.bezier import CubicBezier, CubicBezierSpline
from ..common.shaders import circleShader
from concurrent.futures.thread import ThreadPoolExecutor

class NetworkCutter(object):
    ''' Manages cuts in the InputNetwork '''

    def __init__(self, input_net, net_ui_context):
        #this is all the basic data that is needed
        self.input_net = input_net
        self.net_ui_context = net_ui_context

        #this is fancy "que" of things to be processed
        self.exectutor = ThreadPoolExecutor()  #alright

    def precompute_cut(self, seg):

        print('precomputing cut!')
        #TODO  shuld only take bmesh, input faces and locations.  Should not take BVH ro matrix as inputs
        self.face_chain = []
        #TODO: Separate this into NetworkCutter.
        # * return either bad segment or other important data.
        f0 = self.net_ui_context.bme.faces[seg.ip0.face_index]  #<<--- Current BMFace
        f1 = self.net_ui_context.bme.faces[seg.ip1.face_index] #<<--- Next BMFace

        if f0 == f1:
            seg.path = [seg.ip0.world_loc, seg.ip1.world_loc]
            seg.bad_segment = False  #perhaps a dict self.bad_segments[seg] = True
            return

        ###########################
        ## Define the cutting plane for this segment#
        ############################

        surf_no = self.net_ui_context.imx.to_3x3() * seg.ip0.view.lerp(seg.ip1.view, 0.5)  #must be a better way.
        e_vec = seg.ip1.local_loc - seg.ip0.local_loc
        #define
        cut_no = e_vec.cross(surf_no)
        #cut_pt = .5*self.cut_pts[ind_p1] + 0.5*self.cut_pts[ind]
        cut_pt = .5 * seg.ip0.local_loc + 0.5 * seg.ip1.local_loc

        #find the shared edge,, check for adjacent faces for this cut segment
        cross_ed = None
        for ed in f0.edges:
            if f1 in ed.link_faces:
                cross_ed = ed
                seg.face_chain.add(f1)
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
                vs, eds, eds_crossed, faces_crossed, error = path_between_2_points_clean(self.net_ui_context.bme,
                    seg.ip0.local_loc, seg.ip0.face_index,
                    seg.ip1.local_loc, seg.ip1.face_index,
                    max_tests = 5000, debug = True,
                    prev_face = p_face,
                    use_limit = use_limit,
                    epsilon = epp)
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
                        self.net_ui_context.bme,
                        cut_pt, cut_no,
                        f0.index,seg.ip0.local_loc,
                        #f1.index, self.cut_pts[ind_p1],
                        f1.index, seg.ip1.local_loc,
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
                seg.face_chain = (faces_crossed)
                seg.path = [self.net_ui_context.mx * v for v in vs]
                seg.bad_segment = False

            else:  #we failed to find the next face in the face group
                self.bad_segment = True
                self.path = [self.ip0.world_loc, self.ip1.world_loc]
                print('cut failure!!!')
        
        return
        
    def knife_geometry(self):
        
        cycles = self.input_net.find_network_cycles()
        
        for p_cycle, seg_cycle in cycles:
            
            pass
            #check a closed loop vs edge to edge
            
            #check for nodiness along the lopo that will need to be updated  
            #Eg,an InputPoint that is on BMEdge will be on a BMVert after this cycle is executed
            #For now, nodes are not allowed
            
            
            #check for face_map overlap with other cycles? and update those cycles afterward?
            
            #calculate the face crossings and create new Bmverts
            
            #figure out all the goodness for splititng faces, face changes etc 
            
            
        return    

class InputPoint(object):  # NetworkNode
    '''
    Representation of an input point
    '''
    def __init__(self, world, local, view, face_ind, seed_geom = None):
        self.world_loc = world
        self.local_loc = local
        self.view = view
        self.face_index = face_ind
        self.link_segments = []

        #SETTING UP FOR MORE COMPLEX MESH CUTTING    ## SHould this exist in InputPoint??
        self.seed_geom = seed_geom #UNUSED, but will be needed if input point exists on an EDGE or VERT in the source mesh

    def is_endpoint(self):
        if self.seed_geom and self.num_linked_segs > 0: return False  #TODO, better system to delinate edge of mesh
        if self.num_linked_segs < 2: return True # What if self.linked_segs == 2 ??
        
    def num_linked_segs(self): return len(self.link_segments)
    
    is_endpoint = property(is_endpoint)
    
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

    def are_connected(self, point):   
        '''
        takes another input point, and returns InputSegment if they are connected
        returns False if they are not connected
        '''
        for seg in self.link_segments:
            if seg.other_point(self) == point:
                return seg
            
        return False
    
    
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
        self.points = [ip0, ip1]
        self.path = []  #list of 3d points for previsualization
        self.bad_segment = False
        ip0.link_segments.append(self)
        ip1.link_segments.append(self)

        self.face_chain = []   #TODO, get a better structure within Netork Cutter


    def is_bad(self): return self.bad_segment
    is_bad = property(is_bad)

    def other_point(self, p):
        if p not in self.points: return None
        return self.ip0 if p == self.ip1 else self.ip1

    def detach(self):
        #TODO safety?  Check if in ip0.link_sgements?
        self.ip0.link_segments.remove(self)
        self.ip1.link_segments.remove(self)

    def make_path(self, bme, bvh, mx, imx): 
        #TODO  shuld only take bmesh, input faces and locations.  Should not take BVH ro matrix as inputs
        self.face_chain = []
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
    def __init__(self, net_ui_context, ui_type="DENSE_POLY"):
        self.net_ui_context = net_ui_context
        self.bvh = self.net_ui_context.bvh

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

    def disconnect_points(self, p1, p2):
        seg = self.are_connected(p1, p2)
        if seg:
            self.segments.remove(seg)
            p1.link_segments.remove(seg)
            p2.link_segments.remove(seg)

    def are_connected(self, p1, p2): #TODO: Needs to be in InputPoint 
        ''' Sees if 2 points are connected, returns connecting segment if True '''
        for seg in p1.link_segments:
            if seg.other_point(p1) == p2:
                return seg
        return False

    def connected_points(self, p):
        return [seg.other_point(p) for seg in p.link_segments]

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

    def get_endpoints(self):
        #maybe later...be smart and carefully add/remove endpoints
        #as they are inserted/created/removed etc
        #probably not necessary
        endpoints = [ip for ip in self.points if ip.is_endpoint] #TODO self.endpoints?
        
        return endpoints
        
    def find_network_cycles(self):  #TODO
        #this is the equivalent of "edge_loops"
        #TODO, mirror the get_cycle method from polystrips
        #right now ther eare no T or X junctions, only cuts across mesh or loops within mesh
        #will need to implement "IputNode.get_segment_to_right(InputSegment) to take care this
        
        
        ip_set = set(self.points)
        endpoints = set(self.get_endpoints())
        
        print('There are %i endpoints' % len(endpoints))
        print('there are %i input points' % len(ip_set))
        
        unclosed_ip_cycles = []
        unclosed_seg_cycles = []
        
        def next_segment(ip, current_seg): #TODO Code golf this
            if len(ip.link_segments) != 2: return None  #TODO, the the segment to right
            return [seg for seg in ip.link_segments if seg != current_seg][0]
              
        while len(endpoints):
            current_ip = endpoints.pop()
            ip_start = current_ip
            ip_set.remove(current_ip)
            
            node_cycle = [current_ip]
            if len(current_ip.link_segments) == 0: continue #Lonely Input Point, ingore it
            
            current_seg = current_ip.link_segments[0]
            seg_cycle = [current_seg]
            
            while current_seg:
                next_ip = current_seg.other_point(current_ip)  #always true
                
                if next_ip == ip_start: break  #we have found the end, no need to get the next segment
                
                #take care of sets
                if next_ip in ip_set: ip_set.remove(next_ip)
                if next_ip in endpoints: endpoints.remove(next_ip)
                node_cycle += [next_ip]
                
                #find next segment
                next_seg = next_segment(next_ip, current_seg)
                if not next_seg:  break  #we have found an endpoint
                seg_cycle += [next_seg]
               
                #reset variable for next iteration
                current_ip = next_ip
                current_seg = next_seg
                
            unclosed_ip_cycles += [node_cycle] 
            unclosed_seg_cycles += [seg_cycle] 
         
            
        print('there are %i unclosed cycles' % len(unclosed_ip_cycles))
        print('there are %i ip points in ip set' % len(ip_set))
        for i, cyc in enumerate(unclosed_ip_cycles):
            print('There are %i nodes in %i unclosed cycle' % (len(cyc), i))
        
        ip_cycles = []
        seg_cycles = []   #<<this basicaly becomes a PolyLineKine
        while len(ip_set):
            current_ip = ip_set.pop()
            ip_start = current_ip
                
            node_cycle = [current_ip]
            if len(current_ip.link_segments) == 0: continue #Lonely Input Point, ingore it
            
            current_seg = current_ip.link_segments[0]
            seg_cycle = [current_seg]
            
            while current_seg:
                next_ip = current_seg.other_point(current_ip)  #always true
                
                if next_ip == ip_start: break  #we have found the end, no need to get the next segment
                
                #take care of sets
                if next_ip in ip_set: ip_set.remove(next_ip)  #<-- i what circumstance would this not be true?
                node_cycle += [next_ip]
                
                #find next segment
                next_seg = next_segment(next_ip, current_seg)
                if not next_seg:  break  #we have found an endpoint
                seg_cycle += [next_seg]
               
                #reset variable for next iteration
                current_ip = next_ip
                current_seg = next_seg
                
            ip_cycles += [node_cycle] 
            seg_cycles += [seg_cycle] 
        
        
        print('there are %i closed seg cycles' % len(seg_cycle))
        for i, cyc in enumerate(ip_cycles):
            print('There are %i nodes in %i closed cycle' % (len(cyc), i))
        
        return