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
import random

import bpy
import bmesh
import bgl

from collections import defaultdict
from mathutils import Vector, Matrix, Color, kdtree
from mathutils.bvhtree import BVHTree
from mathutils.geometry import intersect_point_line, intersect_line_plane
from bpy_extras import view3d_utils

from ..bmesh_fns import grow_selection_to_find_face, flood_selection_faces, edge_loops_from_bmedges_old, flood_selection_by_verts, flood_selection_edge_loop, ensure_lookup
from ..cut_algorithms import cross_section_2seeds_ver1, path_between_2_points, path_between_2_points_clean, find_bmedges_crossing_plane
from ..geodesic import GeoPath, geodesic_walk, continue_geodesic_walk, gradient_descent
from .. import common_drawing
from ..common.rays import get_view_ray_data, ray_cast
from ..common.blender import bversion
from ..common.utils import get_matrices
from ..common.bezier import CubicBezier, CubicBezierSpline
from ..common.shaders import circleShader
from ..common.profiler import profiler

from concurrent.futures.thread import ThreadPoolExecutor



#helper function to split a face
def split_face_by_verts(bme, f, ed_enter, ed_exit, bmvert_chain):
    '''
    bme - BMesh
    f - f in bme to be split
    ed_enter - the BMEdge that bmvert_chain[0] corresponds to
    ed_exit - the BMEdge that bmvert_chain[-1] corresponds to
    bmvert_chain - list of BMVerts that define the path that f is split on. len() >= 2
    
    
    returns f1 and f2 the newly split faces
    '''

    if len(ed_enter.link_loops) < 1:
        print('we have no link loops; problem')
        
        print(f)
        print([f.edges[:]])
        
        print(ed_enter)
        print(ed_enter.link_faces[:])
        
        print('there are %i link loops' % len(ed_enter.link_loops))
        return None, None
    
    
    if ed_enter.link_loops[0].face == f:
        l_loop = ed_enter.link_loops[0]
    else:
        
        if len(ed_enter.link_loops) < 2:
            print('we not enough link loops; problem')
        
            print(f)
            print([f.edges[:]])
            
            print(ed_enter)
            print(ed_enter.link_faces[:])
            
            print('there are %i link loops' % len(ed_enter.link_loops))
            return None, None    
        l_loop = ed_enter.link_loops[1]
        
    if ed_enter == None:
        #Error....needs to be an edge
        print('NONE EDGE ENTER')
        return None, None
    if ed_exit == None:
        #Error...needs to be an edg 
        print('NONE EDGE EXIT')
        return None, None
     
    if ed_enter == ed_exit:
        print('ed enter and ed exit the same!')
        
        #determine direction/order of bmvert chain that makes sense
        #by testing distance of bmvert_chain[0].co to link_loop.vert.co
        
        d0 = (bmvert_chain[0].co - l_loop.vert.co).length
        d1 = (bmvert_chain[-1].co - l_loop.vert.co).length
        
        verts = []
        start_loop = l_loop
        l_loop = l_loop.link_loop_next
        iters = 0
        while l_loop != start_loop and iters < 100:
            verts += [l_loop.vert]
            l_loop = l_loop.link_loop_next
            iters += 1
        
        verts += [start_loop.vert]
            
        if iters >= 99:
            
            print('iteration problem')
            
            print(f, ed_enter, ed_exit)
            return None, None
        if d0 < d1:
            f1 = bme.faces.new(verts + bmvert_chain)
            f2 = bme.faces.new(bmvert_chain[::-1])
            
        else:
            f1 = bme.faces.new(verts + bmvert_chain[::-1])
            f2 = bme.faces.new(bmvert_chain)
        
        return f1, f2
    else:
        iters = 0
        verts = []  #the link_loop.vert will be behind the intersection so we don't need to include it
        while l_loop.edge != ed_exit and iters < 100:
            iters += 1
            verts += [l_loop.link_loop_next.vert]
            l_loop = l_loop.link_loop_next
        
        if iters >= 99:
            print('iteration problem')
            print(f, ed_enter, ed_exit)
            return None, None

        f1verts = verts + bmvert_chain[::-1]
        #keep going around
        verts = []
        iters = 0
        while l_loop.edge != ed_enter and iters < 100:
            verts += [l_loop.link_loop_next.vert]
            l_loop = l_loop.link_loop_next
            iters += 1
            
        if iters >= 99:
            print('iteration problem')
            print(f, ed_enter, ed_exit)
            return None, None
        
        
        f1 = bme.faces.new(f1verts)
        f2 = bme.faces.new(verts + bmvert_chain)
        return f1, f2
    

class BMFacePatch(object):
    '''
    Data Structure for managing patches on BMeshes meant to help
    in segmentation of surface patcehs
    '''
    def __init__(self, bmface, local_loc, world_loc, color = (1.0, .7, 0)):
        self.seed_face = bmface
        self.local_loc = local_loc
        self.world_loc = world_loc
        
        self.patch_faces = set()  #will find these
        self.boundary_edges = set() #set of BMEdges
        self.color = Color(color)
        
        
    def grow_seed(self, bme, boundary_edges):  
        island = flood_selection_edge_loop(bme, boundary_edges, self.seed_face, max_iters = 10000)
        self.patch_faces = island
        
    def color_patch(self, color_layer):
        for f in self.patch_faces:
            for loop in f.loops:
                loop[color_layer] = self.color


#Input Net Topolocy Functons to help

def next_segment(ip, current_seg): #TODO Code golf this
    if len(ip.link_segments) != 2: return None  #TODO, the the segment to right
    return [seg for seg in ip.link_segments if seg != current_seg][0]

#TODO def next_segment_to_right(ip, current_segment):
    #if len(ip.link_sgements) > 2:  find the winding
    #if len(ip.link_segments == 2: normal
    #if len(ip.link_segments_ == 1:  return None            
