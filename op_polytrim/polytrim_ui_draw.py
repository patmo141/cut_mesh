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

from .polytrim_datastructure import InputPoint, CurveNode, SplineSegment


# some useful colors
clear       = (0.0, 0.0, 0.0, 0.0)
red         = (1.0, 0.1, 0.1, 1.0)
orange      = (1.0, 0.8, 0.2, 1.0)
orange2     = (1.0, 0.65, 0.2, 1.0)
yellow      = (1.0, 1.0, 0.1, 1.0)
green       = (0.3, 1.0, 0.3, 1.0)
green_trans = (0.3, 1.0, 0.3, 0.5)
green2      = (0.2, 0.5, 0.2, 1.0)
cyan        = (0.0, 1.0, 1.0, 1.0)
blue        = (0.1, 0.1, 0.8, 1.0)
blue_trans  = (0.0, 0.0, 1.0, 0.2)
blue2       = (0.1, 0.2, 1.0, 0.8)
navy_trans  = (0.0, 0.2, 0.2, 0.5)
purple      = (0.8, 0.1, 0.8, 1.0)
pink        = (1.0, 0.8, 0.8, 1.0)

preview_line_clr = (0.0, 1.0, 0.0, 0.4)
preview_line_wdth = 2


class Polytrim_UI_Draw():
    @CookieCutter.Draw('post3d')
    def draw_postview(self):

        self.draw_3D_stuff()

        # skip the rest of the drawing if user is navigating or doing stuff with ui
        if self._nav or self._ui: return

        # circle around point to be drawn
        if self.net_ui_context.hovered_near[0] in {'NON_MAN_ED', 'NON_MAN_VERT'}:
            loc = self.net_ui_context.hovered_near[1][1]
            self.draw_circle(loc, 10, .7, green_trans, clear)

        if self.net_ui_context.hovered_near[0] in {'POINT', 'POINT CONNECT'}:
            loc = self.net_ui_context.hovered_near[1].world_loc
            d2d = self.net_ui_context.hovered_dist2D
            if d2d < 12:
                self.draw_circle(loc, 12, .7, green_trans, clear)
            elif d2d < 24:
                self.draw_circle(loc, 24, .7, green_trans, clear)

        # draw region paint brush
        if self._state == 'region':
            self.brush.draw_postview(self.context, self.actions.mouse)

    @CookieCutter.Draw('post2d')
    def draw_postpixel(self):
        self.draw_2D_stuff()
        if self.sketcher.has_locs:
            common_drawing.draw_polyline_from_points(self.context, self.sketcher.get_locs(), (0,1,0,.4), 2, "GL_LINE_SMOOTH")


    #TODO: Clean up/ Organize this function into parts
    def draw_2D_stuff(self):
        '''
        2d drawing
        '''
        context = self.context
        mouse_loc = self.actions.mouse
        is_nav = self._nav
        ctrl_pressed = self.actions.ctrl

        loc3d_reg2D = view3d_utils.location_3d_to_region_2d

        ## Hovered Non-manifold Edge or Vert
        if self.net_ui_context.hovered_near[0] in {'NON_MAN_ED', 'NON_MAN_VERT'} and not is_nav:
            ed, pt = self.net_ui_context.hovered_near[1]
            common_drawing.draw_3d_points(context,[pt], 6, green)

        #if  self.input_net.is_empty: return

        ## Selected Point
        if self.net_ui_context.selected and isinstance(self.net_ui_context.selected, InputPoint):
            common_drawing.draw_3d_points(context,[self.net_ui_context.selected.world_loc], 8, orange)

        if self.net_ui_context.selected and isinstance(self.net_ui_context.selected, CurveNode):
            common_drawing.draw_3d_points(context,[self.net_ui_context.selected.world_loc], 8, green)

        # Grab Location Dot and Lines XXX:This part is gross..
        if self.grabber.grab_point:
            # Dot
            common_drawing.draw_3d_points(context,[self.grabber.grab_point.world_loc], 5, blue_trans)
            # Lines

            point_orig = self.net_ui_context.selected  #had to be selected to be grabbed
            other_locs = [seg.other_point(point_orig).world_loc for seg in point_orig.link_segments]

            for pt_3d in other_locs:
                other_loc = loc3d_reg2D(context.region, context.space_data.region_3d, pt_3d)
                grab_loc = loc3d_reg2D(context.region, context.space_data.region_3d, self.grabber.grab_point.world_loc)
                if other_loc and grab_loc:
                    common_drawing.draw_polyline_from_points(context, [grab_loc, other_loc], preview_line_clr, preview_line_wdth,"GL_LINE_STRIP")
        elif not is_nav:
            ## Hovered Point
            if self.net_ui_context.hovered_near[0] == 'POINT':
                common_drawing.draw_3d_points(context,[self.net_ui_context.hovered_near[1].world_loc], 8, color = (0,1,0,1))
            # Insertion Lines (for adding in a point to edge)
            elif self.net_ui_context.hovered_near[0] == 'EDGE':
                seg = self.net_ui_context.hovered_near[1]
                if isinstance(seg, SplineSegment):
                    a = loc3d_reg2D(context.region, context.space_data.region_3d, seg.n0.world_loc)
                    b = loc3d_reg2D(context.region, context.space_data.region_3d, seg.n1.world_loc)
                else:
                    a = loc3d_reg2D(context.region, context.space_data.region_3d, seg.ip0.world_loc)
                    b = loc3d_reg2D(context.region, context.space_data.region_3d, seg.ip1.world_loc)
                if a and b:
                    common_drawing.draw_polyline_from_points(context, [a,mouse_loc, b], preview_line_clr, preview_line_wdth,"GL_LINE_STRIP")
            # Insertion Lines (for adding closing loop)
            elif self.net_ui_context.snap_element != None and self.net_ui_context.connect_element != None:
                a = loc3d_reg2D(context.region, context.space_data.region_3d, self.net_ui_context.connect_element.world_loc)
                b = loc3d_reg2D(context.region, context.space_data.region_3d, self.net_ui_context.snap_element.world_loc)
                if a and b:
                    common_drawing.draw_polyline_from_points(context, [a, b], preview_line_clr, preview_line_wdth,"GL_LINE_STRIP")
            # Insertion Line (for general adding of points)
            elif self.net_ui_context.closest_ep and not ctrl_pressed:
                ep_screen_loc = loc3d_reg2D(context.region, context.space_data.region_3d, self.net_ui_context.closest_ep.world_loc)
                if self.net_ui_context.hovered_near[0] in {'NON_MAN_ED', 'NON_MAN_VERT'}:
                    point_loc = loc3d_reg2D(context.region, context.space_data.region_3d, self.net_ui_context.hovered_near[1][1])
                else: point_loc = mouse_loc
                common_drawing.draw_polyline_from_points(context, [ep_screen_loc, point_loc], preview_line_clr, preview_line_wdth,"GL_LINE_STRIP")


    def draw_3D_stuff(self):
        '''
        3d drawing
         * ADAPTED FROM POLYSTRIPS John Denning @CGCookie and Taylor University
        '''
        context = self.context
        #if self.input_net.is_empty: return #TODO while diagnosing

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

        #CurveNetwork, BezierSegments
        for seg in self.spline_net.segments:
            if len(seg.draw_tessellation) == 0: continue

            #has not been successfully converted to InputPoints and InputSegments
            if seg.is_inet_dirty:
                draw3d_polyline(context, seg.draw_tessellation,  orange2, 4, 'GL_LINE_STRIP' )

            #if len(seg.ip_tesselation):
            #    draw3d_polyline(context, seg.ip_tesselation,  blue, 2, 'GL_LINE_STRIP' )
            #    draw3d_points(context, seg.ip_tesselation, green2, 4)

        draw3d_points(context, self.spline_net.point_world_locs, green2, 6)

        # Polylines...InputSegments
        for seg in self.input_net.segments:

            #bad segment with a preview path provided by geodesic
            if seg.bad_segment and not len(seg.path) > 2:
                draw3d_polyline(context, [seg.ip0.world_loc, seg.ip1.world_loc],  pink, 2, 'GL_LINE_STRIP' )

            #s
            elif len(seg.path) >= 2 and not seg.bad_segment and seg not in self.network_cutter.completed_segments:
                draw3d_polyline(context, seg.path,  blue, 2, 'GL_LINE_STRIP' )

            elif len(seg.path) >= 2 and not seg.bad_segment and seg in self.network_cutter.completed_segments:
                draw3d_polyline(context, seg.path,  green2, 2, 'GL_LINE_STRIP' )

            elif len(seg.path) >= 2 and seg.bad_segment:
                draw3d_polyline(context, seg.path,  orange2, 2, 'GL_LINE_STRIP' )
                draw3d_polyline(context, [seg.ip0.world_loc, seg.ip1.world_loc],  orange2, 2, 'GL_LINE_STRIP' )

            elif seg.calculation_complete == False:
                draw3d_polyline(context, [seg.ip0.world_loc, seg.ip1.world_loc],  orange2, 2, 'GL_LINE_STRIP' )
            else:
                draw3d_polyline(context, [seg.ip0.world_loc, seg.ip1.world_loc],  blue2, 2, 'GL_LINE_STRIP' )


        if self.network_cutter.the_bad_segment:
            seg = self.network_cutter.the_bad_segment
            draw3d_polyline(context, [seg.ip0.world_loc, seg.ip1.world_loc],  red, 4, 'GL_LINE_STRIP' )

        if self._state == 'main':
            draw3d_points(context, self.input_net.point_world_locs, blue, 2)
        else:
            draw3d_points(context, self.input_net.point_world_locs, blue, 6)

        #draw the seed/face patch points
        draw3d_points(context, [p.world_loc for p in self.network_cutter.face_patches], orange2, 6)


        #draw the actively processing Input Point (IP Steper Debug)
        if self.network_cutter.active_ip:
            draw3d_points(context, [self.network_cutter.active_ip.world_loc], purple, 20)
            draw3d_points(context, [ip.world_loc for ip in self.network_cutter.ip_chain], purple, 12)

        if self.network_cutter.seg_enter:
            draw3d_polyline(context, self.network_cutter.seg_enter.path,  green2, 4, 'GL_LINE_STRIP' )

        if self.network_cutter.seg_exit:
            draw3d_polyline(context, self.network_cutter.seg_exit.path,  red, 4, 'GL_LINE_STRIP' )

        bgl.glLineWidth(1)
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthRange(0.0, 1.0)
        bgl.glDepthMask(bgl.GL_TRUE)

    def draw_circle(self, world_loc, radius, inner_ratio, color_outside, color_inside):
        bgl.glDepthRange(0, 0.9999)     # squeeze depth just a bit
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glDepthMask(bgl.GL_FALSE)   # do not overwrite depth
        bgl.glEnable(bgl.GL_DEPTH_TEST)
        bgl.glDepthFunc(bgl.GL_LEQUAL)  # draw in front of geometry

        circleShader.enable()
        self.drawing.point_size(2.0 * radius)
        circleShader['uMVPMatrix'] = self.drawing.get_view_matrix_buffer()
        circleShader['uInOut']     = inner_ratio

        bgl.glBegin(bgl.GL_POINTS)
        circleShader['vOutColor'] = color_outside
        circleShader['vInColor']  = color_inside
        bgl.glVertex3f(*world_loc)
        bgl.glEnd()

        circleShader.disable()

        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthRange(0.0, 1.0)
        bgl.glDepthMask(bgl.GL_TRUE)
