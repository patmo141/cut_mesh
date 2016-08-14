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

        #after navigation filter, these are relevant events in this state
        if eventd['press'] == 'G':
            if self.knife.grab_initiate():
                return 'grab'
            else:
                #need to select a point
                return 'main'
        
        if  eventd['type'] == 'MOUSEMOVE':
            x,y = eventd['mouse']
            self.knife.hover(context, x, y)    
            return 'main'
        
        if  eventd['press'] == 'LEFTMOUSE':
            x,y = eventd['mouse']
            self.knife.click_add_point(context, x,y)  #takes care of selection too
            if self.knife.ui_type == 'DENSE_POLY' and self.knife.hovered[0] == 'POINT':
                self.sketch = [(x,y)]
                return 'sketch'
            return 'main'
        
        if eventd['press'] == 'RIGHTMOUSE':
            self.knife.click_delete_point(mode = 'mouse')
            return 'main'
                
        if eventd['press'] == 'C':
            self.knife.make_cut()
            context.area.header_text_set("Red segments have cut failures, modify polyline to fix.  When ready press 'S' to set seed point")
        
            return 'main' 
        
        if eventd['press'] == 'D':
            if not self.knife.face_seed:
                showErrorMessage('Must select seed point first')
                return 'main'
            
            if len(self.knife.new_cos) and len(self.knife.bad_segments) == 0 and not self.knife.split:
                self.knife.confirm_cut_to_mesh_no_ops()
                
                context.area.header_text_set("X:delete, P:separate, SHIFT+D:duplicate, K:knife, Y:split")
        
                return 'main' 
            
        if eventd['press'] == 'K':     
            if self.knife.split and self.knife.face_seed and len(self.knife.ed_map):
                self.knife.split_geometry(eventd['context'], mode = 'KNIFE')
                return 'finish' 
        
        if eventd['press'] == 'P':
            #self.knife.preview_mesh(eventd['context'])
            self.knife.split_geometry(eventd['context'], mode = 'SEPARATE')
            return 'finish'
        
        if eventd['press'] == 'X':
            self.knife.split_geometry(eventd['context'], mode = 'DELETE')
            return 'finish'
        
        if eventd['press'] == 'Y':
            self.knife.split_geometry(eventd['context'], mode = 'SPLIT')
            return 'finish'
        
        if eventd['press'] == 'SHIFT+D':
            self.knife.split_geometry(eventd['context'], mode = 'DUPLICATE')
            return 'finish'
            
        if eventd['press'] == 'S':
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
            self.knife.grab_confirm()
            self.knife.make_cut()
            return 'main'
        
        elif eventd['press'] in {'RIGHTMOUSE', 'ESC'}:
            #put it back!
            self.knife.grab_cancel()
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
            (lx, ly) = self.sketch[-1]
            ss0,ss1 = self.stroke_smoothing ,1-self.stroke_smoothing
            self.sketch += [(lx*ss0+x*ss1, ly*ss0+y*ss1)]
            return 'sketch'
        
        elif eventd['release'] == 'LEFTMOUSE':
            self.sketch_confirm(context, eventd)
            self.sketch = []
            return 'main'
        
    def modal_inner(self,context,eventd):
        
        if eventd['press'] == 'LEFTMOUSE':
            print('left click modal inner')
            x,y = eventd['mouse']
            if self.knife.click_seed_select(context, x,y):
                print('seed set')
                return 'main'
            else:
                return 'inner'
        
        if eventd['press'] in {'RET', 'ESC'}:
            return 'main'