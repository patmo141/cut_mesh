'''
Created on Oct 8, 2015

@author: Patrick
'''
from ..cookiecutter.cookiecutter import CookieCutter
from .. import common_drawing


class Polytrim_UI_Draw():
    @CookieCutter.Draw('post3d')
    def draw_postview(self):
        ''' Place post view drawing code in here '''
        context = self.context
        if self.PLM.mode == 'wait':
            for polyline in self.PLM.polylines:
                if polyline == self.PLM.current: polyline.draw3d(context)
                else: polyline.draw3d(context, special="extra-lite")
        elif self.PLM.mode == 'select':
            for polyline in self.PLM.polylines:
                if polyline == self.PLM.hovered: polyline.draw3d(context, special="green")
                else: polyline.draw3d(context, special="lite")

    @CookieCutter.Draw('post2d')
    def draw_postpixel(self):
        ''' Place post pixel drawing code in here '''
        context = self.context
        
        if self.PLM.current:
            self.PLM.current.draw(context)

        if self.sketch:
            common_drawing.draw_polyline_from_points(context, self.sketch, (.8,.3,.3,.8), 2, "GL_LINE_SMOOTH")