class NetworkCutter(object):
    ''' Manages cuts in the InputNetwork '''

    def __init__(self, input_net, net_ui_context):
        #this is all the basic data that is needed
        self.input_net = input_net
        self.net_ui_context = net_ui_context

        #this is fancy "que" of things to be processed
        self.executor = ThreadPoolExecutor()  
        self.executor_tasks = {}
        
        
        #TODO consider packaging this up into some structure
        self.cut_data = {}  #a dictionary of cut data
        self.ip_bmvert_map = {} #dictionary of new bm verts to InputPoints  in input_net 
        self.reprocessed_edge_map = {}
        self.completed_segments = set()
        
        self.original_indices_map = {}
        self.new_to_old_face_map = {}
        self.old_to_new_face_map = {}
        self.completed_input_points = set()
        
        #have to store all these beacuse we are about to alter the bme
        self.old_face_indices = {}
        for f in self.input_net.bme.faces:
            self.old_face_indices[f.index] = f
            
            
        self.boundary_edges = set()  #this is a list of the newly created cut edges (the seams)
        self.face_patches = []
        
        
        self.active_ip = None
        self.ip_chain = []
        self.ip_set = set()
        
    def update_segments(self):
        
        for seg in self.input_net.segments:
            
            if seg.needs_calculation and not seg.calculation_complete:
                self.precompute_cut(seg)
                
        return
    
    def update_segments_async(self):
        for seg in self.input_net.segments:
            
            if seg.needs_calculation and not seg.calculation_complete:
                seg.needs_calculation = False #this will prevent it from submitting it again before it's done
                                
                #TODO check for existing task
                #TODO if still computing, cancel it
                #start a new task
                future = self.executor.submit(self.precompute_cut, (seg))
                
                self.executor_tasks[seg] = future  
        return
    
    def validate_cdata(self):
        old_cdata = []
        for seg, cdata in self.cut_data.items():
            if seg not in self.input_net.segments:
                old_cdata.append(seg)
        
        for seg in old_cdata:
            self.cut_data.pop(seg, None)
                        
    def compute_cut_normal(self, seg):
        surf_no = self.net_ui_context.imx.to_3x3() * seg.ip0.view.lerp(seg.ip1.view, 0.5)  #must be a better way.
        e_vec = seg.ip1.local_loc - seg.ip0.local_loc
        #define
        cut_no = e_vec.cross(surf_no)
        
        return cut_no              
    def precompute_cut(self, seg):

        print('precomputing cut!')
        #TODO  shuld only take bmesh, input faces and locations.  Should not take BVH or matrix as inputs
        self.face_chain = []

        # * return either bad segment or other important data.
        f0 = self.net_ui_context.bme.faces[seg.ip0.face_index]  #<<--- Current BMFace #TODO use actual BMFace reference
        f1 = self.net_ui_context.bme.faces[seg.ip1.face_index] #<<--- Next BMFace #TODO use actual BMFace reference

        if f0 == f1:
            seg.path = [seg.ip0.world_loc, seg.ip1.world_loc]
            seg.bad_segment = False  #perhaps a dict self.bad_segments[seg] = True
            seg.needs_calculation = False
            seg.calculation_complete = True
            seg.cut_method = 'SAME_FACE'
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
                print('this face is adjacent to the next face')
                cut_data = {} 
                cut_data['face_crosses'] = []
                cut_data['face_set'] = set()
                cut_data['edge_crosses'] = [ed]
                cross = intersect_line_plane(ed.verts[0].co, ed.verts[1].co, cut_pt, cut_no)
                cut_data['verts'] = [cross]
                self.cut_data[seg] = cut_data
                
                seg.path = [self.net_ui_context.mx * v for v in [seg.ip0.local_loc, cross, seg.ip1.local_loc]] #TODO
                cross_ed = ed
                seg.needs_calculation = False
                seg.calculation_complete = True
                seg.bad_segment = False
                seg.cut_method = 'ADJACENT_FACE'
                break

        #if no shared edge, need to cut across to the next face
        if not cross_ed:
            p_face = None

            vs = []
            epp = .0000000001
            use_limit = True
            attempts = 0
            seg.cut_method = 'PATH_2_POINTS'
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
                    print('too bad, could not adjust due to ' + error)
                    print(p_face)
                    print(f0)
                    break

            if not len(vs):
                print('\n')
                print('CUTTING METHOD 2seeds ver1')
                seg.cut_method = 'CROSS_SECTION_2_SEEDS'
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
                seg.face_chain = faces_crossed
                seg.path = [self.net_ui_context.mx * v for v in vs]
                seg.bad_segment = False
                seg.needs_calculation = False
                seg.calculation_complete = True

                cut_data = {} 
                cut_data['face_crosses'] = faces_crossed
                cut_data['face_set'] = set(faces_crossed)
                cut_data['edge_crosses'] = eds_crossed
                cut_data['verts'] = vs
                
                old_cdata = []
                for other_seg, cdata in self.cut_data.items():
                    if other_seg == seg: continue
                    if other_seg not in self.input_net.segments:
                        continue
                    
                    if not cut_data['face_set'].isdisjoint(cdata['face_set']):
                        bad_seg = False
                
                        print("\n Found self intersection on this segment")
                        
                        overlap = cut_data['face_set'].intersection(cdata['face_set'])
                        
                        middle_overlap = overlap - set([cdata['face_crosses'][0], cdata['face_crosses'][-1]])
                        
                        if len(middle_overlap):
                            print('there is a middle self intersection')
                            bad_seg = True
                        #if overlap includes faces other than tip and tail
                        
                        #check that it does not touch any InputPoint faces
                        ipfaces = set(ip.bmface for ip in self.input_net.points)
                        if not cut_data['face_set'].isdisjoint(ipfaces):
                            print('crossed an IP Face, needs to not do that')
                            bad_seg = True
                        
                        if bad_seg:
                            seg.bad_segment = True #intersection
                            if seg in self.cut_data:
                                self.cut_data.pop(seg, None)
                        
                            print('\n')
                            #only return if there is a forbidden self intersection
                            return  #found a self intersection, for now forbidden
                    
                self.cut_data[seg] = cut_data
                
            else:  #we failed to find the next face in the face group
                seg.bad_segment = True
                seg.needs_calculation = False
                seg.calculation_complete = True
                seg.path = [seg.ip0.world_loc, seg.ip1.world_loc]
                print('cut failure!!!')
                
        return
    
    
    def pre_vis_geo(self, seg, bme, bvh, mx):

        geo = GeoPath(bme, bvh, mx)
        geo.seed = bme.faces[seg.ip0.face_index]
        geo.seed_loc = seg.ip0.local_loc
        geo.target = bme.faces[seg.ip1.face_index]
        geo.target_loc =  seg.ip0.local_loc
            
        geo.calculate_walk()
        
        self.geodesic = geo
        
        if geo.found_target():
            geo.gradient_descend()
            seg.path = [mx * v for v in geo.path]

    def preview_bad_segments_geodesic(self):
        for seg in self.input_net.segments:
            if seg.bad_segment:
                self.pre_vis_geo(seg, self.input_net.bme, self.input_net.bvh, self.net_ui_context.mx)   


    #########################################################
    #### Helper Functions for committing cut ot BMesh #######
    #########################################################
    
    def find_old_face(self, new_f, max_iters = 5):
        '''
        iteratively drill down to find source face of new_f
        TODO return a list in order of inheritance?
        '''
        iters = 0
        old_f = None
        while iters < max_iters:
            iters += 1
            if new_f not in self.new_to_old_face_map: break
            old_f = self.new_to_old_face_map[new_f]
            new_f = old_f
            
        return old_f
        
    def find_new_faces(self, old_f, max_iters = 5):
        '''
        TODO, may want to only find NEWEST
        faces
        '''    
        if old_f not in self.old_to_new_face_map: return []
        
        iters = 0
        new_fs = []
        
        child_fs = self.old_to_new_face_map[old_f]
        new_fs += child_fs
        while iters < max_iters and len(child_fs):
            iters += 1
            next_gen = []
            for f in child_fs:
                if f in self.old_to_new_face_map:
                    next_gen += self.old_to_new_face_map[f] #this is always a pair
            
            new_fs += next_gen
            child_fs = next_gen

        #new_fs = old_to_new_face_map[old_f]
            
        return new_fs
            
    def find_newest_faces(self,old_f, max_iters = 5):
        '''
        '''    
        if old_f not in self.old_to_new_face_map: return []
        
        iters = 0
        child_fs = self.old_to_new_face_map[old_f]
        newest_faces = []
        
        if not any([f in self.old_to_new_face_map for f in child_fs]):
            return child_fs
        
        while iters < max_iters and any([f in self.old_to_new_face_map for f in child_fs]):
            iters += 1
            next_gen = []
            for f in child_fs:
                if f in self.old_to_new_face_map:
                    next_gen += self.old_to_new_face_map[f]
            
                else:
                    newest_faces += [f]
                    
                print(f)
            print(next_gen)
            child_fs = next_gen

        return newest_faces  
    
    def remap_input_point(self, ip):

        if ip.bmface not in self.old_to_new_face_map: return
        newest_faces = self.find_newest_faces(ip.bmface)
        found = False
        for new_f in newest_faces:
            if bmesh.geometry.intersect_face_point(new_f, ip.local_loc):
                print('found the new face that corresponds')
                f = new_f
                found = True
                ip.bmface = f
                break
            
        return found
            
        
        #identify closed loops in the input
        #we might need to recompute cycles if we are creating new segments   
        
    def find_ip_chain_edgepoint(self,ip):
        '''
        will find all the Input Points that are connected
        to and on the same face as ip
        '''
        #TODO, split this off, thanks
        ip_chain =[ip]
        current_seg = ip.link_segments[0]  #edge poitns only have 1 seg
        ip_next = current_seg.other_point(ip)

        if not ip_next.bmface.is_valid:
            remap_input_point(ip_next)
            
        while ip_next and ip_next.bmface == ip.bmface:
            
            #if ip_next in ip_set:
            #    ip_set.remove(ip_next)  #TODO, remove the whole chain from ip_set
                
            ip_chain += [ip_next]
            
            next_seg = next_segment(ip_next, current_seg)
            if next_seg == None: 
                print('there is no next seg')
                break
        
            ip_next = next_seg.other_point(ip_next)
            if not ip_next.bmface.is_valid:
                self.remap_input_point(ip_next)
            
            if ip_next.is_edgepoint(): 
                #ip_set.remove(ip_next)
                ip_chain += [ip_next]
                break
            current_seg = next_seg
            
            #implied if ip_next.bmface != ip.bmface...we have stepped off of this face
        

        return ip_chain
        
    def find_ip_chain_facepoint(self,ip):
        '''
        this is the more generic which finds the chain
        in both directions along an InputPoint
        '''
                
        ip_chain = []
        
        #wak forward and back
        chain_0 = []
        chain_1 = []
        for seg in ip.link_segments:
            
            if seg == ip.link_segments[0]:
                chain = chain_0
            else:
                chain = chain_1
            
            current_seg = seg
            ip_next = current_seg.other_point(ip)
        
            if not ip_next.bmface.is_valid:
                remap_input_point(ip_next)

            while ip_next and ip_next.bmface == ip.bmface:  #walk along the input segments as long as the next input point is on the same face
                #if ip_next in ip_set:  #we remove it here only if its on the same face
                #    ip_set.remove(ip_next)
        
                chain += [ip_next]
                next_seg = next_segment(ip_next, current_seg)
                if next_seg == None: 
                    print('there is no next seg we are on an open loop')
                    break
        
                ip_next = next_seg.other_point(ip_next)
                if not ip_next.bmface.is_valid:
                    remap_input_point(ip_next)
                if ip_next.is_edgepoint(): 
                    print('we broke on an endpoint')
                    #ip_set.remove(ip_next)
                    break
                current_seg = next_seg
            
        chain_0.reverse()
        
        if len(chain_0)  and len(chain_1):
            print(chain_0 + [ip] + chain_1)
            
        return chain_0 + [ip] + chain_1    
   
    def knife_gometry_stepper_prepare(self):
        
        self.new_bmverts = set()
        for ip in self.input_net.points:
            bmv = self.input_net.bme.verts.new(ip.local_loc)
            self.ip_bmvert_map[ip] = bmv
            self.new_bmverts.add(bmv)
        
        self.input_net.bme.verts.ensure_lookup_table()
        self.input_net.bme.edges.ensure_lookup_table()
        self.input_net.bme.faces.ensure_lookup_table()
        
        ip_cycles, seg_cycles = self.input_net.find_network_cycles()
        
        #create a set of input points that we will pull from
        self.ip_set = set()
        
        for ip_cyc in ip_cycles:
            self.ip_set.update(ip_cyc)
        
        #pick an active IP
        self.active_ip = self.ip_set.pop()
        
        if self.active_ip.is_edgepoint():
            self.ip_chain = self.find_ip_chain_edgepoint(self.active_ip)
        else:
            self.ip_chain = self.find_ip_chain_facepoint(self.active_ip)
        
    def knife_geometry_step(self):
        
        #ensure we have prepared
        if len(self.ip_set) == 0: return
        
        #just pick one
        self.active_ip = self.ip_set.pop()
        
        #find all connected IP on the same face
        if self.active_ip.is_edgepoint():
            self.ip_chain = self.find_ip_chain_edgepoint(self.active_ip)
        else:
            self.ip_chain = self.find_ip_chain_facepoint(self.active_ip)
    
        print(len(self.ip_chain))
        
    def knife_geometry3(self):
        #check all deferred calculations
        knife_sart = time.time()
        for seg in self.input_net.segments:
            if (seg.needs_calculation == True) or (seg.calculation_complete == False):
                print('segments still computing')
                return
            
            if seg.is_bad:
                print('bad_segment')  #TODO raise error message #TODO put this in a can_start/can_enter kind of check
                return
        #ensure no bad segments
        
        
        #dictionaries to map newly created faces to their original faces and vice versa
        original_face_indices = self.original_indices_map
        new_to_old_face_map = self.new_to_old_face_map
        old_to_new_face_map = self.old_to_new_face_map
        completed_segments = self.completed_segments
        completed_input_points = self.completed_input_points
        ip_bmvert_map = self.ip_bmvert_map
    
        new_bmverts = set()
        
       
        
        #helper function to walk along input point chains
        def next_segment(ip, current_seg): #TODO Code golf this
            if len(ip.link_segments) != 2: return None  #TODO, the the segment to right
            return [seg for seg in ip.link_segments if seg != current_seg][0]
        
        def find_old_face(new_f, max_iters = 5):
            '''
            iteratively drill down to find source face of new_f
            TODO return a list in order of inheritance?
            '''
            iters = 0
            old_f = None
            while iters < max_iters:
                iters += 1
                if new_f not in new_to_old_face_map: break
                old_f = new_to_old_face_map[new_f]
                new_f = old_f
                
            return old_f
        
        def find_new_faces(old_f, max_iters = 5):
            '''
            TODO, may want to only find NEWEST
            faces
            '''    
            if old_f not in old_to_new_face_map: return []
            
            iters = 0
            new_fs = []
            
            child_fs = old_to_new_face_map[old_f]
            new_fs += child_fs
            while iters < max_iters and len(child_fs):
                iters += 1
                next_gen = []
                for f in child_fs:
                    if f in old_to_new_face_map:
                        next_gen += old_to_new_face_map[f] #this is always a pair
                
                new_fs += next_gen
                child_fs = next_gen
    
            #new_fs = old_to_new_face_map[old_f]
                
            return new_fs
            
        def find_newest_faces(old_f, max_iters = 5):
            '''
            '''    
            if old_f not in old_to_new_face_map: return []
            
            iters = 0
            child_fs = old_to_new_face_map[old_f]
            newest_faces = []
            
            if not any([f in old_to_new_face_map for f in child_fs]):
                return child_fs
            
            while iters < max_iters and any([f in old_to_new_face_map for f in child_fs]):
                iters += 1
                next_gen = []
                for f in child_fs:
                    if f in old_to_new_face_map:
                        next_gen += old_to_new_face_map[f]
                
                    else:
                        newest_faces += [f]
                        
                    print(f)
                print(next_gen)
                child_fs = next_gen

            return newest_faces     
        
        def recompute_segment(seg):
            
            '''
            recomputation most often needs to happen with the first or last face is crossed by
            2 segments.  It also happens when the user draws self intersecting cuts which
            is less common is handled by this
            '''
            if seg not in self.cut_data:  #check for pre-processed cut data
                print('no cut data for this segment, must need to precompute or perhaps its internal to a face')
                
                print(seg.ip0.bmface)
                print(seg.ip1.bmface)
                
                seg.ip0.bmface.select_set(True)
                seg.ip1.bmface.select_set(True)
                
                print("NOT RECOMPUTING?")
                print(seg.cut_method)
                return False
            
            start = time.time()
            cdata = self.cut_data[seg]
            bmedge_to_new_vert_map = {}
            cdata['bmedge_to_new_bmv'] = bmedge_to_new_vert_map
            
            bad_fs = [f for f in cdata['face_crosses'] if not f.is_valid]
            tip_bad = cdata['face_crosses'][0].is_valid == False
            tail_bad = cdata['face_crosses'][-1].is_valid == False
    
            #check for self intersections in the middle
            #if tip_bad and not tail_bad and len(bad_fs) > 1:
            #    print('bad tip, and bad middle not handled')
            #    return False
            
            #if tail_bad and not tip_bad and len(bad_fs) > 1:
            #    print('bad tail, and bad middle not handled')
            #    return False
            
            #if tip_bad and tail_bad and len(bad_fs) > 2:
            #    print('bad tip, tail and, middle not handled')
            #    return False
            
            #if not tip_bad and not tail_bad and len(bad_fs) >= 1:
            #    print('just a bad middle, not handled')
            #    return False
            
            #print('there are %i bad faces' % len(bad_fs))
            
            
            tip_bad, tail_bad = False, False
            
            f0 = seg.ip0.bmface  #TODO check validity in case rare cutting on IPFaces
            f1 = seg.ip1.bmface  #TDOO check validity in case rare cutting on IPFaces
            
            no = self.compute_cut_normal(seg)
            if len(cdata['edge_crosses']) == 2 and len(cdata['face_crosses']) == 1:
                tip_bad = True
                tail_bad = True
                co0 = cdata['verts'][0]
                co1 = cdata['verts'][0]  #wait shouldn't this be verts [1]
                new_fs = find_new_faces(cdata['face_crosses'][0])
                
                #fix the tip
                #find the new edge in new_faces that matches old ed_crosses[0]
                fixed_tip, fixed_tail = False, False
                for f in new_fs:
                    ed_inters = find_bmedges_crossing_plane(co0, no, f.edges[:], .000001, sort = True)
                    if len(ed_inters):
                        ed, loc = ed_inters[0]
                        
                        print('reality check, distance co to loc %f' % (co0 - loc).length)
                        
                        #create the new tip vertex
                        bmv = self.input_net.bme.verts.new(co0)
                        new_bmverts.add(bmv)
                        
                        #map the new edge and the old edge to that vertex
                        cdata['bmedge_to_new_bmv'][ed] = bmv
                        cdata['bmedge_to_new_bmv'][cdata['edge_crosses'][0]] = bmv
                        
                        #map new edge to old edge
                        self.reprocessed_edge_map[ed] = cdata['edge_crosses'][0]
                        #replace old edge  ed_crosses[0] with the new edge for
                        cdata['edge_crosses'][0] = ed
                        cdata['face_crosses'][0] = f
                        
                        print('this edge should be the edge we find in the tail ')
                        print(ed_inters[1])
                        
                        break
                #fix the tail
                for f in new_fs:
                    ed_inters = find_bmedges_crossing_plane(co1, no, f.edges[:], .000001, sort = True)
                    if len(ed_inters):
                        ed, loc = ed_inters[0]
                        
                        print('reality check, distance co to loc %f' % (co1 - loc).length)
                        
                        #create the new tip vertex
                        bmv = self.input_net.bme.verts.new(co1)
                        new_bmverts.add(bmv)
                        #map the new edge and the old eget to that vertex
                        cdata['bmedge_to_new_bmv'][ed] = bmv
                        cdata['bmedge_to_new_bmv'][cdata['edge_crosses'][1]] = bmv
                        #map old edge to new edge
                        self.reprocessed_edge_map[ed] = cdata['edge_crosses'][1]
                        #replace ed_crosses[0] with the new edge for
                        cdata['edge_crosses'][1] = ed
                        
                        print('does this edge match?')
                        print(ed)
                        
                        #there is only one face so we already did that
                
                return
            
            elif len(cdata['edge_crosses']) > 2 and len(cdata['face_crosses']) > 1:
                tip_bad = cdata['face_crosses'][0].is_valid == False
                tail_bad = cdata['face_crosses'][-1].is_valid == False
                
                
                co0 = cdata['verts'][0]
                co1 = cdata['verts'][-1]
                
                new_fs = find_new_faces(cdata['face_crosses'][0])
                #fix the tip
                #find the new edge in new_faces that matches old ed_crosses[0]
                fixed_tip, fixed_tail = False, False
                for f in new_fs:
                    ed_inters = find_bmedges_crossing_plane(co0, no, f.edges[:], .000001, sort = True)
                    if len(ed_inters):
                        ed, loc = ed_inters[0]
                        ed1, loc1 = ed_inters[1]
                        
                        print('reality check, distance co to loc %f' % (co0 - loc).length)
                        
                        #create the new tip vertex
                        bmv = self.input_net.bme.verts.new(co0)
                        new_bmverts.add(bmv)
                        #map the new edge and the old eget to that vertex
                        cdata['bmedge_to_new_bmv'][ed] = bmv
                        cdata['bmedge_to_new_bmv'][cdata['edge_crosses'][0]] = bmv
                        #map the new edge to the old edge
                        self.reprocessed_edge_map[ed] = cdata['edge_crosses'][0]
                        #replace ed_crosses[0] with the new edge for
                        cdata['edge_crosses'][0] = ed
                        cdata['face_crosses'][0] = f
                        
                        #now....will the exit edge be the same?
                        cdata['edge_crosses'][1] = ed1
                        
                        #cdata['verts'].pop(0) #prevent a double vert creation
                        #cdata['edge_crosses'].pop(0)
                        
                        print('link faces of redge one')
                        print([f for f in ed1.link_faces])
                        
                        break
                
                #fix the tail
                print('fixnig a bad tail on segment')
                new_fs = find_new_faces(cdata['face_crosses'][-1])
                for f in new_fs:
                    ed_inters = find_bmedges_crossing_plane(co1, no, f.edges[:], .000001, sort = True)
                    if len(ed_inters):
                        ed, loc = ed_inters[0]
                        ed1, loc1 = ed_inters[1]
                        print('reality check, distance co to loc %f' % (co1 - loc).length)
                        #create the new tip vertex
                        bmv = self.input_net.bme.verts.new(co1)
                        new_bmverts.add(bmv)
                        #map the new edge and the old edge to the new BMVert
                        cdata['bmedge_to_new_bmv'][ed] = bmv
                        cdata['bmedge_to_new_bmv'][cdata['edge_crosses'][-1]] = bmv
                        
                        #map the new edge to the old edge
                        self.reprocessed_edge_map[ed] = cdata['edge_crosses'][-1]
                        #replace old edge ed_crosses[-1] with the new edge for
                        cdata['edge_crosses'][-1] = ed
                        cdata['face_crosses'][-1] = f
                        cdata['edge_crosses'][-2] = ed1
                        
                        #cdata['verts'].pop() #prevent a double vert creation
                        #cdata['edge_crosses'].pop()
                        
                        print('link faces of edge one')
                        print([f for f in ed1.link_faces])
                        break        
            
            if tip_bad or tail_bad:
                print('fixed tip and tail , process again')
                
                #create all verts on this segment
                for i, co in enumerate(cdata['verts']):
                    if tip_bad and i == 0: continue
                    if tail_bad and i == len(cdata['verts']) - 1: continue
                    bmedge = cdata['edge_crosses'][i]
                    bmv = self.input_net.bme.verts.new(co)
                    bmedge_to_new_vert_map[bmedge] = bmv
                    new_bmverts.add(bmv)
            
                #now process all the faces crossed
                #for a face to be crossed 2 edges of the face must be crossed
                for f in cdata['face_crosses']:
                    ed_enter = None
                    ed_exit = None
                    bmvs = []
                    for ed in f.edges:
                        if ed in cdata['bmedge_to_new_bmv']:
                            bmvs.append(cdata['bmedge_to_new_bmv'][ed])
                            if ed_enter == None:
                                ed_enter = ed
                            else:
                                ed_exit = ed
                                
                        elif ed in self.reprocessed_edge_map:
                            print('Found reprocessed edge')
                            re_ed = self.reprocessed_edge_map[ed]
                            if re_ed in cdata['bmedge_to_new_bmv']:
                                bmvs.append(cdata['bmedge_to_new_bmv'][ed])
                                if ed_enter == None:
                                    ed_enter = ed
                                else:
                                    ed_exit = ed    
                    
                    if ed_enter == None:
                        print('No ed enter')
                        f.select_set(True)
                        print(f)
                        continue
                    if ed_exit == None:
                        print('no ed exit')
                        f.select_set(True)
                        print(f)
                        continue
                    if len(bmvs) != 2:
                        print('bmvs not 2')
                        continue
                    
                    #print(ed_enter, ed_exit, bmvs)
                    f1, f2 = split_face_by_verts(self.input_net.bme, f, ed_enter, ed_exit, bmvs)   
                    if f1 == None or f2 == None:
                        print('could not split faces in process segment')
                        #self.net_ui_context.bme.to_mesh(self.net_ui_context.ob.data)
                        return
                        #continue 
                    new_to_old_face_map[f1] = f
                    new_to_old_face_map[f2] = f
                    
                    #if this is an original face, store it's index because bvh is going to report original mesh indices
                    if f not in new_to_old_face_map:
                        original_face_indices[f.index] = f
                        
                    old_to_new_face_map[f] = [f1, f2]
                    
            
            finish = time.time()
            print('Made new faces in %f seconds' % (finish - start))
                
            #delete all old faces and edges from bmesh
            #but references remain in InputNetwork elements like InputPoint!
            delete_face_start = time.time()
            #bmesh.ops.delete(self.input_net.bme, geom = cdata['face_crosses'], context = 3)
            for f in cdata['face_crosses']:
                self.input_net.bme.faces.remove(f)
            delete_face_finish = time.time()
            print('Deleted old faces in %f seconds' % (delete_face_finish - delete_face_start))   
            
            delete_edges_start = time.time()    
            del_edges = [ed for ed in cdata['edge_crosses'] if len(ed.link_faces) == 0]
            del_edges = list(set(del_edges))
            #bmesh.ops.delete(self.input_net.bme, geom = del_edges, context = 4)
            for ed in del_edges:
                self.input_net.bme.edges.remove(ed)
            delete_edges_finish = time.time()
            print('Deleted old edges in %f seconds' % (delete_edges_finish - delete_edges_start))
            start = finish
            
            
            completed_segments.add(seg)
            #self.net_ui_context.bme.to_mesh(self.net_ui_context.ob.data)
                
                  
            return False
                    
        def process_segment(seg):
            if seg not in self.cut_data:  #check for pre-processed cut data
                print('no cut data for this segment, must need to precompute or perhaps its internal to a face')
                
                print(seg.ip0.bmface)
                print(seg.ip1.bmface)
                
                print(seg.cut_method)
                seg.ip0.bmface.select_set(True)
                seg.ip1.bmface.select_set(True)
                
                print('PROCESS SEGMENT')
                
                return False
            
            if not all([f.is_valid for f in self.cut_data[seg]['face_crosses']]):  #check the validity of the pre-processed data
                print('segment out of date')
                recompute_segment(seg)
                return False
            
            if seg not in self.cut_data: #dumb check after recompute, #TODO, kick us back out into modal
                print('there is no cut data for this segment')
                return False
            
            if seg in completed_segments:  #don't attempt to cut it again.  TODO, delete InputSegment?  Return some flag for completed?
                print('segment already completed')
                return False
            
            start = time.time()
            
            cdata = self.cut_data[seg]
            if 'bmedge_to_new_bmv' not in cdata:
                bmedge_to_new_vert_map = {}
                cdata['bmedge_to_new_bmv'] = bmedge_to_new_vert_map  #yes, keep a map on the per segment level and on the whole network level
            else:
                bmedge_to_new_vert_map = cdata['bmedge_to_new_bmv']
                
            #create all verts on this segment
            for i, co in enumerate(cdata['verts']):
                bmedge = cdata['edge_crosses'][i]
                bmv = self.input_net.bme.verts.new(co)
                bmedge_to_new_vert_map[bmedge] = bmv
                new_bmverts.add(bmv)
            #now process all the faces crossed
            #for a face to be crossed 2 edges of the face must be crossed
            for f in cdata['face_crosses']:
                ed_enter = None
                ed_exit = None
                bmvs = []
                for ed in f.edges:
                    if ed in cdata['bmedge_to_new_bmv']:
                        bmvs.append(cdata['bmedge_to_new_bmv'][ed])
                        if ed_enter == None:
                            ed_enter = ed
                        else:
                            ed_exit = ed
                            
                    elif ed in self.reprocessed_edge_map:
                        print('Found reprocessed edge')
                        re_ed = self.reprocessed_edge_map[ed]
                        if re_ed in cdata['bmedge_to_new_bmv']:
                            bmvs.append(cdata['bmedge_to_new_bmv'][ed])
                            if ed_enter == None:
                                ed_enter = ed
                            else:
                                ed_exit = ed    
                
                if ed_enter == None:
                    print('No ed enter')
                    f.select_set(True)
                    print(f)
                    continue
                if ed_exit == None:
                    print('no ed exit')
                    f.select_set(True)
                    print(f)
                    continue
                
                if len(bmvs) != 2:
                    print('bmvs not 2')
                    continue
                
                #print(ed_enter, ed_exit, bmvs)
                f1, f2 = split_face_by_verts(self.input_net.bme, f, ed_enter, ed_exit, bmvs)   
                if f1 == None or f2 == None:
                    print('could not split faces in process segment')
                    #self.net_ui_context.bme.to_mesh(self.net_ui_context.ob.data)
                    return
                    #continue 
                new_to_old_face_map[f1] = f
                new_to_old_face_map[f2] = f
                
                if f not in new_to_old_face_map:
                    original_face_indices[f.index] = f
                        
                old_to_new_face_map[f] = [f1, f2]
                
            finish = time.time()
            print('finished adding new faces in %f seconds' % (finish - start))
            
            
            #delete all old faces and edges from bmesh
            #but references remain in InputNetwork elements like InputPoint!
            #perhaps instead of deleting them on the fly, collect them and then delete them
            face_delete_start = time.time()
            #bmesh.ops.delete(self.input_net.bme, geom = cdata['face_crosses'], context = 3)
            
            #try and remove manually
            for bmf in cdata['face_crosses']:
                self.input_net.bme.faces.remove(bmf)
                
            face_delete_finish = time.time()
            print('deleted old faces in %f seconds' % (face_delete_finish - face_delete_start))
            
            
            edge_delete_start = time.time()
            del_edges = [ed for ed in cdata['edge_crosses'] if len(ed.link_faces) == 0]
            del_edges = list(set(del_edges))
            #bmesh.ops.delete(self.input_net.bme, geom = del_edges, context = 4)
            for ed in del_edges:
                self.input_net.bme.edges.remove(ed)
            edge_delete_finish = time.time()
            print('deleted old edges in %f seconds' % (edge_delete_finish - edge_delete_start))
            completed_segments.add(seg)
            #self.net_ui_context.bme.to_mesh(self.net_ui_context.ob.data)
            
            return
        
        #first, we wil attempt to process every segment
        
        #all input points get a BMVert
        
        def remap_input_point(ip):

            if ip.bmface not in old_to_new_face_map: return
            newest_faces = find_newest_faces(ip.bmface)
            found = False
            for new_f in newest_faces:
                if bmesh.geometry.intersect_face_point(new_f, ip.local_loc):
                    print('found the new face that corresponds')
                    f = new_f
                    found = True
                    ip.bmface = f
                    break
                
            return found
            
        
        #identify closed loops in the input
        #we might need to recompute cycles if we are creating new segments   
        
        def find_ip_chain_edgepoint(ip):
            '''
            will find all the Input Points that are connected
            to and on the same face as ip
            '''
            #TODO, split this off, thanks
            ip_chain =[ip]
            current_seg = ip.link_segments[0]  #edge poitns only have 1 seg
            ip_next = current_seg.other_point(ip)

            if not ip_next.bmface.is_valid:
                remap_input_point(ip_next)
                
            while ip_next and ip_next.bmface == ip.bmface:
                
                #if ip_next in ip_set:
                #    ip_set.remove(ip_next)  #TODO, remove the whole chain from ip_set
                    
                ip_chain += [ip_next]
                
                next_seg = next_segment(ip_next, current_seg)
                if next_seg == None: 
                    print('there is no next seg')
                    break
            
                ip_next = next_seg.other_point(ip_next)
                if not ip_next.bmface.is_valid:
                    remap_input_point(ip_next)
                
                if ip_next.is_edgepoint(): 
                    #ip_set.remove(ip_next)
                    ip_chain += [ip_next]
                    break
                current_seg = next_seg
                
                #implied if ip_next.bmface != ip.bmface...we have stepped off of this face
            

            return ip_chain
        
        def find_ip_chain_facepoint(ip):
            '''
            this is the more generic which finds the chain
            in both directions along an InputPoint
            '''
                    
            ip_chain = []
            
            #wak forward and back
            chain_0 = []
            chain_1 = []
            for seg in ip.link_segments:
                
                if seg == ip.link_segments[0]:
                    chain = chain_0
                else:
                    chain = chain_1
                
                current_seg = seg
                ip_next = current_seg.other_point(ip)
            
                if not ip_next.bmface.is_valid:
                    remap_input_point(ip_next)

                while ip_next and ip_next.bmface == ip.bmface:  #walk along the input segments as long as the next input point is on the same face
                    #if ip_next in ip_set:  #we remove it here only if its on the same face
                    #    ip_set.remove(ip_next)
            
                    chain += [ip_next]
                    next_seg = next_segment(ip_next, current_seg)
                    if next_seg == None: 
                        print('there is no next seg we are on an open loop')
                        break
            
                    ip_next = next_seg.other_point(ip_next)
                    if not ip_next.bmface.is_valid:
                        remap_input_point(ip_next)
                    if ip_next.is_edgepoint(): 
                        print('we broke on an endpoint')
                        #ip_set.remove(ip_next)
                        break
                    current_seg = next_seg
                
            chain_0.reverse()
            
            if len(chain_0)  and len(chain_1):
                print(chain_0 + [ip] + chain_1)
                
            return chain_0 + [ip] + chain_1

        def split_ip_face_edgepoint(ip):
            
            ip_chain = find_ip_chain_edgepoint(ip)
            
            ed_enter = ip_chain[0].seed_geom # this is the entrance edge
            
            if len(ip_chain) > 1 and ip_chain[-1].is_edgepoint():  #cut across a single face from edge to tedge
                bmvert_chain  = [self.ip_bmvert_map[ipc] for ipc in ip_chain]           
                ed_exit = ip_chain[-1].seed_geom
            else:
                if current_seg not in completed_segments:
                    result = process_segment(current_seg)
                    #self.net_ui_context.bme.to_mesh(self.net_ui_context.ob.data)
                    #return
            
                if current_seg.ip0 == ip_next:  #test the direction of the segment
                    ed_exit = self.cut_data[current_seg]['edge_crosses'][-1]
                else:
                    ed_exit = self.cut_data[current_seg]['edge_crosses'][0]
                
                bmvert_chain  = [self.ip_bmvert_map[ipc] for ipc in ip_chain] + \
                            [self.cut_data[current_seg]['bmedge_to_new_bmv'][ed_exit]]
            

            self.input_net.bme.verts.ensure_lookup_table()
            self.input_net.bme.edges.ensure_lookup_table()
            self.input_net.bme.faces.ensure_lookup_table()  
                
            f = ip.bmface
            f1, f2 = split_face_by_verts(self.input_net.bme, f, ed_enter, ed_exit, bmvert_chain)
            
            if f1 != None and f2 != None:
                new_to_old_face_map[f1] = f
                new_to_old_face_map[f2] = f
                old_to_new_face_map[f] = [f1, f2]
                
                if f not in new_to_old_face_map:
                    original_face_indices[f.index] = f
                
                self.input_net.bme.faces.remove(f)
                #bmesh.ops.delete(self.input_net.bme, geom = [f], context = 3)
                
                del_eds = [ed for ed in [ed_enter, ed_exit] if len(ed.link_faces) == 0]
                del_eds = list(set(del_eds))
                
                for ded in del_eds:
                    self.input_net.bme.edges.remove(ded)
                #bmesh.ops.delete(self.input_net.bme, geom = del_eds, context = 4)
            
            else:
                #self.net_ui_context.bme.to_mesh(self.net_ui_context.ob.data)
                print('f1 or f2 is none why')
                return
