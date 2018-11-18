'''
Created on Oct 11, 2015

@author: Patrick
'''

import time
import random

from bpy_extras import view3d_utils

from ..cookiecutter.cookiecutter import CookieCutter
from ..common.blender import show_error_message
from ..common.fsm import FSM
from .polytrim_datastructure import InputPoint, SplineSegment, CurveNode

'''
these are the states and substates (tool states)

    main   --> spline     (automatically switch to default tool)
    spline <-> seed
    seed   <-> region
    region <-> spline

    spline tool:
        main --> grab   --> main
        main --> sketch --> main

    seed tool:
        (no states)

    region tool:
        main --> paint --> main
'''



class Polytrim_States():
    # spline, seed, and region are tools with their own states
    spline_fsm = FSM()
    seed_fsm   = FSM()
    region_fsm = FSM()

    def fsm_setup(self):
        # let each fsm know that self should be passed to every fsm state call and transition (main, enter, exit, etc.)
        self.spline_fsm.set_call_args(self)
        self.seed_fsm.set_call_args(self)
        self.region_fsm.set_call_args(self)

    def common(self, fsm):
        # this fn contains common actions for all states

        # test code that will break operator :)
        #if self.actions.pressed('F9'): bad = 3.14 / 0
        #if self.actions.pressed('F10'): assert False

        if self.actions.pressed('S'):
            #TODO what about a button?
            #What about can_enter?
            return 'seed'

        if self.actions.pressed('P'):
            #TODO what about a button?
            #What about can_enter?
            return 'region'

        if self.actions.pressed('RET'):
            self.done()
            return
            #return 'finish'

        if self.actions.pressed('ESC'):
            self.done(cancel=True)
            return
            #return 'cancel'

        # call the currently selected tool
        fsm.update()


    @CookieCutter.FSM_State('main')
    def main(self):
        return 'spline'


    @CookieCutter.FSM_State('spline', 'enter')
    def spline_enter(self):
        self.spline_fsm.reset()

    @CookieCutter.FSM_State('spline', 'exit')
    def spline_exit(self):
        #maybe this needs to happen on paint enter...yes?
        self.spline_fsm.reset()

    @CookieCutter.FSM_State('spline')
    def spline(self):
        return self.common(self.spline_fsm)


    @CookieCutter.FSM_State('seed', 'can enter')
    def seed_can_enter(self):
        # exit spline mode iff cut network has finished and there are no bad segments
        c1 = not any([seg.is_bad for seg in self.input_net.segments])
        c2 = all([seg.calculation_complete for seg in self.input_net.segments])
        return c1 and c2

    @CookieCutter.FSM_State('seed', 'enter')
    def seed_enter(self):
        if self.network_cutter.knife_complete:
            self.network_cutter.find_perimeter_edges()
        else:
            self.network_cutter.find_boundary_faces_cycles()
        self.seed_fsm.reset()

    @CookieCutter.FSM_State('seed')
    def seed(self):
        return self.common(self.seed_fsm)


    @CookieCutter.FSM_State('region', 'can enter')
    def region_can_enter(self):
        # exit spline mode iff cut network has finished and there are no bad segments
        c1 = not any([seg.is_bad for seg in self.input_net.segments])
        c2 = all([seg.calculation_complete for seg in self.input_net.segments])
        return c1 and c2

    @CookieCutter.FSM_State('region', 'enter')
    def region_enter(self):
        self.network_cutter.find_boundary_faces_cycles()
        for patch in self.network_cutter.face_patches:
            patch.grow_seed_faces(self.input_net.bme, self.network_cutter.boundary_faces)
            patch.color_patch()

        self.network_cutter.update_spline_edited_patches(self.spline_net)

        self.net_ui_context.bme.to_mesh(self.net_ui_context.ob.data)
        self.region_fsm.reset()

    @CookieCutter.FSM_State('region', 'exit')
    def region_exit(self):
        self.paint_exit()
        self.region_fsm.reset()


    @CookieCutter.FSM_State('region')
    def region(self):
        return self.common(self.region_fsm)


    ######################################################
    # spline editing

    @spline_fsm.FSM_State('main')
    def spline_main(self):
        self.cursor_modal_set('CROSSHAIR')
        context = self.context

        mouse_just_stopped = self.actions.mousemove_prev and not self.actions.mousemove
        if mouse_just_stopped:
            self.net_ui_context.update(self.actions.mouse)
            #TODO: Bring hover into NetworkUiContext
            self.hover_spline()
            #self.net_ui_context.inspect_print()

        # after navigation filter, these are relevant events in this state
        if self.actions.pressed('grab'):
            self.ui_text_update()
            return 'grab'

        if self.actions.pressed('select', unpress=False):
            if self.net_ui_context.hovered_near[0] == 'POINT':
                self.actions.unpress()
                print('select hovered point')
                self.net_ui_context.selected = self.net_ui_context.hovered_near[1]
                return

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


    @spline_fsm.FSM_State('grab', 'can enter')
    def spline_grab_can_enter(self):
        return (not self.spline_net.is_empty and self.net_ui_context.selected != None)

    @spline_fsm.FSM_State('grab', 'enter')
    def spline_grab_enter(self):
        self.header_text_set("'MoveMouse' and 'LeftClick' to adjust node location, Right Click to cancel the grab")
        self.grabber.initiate_grab_point()
        self.grabber.move_grab_point(self.context, self.actions.mouse)
        self.ui_text_update()

    @spline_fsm.FSM_State('grab')
    def spline_grab(self):
        # no navigation in grab mode
        self.cursor_modal_set('HAND')

        if self.actions.pressed('LEFTMOUSE'):
            #confirm location
            x,y = self.actions.mouse
            self.grabber.finalize(self.context)

            if isinstance(self.net_ui_context.selected, CurveNode):
                self.spline_net.push_to_input_net(self.net_ui_context, self.input_net)
                self.network_cutter.update_segments_async()
            else:
                self.network_cutter.update_segments()

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

    @spline_fsm.FSM_State('grab', 'exit')
    def spline_grab_exit(self):
        self.ui_text_update()


    @spline_fsm.FSM_State('sketch', 'can enter')
    def spline_sketch_can_enter(self):
        print("selected", self.net_ui_context.selected)
        context = self.context
        mouse = self.actions.mouse  #gather the 2D coordinates of the mouse click

        # TODO: do NOT change state in "can enter".  move the following click_add_* stuff to "enter"
        self.click_add_spline_point(context, mouse)  #Send the 2D coordinates to Knife Class
        return  self.net_ui_context.hovered_near[0] == 'POINT' or self.input_net.num_points == 1

    @spline_fsm.FSM_State('sketch', 'enter')
    def spline_sketch_enter(self):
        x,y = self.actions.mouse
        self.sketcher.add_loc(x,y)

    @spline_fsm.FSM_State('sketch')
    def spline_sketch(self):
        if self.actions.mousemove:
            x,y = self.actions.mouse
            if not len(self.sketcher.sketch):
                return 'spline main' #XXX: Delete this??
            self.sketcher.smart_add_loc(x,y)
            return

        if self.actions.released('sketch'):
            return 'spline main'

    @spline_fsm.FSM_State('sketch', 'exit')
    def spline_sketch_exit(self):
        is_sketch = self.sketcher.is_good()
        if is_sketch:
            last_hovered_point = self.net_ui_context.hovered_near[1]
            print("LAST:",self.net_ui_context.hovered_near)
            self.net_ui_context.update(self.actions.mouse)
            self.hover_spline()
            new_hovered_point = self.net_ui_context.hovered_near[1]
            print("NEW:",self.net_ui_context.hovered_near)
            print(last_hovered_point, new_hovered_point)
            self.sketcher.finalize(self.context, last_hovered_point, new_hovered_point)
            self.spline_net.push_to_input_net(self.net_ui_context, self.input_net)
            self.network_cutter.update_segments_async()
        self.ui_text_update()
        self.sketcher.reset()


    ######################################################
    # poly edit
    # note: currently not used!

    # @CookieCutter.FSM_State('poly')
    # def poly(self):
    #     return 'poly main'

    # @CookieCutter.FSM_State('poly main')
    # def poly_main(self):
    #     self.cursor_modal_set('CROSSHAIR')
    #     context = self.context

    #     # test code that will break operator :)
    #     #if self.actions.pressed('F9'): bad = 3.14 / 0
    #     #if self.actions.pressed('F10'): assert False

    #     if self.actions.mousemove:
    #         return
    #     if self.actions.mousemove_prev:
    #         self.net_ui_context.update(self.actions.mouse)
    #         #TODO: Bring hover into NetworkUiContext
    #         self.hover()

    #     #after navigation filter, these are relevant events in this state
    #     if self.actions.pressed('grab'):
    #         self.ui_text_update()
    #         return 'poly grab'

    #     if self.actions.pressed('sketch'):
    #         self.ui_text_update()
    #         return 'poly sketch'

    #     if self.actions.pressed('add point (disconnected)'):
    #         self.click_add_point(context, self.actions.mouse, False)
    #         self.ui_text_update()
    #         return

    #     if self.actions.pressed('delete'):
    #         self.click_delete_point(mode='mouse')
    #         self.net_ui_context.update(self.actions.mouse)
    #         self.hover()
    #         self.ui_text_update()
    #         return

    #     if self.actions.pressed('delete (disconnect)'):
    #         self.click_delete_point('mouse', True)
    #         self.net_ui_context.update(self.actions.mouse)
    #         self.hover()
    #         self.ui_text_update()
    #         return

    #     if self.actions.pressed('S'):
    #         #TODO what about a button?
    #         #What about can_enter?
    #         return 'seed'

    #     if self.actions.pressed('P'):
    #         #TODO what about a button?
    #         #What about can_enter?
    #         return 'paint entering'

    #     if self.actions.pressed('RET'):
    #         #self.done()
    #         return 'main'
    #         #return 'finish'

    #     elif self.actions.pressed('ESC'):
    #         #self.done(cancel=True)
    #         return 'main'
    #         #return 'cancel

    # @CookieCutter.FSM_State('poly sketch', 'can enter')
    # def poly_sketch_can_enter(self):
    #     print("selected", self.net_ui_context.selected)
    #     context = self.context
    #     mouse = self.actions.mouse  #gather the 2D coordinates of the mouse click

    #     # TODO: do NOT change state in "can enter".  move the following click_add_* stuff to "enter"
    #     self.click_add_point(context, mouse)
    #     print("selected 2", self.net_ui_context.selected)
    #     return (self.net_ui_context.ui_type == 'DENSE_POLY' and self.net_ui_context.hovered_near[0] == 'POINT') or self.input_net.num_points == 1

    # @CookieCutter.FSM_State('poly grab', 'can enter')
    # def poly_grab_can_enter(self):
    #     return (not self.input_net.is_empty and self.net_ui_context.selected != None)


    ######################################################
    # seed/patch selection state

    @seed_fsm.FSM_State('main')
    def modal_seed(self):
        self.cursor_modal_set('EYEDROPPER')

        if self.actions.mousemove_prev:
            #update the bmesh geometry under mouse location
            self.net_ui_context.update(self.actions.mouse)

        if self.actions.pressed('LEFTMOUSE'):
            #place seed on surface
            #background watershed form the seed to color the region on the mesh
            self.click_add_seed()

        #if right click
            #remove the seed
            #remove any "patch" data associated with the seed


    ######################################################
    # region painting

    @region_fsm.FSM_State('main', 'enter')
    def region_main_enter(self):
        self.brush = self.PaintBrush(self.net_ui_context, radius=self.brush_radius)

    @region_fsm.FSM_State('main')
    def region_main(self):
        self.cursor_modal_set('PAINT_BRUSH')

        if self.actions.mousemove_prev:
            #update the bmesh geometry under mouse location
            self.net_ui_context.update(self.actions.mouse)

        if self.actions.pressed('LEFTMOUSE'):
            #start painting
            return 'paint'

        if self.actions.pressed('RIGHTMOUSE'):
            return 'paint'


    @region_fsm.FSM_State('paint', 'can enter')
    def region_paint_can_enter(self):
        #any time really, may require a BVH update if
        #network cutter has been executed
        return True

    @region_fsm.FSM_State('paint', 'enter')
    def region_paint_enter(self):
        #set the cursor to to something
        self.network_cutter.find_boundary_faces_cycles()
        self.click_enter_paint()
        self.last_loc = None
        self.last_update = 0
        self.paint_dirty = False

    @region_fsm.FSM_State('paint')
    def region_paint(self):
        self.cursor_modal_set('PAINT_BRUSH')

        if self.actions.released('LEFTMOUSE'):
            return 'main'

        loc,_,_ = self.brush.ray_hit(self.actions.mouse, self.context)
        if loc and (not self.last_loc or (self.last_loc - loc).length > self.brush.radius*(0.25)):
            self.last_loc = loc
            #update the bmesh geometry under mouse location
            #use brush radius to find all geometry within
            #add that geometry to the "stroke region"
            #color it as the "interim" strokeregion color
            self.brush.absorb_geom_geodesic(self.context, self.actions.mouse)
            #self.brush.absorb_geom(self.context, self.actions.mouse)
            self.paint_dirty = True

        if self.paint_dirty and (time.time() - self.last_update) > 0.2:
            self.net_ui_context.bme.to_mesh(self.net_ui_context.ob.data)
            self.paint_dirty = False
            self.last_update = time.time()

    @region_fsm.FSM_State('paint', 'exit')
    def region_paint_exit(self):
        self.brush.absorb_geom_geodesic(self.context, self.actions.mouse)
        self.paint_confirm()
        self.net_ui_context.bme.to_mesh(self.net_ui_context.ob.data)
        #self.paint_confirm()
        #add all geometry (or subtract all geometr) from current patch
        #color it apporpriately
        #reset the paint widget
