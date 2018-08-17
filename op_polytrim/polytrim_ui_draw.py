'''
Created on Oct 8, 2015

@author: Patrick
'''
import math
import bgl

from bpy_extras import view3d_utils
from mathutils import Vector, Matrix, Color

from .. import common_drawing
from ..cookiecutter.cookiecutter import CookieCutter
from ..common.shaders import circleShader

from .polytrim_datastructure import InputPoint



class Polytrim_UI_Draw():
    @CookieCutter.Draw('post3d')
    def draw_postview(self):
        self.draw_stuff_3d()

        # if self.plk.snap_element != None:
        #     bgl.glDepthRange(0, 0.9999)     # squeeze depth just a bit
        #     bgl.glEnable(bgl.GL_BLEND)
        #     bgl.glDepthMask(bgl.GL_FALSE)   # do not overwrite depth
        #     bgl.glEnable(bgl.GL_DEPTH_TEST)

        #     # draw in front of geometry
        #     bgl.glDepthFunc(bgl.GL_LEQUAL)

        #     circleShader.enable()
        #     #print('matriz buffer')
        #     circleShader['uMVPMatrix'] = self.drawing.get_view_matrix_buffer()
        #     #print('set the uMVPMatrix')
        #     #print(self.drawing.get_view_matrix_buffer())
            
        #     circleShader['uInOut'] = 0.5
        #     self.drawing.point_size(80)  #this is diameter
        #     bgl.glBegin(bgl.GL_POINTS)
            
        #     a = 1
        #     circleShader['vOutColor'] = (0.75, 0.75, 0.75, 0.3*a)
        #     circleShader['vInColor']  = (0.25, 0.25, 0.25, 0.3*a)
        #     p1 = self.plk.snap_element.world_loc
        #     bgl.glVertex3f(*p1)
            
        #     bgl.glEnd()
        #     circleShader.disable()
            
        #     bgl.glDepthFunc(bgl.GL_LEQUAL)
        #     bgl.glDepthRange(0.0, 1.0)
        #     bgl.glDepthMask(bgl.GL_TRUE)

    @CookieCutter.Draw('post2d')
    def draw_postpixel(self):
        if self.input_net:
            self.draw_stuff(self.context)
        if self.sketcher.has_locs:
            common_drawing.draw_polyline_from_points(self.context, self.sketcher.get_locs(), (0,1,0,.4), 2, "GL_LINE_SMOOTH")


    def draw_stuff(self, context):
        '''
        2d drawing
        '''
        context = self.context
        mouse_loc = self.actions.mouse

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
        if self.net_ui_manager.hovered[0] in {'NON_MAN_ED', 'NON_MAN_VERT'}:
            ed, pt = self.net_ui_manager.hovered[1]
            common_drawing.draw_3d_points(context,[pt], 6, green)

        if  self.input_net.is_empty: return
   
        ## Selected Point
        if self.net_ui_manager.selected and isinstance(self.net_ui_manager.selected, InputPoint):
            common_drawing.draw_3d_points(context,[self.net_ui_manager.selected.world_loc], 8, orange)


        # Grab Location Dot and Lines XXX:This part is gross..
        if self.grabber.grab_point:
            # Dot
            common_drawing.draw_3d_points(context,[self.grabber.grab_point.world_loc], 5, blue_opaque)
            # Lines

            point_orig = self.net_ui_manager.selected  #had to be selected to be grabbed
            other_locs = [seg.other_point(point_orig).world_loc for seg in point_orig.link_segments]

            for pt_3d in other_locs:
                other_loc = loc3d_reg2D(context.region, context.space_data.region_3d, pt_3d)
                grab_loc = loc3d_reg2D(context.region, context.space_data.region_3d, self.grabber.grab_point.world_loc)
                if other_loc and grab_loc:
                    common_drawing.draw_polyline_from_points(context, [grab_loc, other_loc], preview_line_clr, preview_line_wdth,"GL_LINE_STRIP")
        ## Hovered Point
        elif self.net_ui_manager.hovered[0] == 'POINT':
            common_drawing.draw_3d_points(context,[self.net_ui_manager.hovered[1].world_loc], 8, color = (0,1,0,1))
        # Insertion Lines (for adding in a point to edge)
        elif self.net_ui_manager.hovered[0] == 'EDGE':
            seg = self.net_ui_manager.hovered[1]
            a = loc3d_reg2D(context.region, context.space_data.region_3d, seg.ip0.world_loc)
            b = loc3d_reg2D(context.region, context.space_data.region_3d, seg.ip1.world_loc)
            if a and b:
                common_drawing.draw_polyline_from_points(context, [a,mouse_loc, b], preview_line_clr, preview_line_wdth,"GL_LINE_STRIP")
        # Insertion Lines (for adding closing loop)
        elif self.net_ui_manager.snap_element != None and self.net_ui_manager.connect_element != None:
            a = loc3d_reg2D(context.region, context.space_data.region_3d, self.net_ui_manager.connect_element.world_loc)
            b = loc3d_reg2D(context.region, context.space_data.region_3d, self.net_ui_manager.snap_element.world_loc)
            if a and b:
                common_drawing.draw_polyline_from_points(context, [a, b], preview_line_clr, preview_line_wdth,"GL_LINE_STRIP")
        # Endpoint to Cursor Line
        elif self.net_ui_manager.closest_ep:
            ep_screen_loc = loc3d_reg2D(context.region, context.space_data.region_3d, self.net_ui_manager.closest_ep.world_loc)
            common_drawing.draw_polyline_from_points(context, [ep_screen_loc, mouse_loc], preview_line_clr, preview_line_wdth,"GL_LINE_STRIP")


    def draw_stuff_3d(self):
        '''
        3d drawing
         * ADAPTED FROM POLYSTRIPS John Denning @CGCookie and Taylor University
        '''
        context = self.context
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
            elif len(seg.path) >= 2:
                draw3d_polyline(context, seg.path,  blue, 2, 'GL_LINE_STRIP' )
            else:
                draw3d_polyline(context, [seg.ip0.world_loc, seg.ip1.world_loc],  blue2, 2, 'GL_LINE_STRIP' )
    
        draw3d_points(context, self.input_net.point_world_locs, blue, 6)

        bgl.glLineWidth(1)     
                
        
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthRange(0.0, 1.0)
        bgl.glDepthMask(bgl.GL_TRUE)
