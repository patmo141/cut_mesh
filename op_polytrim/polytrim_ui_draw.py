'''
Created on Oct 8, 2015

@author: Patrick
'''

from .. import common_drawing
from ..cookiecutter.cookiecutter import CookieCutter
from ..common.shaders import circleShader
import bgl

class Polytrim_UI_Draw():
    @CookieCutter.Draw('post3d')
    def draw_postview(self):
        context = self.context
        if self.plm.mode == 'wait':
            for polyline in self.plm.polylines:
                if polyline == self.plm.current: polyline.draw3d(context)
                else: polyline.draw3d(context, special="extra-lite")


            if self.plm.current.snap_element != None:
                bgl.glDepthRange(0, 0.9999)     # squeeze depth just a bit
                bgl.glEnable(bgl.GL_BLEND)
                bgl.glDepthMask(bgl.GL_FALSE)   # do not overwrite depth
                bgl.glEnable(bgl.GL_DEPTH_TEST)

                # draw in front of geometry
                bgl.glDepthFunc(bgl.GL_LEQUAL)

                circleShader.enable()
                #print('matriz buffer')
                circleShader['uMVPMatrix'] = self.drawing.get_view_matrix_buffer()
                #print('set the uMVPMatrix')
                #print(self.drawing.get_view_matrix_buffer())
                
                circleShader['uInOut'] = 0.5
                self.drawing.point_size(80)  #this is diameter
                bgl.glBegin(bgl.GL_POINTS)
                
                a = 1
                circleShader['vOutColor'] = (0.75, 0.75, 0.75, 0.3*a)
                circleShader['vInColor']  = (0.25, 0.25, 0.25, 0.3*a)
                p1 = self.plm.current.snap_element.world_loc
                bgl.glVertex3f(*p1)
                
                bgl.glEnd()
                circleShader.disable()
                
                bgl.glDepthFunc(bgl.GL_LEQUAL)
                bgl.glDepthRange(0.0, 1.0)
                bgl.glDepthMask(bgl.GL_TRUE)
        
        
        elif self.plm.mode == 'select':
            for polyline in self.plm.polylines:
                if polyline == self.plm.hovered: polyline.draw3d(context, special="green")
                else: polyline.draw3d(context, special="lite")

    @CookieCutter.Draw('post2d')
    def draw_postpixel(self):
        context = self.context
        if self.plm.current:
            self.plm.current.draw(context, self.actions.mouse)
        if self.sketch_handler.sketch:
            common_drawing.draw_polyline_from_points(context, self.sketch_handler.sketch, (.8,.3,.3,.8), 2, "GL_LINE_SMOOTH")

