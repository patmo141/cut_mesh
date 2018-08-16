'''
Created on Oct 11, 2015

@author: Patrick
'''

import random

from bpy_extras import view3d_utils

from ..cookiecutter.cookiecutter import CookieCutter
from ..common.blender import show_error_message
from .polytrim_datastructure import PolyLineKnife, InputPoint


class Polytrim_States():
    @CookieCutter.FSM_State('main')
    def modal_main(self):
        context = self.context
        self.cursor_modal_set('CROSSHAIR')

        # test code that will break operator :)
        #if self.actions.pressed('F9'): bad = 3.14 / 0
        #if self.actions.pressed('F10'): assert False

        if self.actions.mousemove:
            return
        if self.actions.mousemove_prev:
            # TODO: update self.hover to use Accel2D?
            self.hover()
            self.ui_text_update()

        #after navigation filter, these are relevant events in this state
        if self.actions.pressed('grab'): return 'grab'

        if self.actions.pressed('sketch'): return 'sketch'

        if self.actions.pressed('delete'):
            print('delete pressed')
            x,y = self.actions.mouse
            self.click_delete_point(self.input_net, mode='mouse')
            self.hover()
            return

        # if self.actions.pressed('up'):
        #     x,y = self.actions.mouse
        #     view = view3d_utils.region_2d_to_vector_3d(context.region, context.region_data, (x,y))
        #     self.input_net.double_points(view)

        # if self.actions.pressed('down'):
        #     self.input_net.halve_points()

        #re-tesselate at 3mm resolution
        if self.actions.pressed('T'):
            n_pts = self.input_net.num_points
            self.input_net.linear_re_tesselate_segment(self.input_net.input_net.points[0],
                                                         self.input_net.input_net.points[n_pts-1],
                                                         res = 3.0)
        
        
        if self.actions.pressed('F1'):
            n_pts = self.input_net.num_points
            self.input_net.linear_re_tesselate_segment(self.input_net.input_net.points[2],
                                                         self.input_net.input_net.points[4],
                                                         res = 3.0)
            
        if self.actions.pressed('F2'):
            n_pts = self.input_net.num_points
            self.input_net.linear_re_tesselate_segment(self.input_net.input_net.points[4],
                                                         self.input_net.input_net.points[2],
                                                         res = 3.0)

        if self.actions.pressed('RET'):
            self.done()
            return
            #return 'finish'

        elif self.actions.pressed('ESC'):
            self.done(cancel=True)
            return
            #return 'cancel'

    ######################################################
    # grab state

    @CookieCutter.FSM_State('grab', 'can enter')
    def grab_can_enter(self):
        return (self.input_net.selected and isinstance(self.input_net.selected, InputPoint))

    @CookieCutter.FSM_State('grab', 'enter')
    def grab_enter(self):
        self.header_text_set("'MoveMouse'and 'LeftClick' to adjust node location, Right Click to cancel the grab")
        self.grabber.initiate_grab_point()
        self.grabber.move_grab_point(self.context, self.actions.mouse)

    @CookieCutter.FSM_State('grab')
    def modal_grab(self):
        # no navigation in grab mode
        self.cursor_modal_set('HAND')

        if self.actions.pressed('LEFTMOUSE'):
            #confirm location
            x,y = self.actions.mouse
            self.grabber.finalize(self.context)

            if self.input_net.selected not in self.input_net.input_net.points:
                self.input_net.selected = -1
            self.ui_text_update()
            return 'main'

        if self.actions.pressed('cancel'):
            #put it back!
            self.grabber.grab_cancel()
            self.ui_text_update()
            return 'main'

        if self.actions.mousemove:
            return
        if self.actions.mousemove_prev:
            #update the b_pt location
            self.grabber.move_grab_point(self.context, self.actions.mouse)

    ######################################################
    # sketch state

    @CookieCutter.FSM_State('sketch', 'can enter')
    def sketch_can_enter(self):
        context = self.context
        mouse = self.actions.mouse  #gather the 2D coordinates of the mouse click
        self.click_add_point(self.input_net, context, mouse)  #Send the 2D coordinates to Knife Class
        return (self.input_net.ui_type == 'DENSE_POLY' and self.input_net.hovered[0] == 'POINT') or self.input_net.num_points == 1

    @CookieCutter.FSM_State('sketch', 'enter')
    def sketch_enter(self):
        x,y = self.actions.mouse
        self.sketcher.add_loc(x,y)

    @CookieCutter.FSM_State('sketch')
    def modal_sketch(self):
        if self.actions.mousemove:
            x,y = self.actions.mouse
            if not len(self.sketcher.sketch): return 'main' #XXX: Delete this??
            self.sketcher.smart_add_loc(x,y)
            return

        if self.actions.released('sketch'):
            is_sketch = self.sketcher.is_good()
            if is_sketch:
                last_hovered_point = self.input_net.hovered[1]
                print("LAST:",self.input_net.hovered)
                self.hover()
                new_hovered_point = self.input_net.hovered[1]   
                print("NEW:",self.input_net.hovered)
                self.sketcher.finalize(self.context, last_hovered_point, new_hovered_point)
            self.ui_text_update()
            self.sketcher.reset()
            return 'main'

