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
            
             
        if self.actions.pressed('preview cut'):
            if self.input_net.start_edge != None and self.input_net.end_edge == None:
                show_error_message('Cut starts on non manifold boundary of mesh and must end on non manifold boundary')
            elif self.input_net.start_edge == None and not self.input_net.cyclic:
                show_error_message('Cut starts within mesh.  Cut must be closed loop.  Click the first point to close the loop')
            else:
                self.input_net.make_cut()
                self.header_text_set("Red segments have cut failures, modify polyline to fix.  When ready press 'S' to set seed point")
            return

        if self.actions.pressed('S'): return 'inner'

        if self.actions.pressed('RET'):
            self.input_net.confirm_cut_to_mesh()
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
        context = self.context
        self.cursor_modal_set('HAND')

        if self.actions.pressed('LEFTMOUSE'):
            #confirm location
            x,y = self.actions.mouse
            self.grabber.finalize(context)

            if self.input_net.selected not in self.input_net.input_net.points:
                self.input_net.selected = -1
            if self.input_net.ed_cross_map.is_used:
                self.input_net.make_cut()
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
            self.grabber.move_grab_point(context, self.actions.mouse)

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

    ######################################################
    # inner state

    @CookieCutter.FSM_State('inner', 'can enter')
    def inner_can_enter(self):
        print('testing if we can enter inner mode')
        if len(self.input_net.bad_segments) != 0:
            show_error_message('Cut has failed segments shown in red.  Move the red segment slightly or add cut nodes to avoid bad part of mesh')
            return False
        if self.input_net.start_edge == None and not self.input_net.cyclic:
            show_error_message('Finish closing cut boundary loop')
            return False
        if self.input_net.start_edge != None and self.input_net.end_edge == None:
            show_error_message('Finish cutting to another non-manifold boundary/edge of the object')
            return False
        if not self.input_net.ed_cross_map.is_used:
            show_error_message('Press "C" to preview the cut success before setting the seed')
            return False

    @CookieCutter.FSM_State('inner', 'enter')
    def inner_enter(self):
        self.header_text_set("Left Click Region to select area to cut")

    @CookieCutter.FSM_State('inner')
    def modal_inner(self):
        self.cursor_modal_set('EYEDROPPER')

        if self.actions.pressed('LEFTMOUSE'):
            x,y = self.actions.mouse

            result = self.input_net.click_seed_select(self.context, self.mouse)
            # found a good face
            if result == 1:
                self.cursor_modal_set('CROSSHAIR')
                if self.input_net.ed_cross_map.is_used and not self.input_net.bad_segments and not self.input_net.split:
                    self.input_net.confirm_cut_to_mesh_no_ops()
                    self.header_text_set("X:delete, P:separate, SHIFT+D:duplicate, K:knife, Y:split")
                return 'main'
            # found a bad face
            elif result == -1:
                show_error_message('Seed is too close to cut boundary, try again more interior to the cut')
                return 'inner'
            # face not found
            else:
                show_error_message('Seed not found, try again')
                return 'inner'

        if self.actions.pressed({'RET','ESC'}):
            return 'main'