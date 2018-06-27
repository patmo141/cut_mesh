'''
Created on Oct 10, 2015

@author: Patrick
'''
from .. import common_utilities
from bpy_extras import view3d_utils

class Polytrim_UI_Tools():

    def sketch_confirm(self, context, eventd):
        # checking to see if sketch functionality shouldn't happen
        if len(self.sketch) < 5 and self.knife.ui_type == 'DENSE_POLY':
            print('A sketch was not detected..')
            if self.knife.hovered== ['POINT', 0] and not self.knife.start_edge and len(self.knife.points_data) > 2:
                self.knife.toggle_cyclic()  #self.knife.cyclic = self.knife.cyclic == False  #toggle behavior?
            return False

        # Get user view ray
        x,y = eventd['mouse']  #coordinates of where LeftMouse was released
        region = context.region
        rv3d = context.region_data
        view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, (x,y))  #get the direction under the mouse given the user 3DView perspective matrix

        ## Preparing sketch information
        hovered_start = self.knife.hovered # need to know what hovered was at the beginning of the sketch
        self.knife.hover(context,x,y)  #rehover to see where sketch ends
        sketch_3d = common_utilities.ray_cast_path(context, self.knife.cut_ob,self.sketch)  #at this moment we are going into 3D space, this returns world space locations
        sketch_points = sketch_3d[0::5] # getting every fifth point
        sketch_data = [{"world_location": p, "view_direction": view_vector} for p in sketch_points] #putting sketch points in structure of points_data datastructure

        # Make the sketch
        self.knife.make_sketch(hovered_start, sketch_data, view_vector)
        self.knife.snap_poly_line()  #why do this again?

        return True

    ## updates the text at the bottom of the viewport depending on certain conditions
    def ui_text_update(self, context):
        if self.knife.bad_segments:
            context.area.header_text_set("Fix Bad segments by moving control points.")
        elif self.knife.new_cos:
            context.area.header_text_set("When cut is satisfactory, press 'S' then 'LeftMouse' in region to cut")
        elif self.knife.hovered[0] == 'POINT':
            if self.knife.hovered[1] == 0:
                context.area.header_text_set("For origin point, left click to toggle cyclic")
            else:
                context.area.header_text_set("Right click to delete point. Hold left click and drag to make a sketch")
        else:
            self.set_ui_text_main(context)

    # sets the viewports text during general creation of line
    def set_ui_text_main(self, context):
        context.area.header_text_set("Left click to place cut points on the mesh, then press 'C' to preview the cut")
