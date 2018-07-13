'''
Created on Oct 8, 2015

@author: Patrick
'''
from .. import common_drawing


class Polytrim_UI_Draw():
    def draw_postview(self, context):
        ''' Place post view drawing code in here '''
        self.draw_3d(context)
        pass

    def draw_postpixel(self, context):
        ''' Place post pixel drawing code in here '''
        self.draw_2d(context)
        pass

    def draw_3d(self,context):
        if self.PLM.mode == 'wait':
            for polyline in self.PLM.polylines:
                if polyline == self.PLM.current: polyline.draw3d(context)
                else: polyline.draw3d(context, special="extra-lite")
        elif self.PLM.mode == 'select':
            for polyline in self.PLM.polylines:
                if polyline == self.PLM.hovered: polyline.draw3d(context, special="green")
                else: polyline.draw3d(context, special="lite")

    def draw_2d(self,context):
        if self.PLM.current: self.PLM.current.draw(context)

        if self.sketch:
            common_drawing.draw_polyline_from_points(context, self.sketch, (.8,.3,.3,.8), 2, "GL_LINE_SMOOTH")
