'''
Created on Oct 11, 2015

@author: Patrick
'''

import random

from bpy_extras import view3d_utils

from ..cookiecutter.cookiecutter import CookieCutter
from ..common.blender import show_error_message
from .polytrim_datastructure import InputPoint, SplineSegment


class Polytrim_States():
    @CookieCutter.FSM_State('main')  #now spline mode
    def modal_main(self):
        context = self.context
        self.cursor_modal_set('CROSSHAIR')

        # test code that will break operator :)
        #if self.actions.pressed('F9'): bad = 3.14 / 0
        #if self.actions.pressed('F10'): assert False

        if self.actions.mousemove:
            return
        if self.actions.mousemove_prev:
            self.net_ui_context.update(self.actions.mouse)
            #TODO: Bring hover into NetworkUiContext
            self.hover_spline()
            #self.net_ui_context.inspect_print()
            
        #after navigation filter, these are relevant events in this state
        if self.actions.pressed('grab'): 
            self.ui_text_update()
            return 'grab'

        if self.actions.pressed('sketch'): 
            self.ui_text_update()
            return 'sketch'

        if self.actions.pressed('add point (disconnected)'):
            self.click_add_spline_point(context, self.actions.mouse, False)
            self.ui_text_update()
            #self.net_ui_context.inspect_print()
            return

        if self.actions.pressed('delete'):
            self.click_delete_spline_point(mode='mouse')
            self.net_ui_context.update(self.actions.mouse)
            self.hover_spline()
            self.ui_text_update()
            return
        
        if self.actions.pressed('delete (disconnect)'):
            self.click_delete_spline_point('mouse', True)
            self.net_ui_context.update(self.actions.mouse)
            self.hover_spline()
            self.ui_text_update()
            return

        if self.actions.pressed('S'):
            #TODO what about a button?
            #What about can_enter?
            return 'seed'
        
        if self.actions.pressed('P'):
            #TODO what about a button?
            #What about can_enter?
            return 'paint_wait'
             
        if self.actions.pressed('RET'):
            self.done()
            return
            #return 'finish'

        elif self.actions.pressed('ESC'):
            self.done(cancel=True)
            return
            #return 'cancel'


    @CookieCutter.FSM_State('point_edit')
    def modal_point_edit(self):
        context = self.context
        self.cursor_modal_set('CROSSHAIR')

        # test code that will break operator :)
        #if self.actions.pressed('F9'): bad = 3.14 / 0
        #if self.actions.pressed('F10'): assert False

        if self.actions.mousemove:
            return
        if self.actions.mousemove_prev:
            self.net_ui_context.update(self.actions.mouse)
            #TODO: Bring hover into NetworkUiContext
            self.hover()

        #after navigation filter, these are relevant events in this state
        if self.actions.pressed('grab'): 
            self.ui_text_update()
            return 'grab'

        if self.actions.pressed('sketch'): 
            self.ui_text_update()
            return 'sketch'

        if self.actions.pressed('add point (disconnected)'):
            self.click_add_point(context, self.actions.mouse, False)
            self.ui_text_update()
            return

        if self.actions.pressed('delete'):
            self.click_delete_point(mode='mouse')
            self.net_ui_context.update(self.actions.mouse)
            self.hover()
            self.ui_text_update()
            return
        
        if self.actions.pressed('delete (disconnect)'):
            self.click_delete_point('mouse', True)
            self.net_ui_context.update(self.actions.mouse)
            self.hover()
            self.ui_text_update()
            return

        if self.actions.pressed('S'):
            #TODO what about a button?
            #What about can_enter?
            return 'seed'
        
        if self.actions.pressed('P'):
            #TODO what about a button?
            #What about can_enter?
            return 'paint_wait'
        
           
        if self.actions.pressed('RET'):
            #self.done()
            return 'main'
            #return 'finish'

        elif self.actions.pressed('ESC'):
            #self.done(cancel=True)
            return 'main'
            #return 'cancel


    ######################################################
    # grab state

    @CookieCutter.FSM_State('grab', 'can enter')
    def grab_can_enter(self):
        can_enter = (not self.input_net.is_empty and self.net_ui_context.selected != None)
        can_enter_spline = (not self.spline_net.is_empty and self.net_ui_context.selected != None)
        if self._state == 'main':
            return can_enter_spline
        else:    
            return can_enter

    @CookieCutter.FSM_State('grab', 'enter')
    def grab_enter(self):
        self.header_text_set("'MoveMouse'and 'LeftClick' to adjust node location, Right Click to cancel the grab")
        self.grabber.initiate_grab_point()
        self.grabber.move_grab_point(self.context, self.actions.mouse)
        self.ui_text_update()

    @CookieCutter.FSM_State('grab')
    def modal_grab(self):
        # no navigation in grab mode
        self.cursor_modal_set('HAND')

        if self.actions.pressed('LEFTMOUSE'):
            #confirm location
            x,y = self.actions.mouse
            self.grabber.finalize(self.context)
            self.network_cutter.update_segments()
            if self.net_ui_context.selected not in self.input_net.points:
                self.net_ui_context.selected = None
            return 'main'

        if self.actions.pressed('cancel'):
            #put it back!
            self.grabber.grab_cancel()
            return 'main'

        if self.actions.mousemove:
            self.net_ui_context.update(self.actions.mouse)
            #self.net_ui_context.hover()
            return
        if self.actions.mousemove_prev:
            #update the b_pt location
            self.net_ui_context.update(self.actions.mouse)
            #self.hover()
            #self.net_ui_context.hover()
            self.grabber.move_grab_point(self.context, self.actions.mouse)

    @CookieCutter.FSM_State('grab', 'exit')
    def grab_exit(self):
        self.ui_text_update()

    ######################################################
    # sketch state

    @CookieCutter.FSM_State('sketch', 'can enter')
    def sketch_can_enter(self):
        print("selected", self.net_ui_context.selected)
        context = self.context
        mouse = self.actions.mouse  #gather the 2D coordinates of the mouse click
        if self._state == 'main':
            self.click_add_spline_point(context, mouse)  #Send the 2D coordinates to Knife Class
            return  self.net_ui_context.hovered_near[0] == 'POINT' or self.input_net.num_points == 1
        elif self._state == 'point_edit':
            self.click_add_point(context, mouse)
            
            print("selected 2", self.net_ui_context.selected)
            return (self.net_ui_context.ui_type == 'DENSE_POLY' and self.net_ui_context.hovered_near[0] == 'POINT') or self.input_net.num_points == 1

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
                last_hovered_point = self.net_ui_context.hovered_near[1]
                print("LAST:",self.net_ui_context.hovered_near)
                self.net_ui_context.update(self.actions.mouse)
                self.hover()
                new_hovered_point = self.net_ui_context.hovered_near[1]   
                print("NEW:",self.net_ui_context.hovered_near)
                print(last_hovered_point, new_hovered_point)
                self.sketcher.finalize(self.context, last_hovered_point, new_hovered_point)
                #self.sketcher.finalize_bezier(self.context)
                self.network_cutter.update_segments_async()
            self.ui_text_update()
            self.sketcher.reset()
            return 'main'

    ######################################################
    # seed/patch selection state

    @CookieCutter.FSM_State('seed', 'can enter')
    def seed_can_enter(self):
        #the cut network has been executed
        return True

    @CookieCutter.FSM_State('seed', 'enter')
    def seed_enter(self):
        #set the cursor to to something
        if self.network_cutter.knife_complete:
            self.network_cutter.find_perimeter_edges()
        else:
            self.network_cutter.find_boundary_faces()
        
        return
    
    @CookieCutter.FSM_State('seed')
    def modal_seed(self):
        self.cursor_modal_set('EYEDROPPER')
        if self.actions.mousemove_prev:
            #update the bmesh geometry under mouse location
            self.net_ui_context.update(self.actions.mouse)
               
        #if left click
            #place seed on surface
            #background watershed form the seed to color the region on the mesh
        
        if self.actions.pressed('LEFTMOUSE'):
            self.click_add_seed()        
        
        #if right click
            #remove the seed
            #remove any "patch" data associated with the seed

        #if escape
            #return to 'main'
            
        #if enter
            #return to 'main'
        if self.actions.pressed('RET'):
            return 'main'
           
        return 'seed'
    
    
    @CookieCutter.FSM_State('paint_wait', 'can enter')
    def paintwait_can_enter(self):
        #the cut network has been executed
        return True

    @CookieCutter.FSM_State('paint_wait', 'enter')
    def paintwait_enter(self):
        
        self.brush = self.PaintBrush(self.net_ui_context)
        return
    
    @CookieCutter.FSM_State('paint_wait')
    def modal_paintwait(self):
        self.cursor_modal_set('PAINT_BRUSH')
        if self.actions.mousemove_prev:
            #update the bmesh geometry under mouse location
            self.net_ui_context.update(self.actions.mouse)
            
                
        if self.actions.pressed('LEFTMOUSE'):
            #start painting
            return 'paint'
        
        if self.actions.pressed('RIGHTMOUSE'):
            
            return 'paint'
        
        if self.actions.pressed('RET'):
            
            del self.brush
            self.brush = None
            self.paint_exit()
            return 'main'
        
        if self.actions.pressed('ESC'):
            del self.brush
            self.brush = None
            return 'main'
        
        return 'paint_wait'
    
    
    @CookieCutter.FSM_State('paint', 'can enter')
    def paint_can_enter(self):
        #any time really, may require a BVH update if
        #network cutter has been executed
        return True

    @CookieCutter.FSM_State('paint', 'enter')
    def paint_enter(self):
        #set the cursor to to something
        self.network_cutter.find_boundary_faces()
        self.click_enter_paint()
        return
    
    @CookieCutter.FSM_State('paint')
    def modal_paint(self):
        self.cursor_modal_set('PAINT_BRUSH')
        if self.actions.mousemove_prev:
            #update the bmesh geometry under mouse location
            #use brush radius to find all geometry within
            #add that geometry to the "stroke region"
            #color it as the "interim" strokeregion color
            self.brush.absorb_geom(self.context, self.actions.mouse)
            self.net_ui_context.bme.to_mesh(self.net_ui_context.ob.data)
            return 'paint'
        
        if self.actions.released('LEFTMOUSE'):
            self.brush.absorb_geom(self.context, self.actions.mouse)
            self.paint_confirm()
            self.net_ui_context.bme.to_mesh(self.net_ui_context.ob.data)
            
            #self.paint_confirm()
            #add all geometry (or subtract all geometr) from current patch
            #color it apporpriately
            #reset the paint widget
            return 'paint_wait'
        
        #if right click
            #remove the seed
            #remove any "patch" data associated with the seed

        #if escape
            #return to 'main'
            
        #if enter
            #return to 'main'
        
           
        return 'paint'