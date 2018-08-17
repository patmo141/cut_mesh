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

    class SketchManager():
        '''
        UI tool for managing sketches made by user.
        * Intermediary between polytrim_states and Network
        '''
        def __init__(self, input_net):
            self.sketch = []
            self.input_net = input_net
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
            ''' Returns whether the sketch attempt should/shouldn't be added to the InputNetwork '''
            # checking to see if sketch functionality shouldn't happen
            if len(self.sketch) < 5 and self.input_net.ui_type == 'DENSE_POLY': return False
            return True

        def finalize(self, context, start_pnt, end_pnt=None):
            ''' takes sketch data and adds it into the datastructures '''
            if not isinstance(end_pnt, InputPoint): end_pnt = None

            prev_pnt = None
            for ind in range(0, len(self.sketch) , 5):
                if not prev_pnt:
                    if self.input_net.num_points == 1: new_pnt = self.input_net.points[0]
                    else: new_pnt = start_pnt
                else:
                    pt_screen_loc = self.sketch[ind]  #in screen space
                    view_vector, ray_origin, ray_target = get_view_ray_data(context, pt_screen_loc)  #a location and direction in WORLD coordinates
                    loc, no, face_ind =  ray_cast(self.input_net.source_ob,self.input_net.imx, ray_origin, ray_target, None)  #intersects that ray with the geometry
                    if face_ind != -1:
                        new_pnt = self.input_net.create_point(self.input_net.mx * loc, loc, view_vector, face_ind)
                if prev_pnt:
                    seg = InputSegment(prev_pnt,new_pnt)
                    self.input_net.segments.append(seg)
                    seg.make_path(self.input_net.bme, self.input_net.bvh, self.input_net.mx, self.input_net.imx)
                prev_pnt = new_pnt
            if end_pnt:
                seg = InputSegment(prev_pnt,end_pnt)
                self.input_net.segments.append(seg)
                seg.make_path(self.input_net.bme, self.input_net.bvh, self.input_net.mx, self.input_net.imx)

    ## TODO: Hovering functions are happening in here, bring them out.
    class GrabManager():
        '''
        UI tool for managing input point grabbing/moving made by user.
        * Intermediary between polytrim_states and Network
        '''
        def __init__(self, input_net, net_ui_manager):
            self.net_ui_manager = net_ui_manager
            self.input_net = input_net
            self.grab_point = None

        def initiate_grab_point(self):
            self.grab_point = self.net_ui_manager.selected.duplicate()
            print("GRAB",self.grab_point)

        def move_grab_point(self,context,mouse_loc):
            '''
            finds what is near
            '''
            region = context.region
            rv3d = context.region_data
            # ray tracing
            view_vector, ray_origin, ray_target= get_view_ray_data(context, mouse_loc)
            loc, no, face_ind = ray_cast(self.input_net.source_ob, self.input_net.imx, ray_origin, ray_target, None)
            if face_ind == -1: return

            #Shouldn't this be checking the grab_point?  which shoudl keep seed_geom in duplicate?
            if isinstance(self.net_ui_manager.selected, InputPoint) and self.net_ui_manager.selected.seed_geom != None:

                #check the 3d mouse location vs non manifold verts
                co3d, index, dist = self.input_net.kd.find(self.input_net.mx * loc)

                #get the actual non man vert from original list
                close_bmvert = self.input_net.bme.verts[self.input_net.non_man_bmverts[index]] #stupid mapping, unreadable, terrible, fix this, because can't keep a list of actual bmverts?  why not?  #undo caching?
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

                screen_0 = loc3d_reg2D(region, rv3d, self.input_net.mx * inter_0)
                screen_1 = loc3d_reg2D(region, rv3d, self.input_net.mx * inter_1)
                screen_v = loc3d_reg2D(region, rv3d, self.input_net.mx * b)

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

                self.grab_point.set_values(self.input_net.mx * pt, pt, view_vector, ed.link_faces[0].index)
                self.grab_point.seed_geom = ed
            else:
                self.grab_point.set_values(self.input_net.mx * loc, loc, view_vector, face_ind)

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
            self.net_ui_manager.selected.world_loc = self.grab_point.world_loc
            self.net_ui_manager.selected.local_loc = self.grab_point.local_loc
            self.net_ui_manager.selected.view = self.grab_point.view
            self.net_ui_manager.selected.seed_geom = self.grab_point.seed_geom
            self.net_ui_manager.selected.face_index = self.grab_point.face_index

            for seg in self.net_ui_manager.selected.link_segments:
                seg.make_path(self.input_net.bme, self.input_net.bvh, self.input_net.mx, self.input_net.imx)

            self.grab_point = None

            return

    ## TODO: Right now it's only storing UI elements,
    class NetworkUIManager():
        '''
        UI tool for storing data depending on where mouse is located
        * Intermediary between polytrim_states and PolyLineKnife
        '''
        def __init__(self, context, bme, bvh, mx, imx, input_net):
            self.context = context
            self.ob = context.object
            self.bme = bme
            self.bvh = bvh
            self.mx = mx
            self.imx = imx

            self.input_net = input_net

            self.mouse_loc = None

            self.hovered2 = {}
            self.selected = -1
            self.snap_element = None
            self.connect_element = None
            self.closest_ep = None
            self.hovered = [None, -1]


        def update(self, context, mouse_loc):
            self.mouse_loc = mouse_loc
            self.ray_cast_mouse()

            self.nearest_non_man_loc()

        def ray_cast_mouse(self):
            view_vector, ray_origin, ray_target= get_view_ray_data(self.context, self.mouse_loc)
            loc, no, face_ind = ray_cast(self.ob, self.imx, ray_origin, ray_target, None)
            if face_ind == -1: self.hovered = {}
            else:
                self.hovered2["local_loc"] = loc
                self.hovered2["normal"] = no
                self.hovered2["face_ind"] = face_ind

        def nearest_non_man_loc(self):
            print('')

        def nearest_endpoint(self, mouse_3d_loc):
            def dist3d(ip):
                return (ip.world_loc - mouse_3d_loc).length

            endpoints = [ip for ip in self.input_net.points if ip.is_endpoint]
            if len(endpoints) == 0: return None

            return min(endpoints, key = dist3d)

    # TODO: Clean this up
    def click_add_point(self, context, mouse_loc):
        '''
        this will add a point into the trim line
        close the curve into a cyclic curve
        
        #Need to get smarter about closing the loop
        '''
        def none_selected(): self.net_ui_manager.selected = None # TODO: Change this weird function in function shizz
        
        view_vector, ray_origin, ray_target= get_view_ray_data(context,mouse_loc)
        loc, no, face_ind = ray_cast(self.input_net.source_ob, self.input_net.imx, ray_origin, ray_target, none_selected)
        if loc == None: return

        if self.net_ui_manager.hovered[0] and 'NON_MAN' in self.net_ui_manager.hovered[0]:
            bmed, wrld_loc = self.net_ui_manager.hovered[1] # hovered[1] is tuple (BMesh Element, location?)
            ip1 = self.closest_endpoint(wrld_loc)

            self.net_ui_manager.selected = self.input_net.create_point(wrld_loc, self.input_net.imx * wrld_loc, view_vector, bmed.link_faces[0].index)
            self.net_ui_manager.selected.seed_geom = bmed

            if ip1:
                seg = InputSegment(self.net_ui_manager.selected, ip1)
                self.input_net.segments.append(seg)
                seg.make_path(self.input_net.bme, self.input_net.bvh, self.input_net.mx, self.input_net.imx)
        
        elif (self.net_ui_manager.hovered[0] == None) and (self.net_ui_manager.snap_element == None):  #adding in a new point at end, may need to specify closest unlinked vs append and do some previs
            closest_endpoint = self.closest_endpoint(self.input_net.mx * loc)
            self.net_ui_manager.selected = self.input_net.create_point(self.input_net.mx * loc, loc, view_vector, face_ind)
            if closest_endpoint:
                self.input_net.connect_points(self.net_ui_manager.selected, closest_endpoint)

        elif self.net_ui_manager.hovered[0] == None and self.net_ui_manager.snap_element != None:  #adding in a new point at end, may need to specify closest unlinked vs append and do some previs

            closest_endpoints = self.closest_endpoints(self.net_ui_manager.snap_element.world_loc, 2)

            if closest_endpoints == None:
                #we are not quite hovered but in snap territory
                return

            if len(closest_endpoints) != 2:
                print('len of closest endpoints not 2')
                return

            seg = InputSegment(closest_endpoints[0], closest_endpoints[1])
            self.input_net.segments.append(seg)
            seg.make_path(self.input_net.bme, self.input_net.bvh, self.input_net.mx, self.input_net.imx)

        elif self.net_ui_manager.hovered[0] == 'POINT':
            self.net_ui_manager.selected = self.net_ui_manager.hovered[1]

        elif self.net_ui_manager.hovered[0] == 'EDGE':  #TODO, actually make InputSegment as hovered
            point = self.input_net.create_point(self.input_net.mx * loc, loc, view_vector, face_ind)
            old_seg = self.net_ui_manager.hovered[1]
            self.input_net.insert_point(point, old_seg)
            self.net_ui_manager.selected = point

    # TODO: Clean this up
    def click_delete_point(self, mode = 'mouse'):
        '''
        removes point from the trim line
        '''
        if mode == 'mouse':
            if self.net_ui_manager.hovered[0] != 'POINT':
                return

            self.input_net.remove_point(self.net_ui_manager.hovered[1])

            if not self.net_ui_manager.hovered[1].is_endpoint:
                last_seg1, last_seg2 = self.net_ui_manager.hovered[1].link_segments
                ip1 = last_seg1.other_point(self.net_ui_manager.hovered[1])
                ip2 = last_seg2.other_point(self.net_ui_manager.hovered[1])
                new_seg = InputSegment(ip1, ip2)
                self.input_net.segments.append(new_seg)
                new_seg.make_path(self.input_net.bme, self.input_net.bvh, self.input_net.mx, self.input_net.imx)

            if self.input_net.is_empty or self.net_ui_manager.selected == self.net_ui_manager.hovered[1]:
                self.net_ui_manager.selected = None

        else: #hard delete with x key
            if not self.net_ui_manager.selected: return
            self.input_net.remove(self.net_ui_manager.selected, disconnect= True)

    # TODO: Make this a NetworkUIManager function
    def closest_endpoint(self, pt3d):
        def dist3d(point):
            return (point.world_loc - pt3d).length

        endpoints = [ip for ip in self.input_net.points if ip.is_endpoint]
        if len(endpoints) == 0: return None

        return min(endpoints, key = dist3d)

    # TODO: Also NetworkUIManager function
    def closest_endpoints(self, pt3d, n_points):
        #in our application, at most there will be 100 endpoints?
        #no need for accel structure here
        n_points = max(0, n_points)

        endpoints = [ip for ip in self.input_net.points if ip.is_endpoint] #TODO self.endpoints?

        if len(endpoints) == 0: return None
        n_points = min(n_points, len(endpoints))


        def dist3d(point):
            return (point.world_loc - pt3d).length

        endpoints.sort(key = dist3d)

        return endpoints[0:n_points+1]

    # TODO: NetworkUIManager??
    def closest_point_3d_linear(self, seg, pt3d):
        '''
        will return the closest point on a straigh line segment
        drawn between the two input points
       
        If the 3D point is not within the infinite cylinder defined
        by 2 infinite disks placed at each input point and orthogonal
        to the vector between them, will return None
       
       
       
        A_pt3d              B_pt3d
          .                    .
          |                    |              
          |                    |              
          |                    |               
          |       ip0._________x_________.ip1   
         
         
         A_pt3d will return None, None.  B_pt3d will return 3d location at orthogonal intersection and the distance
         
         else, will return a tupple (location of intersection, %along line from ip0 to ip1
         
         happens in the world coordinates
       
        '''


        intersect3d = intersect_point_line(pt3d, seg.ip0.world_loc, seg.ip1.world_loc)

        if intersect3d == None: return (None, None)

        dist3d = (intersect3d[0] - pt3d).length

        if  (intersect3d[1] < 1) and (intersect3d[1] > 0):
            return (intersect3d[0], dist3d)

        return (None, None)

    # XXX: Fine for now, but will likely be irrelevant in future
    def ui_text_update(self):
        '''
        updates the text at the bottom of the viewport depending on certain conditions
        '''
        context = self.context
        if self.net_ui_manager.hovered[0] == 'POINT':
            if self.net_ui_manager.hovered[1] == 0:
                context.area.header_text_set("For origin point, left click to toggle cyclic")
            else:
                context.area.header_text_set("Right click to delete point. Hold left click and drag to make a sketch")
        else:
            self.set_ui_text_main()

    # XXX: Fine for now, but will likely be irrelevant in future
    def set_ui_text_main(self):
        ''' sets the viewports text during general creation of line '''
        self.info_label.set_markdown("Left click to place cut points on the mesh, then press 'C' to preview the cut")
        #self.context.area.header_text_set()

    # XXX: NetworkUIManager
    def hover(self, select_radius = 12, snap_radius = 24): #TDOD, these radii are pixels? Shoudl they be settings?
        '''
        finds points/edges/etc that are near ,mouse
         * hovering happens in mixed 3d and screen space, 20 pixels thresh for points, 30 for edges 40 for non_man
        '''

        # TODO: update self.hover to use Accel2D?
        mouse = self.actions.mouse
        context = self.context

        mx, imx = get_matrices(self.input_net.source_ob)
        loc3d_reg2D = view3d_utils.location_3d_to_region_2d
        # ray tracing
        view_vector, ray_origin, ray_target = get_view_ray_data(context, mouse)
        loc, no, face_ind = ray_cast(self.input_net.source_ob, imx, ray_origin, ray_target, None)

        self.net_ui_manager.snap_element = None
        self.net_ui_manager.connect_element = None

        if self.input_net.is_empty:
            self.net_ui_manager.hovered = [None, -1]
            self.hover_non_man()
            return
        if face_ind == -1: self.net_ui_manager.closest_ep = None
        else: self.net_ui_manager.closest_ep = self.closest_endpoint(mx * loc)

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
            delt = v3 - self.input_net.source_ob.matrix_world * loc
            return delt.length

        #closest_3d_loc = min(self.input_net.world_locs, key = dist3d)
        closest_ip = min(self.input_net.points, key = lambda x: dist3d(x.world_loc))
        pixel_dist = dist(loc3d_reg2D(context.region, context.space_data.region_3d, closest_ip.world_loc))

        if pixel_dist  < select_radius:
            print('point is hovered')
            print(pixel_dist)
            self.net_ui_manager.hovered = ['POINT', closest_ip]  #TODO, probably just store the actual InputPoint as the 2nd value?
            self.net_ui_manager.snap_element = None
            return

        elif pixel_dist >= select_radius and pixel_dist < snap_radius:
            print('point is within snap radius')
            print(pixel_dist)
            if closest_ip.is_endpoint:
                self.net_ui_manager.snap_element = closest_ip

                print('This is the close loop scenario')
                closest_endpoints = self.closest_endpoints(self.net_ui_manager.snap_element.world_loc, 2)

                print('these are the 2 closest endpoints, one should be snap element itself')
                print(closest_endpoints)
                if closest_endpoints == None:
                    #we are not quite hovered but in snap territory
                    return

                if len(closest_endpoints) != 2:
                    print('len of closest endpoints not 2')
                    return

                self.net_ui_manager.connect_element = closest_endpoints[1]

            return


        if self.input_net.num_points == 1:  #why did we do this? Oh because there are no segments.
            self.net_ui_manager.hovered = [None, -1]
            self.net_ui_manager.snap_element = None
            return

        ##Check distance between ray_cast point, and segments
        distance_map = {}
        for seg in self.input_net.segments:  #TODO, may need to decide some better naming and better heirarchy
  
            close_loc, close_d = self.closest_point_3d_linear(seg, self.input_net.source_ob.matrix_world * loc)
            if close_loc  == None:
                distance_map[seg] = 10000000
                continue

            distance_map[seg] = close_d

        if self.input_net.segments:
            closest_seg = min(self.input_net.segments, key = lambda x: distance_map[x])

            a = loc3d_reg2D(context.region, context.space_data.region_3d, closest_seg.ip0.world_loc)
            b = loc3d_reg2D(context.region, context.space_data.region_3d, closest_seg.ip1.world_loc)

            if a and b:  #if points are not on the screen, a or b will be None
                intersect = intersect_point_line(Vector(mouse).to_3d(), a.to_3d(),b.to_3d())
                dist = (intersect[0].to_2d() - Vector(mouse)).length_squared
                bound = intersect[1]
                if (dist < select_radius**2) and (bound < 1) and (bound > 0):
                    self.net_ui_manager.hovered = ['EDGE', closest_seg]
                    return

        ## Multiple points, but not hovering over edge or point.
        self.net_ui_manager.hovered = [None, -1]

        self.hover_non_man()  #todo, optimize because double ray cast per mouse move!

    # XXX: NetworkUIManager
    def hover_non_man(self):
        '''
        finds nonman edges and verts nearby to cursor location
        '''
        mouse = self.actions.mouse
        context = self.context

        region = context.region
        rv3d = context.region_data
        mx, imx = get_matrices(self.input_net.source_ob)
        # ray casting
        view_vector, ray_origin, ray_target= get_view_ray_data(context, mouse)
        loc, no, face_ind = ray_cast(self.input_net.source_ob, imx, ray_origin, ray_target, None)

        mouse = Vector(mouse)
        loc3d_reg2D = view3d_utils.location_3d_to_region_2d
        if len(self.plk.non_man_points):
            co3d, index, dist = self.plk.kd.find(mx * loc)

            #get the actual non man vert from original list
            close_bmvert = self.input_net.bme.verts[self.plk.non_man_bmverts[index]] #stupid mapping, unreadable, terrible, fix this, because can't keep a list of actual bmverts
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
                        self.net_ui_manager.hovered = ['NON_MAN_ED', (close_eds[0], mx*inter_0)]
                        return
                    elif 0 < d1 <= 1 and screen_d1 < 20:
                        self.net_ui_manager.hovered = ['NON_MAN_ED', (close_eds[1], mx*inter_1)]
                        return


    ### XXX: Puth these in their own class maybe?
    def interpolate_input_point_pair(self, p0, p1, factor):
        '''
        will return a linear interpolation of this point with other
        needs to be at this level, because snapping to the source object is critical
        
        '''
        assert factor >= 0.0
        assert factor <= 1.0
        
        new_pt = p0.duplicate()
        
        new_pt.set_world_loc(factor * p0.world_loc + (1-factor)*p1.world_loc)
        new_pt.set_local_loc(factor * p0.local_loc + (1-factor)*p1.local_loc)
        new_pt.view = factor * p0.view + (1-factor) * p1.view
        new_pt.view.normalize()
        
        #need to snap it and find face index
        loc, no, ind, d = self.input_net.bvh.find_nearest(new_pt.local_loc)
        
        #view stays the same
        new_pt.set_face_ind(ind)
        new_pt.set_local_loc(loc)
        new_pt.set_world_loc(self.input_net.mx * loc)
    
        return new_pt

    def linear_re_tesselate_segment(self, ip_start, ip_end, res):
        '''
        ip_start - InputPoint
        ip_end = InputPoint
        res - Float (target distance step between points)
        
        
        re tesesselates all segments between ip_start and ip_end
        
        will preserve the original input points, and only add new input points
        between them as necessary
        
        It is important that ip_start to ip_end indicates the direction desired
        for the segment to be re_tesselated.
        
        for example if ip_start is at index 5 and ip_end is at index 2.
        Input points 5,6,7...N, 0,1 2. will be retesselated
        
        However if ip_start is at index 2 and ip_end is at index 5
        InputPoints 2,3,4,5 will be re_tesslated
        
        re_teseselate(ip5, ip2) will not be same as re_tesslate(ip2, ip5)
        
        '''
        assert ip_start in self.input_net.points
        assert ip_end in self.input_net.points
        
        ind_start = self.input_net.points.index(ip_start)
        ind_end = self.input_net.points.index(ip_end)

        if ind_start > ind_end:
            points = self.input_net.points[ind_start:] + self.input_net.points[:ind_end]

        elif ind_start > ind_end:
            ind_start, ind_end = ind_end, ind_start
            points = self.input_net.points[ind_start:ind_end+1]  #need to get the last point
        else:
            points = self.input_net.points[ind_start:ind_end+1]  #need to get the last point
        
        
        new_points = []
        for i in range(0, len(points) - 1):
            L = (points[i+1].world_loc - points[i].world_loc).length
            n_steps = math.floor(L/res)
            
            if n_steps == 0: #don't loose points at closer resolution
                new_points += [points[i].duplicate()]
                
            for n in range(n_steps):
                factor = n/n_steps
                new_points += [self.interpolate_input_point_pair(points[i+1], points[i], factor)]
                
        new_points += [points[-1]]  #get the final point on there
        
        
        if ind_start > ind_end:  
            self.input_net.points = new_points + self.input_net.points[ind_end:ind_start]  #self.input_net.points[ind_start:] + self.input_net.points[:ind_end]
        
        elif ind_start < ind_end:
            
            self.input_net.points = self.input_net.points[0:ind_start] + new_points + self.input_net.points[ind_end:]
                
        else:
            self.input_net.points = self.input_net.points[0:ind_start] + new_points + self.input_net.points[ind_end:]
        
        self.net_ui_manager.selected = None   