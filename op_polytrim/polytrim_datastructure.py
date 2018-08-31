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
from ..cut_algorithms import cross_section_2seeds_ver1, path_between_2_points, path_between_2_points_clean, find_bmedges_crossing_plane
from ..geodesic import GeoPath, geodesic_walk, continue_geodesic_walk, gradient_descent
from .. import common_drawing
from ..common.rays import get_view_ray_data, ray_cast
from ..common.blender import bversion
from ..common.utils import get_matrices
from ..common.bezier import CubicBezier, CubicBezierSpline
from ..common.shaders import circleShader
from concurrent.futures.thread import ThreadPoolExecutor



#helper function to split a face
def split_face_by_verts(bme, f, ed_enter, ed_exit, bmvert_chain):
    '''
    bme - BMesh
    f - f in bme to be split
    ed_enter - the BMEdge that bmvert_chain[0] corresponds to
    ed_exit - the BMEdge that bmvert_chain[-1] corresponds to
    bmvert_chain - list of BMVerts that define the path that f is split on
    
    
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
            
        if iters >= 99:
            print('iteration problem')
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
            return None, None
        
        
        f1 = bme.faces.new(f1verts)
        f2 = bme.faces.new(verts + bmvert_chain)
        return f1, f2
    
    
class NetworkCutter(object):
    ''' Manages cuts in the InputNetwork '''

    def __init__(self, input_net, net_ui_context):
        #this is all the basic data that is needed
        self.input_net = input_net
        self.net_ui_context = net_ui_context

        #this is fancy "que" of things to be processed
        self.executor = ThreadPoolExecutor()  #alright
        self.executor_tasks = {}
        
        self.cut_data = {}  #a dictionary of cut data
        self.ip_bmvert_map = {} #dictionary of new bm verts to InputPoints  in input_net
        self.bmedge_to_new_vert_map = {} 
        self.reprocessed_edge_map = {}
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
        #TODO  shuld only take bmesh, input faces and locations.  Should not take BVH ro matrix as inputs
        self.face_chain = []

        # * return either bad segment or other important data.
        f0 = self.net_ui_context.bme.faces[seg.ip0.face_index]  #<<--- Current BMFace
        f1 = self.net_ui_context.bme.faces[seg.ip1.face_index] #<<--- Next BMFace

        if f0 == f1:
            seg.path = [seg.ip0.world_loc, seg.ip1.world_loc]
            seg.bad_segment = False  #perhaps a dict self.bad_segments[seg] = True
            seg.needs_calculation = False
            seg.calculation_complete = True
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
                        #seg.bad_segment = True #intersection
                        #if seg in self.cut_data:
                        #    self.cut_data.pop(seg, None)
                
                        print("\n Found self intersection on this segment")
                        
                        overlap = cut_data['face_set'].intersection(cdata['face_set'])
                        print(overlap)
                        print(cdata['face_crosses'][0])
                        print(cdata['face_crosses'][1])
                        print('\n')
                        
                        
                        #return  #found a self intersection, for now forbidden
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

    
    def knife_geometry(self):
        #check all deferred calculations
        #ensure no bad segments
        for seg in self.input_net.segments:
            
            if seg.needs_calculation or seg.calculation_complete == False:
                print('segments still computing')
                return
            
            if seg.is_bad:
                print('there are still bad segments')
                return
        
        #TODO make sure no open cycles?
        for ip in self.input_net.points:
            bmv = self.input_net.bme.verts.new(ip.local_loc)
            self.ip_bmvert_map[ip] = bmv
        
        #create all new verts at edge crossings:
        for seg in self.input_net.segments:
            if seg not in self.cut_data: continue
            
            cdata = self.cut_data[seg]
            bmedge_to_new_vert_map = {}
            cdata['bmedge_to_new_bmv'] = bmedge_to_new_vert_map
            for i, co in enumerate(cdata['verts']):
                bmedge = cdata['edge_crosses'][i]
                bmv = self.input_net.bme.verts.new(co)
                bmedge_to_new_vert_map[bmedge] = bmv  #handled in the per segment cut data
        
                
        ip_cycles, seg_cycles = self.input_net.find_network_cycles()
        
        def next_segment(ip, current_seg): #TODO Code golf this
            if len(ip.link_segments) != 2: return None  #TODO, the the segment to right
            return [seg for seg in ip.link_segments if seg != current_seg][0]
        
        
        def split_face_by_verts(f, ed_enter, ed_exit, bmvert_chain):    

            if ed_enter.link_loops[0].face == f:
                l_loop = ed_enter.link_loops[0]
            else:
                l_loop = ed_enter.link_loops[1]
                
                
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
                    
                if iters >= 99:
                    print('iteration problem')
                    return
                if d0 < d1:
                    self.input_net.bme.faces.new(verts + bmvert_chain)
                    self.input_net.bme.faces.new(bmvert_chain[::-1])
                    
                else:
                    self.input_net.bme.faces.new(verts + bmvert_chain[::-1])
                    self.input_net.bme.faces.new(bmvert_chain)
                
                return
            else:
                iters = 0
                verts = []  #the link_loop.vert will be behind the intersection so we don't need to include it
                while l_loop.edge != ed_exit and iters < 100:
                    iters += 1
                    verts += [l_loop.link_loop_next.vert]
                    l_loop = l_loop.link_loop_next
                
                if iters >= 99:
                    print('iteration problem')
                    return
                
                print(verts)
                print(bmvert_chain)
                self.input_net.bme.faces.new(verts + bmvert_chain[::-1])
                
                #keep going around
                verts = []
                iters = 0
                while l_loop.edge != ed_enter and iters < 100:
                    verts += [l_loop.link_loop_next.vert]
                    l_loop = l_loop.link_loop_next
                    iters += 1
                    
                if iters >= 99:
                    print('iteration problem')
                    return
                
                print(verts)
                print(bmvert_chain)
                f = self.input_net.bme.faces.new(verts + bmvert_chain)
                return
  
        for ip_cyc in ip_cycles:
            ip_set = set(ip_cyc)
            
            for i, ip in enumerate(ip_cyc):
                
                print('\n')
                print('attempting ip %i' % i)
                if ip not in ip_set: 
                    print('Already seen this IP %i' % i)
                    #print(ip)
                    continue #already handled this one
                
                #print(ip)
                
                if ip.is_edgepoint(): #we have to treat edge points differently
                    print('cutting starting at boundary edge point')
                    #TODO, split this off, thanks
                    ip_chain =[ip]
                    current_seg = ip.link_segments[0]
                    

                    ip_next = current_seg.other_point(ip)
                    
    
                    while ip_next and ip_next.face_index == ip.face_index:
                        
                        if ip_next in ip_set:
                            ip_set.remove(ip_next)
                            
                        ip_chain += [ip_next]
                        
                        next_seg = next_segment(ip_next, current_seg)
                        if next_seg == None: 
                            print('there is no next seg')
                            break
                    
                        ip_next = next_seg.other_point(ip_next)
                        if ip_next.is_edgepoint(): break
                        current_seg = next_seg
                    
                    print('the last IP next')
                    print(ip_next)
                    ed_enter = ip_chain[0].seed_geom # this is the entrance edge
                    
                    print('there are %i points in ip chain' % len(ip_chain))
                    if ip_next.is_edgepoint():
                        bmvert_chain  = [self.ip_bmvert_map[ipc] for ipc in ip_chain] + \
                                    [self.ip_bmvert_map[ip_next]]
                    else:
                        if current_seg.ip0 == ip_next:  #test the direction of the segment
                            ed_exit = self.cut_data[current_seg]['edge_crosses'][-1]
                        else:
                            ed_exit = self.cut_data[current_seg]['edge_crosses'][0]
                        
                        bmvert_chain  = [self.ip_bmvert_map[ipc] for ipc in ip_chain] + \
                                    [self.cut_data[current_seg]['bmedge_to_new_bmv'][ed_exit]]
                    
                    
                    #this is dumb, expensive?
                    self.input_net.bme.verts.ensure_lookup_table()
                    self.input_net.bme.edges.ensure_lookup_table()
                    self.input_net.bme.faces.ensure_lookup_table()  
                    
                    print('\n Splitting the face that started on an edge')
                    f = self.input_net.bme.faces[ip.face_index]
                    split_face_by_verts(f, ed_enter, ed_exit, bmvert_chain)
                    
                else: #TODO
                    print('starting at a input point within in face')
                    #TODO, split this off, thanks
                    
                    #TODO, generalize to the CCW cycle finding, not assuming 2 link segments
                    ip_chains = []
                    for seg in ip.link_segments:
                    
                        current_seg = seg
                        chain = []
                        ip_next = current_seg.other_point(ip)
        
                        while ip_next and ip_next.face_index == ip.face_index:
                            
                            if ip_next in ip_set:  #we remove it here only if its on the same face
                                ip_set.remove(ip_next)
                        
                            chain += [ip_next]
                            
                            next_seg = next_segment(ip_next, current_seg)
                            if next_seg == None: 
                                print('there is no next seg we ended on edge of mesh?')
                                break
                        
                            ip_next = next_seg.other_point(ip_next)

                            if ip_next.is_edgepoint(): 
                                print('we broke on an endpoint')
                                ip_set.remove(ip_next)
                                break
                            current_seg = next_seg

                        ip_chains += [chain]
                        
                        
                        
                        if current_seg in self.cut_data:
                            cdata = self.cut_data[current_seg]
                        else:
                            print('there is no cdata for this')
                            cdata = None
                        #if this is first segment, we define that as the entrance segment
                        #this is happening in the for seg in ip.link_segments    
                        if seg == ip.link_segments[0]:
                            if ip_next.is_edgepoint() and cdata == None:
                                bmv_enter = self.ip_bmvert_map[ip_next]
                                ed_enter = ip_next.seed_geom #TODO, make this seed_edge, seed_vert or seed_face
                            else:
                                if current_seg.ip0 == ip_next:  #test the direction of the segment
                                    #ed_enter = self.cut_data[current_seg]['edge_crosses'][0]
                                    ed_enter = self.cut_data[current_seg]['edge_crosses'][-1]
                                else:
                                    #ed_enter = self.cut_data[current_seg]['edge_crosses'][-1]
                                    ed_enter = self.cut_data[current_seg]['edge_crosses'][0]
                                
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
                                else:
                                    #ed_exit = self.cut_data[current_seg]['edge_crosses'][-1]
                                    ed_exit = self.cut_data[current_seg]['edge_crosses'][0]    
                            
                                bmv_exit = self.cut_data[current_seg]['bmedge_to_new_bmv'][ed_exit]
                            
                    ip_chains[0].reverse()
                    total_chain = ip_chains[0] + [ip] + ip_chains[1]
                    
                    bmvert_chain  = [bmv_enter] + [self.ip_bmvert_map[ipc] for ipc in total_chain] + [bmv_exit]
                    
                    print(ed_enter, ed_exit)
                    
                    if len(bmvert_chain) != len(set(bmvert_chain)):
                        print('we have duplicates')
                        print(bmvert_chain)
                    else:    
                        #temp way to check bmvert chain
                        #for n in range(0, len(bmvert_chain)-1):
                        #    self.input_net.bme.edges.new((bmvert_chain[n],bmvert_chain[n+1]))
                                    #this is dumb, expensive?
                        self.input_net.bme.verts.ensure_lookup_table()
                        self.input_net.bme.edges.ensure_lookup_table()
                        self.input_net.bme.faces.ensure_lookup_table()  


                        f = self.input_net.bme.faces[ip.face_index]
                        split_face_by_verts(f, ed_enter, ed_exit, bmvert_chain)
                    


        #now we need to go slice the walks
        '''
        for seg_cyc in seg_cycles:
            for seg in seg_cyc:
                if seg not in self.cut_data:
                    #print('we have an error, no cut data for this segment yet')
                    continue
                
                if seg.ip0.is_endpoint or seg.ip1.is_endpoint:  #handled by the IP loop above
                    #print('continuuing')
                    continue
                
                cdata = self.cut_data[seg]
                
                
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
                    
                    if ed_enter == None:
                        print('No ed enter')
                        f.select_set(True)
                        continue
                    if ed_exit == None:
                        print('no ed exit')
                        f.select_set(True)
                        continue
                    
                    if len(bmvs) != 2:
                        print('bmvs not 2')
                        continue
                    
                    #print(ed_enter, ed_exit, bmvs)
                    split_face_by_verts(f, ed_enter, ed_exit, bmvs)
                    #if len(bmvs) == 2:
                    #    print(bmvs)
                    #    if len(set(bmvs)) != 2:
                    #        for v in bmvs:
                    #            v.select_set(True)
                        #else:
                        #    self.input_net.bme.edges.new(bmvs)
                    #else:
                        #print('there are %i bmvs' % len(bmvs))
                        #print(bmvs)
        
        '''
        self.input_net.bme.verts.ensure_lookup_table()
        self.input_net.bme.edges.ensure_lookup_table()
        self.input_net.bme.faces.ensure_lookup_table()    
        #    pass
            #check a closed loop vs edge to edge
            
            #check for nodiness along the lopo that will need to be updated  
            #Eg,an InputPoint that is on BMEdge will be on a BMVert after this cycle is executed
            #For now, nodes are not allowed
            
            
            #check for face_map overlap with other cycles? and update those cycles afterward?
            
            #calculate the face crossings and create new Bmverts
            
            #figure out all the goodness for splititng faces, face changes etc 
            
            
        return    


    def knife_geometry2(self):
        #check all deferred calculations
        #ensure no bad segments
        for seg in self.input_net.segments:
            
            if (seg.needs_calculation == True) or (seg.calculation_complete == False):
                print('segments still computing')
                return
        
        #dictionaries to map newly created faces to their original faces and vice versa
        new_to_old_face_map = {}
        old_to_new_face_map = {}
        completed_segments = set()
        bmedge_to_new_bmv_map = {}  #sometimes, edges will be out of date!
            
        #Create a new BMVert for every input point
        for ip in self.input_net.points:
            bmv = self.input_net.bme.verts.new(ip.local_loc)
            self.ip_bmvert_map[ip] = bmv
        
        #identify closed loops in the input      
        ip_cycles, seg_cycles = self.input_net.find_network_cycles()
        
        
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
            new_f = f
            old_f = None
            while iters < max_iters:
                iters += 1
                if new_f not in new_to_old_face_map: break
                old_f = new_to_old_face_map[new_f]
                new_f = old_f
                
            return old_f
        
        def find_new_faces(old_f, max_iters = 5):
                
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
                        next_gen += [f]
                
                new_fs += next_gen
                child_fs = next_gen
                
            
            #new_fs = old_to_new_face_map[old_f]
                
            return new_fs
            
            
        def recompute_segment(seg):
            
            #scenario a, just ip0 is bad
            
            bad_fs = [f for f in self.cut_data[seg]['face_crosses'] if not f.is_valid]
            
            print('there are %i bad faces' % len(bad_fs))
            
            tip_bad, tail_bad = False, False
            if self.cut_data[seg]['face_crosses'][0] in bad_fs:
                tip_bad = True
                print("the tip is bad")
            if self.cut_data[seg]['face_crosses'][-1] in bad_fs:
                tail_bad = True
                print('The tail is bad')
            
            mid_bad = (len(bad_fs) - tip_bad * 1 - tail_bad * 1) >= 1
            if mid_bad:
                print('the middle is bad')
            
            #if just hte tip and or tail are bad, we can manually replace
            #the edge map by looking up new faces in the new_to_old_face_map
            
                   
            if tip_bad:       
                new_fs = find_new_faces(self.cut_data[seg]['face_crosses'][0])
            
                print('there are the new faces for the tip')
                print(new_fs)
                
                co = self.cut_data[seg]['verts'][0]
                no = self.compute_cut_normal(seg)
                for f in new_fs:
                    ed_inters = find_bmedges_crossing_plane(co, no, f.edges[:], .000001)
                    print('New edges intersecting')
                    print(ed_inters)
                    if len(ed_inters):
                        ed, loc = ed_inters[0]
                        
                        print('replacing old edge with new edge')
                        print(self.cut_data[seg]['edge_crosses'][0])
                        print(ed)
                        self.reprocessed_edge_map[self.cut_data[seg]['edge_crosses'][0]] =  ed
                        self.cut_data[seg]['face_crosses'][0] = f
                        self.cut_data[seg]['edge_crosses'][0] = ed
                        break
                
                
            if tail_bad:       
                new_fs = find_new_faces(self.cut_data[seg]['face_crosses'][-1])
            
                co = self.cut_data[seg]['verts'][-1]
                no = self.compute_cut_normal(seg)
                for f in new_fs:
                    ed_inters = find_bmedges_crossing_plane(co, no, f.edges[:], .000001)
                    
                    print('New edges intersecting')
                    print(ed_inters)
                    if len(ed_inters):
                        ed, loc = ed_inters[0]
                        
                        print('replacing old edge with new edge')
                        print(self.cut_data[seg]['edge_crosses'][0])
                        print(ed)
                        
                        self.reprocessed_edge_map[self.cut_data[seg]['edge_crosses'][-1]] =  ed
                        self.cut_data[seg]['face_crosses'][-1] = f
                        self.cut_data[seg]['edge_crosses'][-1] = ed
                        break
               
                
            if tip_bad or tail_bad:
                print('fixed tip and taill, process again')
                process_segment(seg)   
            return False
        
        
        
        def process_segment(seg):
            if seg not in self.cut_data:
                print('no cut data for this segment, must need to precompute or perhaps its internal to a face')
                return False
            
            if not all([f.is_valid for f in self.cut_data[seg]['face_crosses']]):
                print('segment out of date')
                recompute_segment(seg)
                return False
            
            if seg not in self.cut_data:
                print('there is no cut data for this segment')
                return False
            
            if seg in completed_segments:
                print('segment already completed')
                return False
            
            cdata = self.cut_data[seg]
            bmedge_to_new_vert_map = {}
            cdata['bmedge_to_new_bmv'] = bmedge_to_new_vert_map  #TODO, store this here?  Shouldn't matter..does matter
            
            #create all verts on this segment
            for i, co in enumerate(cdata['verts']):
                bmedge = cdata['edge_crosses'][i]
                bmv = self.input_net.bme.verts.new(co)
                bmedge_to_new_vert_map[bmedge] = bmv
            
            #now process all the faces crossed    
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
                    continue
                if ed_exit == None:
                    print('no ed exit')
                    f.select_set(True)
                    continue
                
                if len(bmvs) != 2:
                    print('bmvs not 2')
                    continue
                
                #print(ed_enter, ed_exit, bmvs)
                f1, f2 = split_face_by_verts(self.input_net.bme, f, ed_enter, ed_exit, bmvs)   
                if f1 == None or f2 == None:
                    continue 
                new_to_old_face_map[f1] = f
                new_to_old_face_map[f2] = f
                old_to_new_face_map[f] = [f1, f2]
                
                
            #delete all old faces and edges from bmesh
            #but references remain in InputNetwork elements like InputPoint!
            bmesh.ops.delete(self.input_net.bme, geom = cdata['face_crosses'], context = 3)
            
            del_edges = [ed for ed in cdata['edge_crosses'] if len(ed.link_faces) == 0]
            del_edges = list(set(del_edges))
            bmesh.ops.delete(self.input_net.bme, geom = del_edges, context = 4)
        
            completed_segments.add(seg)
            
        
        #first we do all the Input Points and split the faces that input points are on
        for ip_cyc in ip_cycles:
            ip_set = set(ip_cyc)
            
            for i, ip in enumerate(ip_cyc):
                print('\n')
                print('attempting ip %i' % i)
                if ip not in ip_set: 
                    print('Already seen this IP %i' % i)
                    #print(ip)
                    continue #already handled this one

                #print(ip)
                if ip.is_edgepoint(): #we have to treat edge points differently
                    print('cutting starting at boundary edge point')
                    #TODO, split this off, thanks
                    ip_chain =[ip]
                    current_seg = ip.link_segments[0]  #edge poitns only have 1 seg
                    ip_next = current_seg.other_point(ip)
                    
    
                    while ip_next and ip_next.bmface == ip.bmface:
                        
                        if ip_next in ip_set:
                            ip_set.remove(ip_next)
                            
                        ip_chain += [ip_next]
                        
                        next_seg = next_segment(ip_next, current_seg)
                        if next_seg == None: 
                            print('there is no next seg')
                            break
                    
                        ip_next = next_seg.other_point(ip_next)
                        if ip_next.is_edgepoint(): break
                        current_seg = next_seg
                    

                    ed_enter = ip_chain[0].seed_geom # this is the entrance edge
                    
                    if ip_next.is_edgepoint():
                        bmvert_chain  = [self.ip_bmvert_map[ipc] for ipc in ip_chain] + \
                                    [self.ip_bmvert_map[ip_next]]
                    else:
                        
                        if current_seg not in completed_segments:
                            result = process_segment(current_seg)

                        if current_seg.ip0 == ip_next:  #test the direction of the segment
                            ed_exit = self.cut_data[current_seg]['edge_crosses'][-1]
                        else:
                            ed_exit = self.cut_data[current_seg]['edge_crosses'][0]
                        
                        bmvert_chain  = [self.ip_bmvert_map[ipc] for ipc in ip_chain] + \
                                    [self.cut_data[current_seg]['bmedge_to_new_bmv'][ed_exit]]
                    
                    #this is dumb, expensive?
                    self.input_net.bme.verts.ensure_lookup_table()
                    self.input_net.bme.edges.ensure_lookup_table()
                    self.input_net.bme.faces.ensure_lookup_table()  
                    
                    f = ip.bmface
                    f1, f2 = split_face_by_verts(self.input_net.bme, f, ed_enter, ed_exit, bmvert_chain)
                    
                    if f1 != None and f2 != None:
                        new_to_old_face_map[f1] = f
                        new_to_old_face_map[f2] = f
                        old_to_new_face_map[f] = [f1, f2]
                        bmesh.ops.delete(self.input_net.bme, geom = [f], context = 3)
                        
                        del_eds = [ed for ed in [ed_enter, ed_exit] if len(ed.link_faces) == 0]
                        bmesh.ops.delete(self.input_net.bme, geom = del_eds, context = 4)
                        
                else: #TODO
                    print('starting at a input point within in face')

                    #TODO, split this off, thanks
        
                    #TODO, generalize to the CCW cycle finding, not assuming 2 link segments
                    ip_chains = []
                    for seg in ip.link_segments:
                        current_seg = seg
                        chain = []
                        ip_next = current_seg.other_point(ip)
        
                        while ip_next and ip_next.bmface == ip.bmface:
                            if ip_next in ip_set:  #we remove it here only if its on the same face
                                ip_set.remove(ip_next)
                        
                            chain += [ip_next]
                            
                            next_seg = next_segment(ip_next, current_seg)
                            if next_seg == None: 
                                print('there is no next seg we ended on edge of mesh?')
                                break
                        
                            ip_next = next_seg.other_point(ip_next)

                            if ip_next.is_edgepoint(): 
                                print('we broke on an endpoint')
                                ip_set.remove(ip_next)
                                break
                            current_seg = next_seg

                        ip_chains += [chain]
                        
                        
                        if current_seg not in completed_segments:
                            result = process_segment(current_seg)
                            
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
                                    ed_enter = self.cut_data[current_seg]['edge_crosses'][-1]
                                    print('Ed enter is IP_1')
                                else:
                                    ed_enter = self.cut_data[current_seg]['edge_crosses'][0]
                                    print('Ed enter is IP_0') 
                                
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
                                    print('Ed exit is IP_1')
                                else:
                                    #ed_exit = self.cut_data[current_seg]['edge_crosses'][-1]
                                    ed_exit = self.cut_data[current_seg]['edge_crosses'][0]
                                    print('Ed exit is IP_0')   
                            
                                bmv_exit = self.cut_data[current_seg]['bmedge_to_new_bmv'][ed_exit]
                            
                    ip_chains[0].reverse()
                    total_chain = ip_chains[0] + [ip] + ip_chains[1]
                    
                    bmvert_chain  = [bmv_enter] + [self.ip_bmvert_map[ipc] for ipc in total_chain] + [bmv_exit]
                    
                    print(ed_enter, ed_exit)
                    
                    if len(bmvert_chain) != len(set(bmvert_chain)):
                        print('we have duplicates')
                        print(bmvert_chain)
                    else:    
                        self.input_net.bme.verts.ensure_lookup_table()
                        self.input_net.bme.edges.ensure_lookup_table()
                        self.input_net.bme.faces.ensure_lookup_table()  

                        f = ip.bmface
                        f1, f2 = split_face_by_verts(self.input_net.bme, f, ed_enter, ed_exit, bmvert_chain)
                        
                        if f1 == None or f2 == None:
                            continue 
                        new_to_old_face_map[f1] = f
                        new_to_old_face_map[f2] = f
                        old_to_new_face_map[f] = [f1, f2]
                        
                        bmesh.ops.delete(self.input_net.bme, geom = [f], context = 3)
                        del_eds = [ed for ed in [ed_enter, ed_exit] if len(ed.link_faces) == 0]
                        bmesh.ops.delete(self.input_net.bme, geom = del_eds, context = 4)
    
        self.input_net.bme.verts.ensure_lookup_table()
        self.input_net.bme.edges.ensure_lookup_table()
        self.input_net.bme.faces.ensure_lookup_table()    
          
        return
    
    
    
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
    
    def find_cycles(self,ip):
        pass
       
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