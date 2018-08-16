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
    def __init__(self,context, cut_object, ui_type = 'DENSE_POLY'):
        self.source_ob = cut_object             #Network
        self.bme = bmesh.new()                  #Network
        self.bme.from_mesh(cut_object.data)
        ensure_lookup(self.bme)
        self.bvh = BVHTree.FromBMesh(self.bme)  #Network ??
        self.mx, self.imx = get_matrices(self.source_ob)    #Network

        self.input_net = InputNetwork() # is network

        self.cyclic = False #R
        self.selected = -1  #UI
        self.hovered = [None, -1]
        self.closest_ep = None   #UI  closest free input point (< 2 segs)
        self.snap_element = None    #UI
        self.connect_element = None #UI

         #TODO: (Cutting with new method, very hard) 
        self.face_chain = set()     

        self.non_man_eds = [ed.index for ed in self.bme.edges if not ed.is_manifold] #UI? (Network,cutting...)
        self.non_man_ed_loops = edge_loops_from_bmedges_old(self.bme, self.non_man_eds) #UI? (Network,cutting...)

        self.non_man_points = []        #UI
        self.non_man_bmverts = []       #UI
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

        self.grab_undo_loc = None
        self.start_edge_undo = None
        self.end_edge_undo = None

        #keep up with these to show user
        self.bad_segments = []      #cutting/ui
        self.split = False          #r
        self.perimeter_edges = []
        self.inner_faces = []
        self.face_seed = None

    def has_points(self): return self.input_net.num_points > 0
    def num_points(self): return self.input_net.num_points
    has_points = property(has_points)
    num_points = property(num_points)

### XXX: Puth these in their own class maybe?
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
        assert ip_start in self.input_net.points
        assert ip_end in self.input_net.points
        
        ind_start = self.input_net.points.index(ip_start)
        ind_end = self.input_net.points.index(ip_end)
        
        print('Am I considered cyclic yet?')
        print(self.cyclic)
        print(ind_start, ind_end)
        
        if ind_start > ind_end and self.cyclic:
            points = self.input_net.points[ind_start:] + self.input_net.points[:ind_end]
            
        elif ind_start > ind_end and not self.cyclic:
            ind_start, ind_end = ind_end, ind_start
            points = self.input_net.points[ind_start:ind_end+1]  #need to get the last point
        else:
            points = self.input_net.points[ind_start:ind_end+1]  #need to get the last point
        
        
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
            self.input_net.points = new_points + self.input_net.points[ind_end:ind_start]  #self.input_net.points[ind_start:] + self.input_net.points[:ind_end]
        
        elif ind_start < ind_end and self.cyclic:
            
            self.input_net.points = self.input_net.points[0:ind_start] + new_points + self.input_net.points[ind_end:]
                
        else:
            self.input_net.points = self.input_net.points[0:ind_start] + new_points + self.input_net.points[ind_end:]
        
        self.selected = None   
####

## UI
  
###

    #################
    #### drawing ####

    def draw(self,context,mouse_loc, grabber):
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

        preview_line_clr = (0,1,0,.4)
        preview_line_wdth = 2

        loc3d_reg2D = view3d_utils.location_3d_to_region_2d

        ## Hovered Non-manifold Edge or Vert
        if self.hovered[0] in {'NON_MAN_ED', 'NON_MAN_VERT'}:
            ed, pt = self.hovered[1]
            common_drawing.draw_3d_points(context,[pt], 6, green)

        if  self.input_net.is_empty: return
   
        ## Selected Point
        if self.selected and isinstance(self.selected, InputPoint):
            common_drawing.draw_3d_points(context,[self.selected.world_loc], 8, orange)


        # Grab Location Dot and Lines XXX:This part is gross..
        if grabber.grab_point:
            # Dot
            common_drawing.draw_3d_points(context,[grabber.grab_point.world_loc], 5, blue_opaque)
            # Lines

            point_orig = self.selected  #had to be selected to be grabbed
            other_locs = [seg.other_point(point_orig).world_loc for seg in point_orig.segments]

            for pt_3d in other_locs:
                other_loc = loc3d_reg2D(context.region, context.space_data.region_3d, pt_3d)
                grab_loc = loc3d_reg2D(context.region, context.space_data.region_3d, grabber.grab_point.world_loc)
                if other_loc and grab_loc:
                    common_drawing.draw_polyline_from_points(context, [grab_loc, other_loc], preview_line_clr, preview_line_wdth,"GL_LINE_STRIP")
        ## Hovered Point
        elif self.hovered[0] == 'POINT':
            common_drawing.draw_3d_points(context,[self.hovered[1].world_loc], 8, color = (0,1,0,1))
        # Insertion Lines (for adding in a point to edge)
        elif self.hovered[0] == 'EDGE':
            seg = self.hovered[1]
            a = loc3d_reg2D(context.region, context.space_data.region_3d, seg.ip0.world_loc)
            b = loc3d_reg2D(context.region, context.space_data.region_3d, seg.ip1.world_loc)
            if a and b:
                common_drawing.draw_polyline_from_points(context, [a,mouse_loc, b], preview_line_clr, preview_line_wdth,"GL_LINE_STRIP")
        # Insertion Lines (for adding closing loop)
        elif self.snap_element != None and self.connect_element != None:
            a = loc3d_reg2D(context.region, context.space_data.region_3d, self.connect_element.world_loc)
            b = loc3d_reg2D(context.region, context.space_data.region_3d, self.snap_element.world_loc)
            if a and b:
                common_drawing.draw_polyline_from_points(context, [a, b], preview_line_clr, preview_line_wdth,"GL_LINE_STRIP")
        # Endpoint to Cursor Line
        elif self.closest_ep:
            ep_screen_loc = loc3d_reg2D(context.region, context.space_data.region_3d, self.closest_ep.world_loc)
            common_drawing.draw_polyline_from_points(context, [ep_screen_loc, mouse_loc], preview_line_clr, preview_line_wdth,"GL_LINE_STRIP")


    def draw3d(self,context):
        '''
        3d drawing
         * ADAPTED FROM POLYSTRIPS John Denning @CGCookie and Taylor University
        '''
        
        if self.input_net.is_empty: return

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

        # Polylines...InputSegments
 
        for seg in self.input_net.segments:
            if seg.is_bad:
                draw3d_polyline(context, [seg.ip0.world_loc, seg.ip1.world_loc],  orange, 2, 'GL_LINE_STRIP' )
            elif len(seg.pre_vis_data) >= 2:
                draw3d_polyline(context, seg.pre_vis_data,  blue, 2, 'GL_LINE_STRIP' )
            else:
                draw3d_polyline(context, [seg.ip0.world_loc, seg.ip1.world_loc],  blue2, 2, 'GL_LINE_STRIP' )
    
        draw3d_points(context, self.input_net.world_locs, blue, 6)

        bgl.glLineWidth(1)     
                
        
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthRange(0.0, 1.0)
        bgl.glDepthMask(bgl.GL_TRUE)