######################################################################
################33 ORIGINAL FUNCTION  ################################            
        ip_cycles, seg_cycles = self.input_net.find_network_cycles()
        
                
        for ip in self.input_net.points:
            bmv = self.input_net.bme.verts.new(ip.local_loc)
            self.ip_bmvert_map[ip] = bmv
            new_bmverts.add(bmv)
        
        
        for ip_cyc in ip_cycles:
            ip_set = set(ip_cyc)
            
            for i, ip in enumerate(ip_cyc):
                print('\n')
                print('attempting ip %i' % i)
                start = time.time()
                if ip not in ip_set: 
                    print('Already seen this IP %i' % i)
                    #print(ip)
                    continue #already handled this one

                if not ip.bmface.is_valid:
                    remap_input_point(ip)
                #print(ip)
                if ip.is_edgepoint(): #we have to treat edge points differently
                    print('cutting starting at boundary edge point')
                    #TODO, split this off, thanks
                    ip_chain =[ip]
                    current_seg = ip.link_segments[0]  #edge poitns only have 1 seg
                    ip_next = current_seg.other_point(ip)
    
                    if not ip_next.bmface.is_valid:
                        remap_input_point(ip_next)
                        
                    while ip_next and ip_next.bmface == ip.bmface:
                        
                        if ip_next in ip_set:
                            ip_set.remove(ip_next)
                            
                        ip_chain += [ip_next]
                        
                        next_seg = next_segment(ip_next, current_seg)
                        if next_seg == None: 
                            print('there is no next seg')
                            break
                    
                        ip_next = next_seg.other_point(ip_next)
                        if not ip_next.bmface.is_valid:
                            remap_input_point(ip_next)
                        
                        if ip_next.is_edgepoint(): 
                            ip_set.remove(ip_next)
                            break
                        current_seg = next_seg
                    

                    ed_enter = ip_chain[0].seed_geom # this is the entrance edge
                    
                    if ip_next.is_edgepoint():
                        bmvert_chain  = [self.ip_bmvert_map[ipc] for ipc in ip_chain] + \
                                    [self.ip_bmvert_map[ip_next]]
                                    
                        ed_exit = ip_next.seed_geom
                    else:
                        
                        if current_seg not in completed_segments:
                            result = process_segment(current_seg)
                            #self.net_ui_context.bme.to_mesh(self.net_ui_context.ob.data)
                            #return
                    
                        if current_seg.ip0 == ip_next:  #test the direction of the segment
                            ed_exit = self.cut_data[current_seg]['edge_crosses'][-1]
                        else:
                            ed_exit = self.cut_data[current_seg]['edge_crosses'][0]
                        
                        bmvert_chain  = [self.ip_bmvert_map[ipc] for ipc in ip_chain] + \
                                    [self.cut_data[current_seg]['bmedge_to_new_bmv'][ed_exit]]
                    
                    interval_start = time.time()
                    #this is dumb, expensive?
                    self.input_net.bme.verts.ensure_lookup_table()
                    self.input_net.bme.edges.ensure_lookup_table()
                    self.input_net.bme.faces.ensure_lookup_table()  
                    
                    finish = time.time()
                    print('updated lookup tables in %f' % (finish - interval_start))
                    interval_start = time.time()
                    
                    f = ip.bmface
                    f1, f2 = split_face_by_verts(self.input_net.bme, f, ed_enter, ed_exit, bmvert_chain)
                    
                    finish = time.time()
                    print('split face in %f' % (finish - interval_start))
                    interval_start = time.time()
                    
                    
                    if f1 != None and f2 != None:
                        new_to_old_face_map[f1] = f
                        new_to_old_face_map[f2] = f
                        old_to_new_face_map[f] = [f1, f2]
                        
                        if f not in new_to_old_face_map:
                            original_face_indices[f.index] = f
                        
                        bmesh.ops.delete(self.input_net.bme, geom = [f], context = 3)
                        
                        del_eds = [ed for ed in [ed_enter, ed_exit] if len(ed.link_faces) == 0]
                        del_eds = list(set(del_eds))
                        bmesh.ops.delete(self.input_net.bme, geom = del_eds, context = 4)
                    
                        finish = time.time()
                        print('deleted split face in %f' % (finish - interval_start))
                        interval_start = time.time()
                    
                    else:
                        #self.net_ui_context.bme.to_mesh(self.net_ui_context.ob.data)
                        print('f1 or f2 is none why')
                        return
                           
                else: #TODO
                    print('starting at a input point within in face')
                    #TODO, split this off, thanks
                    #TODO, generalize to the CCW cycle finding, not assuming 2 link segments
                    ip_chains = []
                    
                    interval_start = time.time()
                    
                    for seg in ip.link_segments:  #go each direction from Input Point on both of it's segments
                        current_seg = seg
                        chain = []
                        ip_next = current_seg.other_point(ip)
                        
                        if not ip_next.bmface.is_valid:
                            remap_input_point(ip_next)
        
                        seg_chain_start = time.time()
                        while ip_next and ip_next.bmface == ip.bmface:  #walk along the input segments as long as the next input point is on the same face
                            if ip_next in ip_set:  #we remove it here only if its on the same face
                                ip_set.remove(ip_next)
                        
                            chain += [ip_next]
                            
                            next_seg_start  = time.time()
                            next_seg = next_segment(ip_next, current_seg)
                            
                            next_seg_finish = time.time()
                            print('next segment %f' % (next_seg_finish - next_seg_start))
                            
                            if next_seg == None: 
                                print('there is no next seg we ended on edge of mesh?')
                                break
                        
                            ip_next = next_seg.other_point(ip_next)
                            if not ip_next.bmface.is_valid:
                                remap_input_point(ip_next)
                            
                            if ip_next.is_edgepoint(): 
                                print('we broke on an endpoint')
                                ip_set.remove(ip_next)
                                break
                            current_seg = next_seg

                        seg_chain_finish = time.time()
                        print('found segment chain in %f seconds' % (seg_chain_finish-seg_chain_start))
                        ip_chains += [chain]
                        

                        if current_seg not in completed_segments:  #here is some time, process as we go
                            process_start = time.time()
                            result = process_segment(current_seg)
                            process_finish = time.time()
                            print('processed a new segment in %f seconds' % (process_finish-process_start))
                        elif current_seg not in self.cut_data:
                            print('Current segment is not in cut data')
                            current_seg.bad_segment = True
                            return
                            
                        if current_seg in self.cut_data:
                            cdata = self.cut_data[current_seg]
                        else:
                            print('there is no cdata for this')
                            cdata = None
                            
                        #if this is first segment, we define that as the entrance segment   
                        if seg == ip.link_segments[0]:
                            if ip_next.is_edgepoint() and cdata == None:
                                bmv_enter = self.ip_bmvert_map[ip_next]
                                ed_enter = ip_next.seed_geom #TODO, make this seed_edge, seed_vert or seed_face
                            else:
                                if current_seg.ip0 == ip_next: #meaning ip_current == ip1  #test the direction of the segment
                                    ed_enter = self.cut_data[current_seg]['edge_crosses'][-1]  #TODO error here some time
                                    print('IP_1 of he input segment entering the face')
                                    if ed_enter in self.reprocessed_edge_map:
                                        ed_enter = self.reprocessed_edge_map[ed_enter]
                                        print('a reprocessed edge')
                                        #print(ed_enter)
                                else:
                                    ed_enter = self.cut_data[current_seg]['edge_crosses'][0]
                                    print('IP_0 of the input segment entering the face')
                                    if ed_enter in self.reprocessed_edge_map:
                                        ed_enter = self.reprocessed_edge_map[ed_enter]
                                        print('a reprocessed edge')
                                        #print(ed_enter)
                                bmv_enter = self.cut_data[current_seg]['bmedge_to_new_bmv'][ed_enter]
                        
                                
                                
                        #the other direction, will find the exit segment?
                        else:
                            if ip_next.is_edgepoint() and cdata == None:
                                print('getting the edgepoint IP bmvert')
                                bmv_exit = self.ip_bmvert_map[ip_next]
                                ed_exit = ip_next.seed_geom
                            else:
                                if current_seg.ip0 == ip_next:  #test the direction of the segment
                                    #ed_exit = self.cut_data[current_seg]['edge_crosses'][0]
                                    ed_exit = self.cut_data[current_seg]['edge_crosses'][-1]
                                    if ed_exit in self.reprocessed_edge_map:
                                        ed_exit = self.reprocessed_edge_map[ed_exit]
                                        print('a reprocessed edge')
                                        #print(ed_exit)
                                        
                                    print('IP_1 of the input segment exiting the face')
                                else:
                                    #ed_exit = self.cut_data[current_seg]['edge_crosses'][-1]
                                    
                                    ed_exit = self.cut_data[current_seg]['edge_crosses'][0] #TODO AGAIN SOMETIMES HERE AN ERROR
                                    
                                    if ed_exit in self.reprocessed_edge_map:
                                        ed_exit = self.reprocessed_edge_map[ed_exit]
                                        print('a reprocessed edge')
                                        #print(ed_exit)
                                    print('IP_0 of the input segment exiting the face')   
                            
                                bmv_exit = self.cut_data[current_seg]['bmedge_to_new_bmv'][ed_exit]
                            
                    ip_chains[0].reverse()
                    total_chain = ip_chains[0] + [ip] + ip_chains[1]
                    
                    bmvert_chain  = [bmv_enter] + [self.ip_bmvert_map[ipc] for ipc in total_chain] + [bmv_exit]

                    finish = time.time()
                    print('found the IPsegment loop %f seconds' % (finish - interval_start))
                    interval_start = time.time()
                    
                    
                    #print(ed_enter, ed_exit)
                    
                    interval_start = time.time()
                    if len(bmvert_chain) != len(set(bmvert_chain)):
                        print('we have duplicates')
                        print(bmvert_chain)
                    else: 
                        interval_start = time.time()   
                        self.input_net.bme.verts.ensure_lookup_table()
                        self.input_net.bme.edges.ensure_lookup_table()
                        self.input_net.bme.faces.ensure_lookup_table()  

                        finish = time.time()
                        print('updated lookup tables %f' % (finish-interval_start))
                        interval_start = time.time()
                        
                        f = ip.bmface
                        f1, f2 = split_face_by_verts(self.input_net.bme, f, ed_enter, ed_exit, bmvert_chain)
                        
                        finish = time.time()
                        print('split the face %f' % (finish-interval_start))
                        interval_start = time.time()
                        
                        if f1 == None or f2 == None:
                            #self.net_ui_context.bme.to_mesh(self.net_ui_context.ob.data)
                            return
                            #continue 
                        new_to_old_face_map[f1] = f
                        new_to_old_face_map[f2] = f
                        old_to_new_face_map[f] = [f1, f2]
                        if f not in new_to_old_face_map:
                            original_face_indices[f.index] = f
                        
                        geom_clean_start = time.time()
                        #bmesh.ops.delete(self.input_net.bme, geom = [f], context = 3)
                        self.input_net.bme.faces.remove(f)
                        
                        del_eds = [ed for ed in [ed_enter, ed_exit] if len(ed.link_faces) == 0]
                        del_eds = list(set(del_eds))
                        #bmesh.ops.delete(self.input_net.bme, geom = del_eds, context = 4)
                        for ed in del_eds:
                            self.input_net.bme.edges.remove(ed)
                        geom_clean_finish = time.time()
                        print('delete old face and edges in %f seconds' % (geom_clean_finish - geom_clean_start))
                    finish = time.time()
                    print('split IP face in %f seconds' % (finish - start)) 
        
        
        #now collect all the newly created edges which represent the cycle boundaries
        perim_edges = set()    
        for ed in self.input_net.bme.edges: #TODO, is there a faster way to collect these edges from the strokes? Yes
            if ed.verts[0] in new_bmverts and ed.verts[1] in new_bmverts:
                perim_edges.add(ed)

        high_genus_verts = set()    
        for v in self.input_net.bme.verts: 
            if v in new_bmverts: 
                if len([ed for ed in v.link_edges if ed in perim_edges]) >2:
                    high_genus_verts.add(v)
                    
        print('there aer %i high genus verts' % len(high_genus_verts))  #this method will fail in the case of a diamond on 4 adjacent quads.   
        for v in high_genus_verts:
            for ed in v.link_edges:
                if ed.other_vert(v) in high_genus_verts:
                    if ed in perim_edges:
                        perim_edges.remove(ed)

        self.boundary_edges = perim_edges             
        #self.input_net.bme.verts.ensure_lookup_table()
        #self.input_net.bme.edges.ensure_lookup_table()
        #self.input_net.bme.faces.ensure_lookup_table()    
        #self.net_ui_context.bme.to_mesh(self.net_ui_context.ob.data)
        knife_finish = time.time()
        print('\n')
        print('Executed the cut in %f seconds' % (knife_finish - knife_sart))
        return    
    
    
    def add_seed(self, face_ind, world_loc, local_loc):
        #dictionaries to map newly created faces to their original faces and vice versa
        original_face_indices = self.original_indices_map
        new_to_old_face_map = self.new_to_old_face_map
        old_to_new_face_map = self.old_to_new_face_map
        completed_segments = self.completed_segments
        completed_input_points = self.completed_input_points
        ip_bmvert_map = self.ip_bmvert_map
    
        if "patches" not in self.input_net.bme.loops.layers.color:
            vcol_layer = self.input_net.bme.loops.layers.color.new("patches")
        else:
            vcol_layer = self.input_net.bme.loops.layers.color["patches"]
            
            
        def find_newest_faces(old_f, max_iters = 5):
            '''
            '''    
            if old_f not in old_to_new_face_map: return []
            
            iters = 0
            child_fs = old_to_new_face_map[old_f]
            newest_faces = []
            
            if not any([f in old_to_new_face_map for f in child_fs]):
                return child_fs
            
            while iters < max_iters and any([f in old_to_new_face_map for f in child_fs]):
                iters += 1
                next_gen = []
                for f in child_fs:
                    if f in old_to_new_face_map:
                        next_gen += old_to_new_face_map[f]
                
                    else:
                        newest_faces += [f]
                        
                    print(f)
                print(next_gen)
                child_fs = next_gen
                
            #new_fs = old_to_new_face_map[old_f]
                
            return newest_faces  
        
        def find_new_faces(old_f, max_iters = 5):
            '''
            TODO, may want to only find NEWEST
            faces
            '''    
            if old_f not in old_to_new_face_map: return []
            
            iters = 0
            new_fs = []
            
            child_fs = old_to_new_face_map[old_f]
            new_fs += child_fs
            while iters < max_iters and len(child_fs):
                iters += 1
                next_gen = []
                for f in child_fs:
                    if f in old_to_new_face_map:
                        next_gen += old_to_new_face_map[f] #this is always a pair
                
                new_fs += next_gen
                child_fs = next_gen
                
            
            #new_fs = old_to_new_face_map[old_f]
                
            return new_fs    
        
        #print(self.original_indices_map)
        
        #first, BVH gives us a face index, but we have deleted all the faces and created new ones
        f = None
        if face_ind in self.original_indices_map:
            print('found an old face that was split')
            old_f = self.original_indices_map[face_ind]
            fs_new = find_newest_faces(old_f, max_iters = 5)
            for new_f in fs_new:
                if bmesh.geometry.intersect_face_point(new_f, local_loc):
                    print('found the new face that corresponds')
                    f = new_f
                
        else:
            self.input_net.bme.faces.ensure_lookup_table()
            self.input_net.bme.verts.ensure_lookup_table()
            self.input_net.bme.edges.ensure_lookup_table()
            
            f = self.old_face_indices[face_ind]
            #f = self.input_net.bme.faces[face_ind]
            
        if f == None:
            print('failed to find the new face')
            return
        
        new_patch = BMFacePatch(f, local_loc, world_loc, (random.random(), random.random(), random.random()))
        new_patch.grow_seed(self.input_net.bme, self.boundary_edges)
        new_patch.color_patch(vcol_layer)
        self.face_patches += [new_patch]
        
        self.net_ui_context.bme.to_mesh(self.net_ui_context.ob.data)
        
