'''
Created on Oct 8, 2015

@author: Patrick
'''
from .polystrips_datastructure import Polystrips, GVert


class Polytrim_UI:
    
    def start_ui(self, context):
        
        self.stroke_smoothing = 0.75          # 0: no smoothing. 1: no change
        
        self.mode_pos        = (0, 0)
        self.cur_pos         = (0, 0)
        self.mode_radius     = 0
        self.action_center   = (0, 0)
        self.action_radius   = 0
        self.is_navigating   = False
        self.sketch_curpos   = (0, 0)
        self.sketch_pressure = 1
        self.sketch          = []
        

        if context.mode == 'OBJECT':

        
    
    def end_ui(self, context):
        if not self.was_fullscreen and self.settings.distraction_free:
            bpy.ops.screen.screen_full_area(use_hide_panels=True)
            self.is_fullscreen = False
        
        
    def cleanup(self, context, cleantype=''):
        '''
        remove temporary object
        '''
        dprint('cleaning up!')
        if cleantype == 'commit':
            pass

        elif cleantype == 'cancel':
            pass
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

    
    ###########################
    # mesh creation
    def create_mesh(self, context):
        verts,quads,non_quads = self.polystrips.create_mesh(self.dest_bme)

        if 'EDIT' in context.mode:  #self.dest_bme and self.dest_obj:  #EDIT MODE on Existing Mesh
            mx = self.dest_obj.matrix_world
            imx = mx.inverted()

            mx2 = self.obj_orig.matrix_world
            imx2 = mx2.inverted()

        else:
            #bm = bmesh.new()  #now new bmesh is created at the start
            mx2 = Matrix.Identity(4)
            imx = Matrix.Identity(4)

            self.dest_obj.update_tag()
            self.dest_obj.show_all_edges = True
            self.dest_obj.show_wire      = True
            self.dest_obj.show_x_ray     = True
         
            self.dest_obj.select = True
            context.scene.objects.active = self.dest_obj
        
        container_bme = bmesh.new()
        
        bmverts = [container_bme.verts.new(imx * mx2 * v) for v in verts]
        container_bme.verts.index_update()
        for q in quads: 
            container_bme.faces.new([bmverts[i] for i in q])
        for nq in non_quads:
            container_bme.faces.new([bmverts[i] for i in nq])
        
        container_bme.faces.index_update()

        if 'EDIT' in context.mode: #self.dest_bme and self.dest_obj:
            bpy.ops.object.mode_set(mode='OBJECT')
            container_bme.to_mesh(self.dest_obj.data)
            bpy.ops.object.mode_set(mode = 'EDIT')
            #bmesh.update_edit_mesh(self.dest_obj.data, tessface=False, destructive=True)
        else: 
            container_bme.to_mesh(self.dest_obj.data)
        
        self.dest_bme.free()
        container_bme.free()

    ###########################
    # fill function

    def fill(self, eventd):
        
        # GVert active
        if self.act_gvert:
            showErrorMessage('Not supported at the moment.')
            return
            lges = self.act_gvert.get_gedges()
            if self.act_gvert.is_ljunction():
                lgepairs = [(lges[0],lges[1])]
            elif self.act_gvert.is_tjunction():
                lgepairs = [(lges[0],lges[1]), (lges[3],lges[0])]
            elif self.act_gvert.is_cross():
                lgepairs = [(lges[0],lges[1]), (lges[1],lges[2]), (lges[2],lges[3]), (lges[3],lges[0])]
            else:
                showErrorMessage('GVert must be a L-junction, T-junction, or Cross type to use simple fill')
                return
            
            # find gedge pair that is not a part of a gpatch
            lgepairs = [(ge0,ge1) for ge0,ge1 in lgepairs if not set(ge0.gpatches).intersection(set(ge1.gpatches))]
            if not lgepairs:
                showErrorMessage('Could not find two GEdges that are not already patched')
                return
            
            self.sel_gedges = set(lgepairs[0])
            self.act_gedge = next(iter(self.sel_gedges))
            self.act_gvert = None
        
        lgpattempt = self.polystrips.attempt_gpatch(self.sel_gedges)
        if type(lgpattempt) is str:
            showErrorMessage(lgpattempt)
            return
        lgp = lgpattempt
        
        self.act_gvert = None
        self.act_gedge = None
        self.sel_gedges.clear()
        self.sel_gverts.clear()
        self.act_gpatch = lgp[0]
        
        for gp in lgp:
            gp.update()
        self.polystrips.update_visibility(eventd['r3d'])



    ###########################
    # hover functions

    def hover_geom(self,eventd):
        mx,my = eventd['mouse'] 
        self.help_box.hover(mx, my)
        
        if not len(self.polystrips.extension_geometry): return
        self.hov_gvert = None
        for gv in self.polystrips.extension_geometry:
            if not gv.is_visible(): continue
            rgn   = eventd['context'].region
            r3d   = eventd['context'].space_data.region_3d
            mx,my = eventd['mouse']
            c0 = location_3d_to_region_2d(rgn, r3d, gv.corner0)
            c1 = location_3d_to_region_2d(rgn, r3d, gv.corner1)
            c2 = location_3d_to_region_2d(rgn, r3d, gv.corner2)
            c3 = location_3d_to_region_2d(rgn, r3d, gv.corner3)
            inside = point_inside_loop2d([c0,c1,c2,c3],Vector((mx,my)))
            if inside:
                self.hov_gvert = gv
                break
                print('found hover gv')
    

    ##############################
    # picking function

    def pick(self, eventd):
        x,y = eventd['mouse']
        pts = common_utilities.ray_cast_path_bvh(eventd['context'], mesh_cache['bvh'],self.mx, [(x,y)])
        if not pts:
            # user did not click on the object
            if not eventd['shift']:
                # clear selection if shift is not held
                self.act_gvert,self.act_gedge,self.act_gvert = None,None,None
                self.sel_gedges.clear()
                self.sel_gverts.clear()
            return ''
        pt = pts[0]

        if self.act_gvert or self.act_gedge:
            # check if user is picking an inner control point
            if self.act_gedge and not self.act_gedge.zip_to_gedge:
                lcpts = [self.act_gedge.gvert1,self.act_gedge.gvert2]
            elif self.act_gvert:
                sgv = self.act_gvert
                lge = self.act_gvert.get_gedges()
                lcpts = [ge.get_inner_gvert_at(sgv) for ge in lge if ge and not ge.zip_to_gedge] + [sgv]
            else:
                lcpts = []

            for cpt in lcpts:
                if not cpt.is_picked(pt): continue
                self.act_gedge = None
                self.sel_gedges.clear()
                self.act_gvert = cpt
                self.sel_gverts = set([cpt])
                self.act_gpatch = None
                return ''
        # Select gvert
        for gv in self.polystrips.gverts:
            if gv.is_unconnected(): continue
            if not gv.is_picked(pt): continue
            self.act_gedge = None
            self.sel_gedges.clear()
            self.sel_gverts.clear()
            self.act_gvert = gv
            self.act_gpatch = None
            return ''

        for ge in self.polystrips.gedges:
            if not ge.is_picked(pt): continue
            self.act_gvert = None
            self.act_gedge = ge
            if not eventd['shift']:
                self.sel_gedges.clear()
            self.sel_gedges.add(ge)
            self.sel_gverts.clear()
            self.act_gpatch = None
            
            for ge in self.sel_gedges:
                if ge == self.act_gedge: continue
                self.sel_gverts.add(ge.gvert0)
                self.sel_gverts.add(ge.gvert3)
            
            return ''
        
        # Select patch
        for gp in self.polystrips.gpatches:
            if not gp.is_picked(pt): continue
            self.act_gvert = None
            self.act_gedge = None
            self.sel_gedges.clear()
            self.sel_gverts.clear()
            self.act_gpatch = gp
            return ''
        
        if not eventd['shift']:
            self.act_gedge,self.act_gvert,self.act_gpatch = None,None,None
            self.sel_gedges.clear()
            self.sel_gverts.clear()

    ###########################################################
    # functions to convert beziers and gpencils to polystrips

    def create_polytrim_from_bezier(self, ob_bezier):
        data  = ob_bezier.data
        mx    = ob_bezier.matrix_world

        '''
        def create_gvert(self, mx, co, radius):
            p0  = mx * co
            r0  = radius
            n0  = Vector((0,0,1))
            tx0 = Vector((1,0,0))
            ty0 = Vector((0,1,0))
            return GVert(self.obj_orig,self.dest_obj, p0,r0,n0,tx0,ty0)

        for spline in data.splines:
            pregv = None
            for bp0,bp1 in zip(spline.bezier_points[:-1],spline.bezier_points[1:]):
                gv0 = pregv if pregv else self.create_gvert(mx, bp0.co, 0.2)
                gv1 = self.create_gvert(mx, bp0.handle_right, 0.2)
                gv2 = self.create_gvert(mx, bp1.handle_left, 0.2)
                gv3 = self.create_gvert(mx, bp1.co, 0.2)

                ge0 = GEdge(self.obj_orig, self.dest_obj, gv0, gv1, gv2, gv3)
                ge0.recalc_igverts_approx()
                ge0.snap_igverts_to_object()

                if pregv:
                    self.polystrips.gverts += [gv1,gv2,gv3]
                else:
                    self.polystrips.gverts += [gv0,gv1,gv2,gv3]
                self.polystrips.gedges += [ge0]
                pregv = gv3
                
    '''

    def create_polystrips_from_greasepencil(self):
        Mx = self.obj_orig.matrix_world
        gp = self.obj_orig.grease_pencil
        gp_layers = gp.layers
        # for gpl in gp_layers: gpl.hide = True
        strokes = [[(p.co,p.pressure) for p in stroke.points] for layer in gp_layers for frame in layer.frames for stroke in frame.strokes]
        self.strokes_original = strokes