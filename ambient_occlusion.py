'''
Created on Jun 19, 2018
@author: Patrick

I first read this method for mesh/dental mesh segmentation in the graduate
thesis of David A. Mouritsen at University of Alabam

http://www.mhsl.uab.edu/dt/2013/Mouritsen_uab_0005M_10978.pdf

Using Ambient Occlusion as the 'feature' on which to seed the initial selection
is original work as far as I can tell as opposed to curvature or other salience
values.

The idea of using topological operators was described in this 2000 paper by
Christian Rossl, Leif Kobbelt, Hans-Peter Seidel
Max-Planck-Institut fur Informatik, Computer Graphics Group
https://www.aaai.org/Papers/Symposia/Spring/2000/SS-00-04/SS00-04-012.pdf

I used the following resources to help me adapt the methods to the Blender
BMesh data structure
http://www.inf.u-szeged.hu/~palagyi/skel/skel.html
'''
#bake ambient occlusion

import bpy
import bmesh

def bake_ambient_object(context, ob):

    current_scene = context.scene
    
    #make a dummy scene, AO bakes all objects
    #need a lonely scene
    if "AO" not in bpy.data.scenes:
        scene = bpy.data.scenes.new("AO")
    else:
        scene = bpy.data.scenes.get("AO")
        
        for ob in scene.objects:
            scene.objects.unlink(ob)
            
    scene.objects.link(ob)
        
    context.screen.scene = scene
    
    if "AO" not in bpy.data.worlds:
        
        old_worlds = [w for w in bpy.data.worlds]
        bpy.ops.world.new()
        
        new_worlds = [w for w in bpy.data.worlds if w not in old_worlds]
        world = new_worlds[0]
        world.name = "AO"
        world = bpy.data.worlds["AO"]
    else:
        world = bpy.data.worlds.get("AO")
        
    
    
    #TODO, get theses values from the scene AO setings that shows the AO preview
    scene.world = world
    
    world.light_settings.use_ambient_occlusion = True
    world.light_settings.ao_factor = 5.0
    world.light_settings.ao_blend_type = 'MULTIPLY'
    
    world.light_settings.samples = 10
    world.light_settings.use_falloff = True
    world.light_settings.falloff_strength = .5
    world.light_settings.distance = .5
    
    world.light_settings.use_environment_light = True
    world.light_settings.environment_energy = 1.0

    
    if "AO" not in ob.data.vertex_colors:
        vcol = ob.data.vertex_colors.new(name = "AO")
    else:
        vcol = ob.data.vertex_colors.get("AO")
        
    
    if "AO" not in bpy.data.materials:
        mat = bpy.data.materials.new("AO")
        mat.use_shadeless = True
        mat.use_vertex_color_paint = True
    else:
        mat = bpy.data.materials.get("AO")
        mat.use_shadeless = True
        mat.use_vertex_color_paint = True
        
        
        
        
    if "AO" not in ob.data.materials:
        ob.data.materials.append(mat)
        
    ob.material_slots[0].material = mat
    
    scene.render.bake_type = "AO"
    scene.render.use_bake_to_vertex_color = True
    scene.render.use_bake_normalize = True 
    
    scene.objects.active = ob
    bpy.ops.object.bake_image()
    
    #put the active scene back
    context.screen.scene = scene
    
def pick_verts_by_AO_color(obj, threshold = .95):
    """Paints a single vertex where vert is the index of the vertex
    and color is a tuple with the RGB values."""

    mesh = obj.data 
    
    vcol_layer = mesh.vertex_colors.get("AO")
    if vcol_layer == None:
        return
    
    to_select = []
    
    for poly in mesh.polygons:
        for loop_index in poly.loop_indices:
            loop_vert_index = mesh.loops[loop_index].vertex_index
            col = vcol_layer.data[loop_index].color
            if any([col[0] < threshold, col[1] < threshold, col[2] < threshold]):
                to_select.append(mesh.vertices[loop_vert_index])
    
    for v in mesh.vertices:
        v.select = False
    for v in to_select:
        v.select = True
        
        
#https://blender.stackexchange.com/questions/92406/circular-order-of-edges-around-vertex
# Return edges around param vertex in counter-clockwise order
def connectedEdgesFromVertex_CCW(vertex):

    vertex.link_edges.index_update()
    first_edge = vertex.link_edges[0]

    edges_CCW_order = []

    edge = first_edge
    while edge not in edges_CCW_order:
        edges_CCW_order.append(edge)
        edge = rightEdgeForEdgeRegardToVertex(edge, vertex)

    return edges_CCW_order

# Return the right edge of param edge regard to param vertex
def rightEdgeForEdgeRegardToVertex(edge, vertex):
    right_loop = None

    for loop in edge.link_loops:
        if loop.vert == vertex:
            right_loop = loop
            break
    return loop.link_loop_prev.edge



