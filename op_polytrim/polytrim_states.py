'''
Created on Oct 11, 2015

@author: Patrick
'''

import random

from bpy_extras import view3d_utils

from ..cookiecutter.cookiecutter import CookieCutter
from ..common.blender import show_error_message
from .polytrim_datastructure import PolyLineKnife


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
            self.plm.current.click_delete_point(mode='mouse')
            self.hover()
            return

        if self.actions.pressed('toggle selection'):
            if self.plm.current.num_points > 1:
                context.window.cursor_modal_set('DEFAULT')
                context.area.header_text_set("LEFT-CLICK: select, RIGHT-CLICK: delete, PRESS-N: new, ESC: cancel")
                self.plm.initiate_select_mode(context)
                return 'select'
            else: show_error_message("You must have 2 or more points out before you can ")
            return

        # if self.actions.pressed('up'):
        #     x,y = self.actions.mouse
        #     view = view3d_utils.region_2d_to_vector_3d(context.region, context.region_data, (x,y))
        #     self.plm.current.double_points(view)

        # if self.actions.pressed('down'):
        #     self.plm.current.halve_points()

        #re-tesselate at 3mm resolution
        #if self.actions.pressed('T'):
        #    n_pts = self.plm.current.num_points
        #    self.plm.current.linear_re_tesselate_segment(self.plm.current.input_points.points[0],
        #                                                 self.plm.current.input_points.points[n_pts-1],
        #                                                 res = 3.0)
        
        
        #if self.actions.pressed('F1'):
        #    n_pts = self.plm.current.num_points
        #    self.plm.current.linear_re_tesselate_segment(self.plm.current.input_points.points[2],
        #                                                 self.plm.current.input_points.points[4],
        #                                                 res = 3.0)
            
        #if self.actions.pressed('F2'):
        #    n_pts = self.plm.current.num_points
        #    self.plm.current.linear_re_tesselate_segment(self.plm.current.input_points.points[4],
        #                                                 self.plm.current.input_points.points[2],
        #                                                 res = 3.0)
            
        if self.actions.pressed('F2'):
            self.plm.current.preview_bad_segments_geodesic()
            
        
        if self.actions.pressed('F1'):
            self.plm.current.input_points.find_network_cycles()
        
        if self.actions.pressed('preview cut'):
            if self.plm.current.start_edge != None and self.plm.current.end_edge == None:
                show_error_message('Cut starts on non manifold boundary of mesh and must end on non manifold boundary')
            elif self.plm.current.start_edge == None and not self.plm.current.cyclic:
                show_error_message('Cut starts within mesh.  Cut must be closed loop.  Click the first point to close the loop')
            else:
                self.plm.current.make_cut()
                self.header_text_set("Red segments have cut failures, modify polyline to fix.  When ready press 'S' to set seed point")
            return

        if self.actions.pressed('K'):
            if self.plm.current.split and self.plm.current.face_seed and self.plm.current.ed_cross_map.is_used:
                self.plm.current.split_geometry(context, mode = 'KNIFE')
                self.plm.polylines.pop(self.plm.polylines.index(self.plm.current))
                if len(self.plm.polylines):
                    self.plm.current = self.plm.polylines[-1]
                    return 'main'
                return 'finish'

        if self.actions.pressed('P'):
            if self.plm.current.split and self.plm.current.face_seed and self.plm.current.ed_cross_map.is_used:
                self.plm.current.split_geometry(context, mode = 'SEPARATE')
                self.plm.polylines.pop(self.plm.polylines.index(self.plm.current))
                if len(self.plm.polylines):
                    self.plm.current = self.plm.polylines[-1]
                    return 'main'
                return 'finish'

        if self.actions.pressed('X'):
            if self.plm.current.split and self.plm.current.face_seed and self.plm.current.ed_cross_map.is_used:
                self.plm.current.split_geometry(context, mode = 'DELETE')
                self.plm.polylines.pop(self.plm.polylines.index(self.plm.current))
                if len(self.plm.polylines):
                    self.plm.current = self.plm.polylines[-1]
                    return
                return 'finish'

        # if self.actions.pressed('Y'):
        #     if self.plm.current.split and self.plm.current.face_seed and self.plm.current.ed_cross_map.is_used:
        #         self.plm.current.split_geometry(context, mode = 'SPLIT')
        #         self.plm.polylines.pop(self.plm.polylines.index(self.plm.current))
        #         if len(self.plm.polylines):
        #             self.plm.current = self.plm.polylines[-1]
        #             return 'main'
        #         return 'finish'

        if self.actions.pressed('SHIFT+D'):
            if self.plm.current.split and self.plm.current.face_seed and self.plm.current.ed_cross_map.is_used:
                self.plm.current.split_geometry(context, mode = 'DUPLICATE')
                self.plm.polylines.pop(self.plm.polylines.index(self.plm.current))
                if len(self.plm.polylines):
                    self.plm.current = self.plm.polylines[-1]
                    return 'main'
                return 'finish'

        if self.actions.pressed('S'): return 'inner'

        if self.actions.pressed('RET'):
            self.plm.current.confirm_cut_to_mesh()
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
        return self.plm.current.grab_initiate()

    @CookieCutter.FSM_State('grab', 'enter')
    def grab_enter(self):
        self.header_text_set("'MoveMouse'and 'LeftClick' to adjust node location, Right Click to cancel the grab")
        self.plm.current.grab_mouse_move(self.context, self.actions.mouse)

    @CookieCutter.FSM_State('grab')
    def modal_grab(self):
        # no navigation in grab mode
        context = self.context
        self.cursor_modal_set('HAND')

        if self.actions.pressed('LEFTMOUSE'):
            #confirm location
            x,y = self.actions.mouse
            self.plm.current.grab_confirm(context)
            
            if self.plm.current.selected not in self.plm.current.input_points.points:
                self.plm.current.selected = -1
            if self.plm.current.ed_cross_map.is_used:
                self.plm.current.make_cut()
            self.ui_text_update()
            return 'main'

        if self.actions.pressed('cancel'):
            #put it back!
            self.plm.current.grab_cancel()
            self.ui_text_update()
            return 'main'

        if self.actions.mousemove:
            return
        if self.actions.mousemove_prev:
            #update the b_pt location
            self.plm.current.grab_mouse_move(context, self.actions.mouse)

    ######################################################
    # sketch state

    @CookieCutter.FSM_State('sketch', 'can enter')
    def sketch_can_enter(self):
        context = self.context
        mouse = self.actions.mouse  #gather the 2D coordinates of the mouse click
        self.plm.current.click_add_point(context, mouse)  #Send the 2D coordinates to Knife Class
        return (self.plm.current.ui_type == 'DENSE_POLY' and self.plm.current.hovered[0] == 'POINT') or self.plm.current.num_points == 1

    @CookieCutter.FSM_State('sketch', 'enter')
    def sketch_enter(self):
        x,y = self.actions.mouse  #gather the 2D coordinates of the mouse click
        self.sketch = [(x,y)]

    @CookieCutter.FSM_State('sketch')
    def modal_sketch(self):
        if self.actions.mousemove:
            x,y = self.actions.mouse
            if not len(self.sketch): return 'main'
            ## Manipulating sketch data
            (lx, ly) = self.sketch[-1]
            ss0,ss1 = self.stroke_smoothing ,1-self.stroke_smoothing  #First data manipulation
            self.sketch += [(lx*ss0+x*ss1, ly*ss0+y*ss1)]
            return

        if self.actions.released('sketch'):
            is_sketch = self.sketch_confirm()
            if self.plm.current.ed_cross_map.is_used and is_sketch:
                self.plm.current.make_cut()
            self.ui_text_update()
            self.sketch = []
            return 'main'

    ######################################################
    # select state

    @CookieCutter.FSM_State('select')
    def modal_select(self):
        context = self.context

        if self.actions.mousemove:
            x,y = self.actions.mouse
            self.plm.hover(context, x, y)
            return 'select'

        if self.actions.pressed('LEFTMOUSE'):
            if self.plm.hovered:
                self.plm.select(context)
                self.set_ui_text_main()
                self.cursor_modal_set('CROSSHAIR')
                return 'main'
            return 'select'

        if self.actions.pressed('RIGHTMOUSE'):
            if self.plm.hovered and self.plm.num_polylines > 1:
                self.plm.delete(context)
            return 'select'

        if self.actions.pressed('N'):
            self.plm.start_new_polyline(context)
            self.cursor_modal_set('CROSSHAIR')
            self.set_ui_text_main()
            return 'main'

        if self.actions.pressed({'ESC', 'A'}):
            self.plm.terminate_select_mode()
            self.cursor_modal_set('CROSSHAIR')
            self.set_ui_text_main()
            return 'main'

    ######################################################
    # inner state

    @CookieCutter.FSM_State('inner', 'can enter')
    def inner_can_enter(self):
        print('testing if we can enter inner mode')
        if len(self.plm.current.bad_segments) != 0:
            show_error_message('Cut has failed segments shown in red.  Move the red segment slightly or add cut nodes to avoid bad part of mesh')
            return False
        if self.plm.current.start_edge == None and not self.plm.current.cyclic:
            show_error_message('Finish closing cut boundary loop')
            return False
        if self.plm.current.start_edge != None and self.plm.current.end_edge == None:
            show_error_message('Finish cutting to another non-manifold boundary/edge of the object')
            return False
        if not self.plm.current.ed_cross_map.is_used:
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

            result = self.plm.current.click_seed_select(self.context, self.mouse)
            # found a good face
            if result == 1:
                self.cursor_modal_set('CROSSHAIR')
                if self.plm.current.ed_cross_map.is_used and not self.plm.current.bad_segments and not self.plm.current.split:
                    self.plm.current.confirm_cut_to_mesh_no_ops()
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