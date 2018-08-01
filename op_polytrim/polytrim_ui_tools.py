'''
Created on Oct 10, 2015

@author: Patrick
'''
from ..common.utils import get_matrices
from ..common.rays import get_view_ray_data, ray_cast, ray_cast_path
from .polytrim_datastructure import InputPointMap, PolyLineKnife
from bpy_extras import view3d_utils
from mathutils import Vector
from mathutils.geometry import intersect_point_line



class Polytrim_UI_Tools():
    '''
    Functions helpful with user interactions in polytrim
    '''

    def sketch_confirm(self, context, eventd):
        '''
        prepares the points gathered from sketch for adding to PolyLineKnife 
        '''
        # checking to see if sketch functionality shouldn't happen
        if len(self.sketch) < 5 and self.plm.current.ui_type == 'DENSE_POLY':
            print('A sketch was not detected..')
            if self.plm.current.hovered== ['POINT', 0] and not self.plm.current.start_edge and self.plm.current.num_points > 2:
                self.plm.current.toggle_cyclic()  #self.plm.current.cyclic = self.plm.current.cyclic == False  #toggle behavior?
            return False

        # Get user view ray
        region = context.region
        rv3d = context.region_data
        view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, self.mouse)  #get the direction under the mouse given the user 3DView perspective matrix

        ## Preparing sketch information
        hovered_start = self.plm.current.hovered # need to know what hovered was at the beginning of the sketch
        self.hover(context)  #rehover to see where sketch ends
        sketch_3d = ray_cast_path(context, self.plm.current.source_ob, self.sketch)  #at this moment we are going into 3D space, this returns world space locations
        sketch_locs = sketch_3d[0::5] # getting every fifth point's location
        sketch_views = [view_vector]*len(sketch_locs)
        sketch_points = InputPointMap()
        sketch_points.add_multiple(sketch_locs, [None]*len(sketch_locs), sketch_views, [None]*len(sketch_locs))

        # Add the sketch in
        self.plm.current.add_sketch_points(hovered_start, sketch_points, view_vector)
        self.plm.current.snap_poly_line()  #why do this again?

        return True

    def ui_text_update(self, context):
        '''
        updates the text at the bottom of the viewport depending on certain conditions
        '''
        if self.plm.current.bad_segments:
            context.area.header_text_set("Fix Bad segments by moving control points.")
        elif self.plm.current.ed_cross_map.is_used:
            context.area.header_text_set("When cut is satisfactory, press 'S' then 'LeftMouse' in region to cut")
        elif self.plm.current.hovered[0] == 'POINT':
            if self.plm.current.hovered[1] == 0:
                context.area.header_text_set("For origin point, left click to toggle cyclic")
            else:
                context.area.header_text_set("Right click to delete point. Hold left click and drag to make a sketch")
        else:
            self.set_ui_text_main(context)

    def set_ui_text_main(self, context):
        ''' sets the viewports text during general creation of line '''
        context.area.header_text_set("Left click to place cut points on the mesh, then press 'C' to preview the cut")

    def hover(self,context):
        '''
        finds points/edges/etc that are near cursor
         * hovering happens in mixed 3d and screen space, 20 pixels thresh for points, 30 for edges 40 for non_man
        '''
        polyline = self.plm.current

        mx, imx = get_matrices(polyline.source_ob)
        loc3d_reg2D = view3d_utils.location_3d_to_region_2d
        # ray tracing
        view_vector, ray_origin, ray_target = get_view_ray_data(context,self.mouse)
        loc, no, face_ind = ray_cast(polyline.source_ob, imx, ray_origin, ray_target, None)

        if polyline.input_points.is_empty:
            polyline.hovered = [None, -1]
            self.hover_non_man(context)
            return

       # find length between vertex and mouse
        def dist(v):
            if v == None:
                print('v off screen')
                return 100000000
            diff = v - Vector(self.mouse)
            return diff.length


        def dist3d(v3):
            if v3 == None:
                return 100000000
            delt = v3 - polyline.source_ob.matrix_world * loc
            return delt.length

        closest_3d_loc = min(polyline.input_points.world_locs, key = dist3d)
        pixel_dist = dist(loc3d_reg2D(context.region, context.space_data.region_3d, closest_3d_loc))
        if pixel_dist  < 20:
            polyline.hovered = ['POINT', polyline.input_points.world_locs.index(closest_3d_loc)]
            return

        if polyline.num_points == 1:
            polyline.hovered = [None, -1]
            return

        ## ?? What is happening here
        line_inters3d = []
        for i in range(polyline.num_points):
            nexti = (i + 1) % polyline.num_points
            if next == 0 and not polyline.cyclic:
                polyline.hovered = [None, -1]
                return


            intersect3d = intersect_point_line(polyline.source_ob.matrix_world * loc, polyline.input_points.get(i).world_loc, polyline.input_points.get(nexti).world_loc)

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
        nexti = (i + 1) % polyline.num_points

        ## ?? And here
        a  = loc3d_reg2D(context.region, context.space_data.region_3d,polyline.input_points.get(i).world_loc)
        b = loc3d_reg2D(context.region, context.space_data.region_3d,polyline.input_points.get(nexti).world_loc)

        ## ?? and here, obviously, its stopping and setting hovered to EDGE, but how?
        if a and b:
            intersect = intersect_point_line(Vector(self.mouse).to_3d(), a.to_3d(),b.to_3d())
            dist = (intersect[0].to_2d() - Vector(self.mouse)).length_squared
            bound = intersect[1]
            if (dist < 400) and (bound < 1) and (bound > 0):
                polyline.hovered = ['EDGE', i]
                return

        ## Multiple points, but not hovering over edge or point.
        polyline.hovered = [None, -1]

        if polyline.start_edge != None and polyline.end_edge == None:
            self.hover_non_man(context)  #todo, optimize because double ray cast per mouse move!

    def hover_non_man(self,context):
        '''
        finds nonman edges and verts nearby to cursor location
        '''
        polyline = self.plm.current

        region = context.region
        rv3d = context.region_data
        mx, imx = get_matrices(polyline.source_ob)
        # ray casting
        view_vector, ray_origin, ray_target= get_view_ray_data(context, self.mouse)
        loc, no, face_ind = ray_cast(polyline.source_ob, imx, ray_origin, ray_target, None)

        self.mouse = Vector(self.mouse)
        loc3d_reg2D = view3d_utils.location_3d_to_region_2d
        if len(polyline.non_man_points):
            co3d, index, dist = polyline.kd.find(mx * loc)

            #get the actual non man vert from original list
            close_bmvert = polyline.bme.verts[polyline.non_man_bmverts[index]] #stupid mapping, unreadable, terrible, fix this, because can't keep a list of actual bmverts
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
                        polyline.hovered = ['NON_MAN_ED', (close_eds[0], mx*inter_0)]
                        return
                    elif 0 < d1 <= 1 and screen_d1 < 20:
                        polyline.hovered = ['NON_MAN_ED', (close_eds[1], mx*inter_1)]
                        return
                    elif screen_dv < 20:
                        if abs(d0) < abs(d1):
                            polyline.hovered = ['NON_MAN_VERT', (close_eds[0], mx*b)]
                            return
                        else:
                            polyline.hovered = ['NON_MAN_VERT', (close_eds[1], mx*b)]
                            return

