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
            print('sketch too short, cant confirm')
            
            if self.knife.hovered[0] == 'POINT' and self.knife.hovered[1] == 0:
                self.knife.cyclic = True  #self.knife.cyclic = self.knife.cyclic == False  #toggle behavior?
            return

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
        sketch_data = [{"world_location": p, "normal": view_vector} for p in sketch_points] #putting sketch points in structure of points_data datastructure

        # Make the sketch
        self.knife.make_sketch(hovered_start, sketch_data, view_vector)
        self.knife.snap_poly_line()  #why do this again?