class InputPoint(object):  # NetworkNode
    '''
    Representation of an input point
    '''
    def __init__(self, world, local, view, face_ind, seed_geom = None, bmface = None, bmedge = None, bmvert = None):
        self.world_loc = world
        self.local_loc = local
        self.view = view
        self.face_index = face_ind
        self.link_segments = []

        #SETTING UP FOR MORE COMPLEX MESH CUTTING    ## SHould this exist in InputPoint??
        self.seed_geom = seed_geom #UNUSED, but will be needed if input point exists on an EDGE or VERT in the source mesh

        self.bmface = bmface
        self.bmedge = bmedge
        self.bmvert = bmvert
        
        
    def is_endpoint(self):
        if self.seed_geom and self.num_linked_segs > 0: return False  #TODO, better system to delinate edge of mesh
        if self.num_linked_segs < 2: return True # What if self.linked_segs == 2 ??

    def is_edgepoint(self):
        '''
        defines whether this InputPoint lies on the non_manifold edge 
        of the source mesh
        '''
        if isinstance(self.seed_geom, bmesh.types.BMEdge):
            return True
        else:
            return False

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

    def duplicate_data(self):
        data = {}
        data["world_loc"] = self.world_loc
        data["local_loc"] = self.local_loc
        data["view"] = self.view
        data["face_index"] = self.face_index
        data["seed_geom"] = self.seed_geom
        data["bmface"] = self.bmface
        data["bmedge"] = self.bmedge
        data["bmvert"] = self.bmvert
        
        return data
    
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
        
    def validate_bme_references(self):
        
        if self.bmvert and self.bmvert.is_valid:
            bmvalid = True
        elif self.bmvert == None:
            bmvalid = True   
        else:
            bmvalid = False
            
        if self.bmedge and self.bmedge.is_valid:
            bmedvalid = True
        elif self.bmedge == None:
            bmedvalid = True   
        else:
            bmedvalid = False
            
        if self.bmvert and self.bmvert.is_valid:
            bmvalid = True
        elif self.bmver == None:
            bmvalid = True   
        else:
            bmvalid = False    

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

        self.calculation_complete = False #this is a NetworkCutter Flag
        self.needs_calculation = True
        self.cut_method = 'NONE'
    def is_bad(self): return self.bad_segment
    is_bad = property(is_bad)

    def other_point(self, p):
        if p not in self.points: return None
        return self.ip0 if p == self.ip1 else self.ip1

    def detach(self):
        #TODO safety?  Check if in ip0.link_sgements?
        self.ip0.link_segments.remove(self)
        self.ip1.link_segments.remove(self)


    
    
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
        self.net_ui_context.set_network(self)
        self.bvh = self.net_ui_context.bvh   #this should go into net context.
        self.bme = self.net_ui_context.bme  #the network exists on the BMesh, it is fundamental
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
        self.points.append(InputPoint(world_loc, local_loc, view, face_ind, bmface = self.bme.faces[face_ind]))
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

    def remove_point(self, point, disconnect = False):
        connected_points = self.connected_points(point)
        for cp in connected_points:
            self.disconnect_points(cp, point)

        if len(connected_points) == 2 and not disconnect:
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
    
    
    def get_edgepoints(self):
        
        edge_points = [ip for ip in self.points if ip.is_edgepoint()]
        
        return edge_points
     
    def find_network_cycles(self):  #TODO
        #this is the equivalent of "edge_loops"
        #TODO, mirror the get_cycle method from polystrips
        #right now ther eare no T or X junctions, only cuts across mesh or loops within mesh
        #will need to implement "IputNode.get_segment_to_right(InputSegment) to take care this
        
        
        ip_set = set(self.points)
        endpoints = set(self.get_endpoints())
        
        closed_edgepoints = set(self.get_edgepoints()) - endpoints
        
        
        print('There are %i endpoints' % len(endpoints))
        print('there are %i input points' % len(ip_set))
        print('there are %i closed edge_points' % len(closed_edgepoints))
        
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
            
            if len(closed_edgepoints):  #this makes sure we start with a closed edge point
                current_ip = closed_edgepoints.pop()
                ip_set.remove(current_ip)
            else:
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
                if next_ip in closed_edgepoints: closed_edgepoints.remove(next_ip)
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
        
        
        print('there are %i closed seg cycles' % len(seg_cycles))
        for i, cyc in enumerate(ip_cycles):
            print('There are %i nodes in %i closed cycle' % (len(cyc), i))
        
        return ip_cycles, seg_cycles