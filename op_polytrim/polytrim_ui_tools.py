'''
Created on Oct 10, 2015

@author: Patrick
'''
import bmesh
import bpy
import time
import math

from ..bmesh_fns import edge_loops_from_bmedges_old, ensure_lookup
from ..common.utils import get_matrices
from ..common.rays import get_view_ray_data, ray_cast, ray_cast_path, ray_cast_bvh

from .polytrim_datastructure import InputNetwork, InputPoint, InputSegment, SplineSegment, CurveNode

import bgl
from bpy_extras import view3d_utils
from mathutils import Vector, kdtree, Color
from mathutils.geometry import intersect_point_line
from mathutils.bvhtree import BVHTree
from ..bmesh_fns import edge_loops_from_bmedges_old, flood_selection_by_verts, flood_selection_edge_loop, ensure_lookup
from ..common.maths import Point, Direction, XForm
from ..common.bezier import CubicBezierSpline
from ..common.simplify import simplify_RDP
from ..geodesic import geodesic_walk

class Polytrim_UI_Tools():
    '''
    Functions/classes helpful with user interactions in polytrim
    '''

    class SketchManager():
        '''
        UI tool for managing sketches made by user.
        * Intermediary between polytrim_states and Network
        '''
        def __init__(self, input_net, spline_net, net_ui_context, network_cutter):
            self.sketch = []
            self.input_net = input_net
            self.spline_net = spline_net
            self.network_cutter = network_cutter
            self.net_ui_context = net_ui_context
            self.stroke_smoothing = 0.75  # 0: no smoothing. 1: no change
            self.sketch_curpos = (0, 0)
            self.bez_data = []
            
        def has_locs(self): return len(self.sketch) > 0
        has_locs = property(has_locs)

        def get_locs(self): return self.sketch

        def reset(self): self.sketch = []

        def add_loc(self, x, y):
            ''' Add's a screen location to the sketch list '''
            self.sketch.append((x,y))

        def smart_add_loc(self, x, y):
            ''' Add's a screen location to the sketch list based on smart stuff '''
            (lx, ly) = self.sketch[-1]
            ss0,ss1 = self.stroke_smoothing ,1-self.stroke_smoothing  #First data manipulation
            self.sketch += [(lx*ss0+x*ss1, ly*ss0+y*ss1)]

        def is_good(self):
            ''' Returns whether the sketch attempt should/shouldn't be added to the InputNetwork '''
            # checking to see if sketch functionality shouldn't happen
            if len(self.sketch) < 5 and self.net_ui_context.ui_type == 'DENSE_POLY': return False
            return True

        def finalize(self, context, start_pnt, end_pnt=None):
            ''' takes sketch data and adds it into the datastructures '''
            
            
            print(start_pnt, end_pnt)
            if not isinstance(end_pnt, InputPoint) or isinstance(end_pnt, CurveNode): end_pnt = None    
            if not isinstance(start_pnt, InputPoint)  or isinstance(start_pnt, CurveNode): 
                prev_pnt = None
            else:
                prev_pnt = start_pnt
            
            #FINALIZE INPUT NET MODE
            if isinstance(start_pnt, InputPoint):
                for ind in range(0, len(self.sketch) , 5):
                    if not prev_pnt:
                        if self.input_net.num_points == 1: new_pnt = self.input_net.points[0]
                        else: new_pnt = start_pnt
                    else:
                        pt_screen_loc = self.sketch[ind]  #in screen space
                        view_vector, ray_origin, ray_target = get_view_ray_data(context, pt_screen_loc)  #a location and direction in WORLD coordinates
                        #loc, no, face_ind =  ray_cast(self.net_ui_context.ob,self.net_ui_context.imx, ray_origin, ray_target, None)  #intersects that ray with the geometry
                        loc, no, face_ind =  ray_cast_bvh(self.net_ui_context.bvh,self.net_ui_context.imx, ray_origin, ray_target, None)
                        if face_ind != None:
                            new_pnt = self.input_net.create_point(self.net_ui_context.mx * loc, loc, view_vector, face_ind)
                    if prev_pnt:
                        print(prev_pnt)
                        seg = InputSegment(prev_pnt,new_pnt)
                        self.input_net.segments.append(seg)
                        
                        #self.network_cutter.precompute_cut(seg)
                        #seg.make_path(self.net_ui_context.bme, self.input_net.bvh, self.net_ui_context.mx, self.net_ui_context.imx)
                    prev_pnt = new_pnt
                if end_pnt:
                    seg = InputSegment(prev_pnt,end_pnt)
                    self.input_net.segments.append(seg)
            
            #FINALIZE CURVE NETWORK MODE
            else:
                sketch_3d = []
                other_data = []
                for pt in self.sketch:
                    view_vector, ray_origin, ray_target = get_view_ray_data(context, pt)  #a location and direction in WORLD coordinates
                        #loc, no, face_ind =  ray_cast(self.net_ui_context.ob,self.net_ui_context.imx, ray_origin, ray_target, None)  #intersects that ray with the geometry
                    loc, no, face_ind =  ray_cast_bvh(self.net_ui_context.bvh,self.net_ui_context.imx, ray_origin, ray_target, None)
                    if face_ind != None:
                            sketch_3d += [self.net_ui_context.mx * loc]
                            other_data += [(loc, view_vector, face_ind)]  
                
                feature_inds = simplify_RDP(sketch_3d, .25)  #TODO, sketch threshold
                
                new_points = []
                new_segs = []
                for ind in feature_inds:
                    if not prev_pnt:
                        if self.spline_net.num_points == 1: new_pnt = self.spline_net.points[0]
                        else: new_pnt = start_pnt
                    else:
                        loc3d = sketch_3d[ind]
                        loc, view_vector, face_ind = other_data[ind]
                        new_pnt = self.spline_net.create_point(loc3d, loc, view_vector, face_ind)
                        new_points += [new_pnt]
                    if prev_pnt:
                        print(prev_pnt)
                        seg = SplineSegment(prev_pnt,new_pnt)
                        self.spline_net.segments.append(seg)
                        new_segs += [seg]
                        #self.network_cutter.precompute_cut(seg)
                        #seg.make_path(self.net_ui_context.bme, self.input_net.bvh, self.net_ui_context.mx, self.net_ui_context.imx)
                    prev_pnt = new_pnt
                if end_pnt:
                    seg = SplineSegment(prev_pnt,end_pnt)
                    self.spline_net.segments.append(seg)  
                    new_segs += [seg]
                for p in new_points:
                    p.calc_handles()
                for seg in new_segs:
                    seg.calc_bezier()
                    seg.tessellate()
                    seg.tessellate_IP_error(.1)
    
                    
        def finalize_bezier(self, context):
            
            stroke3d = []
            for ind in range(0, len(self.sketch) , 5):
                pt_screen_loc = self.sketch[ind]  #in screen space
                view_vector, ray_origin, ray_target = get_view_ray_data(context, pt_screen_loc)  #a location and direction in WORLD coordinates
                    #loc, no, face_ind =  ray_cast(self.net_ui_context.ob,self.net_ui_context.imx, ray_origin, ray_target, None)  #intersects that ray with the geometry
                loc, no, face_ind =  ray_cast_bvh(self.net_ui_context.bvh,self.net_ui_context.imx, ray_origin, ray_target, None)
                if face_ind != None:
                    stroke3d += [self.net_ui_context.mx * loc]
                    
            #print(stroke3d)
            cbs = CubicBezierSpline.create_from_points([stroke3d], .05)
            cbs.tessellate_uniform(lambda p,q:(p-q).length, split=20)
            L = cbs.approximate_totlength_tessellation()
            n = L/2  #2mm spacing long strokes?
            #print(cbs.tessellation)
            
            self.bez_data = []
            for btess in cbs.tessellation:
                self.bez_data += [pt.as_vector() for i,pt,d in btess]


    class PaintBrush():  #TODO replace with widget, this is a coars placeholder
        #active patch?  meaning we are updating a selection
        def __init__(self, net_ui_context, radius=1.5, color=(0.8, 0.1, 0.3)):
            self.net_ui_context = net_ui_context
            self.xform = XForm(self.net_ui_context.ob.matrix_world)
            self.radius = radius
            self.brush_color = Color(color)
            #self.brush_rad_pixel = 40
            self.geom_accum = set()  #FACES

            #TODO....figure out if we need a dual color layer?
            if "patches" not in self.net_ui_context.bme.loops.layers.color:
                vcol_layer = self.net_ui_context.bme.loops.layers.color.new("patches")
            else:
                vcol_layer = self.net_ui_context.bme.loops.layers.color["patches"]

            self.vcol = vcol_layer
            self.points = [(math.cos(math.radians(t)), math.sin(math.radians(t))) for t in range(0,361,10)]

        def ray_hit(self, pt_screen, context):
            view_vector, ray_origin, ray_target = get_view_ray_data(context, pt_screen)  #a location and direction in WORLD coordinates
            return ray_cast_bvh(self.net_ui_context.bvh, self.net_ui_context.imx, ray_origin, ray_target, None)

        def absorb_geom(self, context, pt_screen_loc):
            loc, no, face_ind = self.ray_hit(pt_screen_loc, context)
            if not loc: return

            close_geom = self.net_ui_context.bvh.find_nearest_range(loc, self.radius)
            fs = [self.net_ui_context.bme.faces[ind] for  _,_,ind,_ in close_geom]
            self.color_geom(fs)
            self.geom_accum.update(fs)

        def absorb_geom_geodesic(self, context, pt_screen_loc):
            loc, no, face_ind = self.ray_hit(pt_screen_loc, context)
            if not loc: return

            #can do old mapping if bme has been altered
            seed = self.net_ui_context.bme.faces[face_ind]
            geos, fixed_vs, close, far = geodesic_walk(self.net_ui_context.bme, seed, loc, min_dist=self.radius)
            fs_in = set()
            fs_out = set()
            for v in fixed_vs:
                for f in v.link_faces:
                    if f in fs_in or f in fs_out: continue
                    if all([v in fixed_vs for v in f.verts]):
                        fs_in.add(f)
                    else:
                        fs_out.add(f)

            self.color_geom(fs_in)
            self.geom_accum.update(fs_in)

        def color_geom(self, faces):
            for f in faces:
                for loop in f.loops:
                    loop[self.vcol] = self.brush_color

        def color_all_geom(self):
            self.color_geom(self.geom_accum)

        def draw_postview(self, context, pt_screen):
            loc,no,_ = self.ray_hit(pt_screen, context)
            if not loc: return
            loc = self.xform.l2w_point(loc)
            no = self.xform.l2w_normal(no)
            tr = Vector((0,0,1)) if abs(no.z) < 0.9 else Vector((1,0,0))
            tx = Direction(no.cross(tr))
            ty = Direction(no.cross(tx))
            cr,cg,cb = self.brush_color

            bgl.glDepthRange(0, 0.99999)    # squeeze depth just a bit
            bgl.glDepthMask(bgl.GL_FALSE)   # do not overwrite depth
            bgl.glEnable(bgl.GL_BLEND)
            bgl.glEnable(bgl.GL_DEPTH_TEST)
            bgl.glLineWidth(2.0) # self.drawing.line_width(2.0)
            bgl.glPointSize(3.0) # self.drawing.point_size(3.0)

            ######################################
            # draw in front of geometry

            bgl.glDepthFunc(bgl.GL_LEQUAL)

            bgl.glColor4f(cr, cg, cb, 1.0)       # outer ring
            bgl.glBegin(bgl.GL_LINE_STRIP)
            for mx,my in self.points:
                p = loc + (tx * mx + ty * my) * self.radius
                bgl.glVertex3f(*p)
            bgl.glEnd()

            bgl.glColor4f(cr, cg, cb, 0.1)     # inner ring
            bgl.glBegin(bgl.GL_LINE_STRIP)
            for mx,my in self.points:
                p = loc + (tx * mx + ty * my) * (self.radius * 0.5)
                bgl.glVertex3f(*p)
            bgl.glEnd()

            bgl.glColor4f(1, 1, 1, 0.25)    # center point
            bgl.glBegin(bgl.GL_POINTS)
            bgl.glVertex3f(*loc)
            bgl.glEnd()

            ######################################
            # draw behind geometry (hidden below)

            bgl.glDepthFunc(bgl.GL_GREATER)

            bgl.glColor4f(cr, cg, cb, 0.05)    # outer ring
            bgl.glBegin(bgl.GL_LINE_STRIP)
            for mx,my in self.points:
                p = loc + (tx * mx + ty * my) * self.radius
                bgl.glVertex3f(*p)
            bgl.glEnd()

            bgl.glColor4f(cr, cg, cb, 0.01)   # inner ring
            bgl.glBegin(bgl.GL_LINE_STRIP)
            for mx,my in self.points:
                p = loc + (tx * mx + ty * my) * (self.radius * 0.5)
                bgl.glVertex3f(*p)
            bgl.glEnd()

            ######################################
            # reset to defaults

            bgl.glDepthFunc(bgl.GL_LEQUAL)
            bgl.glDepthMask(bgl.GL_TRUE)
            bgl.glDepthRange(0, 1)




    class GrabManager():
        '''
        UI tool for managing input point grabbing/moving made by user.
        * Intermediary between polytrim_states and Network
        '''
        def __init__(self, input_net, net_ui_context, network_cutter):
            self.net_ui_context = net_ui_context
            self.input_net = input_net
            self.network_cutter = network_cutter

            self.grab_point = None
            self.original_point = None
            self.backup_data = {}
        def in_use(self): return self.grab_point != None
        in_use = property(in_use)

        def initiate_grab_point(self):
            self.grab_point = self.net_ui_context.selected
            self.backup_data =  self.grab_point.duplicate_data()

        def move_grab_point(self,context,mouse_loc):
            ''' Moves location of point'''
            d = self.net_ui_context.hovered_mesh
            if d and self.grab_point:
                self.grab_point.set_values(d["world loc"], d["local loc"], d["view"], d["face index"])
                self.grab_point.bmface = self.input_net.bme.faces[d["face index"]]
                
                #update bezier preview
                if isinstance(self.grab_point, CurveNode):
                    self.grab_point.calc_handles()
                    for seg in self.grab_point.link_segments:
                        seg.is_inet_dirty = True
                        node = seg.other_point(self.grab_point)
                        node.calc_handles()
                        node.update_splines()
                        
                        
        def grab_cancel(self):
            ''' returns variables to their status before grab was initiated '''
            if not self.grab_point: return
            for key in self.backup_data:
                setattr(self.grab_point, key, self.backup_data[key])
            
            if isinstance(self.grab_point, CurveNode):
                self.grab_point.calc_handles()
                for seg in self.grab_point.link_segments:
                    seg.is_inet_dirty = False
                    node = seg.other_point(self.grab_point)
                    node.calc_handles()
                    node.update_splines()
                         
            self.grab_point = None #TODO BROKEN
            return

        def finalize(self, context):
            ''' sets new variables based on new location '''
            if not self.grab_point: return
            
            if isinstance(self.net_ui_context.selected, InputPoint):
                for seg in self.net_ui_context.selected.link_segments:
                    seg.path = []
                    seg.needs_calculation = True
                    seg.calculation_complete = False

            else:
                self.net_ui_context.selected.update_input_point(self.input_net)
                self.net_ui_context.selected.calc_handles()
                for seg in self.net_ui_context.selected.link_segments:
                    node = seg.other_point(self.net_ui_context.selected)
                    node.calc_handles()
                    node.update_splines()
                
                print(len(self.grab_point.link_segments))
                print(self.grab_point.face_index)
                print(self.grab_point.seed_geom)
                
            self.grab_point = None


            return

    class NetworkUIContext():
        '''
        UI tool for storing data depending on where mouse is located
        * Intermediary between polytrim_states and Network
        '''
        def __init__(self, context, ui_type='DENSE_POLY'):
            self.context = context
            self.input_net = None

            self.ob = context.object
            self.ob.hide = False
            context.scene.render.engine = 'BLENDER_RENDER'
            context.space_data.show_manipulator = False
            context.space_data.viewport_shade = 'SOLID'  #TODO until smarter drawing
            context.space_data.show_textured_solid = True #TODO until smarter patch drawing
        
            if "patches" not in bpy.data.materials:
                mat = bpy.data.materials.new("patches")
                mat.use_shadeless = True
                mat.use_vertex_color_paint = True
            else:
                mat = bpy.data.materials.get("patches")
                mat.use_shadeless = True
                mat.use_vertex_color_paint = True
        
            if "patches" not in self.ob.data.materials:
                self.ob.data.materials.append(mat)
                self.ob.material_slots[0].material = mat
            
            self.bme = bmesh.new()
            self.bme.from_mesh(self.ob.data)
            ensure_lookup(self.bme)
            self.bvh = BVHTree.FromBMesh(self.bme) 
            self.mx, self.imx = get_matrices(self.ob) 
            self.mx_norm = self.imx.transposed().to_3x3() #local directions to global
            self.imx_norm = self.imx.to_3x3() #global direction to local
            
            
            if ui_type not in {'SPARSE_POLY','DENSE_POLY', 'BEZIER'}: self.ui_type = 'SPARSE_POLY'
            else: self.ui_type = ui_type

            self.mouse_loc = None

            self.hovered_mesh = {}

            # TODO: Organize everything below this
            self.selected = None
            self.snap_element = None
            self.connect_element = None
            self.closest_ep = None
            self.hovered_near = [None, -1]

            self.kd = None
            self.non_man_bmverts = []
            self.find_non_man()
            self.non_man_eds = [ed.index for ed in self.bme.edges if not ed.is_manifold]
            self.non_man_ed_loops = edge_loops_from_bmedges_old(self.bme, self.non_man_eds)
        
        
        def inspect_print(self):
            print(self.selected)
            print(self.snap_element)
            print(self.connect_element)
            print(self.closest_ep) 
            print(self.hovered_near)
            
        def update_bvh(self):
            
            start = time.time()
            del self.bvh
            self.bvh = BVHTree.FromBMesh(self.bme)
            finish = time.time()
            
            print('updated BVH in %f seconds' % (finish-start))
                
        def has_non_man(self): return len(self.non_man_bmverts) > 0
        def is_hovering_mesh(self): 
            if self.hovered_mesh: return self.hovered_mesh["face index"] != -1
            return False
        has_non_man = property(has_non_man)
        is_hovering_mesh = property(is_hovering_mesh)

        def find_non_man(self):
            non_man_eds = [ed.index for ed in self.bme.edges if not ed.is_manifold]
            non_man_ed_loops = edge_loops_from_bmedges_old(self.bme, non_man_eds)
            non_man_points = []
            for loop in non_man_ed_loops:
                non_man_points += [self.ob.matrix_world * self.bme.verts[ind].co for ind in loop]
                self.non_man_bmverts += [self.bme.verts[ind].index for ind in loop]
            if non_man_points:
                self.kd = kdtree.KDTree(len(non_man_points))
                for i, v in enumerate(non_man_points):
                    self.kd.insert(v, i)
                self.kd.balance()
            else:
                self.kd = None

        def set_network(self, input_net): self.input_net = input_net

        def update(self, mouse_loc):
            self.mouse_loc = mouse_loc
            self.ray_cast_mouse()

            #self.nearest_non_man_loc()

        def ray_cast_mouse_ob(self):
            view_vector, ray_origin, ray_target= get_view_ray_data(self.context, self.mouse_loc)
            loc, no, face_ind = ray_cast(self.ob, self.imx, ray_origin, ray_target, None)
            if face_ind == -1: self.hovered_mesh = {}
            else:
                self.hovered_mesh["world loc"] = self.mx * loc
                self.hovered_mesh["local loc"] = loc
                self.hovered_mesh["normal"] = no
                self.hovered_mesh["face index"] = face_ind
                self.hovered_mesh["view"] = view_vector

        
        def ray_cast_mouse(self):
            view_vector, ray_origin, ray_target= get_view_ray_data(self.context, self.mouse_loc)
            loc, no, face_ind = ray_cast_bvh(self.bvh, self.imx, ray_origin, ray_target, None)
            if face_ind == None: self.hovered_mesh = {}
            else:
                self.hovered_mesh["world loc"] = self.mx * loc
                self.hovered_mesh["local loc"] = loc
                self.hovered_mesh["normal"] = no
                self.hovered_mesh["face index"] = face_ind
                self.hovered_mesh["view"] = view_vector
              
        def nearest_non_man_loc(self):
            '''
            finds nonman edges and verts nearby to cursor location
            '''
            if self.has_non_man and self.hovered_mesh:
                co3d, index, dist = self.kd.find(self.mx * self.hovered_mesh["local loc"])

                #get the actual non man vert from original list
                close_bmvert = self.bme.verts[self.non_man_bmverts[index]] #stupid mapping, unreadable, terrible, fix this, because can't keep a list of actual bmverts
                close_eds = [ed for ed in close_bmvert.link_edges if not ed.is_manifold]
                if len(close_eds) == 2:
                    bm0 = close_eds[0].other_vert(close_bmvert)
                    bm1 = close_eds[1].other_vert(close_bmvert)

                    a0 = bm0.co
                    b   = close_bmvert.co
                    a1  = bm1.co

                    inter_0, d0 = intersect_point_line(self.hovered_mesh["local loc"], a0, b)
                    inter_1, d1 = intersect_point_line(self.hovered_mesh["local loc"], a1, b)

                    region = self.context.region
                    rv3d = self.context.region_data
                    loc3d_reg2D = view3d_utils.location_3d_to_region_2d
                    mouse_v = Vector(self.mouse_loc)

                    screen_0 = loc3d_reg2D(region, rv3d, self.mx * inter_0)
                    screen_1 = loc3d_reg2D(region, rv3d, self.mx * inter_1)
                    screen_v = loc3d_reg2D(region, rv3d, self.mx * b)

                    if screen_0 and screen_1 and screen_v:
                        screen_d0 = (mouse_v - screen_0).length
                        screen_d1 = (mouse_v - screen_1).length
                        screen_dv = (mouse_v - screen_v).length

                        #TODO, decid how to handle when very very close to vertcies
                        if 0 < d0 <= 1 and screen_d0 < 20:
                            self.hovered_near = ['NON_MAN_ED', (close_eds[0], self.mx*inter_0)]
                            return
                        elif 0 < d1 <= 1 and screen_d1 < 20:
                            self.hovered_near = ['NON_MAN_ED', (close_eds[1], self.mx*inter_1)]
                            return



        def nearest_endpoint(self, mouse_3d_loc):
            def dist3d(ip):
                return (ip.world_loc - mouse_3d_loc).length

            endpoints = [ip for ip in self.input_net.points if ip.is_endpoint]
            if len(endpoints) == 0: return None

            return min(endpoints, key = dist3d)

    # TODO: Clean this up
    def click_add_point(self, context, mouse_loc, connect=True):
        '''
        this will add a point into the trim line
        close the curve into a cyclic curve
        
        #Need to get smarter about closing the loop
        '''
        def none_selected(): self.net_ui_context.selected = None # TODO: Change this weird function in function shizz
        
        view_vector, ray_origin, ray_target= get_view_ray_data(context,mouse_loc)
        #loc, no, face_ind = ray_cast(self.net_ui_context.ob, self.net_ui_context.imx, ray_origin, ray_target, none_selected)
        loc, no, face_ind = ray_cast_bvh(self.net_ui_context.bvh, self.net_ui_context.imx, ray_origin, ray_target, none_selected)
        
        if loc == None: 
            print("Here")
            return

        if self.net_ui_context.hovered_near[0] and 'NON_MAN' in self.net_ui_context.hovered_near[0]:
            bmed, wrld_loc = self.net_ui_context.hovered_near[1] # hovered_near[1] is tuple (BMesh Element, location?)
            ip1 = self.closest_endpoint(wrld_loc)

            self.net_ui_context.selected = self.input_net.create_point(wrld_loc, self.net_ui_context.imx * wrld_loc, view_vector, bmed.link_faces[0].index)
            self.net_ui_context.selected.seed_geom = bmed
            self.net_ui_context.selected.bmedge = bmed  #UNUSED BUT PREPARING FOR FUTURE

            if ip1:
                seg = InputSegment(self.net_ui_context.selected, ip1)
                self.input_net.segments.append(seg)
                self.network_cutter.precompute_cut(seg)
                #seg.make_path(self.net_ui_context.bme, self.input_net.bvh, self.net_ui_context.mx, self.net_ui_context.imx)
        
        #Add a New Point at end
        elif (self.net_ui_context.hovered_near[0] == None) and (self.net_ui_context.snap_element == None):  #adding in a new point at end, may need to specify closest unlinked vs append and do some previs
            print("Here 11")
            closest_endpoint = self.closest_endpoint(self.net_ui_context.mx * loc)
            self.net_ui_context.selected = self.input_net.create_point(self.net_ui_context.mx * loc, loc, view_vector, face_ind)
            print('create new point')
            
            if len(self.spline_net.points):
                last_node = self.spline_net.points[-1]
                new_node = self.spline_net.create_point(self.net_ui_context.mx * loc, loc, view_vector, face_ind)
                self.spline_net.connect_points(new_node, last_node)
                new_node.update_splines()
                last_node.update_splines()  #this is going to update the spline twice?
            else:
                new_node = self.spline_net.create_point(self.net_ui_context.mx * loc, loc, view_vector, face_ind)
                   
            if closest_endpoint and connect:
                self.input_net.connect_points(self.net_ui_context.selected, closest_endpoint)
                self.network_cutter.precompute_cut(self.input_net.segments[-1])  #<  Hmm...not very clean.  

        elif self.net_ui_context.hovered_near[0] == None and self.net_ui_context.snap_element != None:  #adding in a new point at end, may need to specify closest unlinked vs append and do some previs
            print("Here 2")
            closest_endpoints = self.closest_endpoints(self.net_ui_context.snap_element.world_loc, 2)

            if closest_endpoints == None:
                #we are not quite hovered_near but in snap territory
                return

            if len(closest_endpoints) < 2:
                return

            seg = InputSegment(closest_endpoints[0], closest_endpoints[1])
            self.input_net.segments.append(seg)
            self.network_cutter.precompute_cut(seg)
            #seg.make_path(self.net_ui_context.bme, self.input_net.bvh, self.net_ui_context.mx, self.net_ui_context.imx)

        elif self.net_ui_context.hovered_near[0] == 'POINT':
            self.net_ui_context.selected = self.net_ui_context.hovered_near[1]

        elif self.net_ui_context.hovered_near[0] == 'EDGE':  #TODO, actually make InputSegment as hovered_near
            point = self.input_net.create_point(self.net_ui_context.mx * loc, loc, view_vector, face_ind)
            old_seg = self.net_ui_context.hovered_near[1]
            self.input_net.insert_point(point, old_seg)
            self.net_ui_context.selected = point
            self.network_cutter.update_segments()

    def click_add_spline_point(self, context, mouse_loc, connect=True):
        '''
        this will add a point into the trim line
        close the curve into a cyclic curve
        
        #Need to get smarter about closing the loop
        '''
        def none_selected(): self.net_ui_context.selected = None # TODO: Change this weird function in function shizz
        
        view_vector, ray_origin, ray_target= get_view_ray_data(context,mouse_loc)
        #loc, no, face_ind = ray_cast(self.net_ui_context.ob, self.net_ui_context.imx, ray_origin, ray_target, none_selected)
        loc, no, face_ind = ray_cast_bvh(self.net_ui_context.bvh, self.net_ui_context.imx, ray_origin, ray_target, none_selected)
        
        if not loc: return

        #Add a new edge_point?
        if self.net_ui_context.hovered_near[0] and 'NON_MAN' in self.net_ui_context.hovered_near[0]:
            bmed, wrld_loc = self.net_ui_context.hovered_near[1] # hovered_near[1] is tuple (BMesh Element, location?)
            ip1 = self.closest_spline_endpoint(wrld_loc)

            self.net_ui_context.selected = self.spline_net.create_point(wrld_loc, self.net_ui_context.imx * wrld_loc, view_vector, bmed.link_faces[0].index)
            self.net_ui_context.selected.seed_geom = bmed
            self.net_ui_context.selected.bmedge = bmed  #UNUSED, but preparing for future

            self.net_ui_context.selected.update_splines()
                
            if ip1:
                seg = SplineSegment(self.net_ui_context.selected, ip1)
                self.spline_net.segments.append(seg)
                ip1.update_splines()
                #self.network_cutter.precompute_cut(seg)
                #seg.make_path(self.net_ui_context.bme, self.input_net.bvh, self.net_ui_context.mx, self.net_ui_context.imx)
        
        #Add a New Point at end free chains
        elif (self.net_ui_context.hovered_near[0] == None) and (self.net_ui_context.snap_element == None):  #adding in a new point at end, may need to specify closest unlinked vs append and do some previs
            
            closest_endpoint = self.closest_spline_endpoint(self.net_ui_context.mx * loc)
            self.net_ui_context.selected = self.spline_net.create_point(self.net_ui_context.mx * loc, loc, view_vector, face_ind)
            print('create new point')
                
            if closest_endpoint and connect:
                self.spline_net.connect_points(self.net_ui_context.selected, closest_endpoint)
                self.net_ui_context.selected.update_splines()
                closest_endpoint.update_splines() 

        elif self.net_ui_context.hovered_near[0] == 'POINT CONNECT' and self.net_ui_context.snap_element != None:  #adding in a new point at end, may need to specify closest unlinked vs append and do some previs
            print("Here 2")
            closest_endpoints = self.closest_spline_endpoints(self.net_ui_context.snap_element.world_loc, 2)
            # bail if we did not find at least two nearby endpoints
            if len(closest_endpoints) < 2: return
            seg = SplineSegment(closest_endpoints[0], closest_endpoints[1])
            self.spline_net.segments.append(seg)
            closest_endpoints[0].update_splines()
            closest_endpoints[1].update_splines()

            #self.network_cutter.precompute_cut(seg)
            #seg.make_path(self.net_ui_context.bme, self.input_net.bvh, self.net_ui_context.mx, self.net_ui_context.imx)

        elif self.net_ui_context.hovered_near[0] == 'POINT':
            self.net_ui_context.selected = self.net_ui_context.hovered_near[1]

        elif self.net_ui_context.hovered_near[0] == 'EDGE':  #TODO, actually make InputSegment as hovered_near
            point = self.spline_net.create_point(self.net_ui_context.mx * loc, loc, view_vector, face_ind)
            old_seg = self.net_ui_context.hovered_near[1]
            self.spline_net.insert_point(point, old_seg)
            old_seg.clear_input_net_references(self.input_net)
            self.net_ui_context.selected = point
            
            point.update_splines()
            for node in old_seg.points:
                node.update_splines()
            
            
        self.spline_net.push_to_input_net(self.net_ui_context, self.input_net)
        self.network_cutter.update_segments_async()

    # TODO: Clean this up
    def click_delete_point(self, mode = 'mouse', disconnect=False):
        '''
        removes point from the trim line
        '''
        if mode == 'mouse':
            if self.net_ui_context.hovered_near[0] != 'POINT': return

            self.input_net.remove_point(self.net_ui_context.hovered_near[1], disconnect) 
            self.network_cutter.update_segments()

            if self.input_net.is_empty or self.net_ui_context.selected == self.net_ui_context.hovered_near[1]:
                self.net_ui_context.selected = None

        else: #hard delete with x key
            if not self.net_ui_context.selected: return
            self.input_net.remove(self.net_ui_context.selected, disconnect= True)

    def click_delete_spline_point(self, mode = 'mouse', disconnect=False):
        '''
        removes point from the trim line
        '''
        if mode == 'mouse':
            if self.net_ui_context.hovered_near[0] != 'POINT': return
            curve_point = self.net_ui_context.hovered_near[1]  #CurveNode

            #Clear the CurveNode to InputNetwork mappings and delete corresponding
            #elements
            for seg in curve_point.link_segments:
                seg.clear_input_net_references(self.input_net)
            if curve_point.input_point in self.input_net.points:
                self.input_net.remove_point(curve_point.input_point, disconnect)
            #Remove CurveNode from SplineNetwork
            self.spline_net.remove_point(curve_point, disconnect)
                
            if self.spline_net.is_empty or self.net_ui_context.selected == self.net_ui_context.hovered_near[1]:
                self.net_ui_context.selected = None

        else: #hard delete with x key
            if not self.net_ui_context.selected: return
            self.spline_net.remove(self.net_ui_context.selected, disconnect= True)
    
    def click_add_seed(self):
        
        if self.net_ui_context.hovered_mesh == {}: return
        
        face_ind = self.net_ui_context.hovered_mesh['face index']
        world_loc = self.net_ui_context.hovered_mesh['world loc']
        local_loc = self.net_ui_context.hovered_mesh['local loc']
        self.network_cutter.add_seed(face_ind, world_loc, local_loc)
    
    def click_enter_paint(self):
        
        if self.net_ui_context.hovered_mesh == {}: return
        
        face_ind = self.net_ui_context.hovered_mesh['face index']
        world_loc = self.net_ui_context.hovered_mesh['world loc']
        local_loc = self.net_ui_context.hovered_mesh['local loc']
        
        f= self.net_ui_context.bme.faces[face_ind] 
         
        self.network_cutter.active_patch = None  #TODO, this should already be none..should we enforce it?
        for patch in self.network_cutter.face_patches:
            if f in patch.patch_faces:  #just change the color but don't add a duplicate
                self.network_cutter.active_patch = patch
                self.brush.brush_color = patch.color
                print('found the active patch')
        
        if self.network_cutter.active_patch == None:
            self.network_cutter.add_patch_start_paint(face_ind, world_loc, local_loc)
                       
    def paint_confirm(self):
        print('paint confirm')
        for patch in self.network_cutter.face_patches:
            if patch == self.network_cutter.active_patch:continue
            
            if not patch.patch_faces.isdisjoint(self.brush.geom_accum):
                patch.paint_modified = True
            patch.patch_faces.difference_update(self.brush.geom_accum)
            

        #Destroy all Discrete Network Elements touched by brush
        remove_points = []
        for ip in self.input_net.points:
            if ip.bmface in self.brush.geom_accum:
                #self.input_net.remove_point(ip, disconnect = True)
                remove_points += [ip]
                
        for ip in remove_points:
            self.input_net.remove_point(ip, disconnect = True)
            
        remove_segs = []        
        for seg in self.input_net.segments:
            if seg not in self.network_cutter.cut_data: continue #uh oh
            if not self.brush.geom_accum.isdisjoint(self.network_cutter.cut_data[seg]['face_set']):
                #self.input_net.remove_segment(seg)                             
                remove_segs += [seg]
        
        for seg in remove_segs:
            self.input_net.remove_segment(seg)
    
        #perhaps create new spline endpoints at the discrete endpoints..YES
        #Destroy all Spline Network Elements touched by brush
        remove_nodes = []
        for node in self.spline_net.points:
            if node.bmface in self.brush.geom_accum:
                #self.spline_net.remove_point(node, disconnect = True)
                remove_nodes += [node]
                
        for node in remove_nodes:
            #the seg is about to get deleted because it's node is gone
            #so we will loose the opportuity to clear out the children
            #segments
            for seg in node.link_segments:
                seg.clear_input_net_references(self.input_net)
            #actually delete the node
            self.spline_net.remove_point(node, disconnect = True)
            node.clear_input_net_references(self.input_net)  #Should  not be any
            
        remove_splines = []    
        for spline in self.spline_net.segments:
            for ip_seg in spline.input_segments:
                if ip_seg not in self.input_net.segments:
                    #  #remove teh associated SPLINE segment  #TODO get smarter later 
                    remove_splines += [spline]
                    
        for spline in remove_splines:
            self.spline_net.remove_segment(spline)            
            spline.clear_input_net_references(self.input_net) #if the spline parent is gone, we take all children away from the border too....#TRUMP?        
        
        loose_nodes = []     
        for node in self.spline_net.points:
            if len(node.link_segments) == 0:
                loose_nodes += [node]
                
        print('deleting %i loose nodes' % len(loose_nodes))       
        for node in loose_nodes:
            self.spline_net.remove_point(node)

        self.network_cutter.active_patch.patch_faces |= self.brush.geom_accum
        self.network_cutter.active_patch.paint_modified = True
        
        
        #TODO, remove the destroyed elements from the patch references
        
        self.network_cutter.active_patch.color_patch()
        self.network_cutter.validate_cdata()
        
        
        return
        ####### BRUTE FORCE REMOVE PATCH PERIMETER DATA ########
        for patch in self.network_cutter.face_patches:
            if not patch.paint_modified: continue
            
            print('this patch has %i ip points' % len(patch.ip_points))
            print('this patch has %i spline points' % len(patch.curve_nodes))
            #clear out all input points
            for ip in patch.ip_points:
                if ip in self.input_net.points:  #TODO, get really smart, only remove the affected discreet or curve network geom?
                    self.input_net.remove_point(ip, disconnect = True)
            
            #clear out all SplinePoints
            for seg in patch.spline_net_segments:
                seg.clear_input_net_references(self.input_net) #clear out the InputNet
                self.spline_net.remove_segment(seg) #clear out the SplineNet
                
                print('there are now %i nodes in spline net' % len(self.spline_net.points))
                print('there are now %i points in input net' % len(self.input_net.points))
                
                print('there are now %i segs in input net' % len(self.input_net.segments))
                print('there are now %i segs in spline net' % len(self.spline_net.segments))
            
            for node in patch.curve_nodes:
                if node in self.spline_net.points:
                    self.spline_net.remove_point(node)
      
                   
        
        
        
    def paint_exit(self):
        print('paint exit')
        
        #create new splines around newly created patches
        self.network_cutter.create_spline_network_from_face_patches(self.spline_net)
        
        #fit splines to modified boundaries of existing patches
        self.network_cutter.update_painted_face_patches_splines(self.spline_net)
        
        #now push all the splines back to input net and preview the cuts
        self.spline_net.push_to_input_net(self.net_ui_context, self.input_net)
        self.network_cutter.update_segments_async()
        
        #Do this for now
        self.net_ui_context.bme.to_mesh(self.net_ui_context.ob.data)
        
    # TODO: Make this a NetworkUIContext function
    def closest_endpoint(self, pt3d):
        def dist3d(point):
            return (point.world_loc - pt3d).length

        endpoints = [ip for ip in self.input_net.points if ip.is_endpoint]
        if len(endpoints) == 0: return None

        return min(endpoints, key = dist3d)
    
    # TODO: Make this a NetworkUIContext function
    def closest_spline_endpoint(self, pt3d):
        def dist3d(point):
            return (point.world_loc - pt3d).length

        endpoints = [ip for ip in self.spline_net.points if ip.is_endpoint]
        if len(endpoints) == 0: return None

        return min(endpoints, key = dist3d)
    
    # TODO: Also NetworkUIContext function
    def closest_endpoints(self, pt3d, n_points):
        #in our application, at most there will be 100 endpoints?
        #no need for accel structure here
        n_points = max(0, n_points)

        endpoints = [ip for ip in self.input_net.points if ip.is_endpoint] #TODO self.endpoints?

        if len(endpoints) == 0: return None
        n_points = min(n_points, len(endpoints))

        def dist3d(point):
            return (point.world_loc - pt3d).length

        endpoints.sort(key = dist3d)

        return endpoints[0:n_points+1]

    def closest_spline_endpoints(self, pt3d, n_points):
        #in our application, at most there will be 100 endpoints?
        #no need for accel structure here
        n_points = max(0, n_points)

        endpoints = [ip for ip in self.spline_net.points if ip.is_endpoint] #TODO self.endpoints?
        if len(endpoints) == 0: return []
        n_points = min(n_points, len(endpoints))

        def dist3d(point): return (point.world_loc - pt3d).length

        endpoints.sort(key = dist3d)
        return endpoints[0:n_points+1]

    # TODO: NetworkUIContext??
    def closest_point_3d_linear(self, seg, pt3d):
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

        if isinstance(seg, SplineSegment):
            intersect3d = intersect_point_line(pt3d, seg.n0.world_loc, seg.n1.world_loc)
        else:
            intersect3d = intersect_point_line(pt3d, seg.ip0.world_loc, seg.ip1.world_loc)

        if intersect3d == None: return (None, None)

        dist3d = (intersect3d[0] - pt3d).length

        if  (intersect3d[1] < 1) and (intersect3d[1] > 0):
            return (intersect3d[0], dist3d)

        return (None, None)

    def enter_poly_mode(self):
        if self._state == 'main': return
        
        if self._state == 'paint main':
            del self.brush
            self.brush = None
            self.paint_exit()
            self.fsm_change('main')
    
        elif self._state == 'seed':
            self.fsm_change('main')
            
            
    def enter_paint_mode(self):
        self.fsm_change('paint entering')
               
        
        
    def find_network_cycles_button(self):
        self.input_net.find_network_cycles()
    
    def knife_stepwise_prepare_button(self):
        self.network_cutter.knife_gometry_stepper_prepare()
        
    def knife_step_button(self):
        self.network_cutter.knife_geometry_step()
        self.net_ui_context.bme.to_mesh(self.net_ui_context.ob.data)
         
    def compute_cut_button(self):
        self.network_cutter.knife_geometry4()
        
        self.network_cutter.find_perimeter_edges()
        for patch in self.network_cutter.face_patches:
            patch.grow_seed(self.input_net.bme, self.network_cutter.boundary_edges)
            patch.color_patch()
        self.net_ui_context.bme.to_mesh(self.net_ui_context.ob.data)
        
        self._sate_next = 'seed'
        
    def enter_seed_select_button(self):
        self.fsm_change('seed')
        self.cursor_modal_set('EYEDROPPER')
        return
    
       
    def hover(self, select_radius = 12, snap_radius = 24): #TDOD, these radii are pixels? Shoudl they be settings?
        '''
        finds points/edges/etc that are near ,mouse
         * hovering happens in mixed 3d and screen space, 20 pixels thresh for points, 30 for edges 40 for non_man
        '''

        # TODO: update self.hover to use Accel2D?
        mouse = self.actions.mouse
        context = self.context

        mx, imx = get_matrices(self.net_ui_context.ob)
        loc3d_reg2D = view3d_utils.location_3d_to_region_2d
        # ray tracing
        view_vector, ray_origin, ray_target = get_view_ray_data(context, mouse)
        #loc, no, face_ind = ray_cast(self.net_ui_context.ob, imx, ray_origin, ray_target, None)
        loc, no, face_ind = ray_cast_bvh(self.net_ui_context.bvh, imx, ray_origin, ray_target, None)
        self.net_ui_context.snap_element = None
        self.net_ui_context.connect_element = None

        if self.input_net.is_empty:
            self.net_ui_context.hovered_near = [None, -1]
            self.net_ui_context.nearest_non_man_loc()
            return
        
        if face_ind == -1 or face_ind == None: 
            self.net_ui_context.closest_ep = None
            return
        else: self.net_ui_context.closest_ep = self.closest_endpoint(mx * loc)

        #find length between vertex and mouse
        def dist(v):
            if v == None:
                print('v off screen')
                return 100000000
            diff = v - Vector(mouse)
            return diff.length

        #find length between 2 3d points
        def dist3d(v3):
            if v3 == None:
                return 100000000
            delt = v3 - self.net_ui_context.ob.matrix_world * loc
            return delt.length

        #closest_3d_loc = min(self.input_net.world_locs, key = dist3d)
        closest_ip = min(self.input_net.points, key = lambda x: dist3d(x.world_loc))
        pixel_dist = dist(loc3d_reg2D(context.region, context.space_data.region_3d, closest_ip.world_loc))

        if pixel_dist  < select_radius:
            #print('point is hovered_near')
            #print(pixel_dist)
            self.net_ui_context.hovered_near = ['POINT', closest_ip]  #TODO, probably just store the actual InputPoint as the 2nd value?
            self.net_ui_context.snap_element = None
            return

        elif pixel_dist >= select_radius and pixel_dist < snap_radius:
            #print('point is within snap radius')
            #print(pixel_dist)
            if closest_ip.is_endpoint:
                self.net_ui_context.snap_element = closest_ip

                #print('This is the close loop scenario')
                closest_endpoints = self.closest_endpoints(self.net_ui_context.snap_element.world_loc, 2)

                #print('these are the 2 closest endpoints, one should be snap element itself')
                #print(closest_endpoints)
                if closest_endpoints == None:
                    #we are not quite hovered_near but in snap territory
                    return

                if len(closest_endpoints) < 2:
                    #print('len of closest endpoints not 2')
                    return

                self.net_ui_context.connect_element = closest_endpoints[1]

            return


        if self.input_net.num_points == 1:  #why did we do this? Oh because there are no segments.
            self.net_ui_context.hovered_near = [None, -1]
            self.net_ui_context.snap_element = None
            return

        ##Check distance between ray_cast point, and segments
        distance_map = {}
        for seg in self.input_net.segments:  #TODO, may need to decide some better naming and better heirarchy
  
            close_loc, close_d = self.closest_point_3d_linear(seg, self.net_ui_context.ob.matrix_world * loc)
            if close_loc  == None:
                distance_map[seg] = 10000000
                continue

            distance_map[seg] = close_d

        if self.input_net.segments:
            closest_seg = min(self.input_net.segments, key = lambda x: distance_map[x])

            a = loc3d_reg2D(context.region, context.space_data.region_3d, closest_seg.ip0.world_loc)
            b = loc3d_reg2D(context.region, context.space_data.region_3d, closest_seg.ip1.world_loc)

            if a and b:  #if points are not on the screen, a or b will be None
                intersect = intersect_point_line(Vector(mouse).to_3d(), a.to_3d(),b.to_3d())
                dist = (intersect[0].to_2d() - Vector(mouse)).length_squared
                bound = intersect[1]
                if (dist < select_radius**2) and (bound < 1) and (bound > 0):
                    self.net_ui_context.hovered_near = ['EDGE', closest_seg]
                    return

        ## Multiple points, but not hovering over edge or point.
        self.net_ui_context.hovered_near = [None, -1]

        self.net_ui_context.nearest_non_man_loc()


    def hover_spline(self, select_radius=12, snap_radius=24): #TODO, these radii are pixels? Should they be settings?
        '''
        finds points/edges/etc that are near ,mouse
         * hovering happens in mixed 3d and screen space, 20 pixels thresh for points, 30 for edges 40 for non_man
        '''

        self.net_ui_context.snap_element    = None
        self.net_ui_context.connect_element = None
        self.net_ui_context.hovered_near    = [None, -1]
        self.net_ui_context.hovered_dist2D  = float('inf')
        self.net_ui_context.closest_ep      = None

        # TODO: update self.hover to use Accel2D?
        mouse = self.actions.mouse
        mouse_vec = Vector(mouse)
        context = self.context
        mx, imx = get_matrices(self.net_ui_context.ob)
        loc3d_reg2D = view3d_utils.location_3d_to_region_2d

        if self.spline_net.is_empty:
            # no points to be near
            self.net_ui_context.nearest_non_man_loc()
            return

        # ray tracing
        view_vector, ray_origin, ray_target = get_view_ray_data(context, mouse)
        #loc, no, face_ind = ray_cast(self.net_ui_context.ob, imx, ray_origin, ray_target, None)
        loc,_,face_ind = ray_cast_bvh(self.net_ui_context.bvh, imx, ray_origin, ray_target, None)

        # bail if we did not hit the source
        if face_ind == -1 or face_ind == None: return

        loc = mx * loc      # transform loc to world
        self.net_ui_context.closest_ep = self.closest_spline_endpoint(loc)

        # find length between vertex and mouse
        def dist(v): return (v - mouse_vec).length if v else float('inf')
        # find length between 2 3d points
        def dist3d(v3): return (v3 - loc).length if v3 else float('inf')

        #closest_3d_loc = min(self.spline_net.world_locs, key = dist3d)
        closest_ip = min(self.spline_net.points, key = lambda x: dist3d(x.world_loc))
        pixel_dist = dist(loc3d_reg2D(context.region, context.space_data.region_3d, closest_ip.world_loc))

        if pixel_dist < select_radius:
            # the mouse is hovering over a point
            self.net_ui_context.hovered_near = ['POINT', closest_ip]  #TODO, probably just store the actual InputPoint as the 2nd value?
            self.net_ui_context.hovered_dist2D = pixel_dist
            return

        if select_radius <= pixel_dist < snap_radius:
            # the mouse is near a point (just outside of hovering)
            if closest_ip.is_endpoint:
                # only care about endpoints at this moment
                self.net_ui_context.snap_element = closest_ip
                self.net_ui_context.hovered_dist2D = pixel_dist
                #print('This is the close loop scenario')
                closest_endpoints = self.closest_spline_endpoints(self.net_ui_context.snap_element.world_loc, 2)
                # bail if we did not find at least two nearby endpoints
                if len(closest_endpoints) < 2: return
                self.net_ui_context.hovered_near = ['POINT CONNECT', closest_ip]
                self.net_ui_context.connect_element = closest_endpoints[1]
            return

        # bail if there are only one num_points (no segments)
        if self.spline_net.num_points == 1: return

        ##Check distance between ray_cast point, and segments
        distance_map = {}
        for seg in self.spline_net.segments:  #TODO, may need to decide some better naming and better hierarchy
            close_loc, close_d = self.closest_point_3d_linear(seg, loc)
            distance_map[seg] = close_d if close_loc else float('inf')

        if self.spline_net.segments:
            closest_seg = min(self.spline_net.segments, key = lambda x: distance_map[x])

            a = loc3d_reg2D(context.region, context.space_data.region_3d, closest_seg.n0.world_loc)
            b = loc3d_reg2D(context.region, context.space_data.region_3d, closest_seg.n1.world_loc)

            if a and b:  #if points are not on the screen, a or b will be None
                intersect = intersect_point_line(mouse_vec.to_3d(), a.to_3d(),b.to_3d())
                dist = (intersect[0].to_2d() - mouse_vec).length_squared
                bound = intersect[1]
                if (dist < select_radius**2) and (bound < 1) and (bound > 0):
                    self.net_ui_context.hovered_near = ['EDGE', closest_seg]
                    return
        ## Multiple points, but not hovering over edge or point.

        self.net_ui_context.nearest_non_man_loc()


    ### XXX: Put these in their own class maybe?
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
        loc, no, ind, d = self.input_net.bvh.find_nearest(new_pt.local_loc)
        
        #view stays the same
        new_pt.set_face_ind(ind)
        new_pt.set_local_loc(loc)
        new_pt.set_world_loc(self.net_ui_context.mx * loc)
    
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

        if ind_start > ind_end:
            points = self.input_net.points[ind_start:] + self.input_net.points[:ind_end]

        elif ind_start > ind_end:
            ind_start, ind_end = ind_end, ind_start
            points = self.input_net.points[ind_start:ind_end+1]  #need to get the last point
        else:
            points = self.input_net.points[ind_start:ind_end+1]  #need to get the last point
        
        
        new_points = []
        for i in range(0, len(points) - 1):
            L = (points[i+1].world_loc - points[i].world_loc).length
            n_steps = round(L/res)
            
            if n_steps == 0: #don't loose points at closer resolution
                new_points += [points[i].duplicate()]
                
            for n in range(n_steps):
                factor = n/n_steps
                new_points += [self.interpolate_input_point_pair(points[i+1], points[i], factor)]
                
        new_points += [points[-1]]  #get the final point on there
        
        
        if ind_start > ind_end:  
            self.input_net.points = new_points + self.input_net.points[ind_end:ind_start]  #self.input_net.points[ind_start:] + self.input_net.points[:ind_end]
        
        elif ind_start < ind_end:
            
            self.input_net.points = self.input_net.points[0:ind_start] + new_points + self.input_net.points[ind_end:]
                
        else:
            self.input_net.points = self.input_net.points[0:ind_start] + new_points + self.input_net.points[ind_end:]
        
        self.net_ui_context.selected = None   