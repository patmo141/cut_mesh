'''
Created on Oct 10, 2015

@author: Patrick
'''
from .. import common_utilities
from .polytrim_datastructure import InputPointMap, PolyLineKnife
from bpy_extras import view3d_utils
from mathutils import Vector



class Polytrim_UI_Tools():

    def sketch_confirm(self, context, eventd):
        # checking to see if sketch functionality shouldn't happen
        if len(self.sketch) < 5 and self.PLM.current.ui_type == 'DENSE_POLY':
            print('A sketch was not detected..')
            if self.PLM.current.hovered== ['POINT', 0] and not self.PLM.current.start_edge and self.PLM.current.num_points > 2:
                self.PLM.current.toggle_cyclic()  #self.PLM.current.cyclic = self.PLM.current.cyclic == False  #toggle behavior?
            return False

        # Get user view ray
        x,y = eventd['mouse']  #coordinates of where LeftMouse was released
        region = context.region
        rv3d = context.region_data
        view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, (x,y))  #get the direction under the mouse given the user 3DView perspective matrix

        ## Preparing sketch information
        hovered_start = self.PLM.current.hovered # need to know what hovered was at the beginning of the sketch
        self.PLM.current.hover(context,x,y)  #rehover to see where sketch ends
        sketch_3d = common_utilities.ray_cast_path(context, self.PLM.current.source_ob, self.sketch)  #at this moment we are going into 3D space, this returns world space locations
        sketch_locs = sketch_3d[0::5] # getting every fifth point's location
        sketch_views = [view_vector]*len(sketch_locs)
        sketch_points = InputPointMap()
        sketch_points.add_multiple(sketch_locs, [None]*len(sketch_locs), sketch_views, [None]*len(sketch_locs))

        # Make the sketch
        self.PLM.current.make_sketch(hovered_start, sketch_points, view_vector)
        self.PLM.current.snap_poly_line()  #why do this again?

        return True

    ## updates the text at the bottom of the viewport depending on certain conditions
    def ui_text_update(self, context):
        if self.PLM.current.bad_segments:
            context.area.header_text_set("Fix Bad segments by moving control points.")
        elif self.PLM.current.ed_cross_map.is_used:
            context.area.header_text_set("When cut is satisfactory, press 'S' then 'LeftMouse' in region to cut")
        elif self.PLM.current.hovered[0] == 'POINT':
            if self.PLM.current.hovered[1] == 0:
                context.area.header_text_set("For origin point, left click to toggle cyclic")
            else:
                context.area.header_text_set("Right click to delete point. Hold left click and drag to make a sketch")
        else:
            self.set_ui_text_main(context)

    # sets the viewports text during general creation of line
    def set_ui_text_main(self, context):
        context.area.header_text_set("Left click to place cut points on the mesh, then press 'C' to preview the cut")


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

    ## MANAGE/SELECT MODE FUNCTIONS

    # does necessary tasks for when the user enters polylines manage mode
    def initiate_select_mode(self, context):
        self.mode = 'select'
        self.previous = self.current
        self.current = None
        self.update_screen_locs(context)

    # does necessary tasks for when user is moving mouse while in polylines manage mode
    def hover(self, context, x, y):
        print(self.num_polylines)
        for polyline in self.vert_screen_locs:
            for loc in self.vert_screen_locs[polyline]:
                if self.dist(loc, x, y) < 20:
                    self.hovered = polyline
                    return
        self.hovered = None

    # does necessary tasks when user cliicks a polyline while in polylines manage mode
    def select(self, context):
        self.mode = 'wait'
        self.current = self.hovered
        self.hovered = None

    # does necessary tasks when user right-clicks a polyline in polylines manage mode
    def delete(self, context):
        if self.previous == self.hovered: self.previous = self.polylines[self.polylines.index(self.hovered) - 1]
        self.polylines.remove(self.hovered)
        self.hovered = None
        self.update_screen_locs(context)

    # does necessary tasks when user presses 'N' to start a new polyline and terminate polylines manage mode
    def start_new_polyline(self, context):
        self.mode = 'wait'
        self.hovered = None
        self.previous = None
        self.current = PolyLineKnife(context, context.object)
        self.add(self.current)

    # does necessary tasks when user terminates polylines manage mode and returns to polyline edit mode
    def terminate_select_mode(self):
        self.mode = 'wait'
        self.hovered = None
        self.current = self.previous

    # OTHER FUNCTIONS

    # add a polyline to the PLM's polyline list
    def add(self, polyline):
        self.polylines.append(polyline)

    # fills dictionary with keys--> polylines and values--> vertex screen locations
    def update_screen_locs(self, context):
        self.vert_screen_locs = {}
        loc3d_reg2D = view3d_utils.location_3d_to_region_2d
        for polyline in self.polylines:
            self.vert_screen_locs[polyline] = []
            for loc in polyline.input_points.world_locs:
                loc2d = loc3d_reg2D(context.region, context.space_data.region_3d, loc)
                self.vert_screen_locs[polyline].append(loc2d)

    # finds screen distance between mouse location and specified point
    def dist(self, v, x, y):
            if v == None:
                print('v off screen')
                return 100000000
            diff = v - Vector((x, y))
            return diff.length