def skeletonize_selection(bme, allow_tails = False):

    '''
    bme  - BMesh with a selection of verts
    allow_tails - Bool.  If set to True, all peninsulas will be removed.
    '''
    selected_verts = [v for v in bme.verts if v.select]
    
    #store the sorted 1 ring neighbors
    print('starting neighbrhood storage')
    disk_dict = {}
    for v in selected_verts:
        disk_dict[v] = [ed.other_vert(v) for ed in connectedEdgesFromVertex_CCW(v)]
    
    print('finished neighbrhood storage')
    
    skeleton = set(selected_verts)
    
    centers = set()  #centers, not sure we need this
    complex = set()  #all complex vertices, which shall not be removed
    to_scratch = set()  #the verts to be removed at the end of an iteration
    border = set() #all perimeter vertices
    
    
    def complexity(v):
        disk = disk_dict[v]
        changes = 0
        current = disk[-1] in skeleton
        
        for v_disk in disk:
            if (v_disk in skeleton) != current:
                changes += 1
                current = v_disk in skeleton     
        return changes
    
    def is_boundary(v):
        return not all([ed.other_vert(v) in skeleton for ed in v.link_edges])
        
        
    #cache complexity at first pass
    
    print('caching complexity')
    complexity_dict = {}
    for v in skeleton:
        if is_boundary(v):
            border.add(v)
            
            K = complexity(v)
            complexity_dict[v] = K
            if K >= 4:
                complex.add(v)
    
            
    print('finished caching complexity')
    print("There are %i complex verts" % len(complex))
    print("there are %i boundary verts" % len(border))
    
    border.difference_update(complex)
    
    print("there are %i boundary verts" % len(border))
    
    changed = True
    iterations = 0
    
    new_border = set()
    
    L = len(skeleton)  #we are going to go vert by vert and pluck it off and update locally the complexity as we go.
    
    
    while iterations < L and ((len(border) != 0) or (len(new_border) != 0))and changed == True:     
        
        iterations += 1
        v = border.pop()
        skeleton.remove(v)
        
        neighbors = disk_dict[v]
        
        for v_disk in neighbors:
            if v_disk not in skeleton: continue
        
            
            if len([ed.other_vert(v_disk) in skeleton for ed in v_disk.link_edges]) == 2:
                print('found a tail')
                if v_disk in border:
                    border.remove(v_disk)
                if v_disk in new_border:
                    new_border.remove(v_disk)
                changed = True
    
            
            if  allow_tails and v_disk in complex: continue  #complex verts are always complex
            
            K = complexity(v_disk)  #recalculate complexity
            if K >= 4:
                complex.add(v_disk)
                if v_disk in border:
                    border.remove(v_disk)
                if v_disk in new_border:
                    new_border.remove(v_disk)
                changed = True
            else:
                if v_disk not in border:
                    new_border.add(v_disk)
                changed = True
                
        if len(border) == 0 and len(new_border) != 0:
            #by doing this, we scratch all of the most outer layer
            #before proceding to the next layer
            border = new_border
            new_border = set()
            
    print('There are %i complex verts after pruning' % len(complex))
        
    for v in bme.verts:
        if v in skeleton:
            v.select_set(True)
        else:
            v.select_set(False)    
                    
    
    bme.select_flush_mode()
    
    
    print("There are %i verts to scratch" % len(to_scratch))
  
    del disk_dict
            
#simple test operator   
class CutMesh_OT_bake_ambient_occlusion(bpy.types.Operator):
    """Bake single object ambient occlusion in a separate scene"""
    bl_idname = "cut_mesh.bake_ambient_occlusion"
    bl_label = "Cut Mesh Bake Ambient Occlusion"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self,context):
        if context.object:
            print('bake object')
            bake_ambient_object(context, context.object)
            
        return {'FINISHED'}


class CutMesh_OT_select_verts_by_ambient_color(bpy.types.Operator):
    """Select mesh vertice by the vertex color"""
    bl_idname = "cut_mesh.select_verts_ao_color"
    bl_label = "Cut Mesh Select Ambient Occlusion"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self,context):
        if context.object:
            if context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode = 'OBJECT')
            
            pick_verts_by_AO_color(context.object, threshold = .95)
            
        return {'FINISHED'}


class CutMesh_OT_skeletonize_selection(bpy.types.Operator):
    """Skeletonize Selection to one vertex width path"""
    bl_idname = "cut_mesh.skeletonize_selection"
    bl_label = "Cut Mesh Skeletonize Selection"
    bl_options = {'REGISTER', 'UNDO'}
    
    allow_tails = bpy.props.BoolProperty(name = 'Allow Tails', default = False, description = 'If False, will only allow loops')
    def execute(self,context):
        
        if bpy.context.mode == 'OBJECT':
            bme = bmesh.new()
            bme.from_mesh(bpy.context.object.data)
            bme.verts.ensure_lookup_table()
            bme.edges.ensure_lookup_table()
            bme.faces.ensure_lookup_table()
        
        else:
            bme = bmesh.from_edit_mesh(bpy.context.object.data)
            
            
        skeletonize_selection(bme, allow_tails = self.allow_tails)
        
        if bpy.context.mode == 'OBJECT':
            bme.to_mesh(bpy.context.object.data)
            bme.free()
    
        else:
            bmesh.update_edit_mesh(bpy.context.object.data)
    
        return {'FINISHED'}
    
def register():
    print('Registering ambient occlusion operator')
    bpy.utils.register_class(CutMesh_OT_bake_ambient_occlusion)
    bpy.utils.register_class(CutMesh_OT_select_verts_by_ambient_color)
    bpy.utils.register_class(CutMesh_OT_skeletonize_selection)
def unregister():
    bpy.utils.unregister_class(CutMesh_OT_bake_ambient_occlusion)
    bpy.utils.unregister_class(CutMesh_OT_select_verts_by_ambient_color)
    bpy.utils.unregister_class(CutMesh_OT_skeletonize_selection)
