'''
Created on Oct 11, 2015

@author: Patrick
'''
from ..common_utilities import showErrorMessage
from .polytrim_datastructure import PolyLineKnife

class Polytrim_UI_ModalWait():

    def modal_wait(self,context,eventd):
        # general navigation
        nmode = self.modal_nav(context, eventd)
        if nmode != '':
            print("nmode")
            return nmode  #stop here and tell parent modal to 'PASS_THROUGH'

        # test code that will break operator :)
        #if eventd['press'] == 'F9': bad = 3.14 / 0
        #if eventd['press'] == 'F10': assert False

        #after navigation filter, these are relevant events in this state
        if eventd['press'] == 'G':
            if self.PLM.current.grab_initiate():
                context.area.header_text_set("'MoveMouse'and 'LeftClick' to adjust node location, Right Click to cancel the grab")
                return 'grab'
            return 'main'

        if eventd['press'] == 'R':
            self.PLM.current.reprocess_points(2)
            return 'main'
            
        if  eventd['type'] == 'MOUSEMOVE':
            x,y = eventd['mouse']
            self.PLM.current.hover(context, x, y)
            self.ui_text_update(context)
            return 'main'

        if  eventd['press'] == 'LEFTMOUSE':
            x,y = eventd['mouse']  #gather the 2D coordinates of the mouse click
            self.PLM.current.click_add_point(context, x,y)  #Send the 2D coordinates to Knife Class
            if (self.PLM.current.ui_type == 'DENSE_POLY' and self.PLM.current.hovered[0] == 'POINT') or self.PLM.current.input_points.num_points == 1:
                self.sketch = [(x,y)]
                return 'sketch'
            return 'main'

        if eventd['press'] == 'RIGHTMOUSE':
            x,y = eventd['mouse']
            if self.PLM.current.start_edge and self.PLM.current.hovered[1] == 0 and self.PLM.current.input_points.num_points > 1:
                showErrorMessage('Can not delete the first point for this kind of cut.')
                return 'main'
            self.PLM.current.click_delete_point(mode = 'mouse')
            self.PLM.current.hover(context, x, y) ## this fixed index out range error in draw function after deleteing last point.
            return 'main'

        if eventd['press'] == 'A':
            if self.PLM.current.input_points.num_points > 1:
                context.window.cursor_modal_set('DEFAULT')
                context.area.header_text_set("LEFT-CLICK: select, RIGHT-CLICK: delete, PRESS-N: new, ESC: cancel")
                self.PLM.initiate_select_mode(context)
                return 'select'
            else: showErrorMessage("You must have 2 or more points out before you can ")
            return 'main'

        if eventd['press'] == 'C':
            if self.PLM.current.start_edge != None and self.PLM.current.end_edge == None:
                showErrorMessage('Cut starts on non manifold boundary of mesh and must end on non manifold boundary')
            elif self.PLM.current.start_edge == None and not self.PLM.current.cyclic:
                showErrorMessage('Cut starts within mesh.  Cut must be closed loop.  Click the first point to close the loop')
            else:
                self.PLM.current.make_cut()
                context.area.header_text_set("Red segments have cut failures, modify polyline to fix.  When ready press 'S' to set seed point")

            return 'main'

        if eventd['press'] == 'K':
            if self.PLM.current.split and self.PLM.current.face_seed and self.PLM.current.ed_cross_map.is_used:
                self.PLM.current.split_geometry(eventd['context'], mode = 'KNIFE')
                self.PLM.polylines.pop(self.PLM.polylines.index(self.PLM.current))
                if len(self.PLM.polylines):
                    self.PLM.current = self.PLM.polylines[-1]
                    return 'main'
                return 'finish'

        if eventd['press'] == 'P':
            if self.PLM.current.split and self.PLM.current.face_seed and self.PLM.current.ed_cross_map.is_used:
                self.PLM.current.split_geometry(eventd['context'], mode = 'SEPARATE')
                self.PLM.polylines.pop(self.PLM.polylines.index(self.PLM.current))
                if len(self.PLM.polylines):
                    self.PLM.current = self.PLM.polylines[-1]
                    return 'main'
                return 'finish'

        if eventd['press'] == 'X':
            if self.PLM.current.split and self.PLM.current.face_seed and self.PLM.current.ed_cross_map.is_used:
                self.PLM.current.split_geometry(eventd['context'], mode = 'DELETE')
                self.PLM.polylines.pop(self.PLM.polylines.index(self.PLM.current))
                if len(self.PLM.polylines):
                    self.PLM.current = self.PLM.polylines[-1]
                    return 'main'
                return 'finish'

        if eventd['press'] == 'Y':
            if self.PLM.current.split and self.PLM.current.face_seed and self.PLM.current.ed_cross_map.is_used:
                self.PLM.current.split_geometry(eventd['context'], mode = 'SPLIT')
                self.PLM.polylines.pop(self.PLM.polylines.index(self.PLM.current))
                if len(self.PLM.polylines):
                    self.PLM.current = self.PLM.polylines[-1]
                    return 'main'
                return 'finish'

        if eventd['press'] == 'SHIFT+D':
            if self.PLM.current.split and self.PLM.current.face_seed and self.PLM.current.ed_cross_map.is_used:
                self.PLM.current.split_geometry(eventd['context'], mode = 'DUPLICATE')
                self.PLM.polylines.pop(self.PLM.polylines.index(self.PLM.current))
                if len(self.PLM.polylines):
                    self.PLM.current = self.PLM.polylines[-1]
                    return 'main'
                return 'finish'

        if eventd['press'] == 'S':
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

            context.window.cursor_modal_set('EYEDROPPER')
            context.area.header_text_set("Left Click Region to select area to cut")
            return 'inner'

        if eventd['press'] == 'RET' :
            self.PLM.current.confirm_cut_to_mesh()
            return 'finish'

        elif eventd['press'] == 'ESC':
            return 'cancel'

        return 'main'

    def modal_grab(self,context,eventd):
        # no navigation in grab mode

        if eventd['press'] == 'LEFTMOUSE':
            #confirm location
            x,y = eventd['mouse']
            self.PLM.current.grab_confirm(context, x, y)
            if self.PLM.current.ed_cross_map.is_used:
                self.PLM.current.make_cut()
            self.ui_text_update(context)
            return 'main'

        elif eventd['press'] in {'RIGHTMOUSE', 'ESC'}:
            #put it back!
            self.PLM.current.grab_cancel()
            self.ui_text_update(context)
            return 'main'

        elif eventd['type'] == 'MOUSEMOVE':
            #update the b_pt location
            x,y = eventd['mouse']
            self.PLM.current.grab_mouse_move(context,x, y)
            return 'grab'

    def modal_sketch(self,context,eventd):
        if eventd['type'] == 'MOUSEMOVE':
            x,y = eventd['mouse']
            if not len(self.sketch):
                return 'main'
            ## Manipulating sketch data
            (lx, ly) = self.sketch[-1]
            ss0,ss1 = self.stroke_smoothing ,1-self.stroke_smoothing  #First data manipulation
            self.sketch += [(lx*ss0+x*ss1, ly*ss0+y*ss1)]
            return 'sketch'

        elif eventd['release'] == 'LEFTMOUSE':
            is_sketch = self.sketch_confirm(context, eventd)
            if self.PLM.current.ed_cross_map.is_used and is_sketch:
                self.PLM.current.make_cut()
            self.ui_text_update(context)
            self.sketch = []
            return 'main'

    def modal_select(self, context, eventd):
        if eventd['type'] == 'MOUSEMOVE':
            x,y = eventd['mouse']
            self.PLM.hover(context, x, y)
            return 'select'

        elif eventd['press'] == 'LEFTMOUSE':
            if self.PLM.hovered:
                self.PLM.select(context)
                self.set_ui_text_main(context)
                context.window.cursor_modal_set('CROSSHAIR')
                return 'main'
            return 'select'

        elif eventd['press'] == 'RIGHTMOUSE':
            if self.PLM.hovered and self.PLM.num_polylines > 1:
                self.PLM.delete(context)
            return 'select'

        elif eventd['press'] == 'N':
            self.PLM.start_new_polyline(context)
            context.window.cursor_modal_set('CROSSHAIR')
            self.set_ui_text_main(context)
            return 'main'

        elif eventd['press'] in {'ESC', 'A'}:
            self.PLM.terminate_select_mode()
            context.window.cursor_modal_set('CROSSHAIR')
            self.set_ui_text_main(context)
            return 'main'

    def modal_inner(self,context,eventd):

        if eventd['press'] == 'LEFTMOUSE':
            x,y = eventd['mouse']

            result = self.PLM.current.click_seed_select(context, x,y)
            # found a good face
            if result == 1:
                context.window.cursor_modal_set('CROSSHAIR')
                if self.PLM.current.ed_cross_map.is_used and not self.PLM.current.bad_segments and not self.PLM.current.split:
                    self.PLM.current.confirm_cut_to_mesh_no_ops()
                    context.area.header_text_set("X:delete, P:separate, SHIFT+D:duplicate, K:knife, Y:split")
                return 'main'
            # found a bad face
            elif result == -1:
                showErrorMessage('Seed is too close to cut boundary, try again more interior to the cut')
                return 'inner'
            # face not found
            else:
                showErrorMessage('Seed not found, try again')
                return 'inner'

        if eventd['press'] in {'RET', 'ESC'}:
            return 'main'