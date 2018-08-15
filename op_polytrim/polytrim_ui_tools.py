'''
Created on Oct 10, 2015

@author: Patrick
'''
from ..common.utils import get_matrices
from ..common.rays import get_view_ray_data, ray_cast, ray_cast_path
from .polytrim_datastructure import InputNetwork, PolyLineKnife, InputPoint, InputSegment
from bpy_extras import view3d_utils
from mathutils import Vector
from mathutils.geometry import intersect_point_line



class Polytrim_UI_Tools():
    '''
    Functions/classes helpful with user interactions in polytrim
    '''

    class SketchHandler():
        '''
        UI tool for handling sketches made by user.
        * Intermediary between polytrim_states and PolyLineKnife
        '''
        def __init__(self, polyline):
            self.sketch = []
            self.polyline = polyline
            self.stroke_smoothing = 0.75  # 0: no smoothing. 1: no change
            self.sketch_curpos = (0, 0)

        def has_locs(self): return len(self.sketch) > 0
        has_locs = property(has_locs)

        def get_locs(self): return self.sketch

        def reset(self): self.sketch = []

        def add_loc(self, x, y):
            ''' Add's a screen location to the sketch list '''
            self.sketch.append((x,y))

        def smart_add_loc(self, x, y):
            ''' Add's a screen location to the sketch list based on smart stuff '''
            (lx, ly) = self.sketch[-1]
            ss0,ss1 = self.stroke_smoothing ,1-self.stroke_smoothing  #First data manipulation
            self.sketch += [(lx*ss0+x*ss1, ly*ss0+y*ss1)]

        def is_good(self):
            ''' Returns whether the sketch attempt should/shouldn't be added to the PolyLineKnife '''
            # checking to see if sketch functionality shouldn't happen
            if len(self.sketch) < 5 and self.polyline.ui_type == 'DENSE_POLY': return False
            return True

        def finalize(self, context, start_pnt, end_pnt=None):
            ''' takes sketch data and adds it into the datastructures '''
            if not isinstance(end_pnt, InputPoint): end_pnt = None

            prev_pnt = None
            for ind in range(0, len(self.sketch) , 5):
                if not prev_pnt:
                    if self.polyline.num_points == 1: new_pnt = self.polyline.input_net.get(0)
                    else: new_pnt = start_pnt
                else:
                    pt_screen_loc = self.sketch[ind]
                    view_vector, ray_origin, ray_target = get_view_ray_data(context, pt_screen_loc)
                    loc, no, face_ind =  ray_cast(self.polyline.source_ob,self.polyline.imx, ray_origin, ray_target, None)
                    if face_ind != -1:
                        new_pnt = InputPoint(self.polyline.mx * loc, loc, view_vector, face_ind)
                        self.polyline.input_net.add(p=new_pnt)
                if prev_pnt:
                    seg = InputSegment(prev_pnt,new_pnt)
                    self.polyline.input_net.segments.append(seg)
                    seg.pre_vis_cut(self.polyline.bme, self.polyline.bvh, self.polyline.mx, self.polyline.imx)
                prev_pnt = new_pnt
            if end_pnt:
                seg = InputSegment(prev_pnt,end_pnt)
                self.polyline.input_net.segments.append(seg)
                seg.pre_vis_cut(self.polyline.bme, self.polyline.bvh, self.polyline.mx, self.polyline.imx)

    class GrabHandler():
        '''
        UI tool for handling input point grabbing/moving made by user.
        * Intermediary between polytrim_states and PolyLineKnife
        '''
        def __init__(self, network):
            self.network = network
            self.grab_point = None

        def initiate_grab_point(self): self.grab_point = self.network.selected.duplicate()

        def move_grab_point(self,context,mouse_loc):
            '''
            finds what is near 
            '''
            region = context.region
            rv3d = context.region_data
            # ray tracing
            view_vector, ray_origin, ray_target= get_view_ray_data(context, mouse_loc)
            loc, no, face_ind = ray_cast(self.network.source_ob, self.network.imx, ray_origin, ray_target, None)
            if face_ind == -1: return

            # check to see if the start_edge or end_edge points are selected
            #Shouldn't this be checking the grab_point?  which shoudl keep seed_geom in duplicate?
            if isinstance(self.network.selected, InputPoint) and self.network.selected.seed_geom != None:

                #check the 3d mouse location vs non manifold verts
                co3d, index, dist = self.network.kd.find(self.network.mx * loc)

                #get the actual non man vert from original list
                close_bmvert = self.network.bme.verts[self.network.non_man_bmverts[index]] #stupid mapping, unreadable, terrible, fix this, because can't keep a list of actual bmverts?  why not?  #undo caching?
                close_eds = [ed for ed in close_bmvert.link_edges if not ed.is_manifold]
                loc3d_reg2D = view3d_utils.location_3d_to_region_2d

                if len(close_eds) != 2: return

                bm0 = close_eds[0].other_vert(close_bmvert)
                bm1 = close_eds[1].other_vert(close_bmvert)

                a0 = bm0.co
                b   = close_bmvert.co
                a1  = bm1.co

                inter_0, d0 = intersect_point_line(loc, a0, b)
                inter_1, d1 = intersect_point_line(loc, a1, b)

                screen_0 = loc3d_reg2D(region, rv3d, self.network.mx * inter_0)
                screen_1 = loc3d_reg2D(region, rv3d, self.network.mx * inter_1)
                screen_v = loc3d_reg2D(region, rv3d, self.network.mx * b)

                screen_d0 = (Vector((mouse_loc)) - screen_0).length
                screen_d1 = (Vector((mouse_loc)) - screen_1).length
                screen_dv = (Vector((mouse_loc)) - screen_v).length

                if 0 < d0 <= 1 and screen_d0 < 60:
                    ed, pt = close_eds[0], inter_0
                elif 0 < d1 <= 1 and screen_d1 < 60:
                    ed, pt = close_eds[1], inter_1
                elif screen_dv < 60:
                    if abs(d0) < abs(d1):
                        ed, pt = close_eds[0], b
                    else:
                        ed, pt = close_eds[1], b
                else:
                    return

                self.grab_point.set_values(self.network.mx * pt, pt, view_vector, ed.link_faces[0].index)
                self.grab_point.seed_geom = ed
            else:
                self.grab_point.set_values(self.network.mx * loc, loc, view_vector, face_ind)

        def grab_cancel(self):
            '''
            returns variables to their status before grab was initiated
            '''
            #we have not touched the oringal point!
            self.grab_point = None
            return

        def finalize(self, context):
            '''
            sets new variables based on new location
            '''
            self.network.selected.world_loc = self.grab_point.world_loc
            self.network.selected.local_loc = self.grab_point.local_loc
            self.network.selected.view = self.grab_point.view
            self.network.selected.seed_geom = self.grab_point.seed_geom
            self.network.selected.face_index = self.grab_point.face_index

            for seg in self.network.selected.segments:
                seg.pre_vis_cut(self.network.bme, self.network.bvh, self.network.mx, self.network.imx)

            self.grab_point = None

            return

    class MouseMove():
        '''
        UI tool for storing data depending on where mouse is located
        * Intermediary between polytrim_states and PolyLineKnife
        '''
        def __init__(self, input_net):
            self.mouse = None
            self.input_net = input_net

            self.hovered = self.Hovered()
            self.near = self.Near()

        def update(self, x, y):
            self.set_loc(x,y)
            view_vector, ray_origin, ray_target= get_view_ray_data(context, self.mouse)
            loc, no, face_ind = ray_cast(self.network.source_ob, self.network.imx, ray_origin, ray_target, None)
            self.hovered.set_ray_cast_data(loc,no,face_ind)

        def set_loc(self, x, y): self.mouse = (x,y)

        class Near():
            ''' Data about what the mouse is near'''
            def __init__(self, handler):
                self.handler = handler

        class Nearest():
            ''' Data values that are closest to the mouse '''
            def __init__(self, handler):
                self.handler = handler
                self.endpoint = self.nearest_endpoint()

            def nearest_endpoint(self):
                return None

        class Hovered():
            ''' Data about what the mouse is directly hovering over'''
            def __init__(self, handler):
                self.handler = handler
                self.face_local_loc = None
                self.face_normal = None
                self.face_ind = None
            
            def set_ray_cast_data(self, local_loc, normal, face_ind):
                self.face_local_loc = local_loc
                self.face_normal = normal
                self.face_ind = face_ind

    def click_add_point(self, network, context, mouse_loc):
        '''
        this will add a point into the trim line
        close the curve into a cyclic curve
        
        #Need to get smarter about closing the loop
        '''
        def none_selected(): network.selected = None # TODO: Change this weird function in function shizz
        
        view_vector, ray_origin, ray_target= get_view_ray_data(context,mouse_loc)
        loc, no, face_ind = ray_cast(network.source_ob, network.imx, ray_origin, ray_target, none_selected)
        if loc == None: return

        if network.hovered[0] and 'NON_MAN' in network.hovered[0]:
            bmed, wrld_loc = network.hovered[1] # hovered[1] is tuple (BMesh Element, location?)
            ip1 = self.closest_endpoint(wrld_loc)
            
            
            network.input_net.add(wrld_loc, network.imx * wrld_loc, view_vector, bmed.link_faces[0].index)
            network.selected = network.input_net.points[-1]
            network.selected.seed_geom = bmed

            if ip1:
                seg = InputSegment(network.selected, ip1)
                network.input_net.segments.append(seg)
                seg.pre_vis_cut(network.bme, network.bvh, network.mx, network.imx)
        
        elif (network.hovered[0] == None) and (network.snap_element == None):  #adding in a new point at end, may need to specify closest unlinked vs append and do some previs
            closest_endpoint = self.closest_endpoint(network.mx * loc)

            network.input_net.add(network.mx * loc, loc, view_vector, face_ind)
            network.selected = network.input_net.points[-1]

            if closest_endpoint:
                seg = InputSegment(closest_endpoint, network.selected)
                network.input_net.segments.append(seg)
                seg.pre_vis_cut(network.bme, network.bvh, network.mx, network.imx)

        elif network.hovered[0] == None and network.snap_element != None:  #adding in a new point at end, may need to specify closest unlinked vs append and do some previs
            
            print('This is the close loop scenario')
            closest_endpoints = self.closest_endpoints(network.snap_element.world_loc, 2)
            
            print('these are the 2 closest endpoints, one should be snap element itself')
            print(closest_endpoints)
            if closest_endpoints == None:
                #we are not quite hovered but in snap territory
                return
            
            if len(closest_endpoints) != 2:
                print('len of closest endpoints not 2')
                return
            
            
            seg = InputSegment(closest_endpoints[0], closest_endpoints[1])
            network.input_net.segments.append(seg)
            seg.pre_vis_cut(network.bme, network.bvh, network.mx, network.imx)
            
        elif network.hovered[0] == 'POINT':
            network.selected = network.hovered[1]

        elif network.hovered[0] == 'EDGE':  #TODO, actually make InputSegment as hovered
            
            #this looks like a TOOLs kind of operation
            point = InputPoint(network.mx * loc, loc, view_vector, face_ind)
            old_seg = network.hovered[1]
            new_seg0, new_seg1 = old_seg.insert_point(point)
            new_seg0.pre_vis_cut(network.bme, network.bvh, network.mx, network.imx)
            new_seg1.pre_vis_cut(network.bme, network.bvh, network.mx, network.imx)
            network.input_net.segments += [new_seg0, new_seg1]
            network.input_net.points.append(point)
            network.input_net.segments.remove(old_seg)
            network.selected = point

    def click_delete_point(self, network, mode = 'mouse'):
        '''
        removes point from the trim line
        '''
        if mode == 'mouse':
            if network.hovered[0] != 'POINT': 
                print('hovered is not a point')
                print(network.hovered[0])
                return

            network.input_net.remove(network.hovered[1])

            if not network.hovered[1].is_endpoint:
                last_seg1, last_seg2 = network.hovered[1].segments
                ip1 = last_seg1.other_point(network.hovered[1])
                ip2 = last_seg2.other_point(network.hovered[1])
                new_seg = InputSegment(ip1, ip2)
                network.input_net.segments.append(new_seg)
                new_seg.pre_vis_cut(network.bme, network.bvh, network.mx, network.imx)

            if network.input_net.is_empty or network.selected == network.hovered[1]:
                network.selected = None

        else: #hard delete with x key
            if not network.selected: return
            network.input_net.remove(network.selected, disconnect= True)

        #if network.ed_cross_map.is_used:
        #    network.make_cut()

    def closest_endpoint(self, pt3d):
        def dist3d(point):
            return (point.world_loc - pt3d).length

        endpoints = [ip for ip in self.input_net.input_net.points if ip.is_endpoint] 
        if len(endpoints) == 0: return None

        return min(endpoints, key = dist3d)

    def closest_endpoints(self, pt3d, n_points):
        #in our application, at most there will be 100 endpoints?
        #no need for accel structure here
        n_points = max(0, n_points)

        endpoints = [ip for ip in self.input_net.input_net.points if ip.is_endpoint] #TODO self.endpoints?

        if len(endpoints) == 0: return None
        n_points = min(n_points, len(endpoints))


        def dist3d(point):
            return (point.world_loc - pt3d).length

        endpoints.sort(key = dist3d)

        return endpoints[0:n_points+1]

    def ui_text_update(self):
        '''
        updates the text at the bottom of the viewport depending on certain conditions
        '''
        context = self.context
        if self.input_net.bad_segments:
            context.area.header_text_set("Fix Bad segments by moving control points.")
        elif self.input_net.ed_cross_map.is_used:
            context.area.header_text_set("When cut is satisfactory, press 'S' then 'LeftMouse' in region to cut")
        elif self.input_net.hovered[0] == 'POINT':
            if self.input_net.hovered[1] == 0:
                context.area.header_text_set("For origin point, left click to toggle cyclic")
            else:
                context.area.header_text_set("Right click to delete point. Hold left click and drag to make a sketch")
        else:
            self.set_ui_text_main()

    def set_ui_text_main(self):
        ''' sets the viewports text during general creation of line '''
        self.info_label.set_markdown("Left click to place cut points on the mesh, then press 'C' to preview the cut")
        #self.context.area.header_text_set()

    def hover(self, select_radius = 12, snap_radius = 24): #TDOD, these radii are pixels? Shoudl they be settings?
        '''
        finds points/edges/etc that are near ,mouse
         * hovering happens in mixed 3d and screen space, 20 pixels thresh for points, 30 for edges 40 for non_man
        '''

        # TODO: update self.hover to use Accel2D?
        polyline = self.input_net
        mouse = self.actions.mouse
        context = self.context

        mx, imx = get_matrices(polyline.source_ob)
        loc3d_reg2D = view3d_utils.location_3d_to_region_2d
        # ray tracing
        view_vector, ray_origin, ray_target = get_view_ray_data(context, mouse)
        loc, no, face_ind = ray_cast(polyline.source_ob, imx, ray_origin, ray_target, None)

        polyline.snap_element = None
        polyline.connect_element = None
        
        if polyline.input_net.is_empty:
            polyline.hovered = [None, -1]
            self.hover_non_man()
            return
        if face_ind == -1: polyline.closest_ep = None
        else: polyline.closest_ep = self.closest_endpoint(mx * loc)

        #find length between vertex and mouse
        def dist(v):
            if v == None:
                print('v off screen')
                return 100000000
            diff = v - Vector(mouse)
            return diff.length

        #find length between 2 3d points
        def dist3d(v3):
            if v3 == None:
                return 100000000
            delt = v3 - polyline.source_ob.matrix_world * loc
            return delt.length

        #closest_3d_loc = min(polyline.input_net.world_locs, key = dist3d)
        closest_ip = min(polyline.input_net, key = lambda x: dist3d(x.world_loc))
        pixel_dist = dist(loc3d_reg2D(context.region, context.space_data.region_3d, closest_ip.world_loc))

        if pixel_dist  < select_radius:
            print('point is hovered')
            print(pixel_dist)
            polyline.hovered = ['POINT', closest_ip]  #TODO, probably just store the actual InputPoint as the 2nd value?
            polyline.snap_element = None
            return

        elif pixel_dist >= select_radius and pixel_dist < snap_radius:
            print('point is within snap radius')
            print(pixel_dist)
            if closest_ip.is_endpoint:
                polyline.snap_element = closest_ip

                print('This is the close loop scenario')
                closest_endpoints = self.closest_endpoints(polyline.snap_element.world_loc, 2)

                print('these are the 2 closest endpoints, one should be snap element itself')
                print(closest_endpoints)
                if closest_endpoints == None:
                    #we are not quite hovered but in snap territory
                    return

                if len(closest_endpoints) != 2:
                    print('len of closest endpoints not 2')
                    return

                polyline.connect_element = closest_endpoints[1]

            return


        if polyline.num_points == 1:  #why did we do this? Oh because there are no segments.
            polyline.hovered = [None, -1]
            polyline.snap_element = None
            return

        ##Check distance between ray_cast point, and segments
        distance_map = {}
        for seg in polyline.input_net.segments:  #TODO, may need to decide some better naming and better heirarchy

            close_loc, close_d = seg.closes_point_3d_linear(polyline.source_ob.matrix_world * loc)
            if close_loc  == None:
                distance_map[seg] = 10000000
                continue

            distance_map[seg] = close_d

        if polyline.input_net.segments:
            closest_seg = min(polyline.input_net.segments, key = lambda x: distance_map[x])

            a = loc3d_reg2D(context.region, context.space_data.region_3d, closest_seg.ip0.world_loc)
            b = loc3d_reg2D(context.region, context.space_data.region_3d, closest_seg.ip1.world_loc)

            if a and b:  #if points are not on the screen, a or b will be None
                intersect = intersect_point_line(Vector(mouse).to_3d(), a.to_3d(),b.to_3d())
                dist = (intersect[0].to_2d() - Vector(mouse)).length_squared
                bound = intersect[1]
                if (dist < select_radius**2) and (bound < 1) and (bound > 0):
                    polyline.hovered = ['EDGE', closest_seg]
                    return

        ## Multiple points, but not hovering over edge or point.
        polyline.hovered = [None, -1]

        self.hover_non_man()  #todo, optimize because double ray cast per mouse move!

    def hover_non_man(self):
        '''
        finds nonman edges and verts nearby to cursor location
        '''
        polyline = self.input_net
        mouse = self.actions.mouse
        context = self.context

        region = context.region
        rv3d = context.region_data
        mx, imx = get_matrices(polyline.source_ob)
        # ray casting
        view_vector, ray_origin, ray_target= get_view_ray_data(context, mouse)
        loc, no, face_ind = ray_cast(polyline.source_ob, imx, ray_origin, ray_target, None)

        mouse = Vector(mouse)
        loc3d_reg2D = view3d_utils.location_3d_to_region_2d
        if len(polyline.non_man_points):
            co3d, index, dist = polyline.kd.find(mx * loc)

            #get the actual non man vert from original list
            close_bmvert = polyline.bme.verts[polyline.non_man_bmverts[index]] #stupid mapping, unreadable, terrible, fix this, because can't keep a list of actual bmverts
            close_eds = [ed for ed in close_bmvert.link_edges if not ed.is_manifold]
            if len(close_eds) == 2:
                bm0 = close_eds[0].other_vert(close_bmvert)
                bm1 = close_eds[1].other_vert(close_bmvert)

                a0 = bm0.co
                b   = close_bmvert.co
                a1  = bm1.co

                inter_0, d0 = intersect_point_line(loc, a0, b)
                inter_1, d1 = intersect_point_line(loc, a1, b)

                screen_0 = loc3d_reg2D(region, rv3d, mx * inter_0)
                screen_1 = loc3d_reg2D(region, rv3d, mx * inter_1)
                screen_v = loc3d_reg2D(region, rv3d, mx * b)

                if screen_0 and screen_1 and screen_v:
                    screen_d0 = (mouse - screen_0).length
                    screen_d1 = (mouse - screen_1).length
                    screen_dv = (mouse - screen_v).length

                    #TODO, decid how to handle when very very close to vertcies
                    if 0 < d0 <= 1 and screen_d0 < 20:
                        polyline.hovered = ['NON_MAN_ED', (close_eds[0], mx*inter_0)]
                        return
                    elif 0 < d1 <= 1 and screen_d1 < 20:
                        polyline.hovered = ['NON_MAN_ED', (close_eds[1], mx*inter_1)]
                        return
                    
                    #For now, not able to split a vert on the edge of the mesh, only edges
                    #elif screen_dv < 20:
                    #    if abs(d0) < abs(d1):
                    #        polyline.hovered = ['NON_MAN_VERT', (close_eds[0], mx*b)]
                    #        return
                    #    else:
                    #        polyline.hovered = ['NON_MAN_VERT', (close_eds[1], mx*b)]
                    #        return
