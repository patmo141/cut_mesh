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
from ..geodesic import GeoPath, geodesic_walk, continue_geodesic_walk, gradient_descent
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
        self.executor = ThreadPoolExecutor()  #alright
        self.executor_tasks = {}
        
        self.cut_data = {}  #a dictionary of cut data
        self.ip_bmvert_map = {} #dictionary of new bm verts to InputPoints  in input_net
        self.bmedge_to_new_vert_map = {} 
        
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
                print('this face is adjacent to the next face')
                cut_data = {} 
                cut_data['face_crosses'] = []
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
                cut_data['edge_crosses'] = eds_crossed
                cut_data['verts'] = vs
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
                    bisect_pts += [self.input_net.points[vert_inds[0]].local_loc]  #TODO, this only allows for a single point per face

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
                inner_vert_cos = [self.input_net.points[i].local_loc for i in self.face_groups[bmface.index]]
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
                inner_vert_cos = [self.input_net.points[i].local_loc for i in self.face_groups[bmface.index]]
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

    def knife_geometry(self):
        
        for ip in self.input_net.points:
            bmv = self.input_net.bme.verts.new(ip.local_loc)
            
            self.ip_bmvert_map[ip] = bmv
            
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
            
        for ip_cyc in ip_cycles:
            ip_set = set(ip_cyc)
            
            for i, ip in enumerate(ip_cyc):
                print('attempting ip %i' % i)
                if ip not in ip_set: continue #already handled this one
                
                if ip.is_edgepoint(): #we have to treat edge points differently
                    print('cutting boundary edge point')
                    #TODO, split this off, thanks
                    ip_chain =[ip]
                    print('there are %i link segments' % len(ip.link_segments))
                    current_seg = ip.link_segments[0]
                    
                    print(ip)
                    print(current_seg)
                    print(current_seg.points)
                    ip_next = current_seg.other_point(ip)
                    
                    if ip_next in ip_set:
                        ip_set.remove(ip_next)
                    else:
                        print('ip_next not in ip_set')
                        print(ip_next)
                        
                    while ip_next and ip_next.face_index == ip.face_index:
                        print('walking again')
                        ip_chain += [ip_next]
                        
                        next_seg = next_segment(ip_next, current_seg)
                        if next_seg == None: 
                            print('there is no next seg')
                            break
                    
                        ip_next = next_seg.other_point(ip_next)
                        if ip_next in ip_set:
                            ip_set.remove(ip_next)
                        if ip_next.is_edgepoint(): break
                        current_seg = next_seg

                    ed_enter = ip_chain[0].seed_geom # this is the entrance edge
                    
                    print('there are %i points in ip chain' % len(ip_chain))
                    if ip_next.is_edgepoint():
                        bmvert_chain  = [self.ip_bmvert_map[ipc] for ipc in ip_chain] + \
                                    [self.ip_bmvert_map[ip_next]]
                    else:
                        if current_seg.ip0 == ip_next:  #test the direction of the segment
                            ed_exit = self.cut_data[current_seg]['edge_crosses'][0]
                        else:
                            ed_exit = self.cut_data[current_seg]['edge_crosses'][-1]
                        
                        bmvert_chain  = [self.ip_bmvert_map[ipc] for ipc in ip_chain] + \
                                    [self.cut_data[current_seg]['bmedge_to_new_bmv'][ed_exit]]
                    
                    
                    #temp way to check bmvert chain
                    for n in range(0, len(bmvert_chain)-1):
                        self.input_net.bme.edges.new((bmvert_chain[n],bmvert_chain[n+1]))
                    
                else: #TODO
                    print('non edge point')
                    #TODO, split this off, thanks
                    
                    print('there are %i link segments' % len(ip.link_segments))
                    
                    
                    #TODO, generalize to the CCW cycle finding, not assuming 2 link segments
                    ip_chains = []
                    for seg in ip.link_segments:
                    
                        current_seg = seg
                        chain = []
                        print(ip)
                        print(current_seg)
                        print(current_seg.points)
                        ip_next = current_seg.other_point(ip)
                        
                        if ip_next in ip_set:
                            ip_set.remove(ip_next)
                        else:
                            print('ip_next not in ip_set')
                            print(ip_next)
                            
                        while ip_next and ip_next.face_index == ip.face_index:
                            print('walking again')
                            chain += [ip_next]
                            
                            next_seg = next_segment(ip_next, current_seg)
                            if next_seg == None: 
                                print('there is no next seg')
                                break
                        
                            ip_next = next_seg.other_point(ip_next)
                            if ip_next in ip_set:
                                ip_set.remove(ip_next)
                            if ip_next.is_edgepoint(): break
                            current_seg = next_seg

                        ip_chains += [chain]
                        
                        if seg == ip.link_segments[0]:
                            if current_seg.ip0 == ip_next:  #test the direction of the segment
                                ed_enter = self.cut_data[current_seg]['edge_crosses'][0]
                            else:
                                ed_enter = self.cut_data[current_seg]['edge_crosses'][-1]
                            
                            bmv_enter = self.cut_data[current_seg]['bmedge_to_new_bmv'][ed_enter]
                        else:
                            if current_seg.ip0 == ip_next:  #test the direction of the segment
                                ed_exit = self.cut_data[current_seg]['edge_crosses'][0]
                            else:
                                ed_exit = self.cut_data[current_seg]['edge_crosses'][-1]    
                        
                            bmv_exit = self.cut_data[current_seg]['bmedge_to_new_bmv'][ed_exit]
                            
                    ip_chains[0].reverse()
                    total_chain = ip_chains[0] + [ip] + ip_chains[1]
                    
                    
                    print('there are %i points in ip chain' % len(total_chain))
                    
                        
                    bmvert_chain  = [bmv_enter] + [self.ip_bmvert_map[ipc] for ipc in total_chain] + [bmv_exit]
                    
                    
                    #temp way to check bmvert chain
                    for n in range(0, len(bmvert_chain)-1):
                        self.input_net.bme.edges.new((bmvert_chain[n],bmvert_chain[n+1]))
        
        
        
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