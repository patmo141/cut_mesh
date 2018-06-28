'''
Created on Oct 11, 2015

@author: Patrick
'''
from ..common_utilities import showErrorMessage

class Polytrim_UI_ModalWait():

    def modal_wait(self,context,eventd):
        # general navigation
        nmode = self.modal_nav(context, eventd)
        if nmode != '':
            return nmode  #stop here and tell parent modal to 'PASS_THROUGH'

        # test code that will break operator :)
        #if eventd['press'] == 'F9': bad = 3.14 / 0
        #if eventd['press'] == 'F10': assert False

        #after navigation filter, these are relevant events in this state
        if eventd['press'] == 'G':
            context.area.header_text_set("'MoveMouse'and 'LeftClick' to adjust node location, Right Click to cancel the grab")
            if self.knife.grab_initiate():
                return 'grab'
            else:
                #need to select a point
                return 'main'

        if  eventd['type'] == 'MOUSEMOVE':
            x,y = eventd['mouse']
            self.knife.hover(context, x, y)
            self.ui_text_update(context)
            return 'main'

        if  eventd['press'] == 'LEFTMOUSE':
            x,y = eventd['mouse']  #gather the 2D coordinates of the mouse click
            self.knife.click_add_point(context, x,y)  #Send the 2D coordinates to Knife Class
            if (self.knife.ui_type == 'DENSE_POLY' and self.knife.hovered[0] == 'POINT') or len(self.knife.points_data) == 1:
                self.sketch = [(x,y)]
                return 'sketch'
            return 'main'

        if eventd['press'] == 'RIGHTMOUSE':
            x,y = eventd['mouse']
            if self.knife.start_edge and self.knife.hovered[1] == 0 and self.knife.num_points() > 1:
                showErrorMessage('Can not delete the first point for this kind of cut.')
                return 'main'
            self.knife.click_delete_point(mode = 'mouse')
            self.knife.hover(context, x, y) ## this fixed index out range error in draw function after deleteing last point.
            if len(self.knife.new_cos):
                self.knife.make_cut()
            return 'main'

        if eventd['press'] == 'C':
            if self.knife.start_edge != None and self.knife.end_edge == None:
                showErrorMessage('Cut starts on non manifold boundary of mesh and must end on non manifold boundary')
            elif self.knife.start_edge == None and not self.knife.cyclic:
                showErrorMessage('Cut starts within mesh.  Cut must be closed loop.  Click the first point to close the loop')
            else:
                self.knife.make_cut()
                context.area.header_text_set("Red segments have cut failures, modify polyline to fix.  When ready press 'S' to set seed point")

            return 'main'

        if eventd['press'] == 'K':
            if self.knife.split and self.knife.face_seed and len(self.knife.ed_map):
                self.knife.split_geometry(eventd['context'], mode = 'KNIFE')
                return 'finish'

        if eventd['press'] == 'P':
            if self.knife.split and self.knife.face_seed and len(self.knife.ed_map):
                self.knife.split_geometry(eventd['context'], mode = 'SEPARATE')
            return 'finish'

        if eventd['press'] == 'X':
            if self.knife.split and self.knife.face_seed and len(self.knife.ed_map):
                self.knife.split_geometry(eventd['context'], mode = 'DELETE')
            return 'finish'

        if eventd['press'] == 'Y':
            if self.knife.split and self.knife.face_seed and len(self.knife.ed_map):
                self.knife.split_geometry(eventd['context'], mode = 'SPLIT')
            return 'finish'

        if eventd['press'] == 'SHIFT+D':
            if self.knife.split and self.knife.face_seed and len(self.knife.ed_map):
                self.knife.split_geometry(eventd['context'], mode = 'DUPLICATE')
            return 'finish'

        if eventd['press'] == 'S':
            if len(self.knife.bad_segments) != 0:
                showErrorMessage('Cut has failed segments shown in red.  Move the red segment slightly or add cut nodes to avoid bad part of mesh')
                return 'main'

            if self.knife.start_edge == None and not self.knife.cyclic:
                showErrorMessage('Finish closing cut boundary loop')
                return 'main'

            elif self.knife.start_edge != None and self.knife.end_edge == None:
                showErrorMessage('Finish cutting to another non-manifold boundary/edge of the object')
                return 'main'

            elif len(self.knife.new_cos) == 0:
                showErrorMessage('Press "C" to preview the cut success before setting the seed')
                return 'main'

            context.window.cursor_modal_set('EYEDROPPER')
            context.area.header_text_set("Left Click Region to select area to cut")
            return 'inner'

        if eventd['press'] == 'RET' :
            self.knife.confirm_cut_to_mesh()
            return 'finish'

        elif eventd['press'] == 'ESC':
            return 'cancel'

        return 'main'

    def modal_grab(self,context,eventd):
        # no navigation in grab mode

        if eventd['press'] == 'LEFTMOUSE':
            #confirm location
            x,y = eventd['mouse']
            self.knife.grab_confirm(context, x, y)
            if self.knife.new_cos:
                self.knife.make_cut()
            self.ui_text_update(context)
            return 'main'

        elif eventd['press'] in {'RIGHTMOUSE', 'ESC'}:
            #put it back!
            self.knife.grab_cancel()
            self.ui_text_update(context)
            return 'main'

        elif eventd['type'] == 'MOUSEMOVE':
            #update the b_pt location
            x,y = eventd['mouse']
            self.knife.grab_mouse_move(context,x, y)
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
            if self.knife.new_cos and is_sketch:
                self.knife.make_cut()
            self.ui_text_update(context)
            self.sketch = []
            return 'main'

    def modal_inner(self,context,eventd):

        if eventd['press'] == 'LEFTMOUSE':
            x,y = eventd['mouse']

            result = self.knife.click_seed_select(context, x,y)
            # found a good face
            if result == 1:
                context.window.cursor_modal_set('CROSSHAIR')
                if self.knife.new_cos and not self.knife.bad_segments and not self.knife.split:
                    self.knife.confirm_cut_to_mesh_no_ops()
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