class PolyLineManager(object):
    '''
    Manages having multiple instances of PolyLineKnife on an object at once.
    '''
    def __init__(self):
        self.polylines = []
        self.vert_screen_locs = {}
        self.hovered = None
        self.current = None
        self.previous = None
        self.mode = 'wait' # 'wait'  : mode for editing a single polyline's datastructure
                           # 'select': mode for selecting, adding, and deleting polylines

    def num_polylines(self): return len(self.polylines)
    num_polylines = property(num_polylines)

   ######################
   ## user interaction ##

    def initiate_select_mode(self, context):
        self.mode = 'select'
        self.previous = self.current
        self.current = None
        self.update_screen_locs(context)

    def hover(self, context, coord):
        print(self.num_polylines)
        for polyline in self.vert_screen_locs:
            for loc in self.vert_screen_locs[polyline]:
                if self.dist(loc, coord) < 20:
                    self.hovered = polyline
                    return
        self.hovered = None

    def select(self, context):
        self.mode = 'wait'
        self.current = self.hovered
        self.hovered = None

    def delete(self, context):
        if self.previous == self.hovered: self.previous = self.polylines[self.polylines.index(self.hovered) - 1]
        self.polylines.remove(self.hovered)
        self.hovered = None
        self.update_screen_locs(context)

    def start_new_polyline(self, context):
        self.mode = 'wait'
        self.hovered = None
        self.previous = None
        self.current = PolyLineKnife(context, context.object)
        self.add(self.current)

    def terminate_select_mode(self):
        self.mode = 'wait'
        self.hovered = None
        self.current = self.previous

    ###########
    ## other ##

    def add(self, polyline):
        ''' add a polyline to the plm's polyline list '''
        self.polylines.append(polyline)

    def update_screen_locs(self, context):
        ''' fills dictionary: keys -> polylines, values -> vertex screen locations '''
        self.vert_screen_locs = {}
        loc3d_reg2D = view3d_utils.location_3d_to_region_2d
        for polyline in self.polylines:
            self.vert_screen_locs[polyline] = []
            for loc in polyline.input_points.world_locs:
                loc2d = loc3d_reg2D(context.region, context.space_data.region_3d, loc)
                self.vert_screen_locs[polyline].append(loc2d)

    def dist(self, v, screen_loc):
        ''' finds screen distance between mouse location and specified point '''
        if v == None:
            print('v off screen')
            return 100000000
        diff = v - Vector(screen_loc)
        return diff.length