class InputPoint(object):  # NetworkNode
    '''
    Representation of an input point
    '''
    def __init__(self, world, local, view, face_ind, seed_geom = None):
        self.world_loc = world
        self.local_loc = local
        self.view = view
        self.face_index = face_ind
        self.segments = [] #linked segments

        #SETTING UP FOR MORE COMPLEX MESH CUTTING    ## SHould this exist in InputPoint??
        self.seed_geom = seed_geom #UNUSED, but will be needed if input point exists on an EDGE or VERT in the source mesh

    def is_endpoint(self):
        if self.seed_geom and self.num_linked_segs > 0: return False  #TODO, better system to delinate edge of mesh
        if self.num_linked_segs < 2: return True # What if self.segments == 2 ??
    def num_linked_segs(self): return len(self.segments)
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
        self.pre_vis_data = []  #list of 3d points for previsualization
        self.bad_segment = False
        ip0.segments.append(self)
        ip1.segments.append(self)

    def linked_points(self): return [self.ip0, self.ip1]
    def is_bad(self): return self.bad_segment
    linked_points = property(linked_points)
    is_bad = property(is_bad)

    def other_point(self, ip):
        if ip not in self.linked_points: return None
        return self.ip0 if ip == self.ip1 else self.ip1
    

    def insert_point(self, point):
        seg0 = InputSegment(self.ip0, point)
        seg1 = InputSegment(point, self.ip1)
        self.ip0.segments.remove(self)
        self.ip1.segments.remove(self)
        return seg0, seg1
    
    def detach(self):
        #TODO safety?  Check if in ip0.link_sgements?
        self.ip0.segments.remove(self)
        self.ip1.segments.remove(self)
        
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
        #TODO: Separate this into NetworkCutter.
        # * return either bad segment or other important data.
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

class InputNetwork(object): #InputNetwork
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

    def is_empty(self): return (not(self.points or self.segments))
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

    def are_connected(self, p1, p2):
        ''' Sees if 2 points are connected, returns connecting segment if True '''
        for seg in p1.segments:
            if seg.other_point(p1) == p2:
                return seg
        return False

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
            old_seg = self.are_connected(point_behind, point_ahead)
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
        other_points = [seg.other_point(old_p) for seg in old_p.segments]

        for seg in old_p.segments:
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
        connected_points = [seg.other_point(point) for seg in point.segments]

        if len(connected_points) == 2: #maintain connectivity
            new_segment = InputSegment(connected_points[0], connected_points[1])
            self.segments.append(new_segment)

        for seg in point.segments:
            self.segments.remove(seg)

        self.points.remove(point)

    def remove(self, point, disconnect = True):
        if point not in self.points: return False

        connected_points = [seg.other_point(point) for seg in point.segments]

        if len(connected_points) == 2 and not disconnect: #maintain connectivity
            new_segment = InputSegment(connected_points[0], connected_points[1])
            self.segments.append(new_segment)

        for seg in point.segments:
            self.segments.remove(seg)
            seg.other_point(point).segments.remove(seg)

        self.points.remove(point)
        return True

    def duplicate(self):
        new = InputNetwork()
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