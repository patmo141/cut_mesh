'''
Created on Oct 8, 2015

@author: Patrick
'''

from .. import common_drawing
from ..cookiecutter.cookiecutter import CookieCutter

class Polytrim_UI_Draw():
    @CookieCutter.Draw('post3d')
    def draw_postview(self):
        context = self.context
        if self.plm.mode == 'wait':
            for polyline in self.plm.polylines:
                if polyline == self.plm.current: polyline.draw3d(context)
                else: polyline.draw3d(context, special="extra-lite")
        elif self.plm.mode == 'select':
            for polyline in self.plm.polylines:
                if polyline == self.plm.hovered: polyline.draw3d(context, special="green")
                else: polyline.draw3d(context, special="lite")

    @CookieCutter.Draw('post2d')
    def draw_postpixel(self):
        context = self.context
        if self.plm.current:
            self.plm.current.draw(context, self.actions.mouse)
        if self.sketch:
            common_drawing.draw_polyline_from_points(context, self.sketch, (.8,.3,.3,.8), 2, "GL_LINE_SMOOTH")

