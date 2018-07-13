'''
Created on Oct 11, 2015

@author: Patrick
'''

import random

from bpy_extras import view3d_utils

from ..cookiecutter.cookiecutter import CookieCutter
from ..common_utilities import showErrorMessage
from .polytrim_datastructure import PolyLineKnife


class Polytrim_UI_ModalWait():
    @CookieCutter.FSM_State('main')
    def modal_wait(self):
        context = self.context

        # test code that will break operator :)
        #if self.actions.pressed('F9'): bad = 3.14 / 0
        #if self.actions.pressed('F10'): assert False

        if self.actions.mousemove:
            return
        if self.actions.mousemove_prev:
            x,y = self.actions.mouse
            self.PLM.current.hover(context, x, y)
            self.ui_text_update()

        #after navigation filter, these are relevant events in this state
        if self.actions.pressed('grab'):
            if self.PLM.current.grab_initiate():
                self.header_text_set("'MoveMouse'and 'LeftClick' to adjust node location, Right Click to cancel the grab")
                return 'grab'
            return

        if self.actions.pressed('LEFTMOUSE'):
            x,y = self.actions.mouse  #gather the 2D coordinates of the mouse click
            self.PLM.current.click_add_point(context, x,y)  #Send the 2D coordinates to Knife Class
            if (self.PLM.current.ui_type == 'DENSE_POLY' and self.PLM.current.hovered[0] == 'POINT') or self.PLM.current.input_points.num_points == 1:
                self.sketch = [(x,y)]
                return 'sketch'
            return

        if self.actions.pressed('delete'):
            x,y = self.actions.mouse
            if self.PLM.current.start_edge and self.PLM.current.hovered[1] == 0 and self.PLM.current.input_points.num_points > 1:
                showErrorMessage('Can not delete the first point for this kind of cut.')
                return 'main'
            self.PLM.current.click_delete_point(mode = 'mouse')
            self.PLM.current.hover(context, x, y) ## this fixed index out range error in draw function after deleteing last point.
            return

        if self.actions.pressed('up'):
            x,y = self.actions.mouse
            view = view3d_utils.region_2d_to_vector_3d(context.region, context.region_data, (x,y))
            self.PLM.current.double_points(view)

        if self.actions.pressed('down'):
            self.PLM.current.halve_points()

        if self.actions.pressed('toggle selection'):
            if self.PLM.current.input_points.num_points > 1:
                self.cursor_modal_set('DEFAULT')
                self.header_text_set("LEFT-CLICK: select, RIGHT-CLICK: delete, PRESS-N: new, ESC: cancel")
                self.PLM.initiate_select_mode(context)
                return 'select'
            else:
                showErrorMessage("You must have 2 or more points out before you can ")
            return

        if self.actions.pressed('preview cut'):
            if self.PLM.current.start_edge != None and self.PLM.current.end_edge == None:
                showErrorMessage('Cut starts on non manifold boundary of mesh and must end on non manifold boundary')
            elif self.PLM.current.start_edge == None and not self.PLM.current.cyclic:
                showErrorMessage('Cut starts within mesh.  Cut must be closed loop.  Click the first point to close the loop')
            else:
                self.PLM.current.make_cut()
                self.header_text_set("Red segments have cut failures, modify polyline to fix.  When ready press 'S' to set seed point")
            return

        if self.actions.pressed('K'):
            if self.PLM.current.split and self.PLM.current.face_seed and self.PLM.current.ed_cross_map.is_used:
                self.PLM.current.split_geometry(context, mode = 'KNIFE')
                self.PLM.polylines.pop(self.PLM.polylines.index(self.PLM.current))
                if len(self.PLM.polylines):
                    self.PLM.current = self.PLM.polylines[-1]
                    return 'main'
                return 'finish'

        if self.actions.pressed('P'):
            if self.PLM.current.split and self.PLM.current.face_seed and self.PLM.current.ed_cross_map.is_used:
                self.PLM.current.split_geometry(context, mode = 'SEPARATE')
                self.PLM.polylines.pop(self.PLM.polylines.index(self.PLM.current))
                if len(self.PLM.polylines):
                    self.PLM.current = self.PLM.polylines[-1]
                    return 'main'
                return 'finish'

        if self.actions.pressed('X'):
            if self.PLM.current.split and self.PLM.current.face_seed and self.PLM.current.ed_cross_map.is_used:
                self.PLM.current.split_geometry(context, mode = 'DELETE')
                self.PLM.polylines.pop(self.PLM.polylines.index(self.PLM.current))
                if len(self.PLM.polylines):
                    self.PLM.current = self.PLM.polylines[-1]
                    return 'main'
                return 'finish'

        if self.actions.pressed('Y'):
            if self.PLM.current.split and self.PLM.current.face_seed and self.PLM.current.ed_cross_map.is_used:
                self.PLM.current.split_geometry(context, mode = 'SPLIT')
                self.PLM.polylines.pop(self.PLM.polylines.index(self.PLM.current))
                if len(self.PLM.polylines):
                    self.PLM.current = self.PLM.polylines[-1]
                    return 'main'
                return 'finish'

        if self.actions.pressed('SHIFT+D'):
            if self.PLM.current.split and self.PLM.current.face_seed and self.PLM.current.ed_cross_map.is_used:
                self.PLM.current.split_geometry(context, mode = 'DUPLICATE')
                self.PLM.polylines.pop(self.PLM.polylines.index(self.PLM.current))
                if len(self.PLM.polylines):
                    self.PLM.current = self.PLM.polylines[-1]
                    return 'main'
                return 'finish'

        if self.actions.pressed('S'):
            if len(self.PLM.current.bad_segments) != 0:
                showErrorMessage('Cut has failed segments shown in red.  Move the red segment slightly or add cut nodes to avoid bad part of mesh')
                return 'main'

            if self.PLM.current.start_edge == None and not self.PLM.current.cyclic:
                showErrorMessage('Finish closing cut boundary loop')
                return 'main'

            elif self.PLM.current.start_edge != None and self.PLM.current.end_edge == None:
                showErrorMessage('Finish cutting to another non-manifold boundary/edge of the object')
                return 'main'

            elif not self.PLM.current.ed_cross_map.is_used:
                showErrorMessage('Press "C" to preview the cut success before setting the seed')
                return 'main'

            self.cursor_modal_set('EYEDROPPER')
            self.header_text_set("Left Click Region to select area to cut")
            return 'inner'

        if self.actions.pressed('RET'):
            self.PLM.current.confirm_cut_to_mesh()
            self.done()
            return
            #return 'finish'

        elif self.actions.pressed('ESC'):
            self.done(cancel=True)
            return
            #return 'cancel'

        return 'main'

    @CookieCutter.FSM_State('grab')
    def modal_grab(self):
        # no navigation in grab mode
        context = self.context

        if self.actions.pressed('LEFTMOUSE'):
            #confirm location
            x,y = self.actions.mouse
            self.PLM.current.grab_confirm(context, x, y)
            if self.PLM.current.ed_cross_map.is_used:
                self.PLM.current.make_cut()
            self.ui_text_update()
            return 'main'

        if self.actions.pressed('cancel'):
            #put it back!
            self.PLM.current.grab_cancel()
            self.ui_text_update()
            return 'main'

        if self.actions.mousemove:
            return
        if self.actions.mousemove_prev:
            #update the b_pt location
            x,y = self.actions.mouse
            self.PLM.current.grab_mouse_move(context,x, y)

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

        if self.actions.released('LEFTMOUSE'):
            is_sketch = self.sketch_confirm()
            if self.PLM.current.ed_cross_map.is_used and is_sketch:
                self.PLM.current.make_cut()
            self.ui_text_update()
            self.sketch = []
            return 'main'

    @CookieCutter.FSM_State('select')
    def modal_select(self):
        context = self.context

        if self.actions.mousemove:
            x,y = self.actions.mouse
            self.PLM.hover(context, x, y)
            return 'select'

        if self.actions.pressed('LEFTMOUSE'):
            if self.PLM.hovered:
                self.PLM.select(context)
                self.set_ui_text_main(context)
                self.cursor_modal_set('CROSSHAIR')
                return 'main'
            return 'select'

        if self.actions.pressed('RIGHTMOUSE'):
            if self.PLM.hovered and self.PLM.num_polylines > 1:
                self.PLM.delete(context)
            return 'select'

        if self.actions.pressed('N'):
            self.PLM.start_new_polyline(context)
            self.cursor_modal_set('CROSSHAIR')
            self.set_ui_text_main()
            return 'main'

        if self.actions.pressed({'ESC', 'A'}):
            self.PLM.terminate_select_mode()
            self.cursor_modal_set('CROSSHAIR')
            self.set_ui_text_main()
            return 'main'

    @CookieCutter.FSM_State('inner')
    def modal_inner(self):
        if self.actions.pressed('LEFTMOUSE'):
            x,y = self.self.actions.mouse

            result = self.PLM.current.click_seed_select(self.context, x,y)
            # found a good face
            if result == 1:
                self.cursor_modal_set('CROSSHAIR')
                if self.PLM.current.ed_cross_map.is_used and not self.PLM.current.bad_segments and not self.PLM.current.split:
                    self.PLM.current.confirm_cut_to_mesh_no_ops()
                    self.header_text_set("X:delete, P:separate, SHIFT+D:duplicate, K:knife, Y:split")
                return 'main'
            # found a bad face
            elif result == -1:
                showErrorMessage('Seed is too close to cut boundary, try again more interior to the cut')
                return 'inner'
            # face not found
            else:
                showErrorMessage('Seed not found, try again')
                return 'inner'

        if self.actions.pressed({'RET','ESC'}):
            return 'main'