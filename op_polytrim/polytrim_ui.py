'''
Created on Oct 8, 2015

@author: Patrick
'''
import copy

import bpy
import bmesh
from mathutils import Matrix, Vector

from .cache import polytrim_undo_cache

class Polytrim_UI:
    ###############################
    # undo functions
    def create_undo_snapshot(self, action):
        '''
        unsure about all the _timers get deep copied
        and if sel_gedges and verts get copied as references
        or also duplicated, making them no longer valid.
        '''

        p_data = copy.deepcopy(self.polytrim)
        polytrim_undo_cache.append((p_data, action))

        if len(polytrim_undo_cache) > 10:
            polytrim_undo_cache.pop(0)

    def undo_action(self):
        '''
        '''
        if len(polytrim_undo_cache) > 0:
            data, action = polytrim_undo_cache.pop()

            self.polytrim = data[0]

    def create_polytrim_from_bezier(self, ob_bezier):
        #TODO, read al the bezier points or interp the bezier?
        return

    def create_polytrim_from_vert_loop(self, ob_bezier):
        #TODO, read all the mesh data in and make a polylineknife
        return

    def create_polystrips_from_greasepencil(self):
        Mx = self.obj_orig.matrix_world
        gp = self.obj_orig.grease_pencil
        gp_layers = gp.layers
        # for gpl in gp_layers: gpl.hide = True
        strokes = [[(p.co,p.pressure) for p in stroke.points] for layer in gp_layers for frame in layer.frames for stroke in frame.strokes]
        self.strokes_original = strokes