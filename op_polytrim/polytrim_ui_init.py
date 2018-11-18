'''
Created on Oct 11, 2015

@author: Patrick
'''

import time
import random

from bpy_extras import view3d_utils

from ..cookiecutter.cookiecutter import CookieCutter
from ..common import ui
from ..common.blender import show_error_message
from ..common.ui import Drawing

from .polytrim_datastructure import InputPoint, SplineSegment, CurveNode


class Polytrim_UI_Init():
    def ui_setup(self):
        self.instructions = {
            "add": "Left-click on the mesh to add a new point",
            "add (green line)": "Left click on the mesh to add/insert a point. The green line will visualize the new segments created",
            "add (disconnect)": "Ctrl + Leftlick will add a free-floating point",
            "select": "Left-click on a point to select it",
            "sketch (anywhere)": "Hold left-click and drag to sketch in a line of points",
            "sketch (point)": "Hold left-click and drag from a hovered point to sketch in a line of points",
            "delete": "Right-click on a point to remove it",
            "delete (disconnect)": "Ctrl + right-click will remove a point and its connected segments",
            "grab": "Press 'G' to grab and move the selected point",
            "grab confirm": "Left-click to place point at cursor's location",
            "grab cancel": "Right-click to cancel the grab"
        }

        info = self.wm.create_window('PolyTrim Help', {'pos':9, 'movable':True, 'bgcolor':(.3,.6,.3,.6)})
        info.add(ui.UI_Label('Instructions', fontsize=16, align=0, margin=4))
        self.inst_paragraphs = [info.add(ui.UI_Markdown('', min_size=(200,10))) for i in range(7)]

        def mode_getter():
            if self._state is None: return None
            if self._state == 'region': return 'region'
            if self._state == 'spline': return 'spline'
            if self._state == 'seed': return 'seed'
            print('Unknown state for UI getter: "%s"' % self._state)
            return self._state
        def mode_setter(m):
            if   m == 'spline': self.fsm_change('spline')
            elif m == 'region': self.fsm_change('region')
            elif m == 'seed':   self.fsm_change('seed')
            else: print('Unknown state for UI setter: "%s"' % m)
        ui_mode = info.add(ui.UI_Options(mode_getter, mode_setter))
        ui_mode.set_label('Pre Cut Tools', fontsize=16, align=0, margin=4)
        ui_mode.add_option('Boundary Edit', value='spline', icon=ui.UI_Image('polyline.png'))
        ui_mode.add_option('Boundary > Region', value='seed', icon=ui.UI_Image('seed.png'))
        ui_mode.add_option('Region Paint', value='region', icon=ui.UI_Image('paint.png'))

        def radius_getter():
            return self.brush_radius
        def radius_setter(v):
            self.brush_radius = max(0.1, int(v*10)/10)
            if self.brush:
                self.brush.radius = self.brush_radius
        info.add(ui.UI_Number("Paint radius", radius_getter, radius_setter))

        info.add(ui.UI_Label('Cut Tools', fontsize=16, align=0, margin=4))
        info.add(ui.UI_Button('Compute Cut', self.compute_cut_button, margin=5))

        #Knife geometry stepper buttons
        info.add(ui.UI_Button('Prepare Stepwise Cut', self.knife_stepwise_prepare_button, margin=5))
        info.add(ui.UI_Button('Step Cut', self.knife_step_button, margin=5))

        exitbuttons = info.add(ui.UI_EqualContainer(margin=0,vertical=False))
        exitbuttons.add(ui.UI_Button('commit', self.done, margin=5))
        exitbuttons.add(ui.UI_Button('cancel', lambda:self.done(cancel=True), margin=5))

        self.set_ui_text_no_points()


    # XXX: Fine for now, but will likely be irrelevant in future
    def ui_text_update(self):
        '''
        updates the text at the bottom of the viewport depending on certain conditions
        '''
        if self.input_net.is_empty:
            self.set_ui_text_no_points()
        elif self.grabber.in_use:
            self.set_ui_text_grab_mode()
        elif self.input_net.num_points == 1:
            self.set_ui_text_1_point()
        elif self.input_net.num_points > 1:
            self.set_ui_text_multiple_points()
        else:
            self.reset_ui_text()

    # XXX: Fine for now, but will likely be irrelevant in future
    def set_ui_text_no_points(self):
        ''' sets the viewports text when no points are out '''
        self.reset_ui_text()
        self.inst_paragraphs[0].set_markdown('A) ' + self.instructions['add'])
        self.inst_paragraphs[1].set_markdown('B) ' + self.instructions['sketch (anywhere)'])

    def set_ui_text_1_point(self):
        ''' sets the viewports text when 1 point has been placed'''
        self.reset_ui_text()
        self.inst_paragraphs[0].set_markdown('A) ' + self.instructions['add (green line)'])
        self.inst_paragraphs[1].set_markdown('B) ' + self.instructions['delete'])
        self.inst_paragraphs[2].set_markdown('C) ' + self.instructions['sketch (point)'])
        self.inst_paragraphs[3].set_markdown('D) ' + self.instructions['grab'])
        self.inst_paragraphs[4].set_markdown('E) ' + self.instructions['add (disconnect)'])
        self.inst_paragraphs[5].set_markdown('F) ' + self.instructions['delete (disconnect)'])

    def set_ui_text_multiple_points(self):
        ''' sets the viewports text when there are multiple points '''
        self.reset_ui_text()
        self.inst_paragraphs[0].set_markdown('A) ' + self.instructions['add (green line)'])
        self.inst_paragraphs[1].set_markdown('B) ' + self.instructions['delete'])
        self.inst_paragraphs[2].set_markdown('C) ' + self.instructions['sketch (point)'])
        self.inst_paragraphs[3].set_markdown('C) ' + self.instructions['select'])
        self.inst_paragraphs[4].set_markdown('D) ' + self.instructions['grab'])
        self.inst_paragraphs[5].set_markdown('E) ' + self.instructions['add (disconnect)'])
        self.inst_paragraphs[6].set_markdown('F) ' + self.instructions['delete (disconnect)'])

    def set_ui_text_grab_mode(self):
        ''' sets the viewports text during general creation of line '''
        self.reset_ui_text()
        self.inst_paragraphs[0].set_markdown('A) ' + self.instructions['grab confirm'])
        self.inst_paragraphs[1].set_markdown('B) ' + self.instructions['grab cancel'])

    def reset_ui_text(self):
        for inst_p in self.inst_paragraphs:
            inst_p.set_markdown('')
