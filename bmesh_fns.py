'''
Created on Oct 8, 2015

@author: Patrick
'''

def face_neighbors(bmface):
    neighbors = []
    for ed in bmface.edges:
        neighbors += [f for f in ed.link_faces if f != bmface]
        
    return neighbors


def face_neighbors_strict(bmface):
    neighbors = []
    for ed in bmface.edges:
        if not (ed.verts[0].is_manifold and ed.verts[1].is_manifold):
            if len(ed.link_faces) == 1:
                print('found an ed, with two non manifold verts')
            continue
        neighbors += [f for f in ed.link_faces if f != bmface]
        
    return neighbors


def vert_neighbors(bmvert):
    
    neighbors = [ed.other_vert(bmvert) for ed in bmvert.link_edges]
    return [v for v in neighbors if v.is_manifold]
     
def flood_selection_by_verts(bme, selected_faces, seed_face, max_iters = 1000):
    '''
    bme - bmesh
    selected_faces - should create a closed face loop to contain "flooded" selection
    if an empty set, selection willg grow to non manifold boundaries
    seed_face - a face within/out selected_faces loop
    max_iters - maximum recursions to select_neightbors
    
    return - set of faces
    '''
    total_selection = set([f for f in selected_faces])
    levy = set([f for f in selected_faces])  #it's funny because it stops the flood :-)

    new_faces = set(face_neighbors_strict(seed_face)) - levy
    iters = 0
    while iters < max_iters and new_faces:
        iters += 1
        new_candidates = set()
        for f in new_faces:
            new_candidates.update(face_neighbors_strict(f))
            
        new_faces = new_candidates - total_selection
        
        if new_faces:
            total_selection |= new_faces    
    if iters == max_iters:
        print('max iterations reached')    
    return total_selection

def flood_selection_faces(bme, selected_faces, seed_face, max_iters = 1000):
    '''
    bme - bmesh
    selected_faces - should create a closed face loop to contain "flooded" selection
    if an empty set, selection willg grow to non manifold boundaries
    seed_face - a face within/out selected_faces loop
    max_iters - maximum recursions to select_neightbors
    
    return - set of faces
    '''
    total_selection = set([f for f in selected_faces])
    levy = set([f for f in selected_faces])  #it's funny because it stops the flood :-)

    new_faces = set(face_neighbors(seed_face)) - levy
    iters = 0
    while iters < max_iters and new_faces:
        iters += 1
        new_candidates = set()
        for f in new_faces:
            new_candidates.update(face_neighbors(f))
            
        new_faces = new_candidates - total_selection
        
        if new_faces:
            total_selection |= new_faces    
    if iters == max_iters:
        print('max iterations reached')    
    return total_selection


def flood_selection_edge_loop(bme, edge_loop, seed_face, max_iters = 1000):
    '''
    bme - bmesh
    edge_loop - should create a closed edge loop to contain "flooded" selection
    if an empty set, selection will grow to non manifold boundaries
    seed_face - a face within/out selected_faces loop
    max_iters - maximum recursions to select_neightbors
    
    return - set of faces
    '''
    total_selection = set([f for f in edge_loop]) #<we pop and remove things, and lists are mutable so we copy it
    
    
    levy = set([e for e in edge_loop])  #it's funny because it stops the flood :-)

    new_faces = set(face_neighbors(seed_face))
    iters = 0
    while iters < max_iters and new_faces:
        iters += 1
        new_candidates = set()
        for f in new_faces:
            new_candidates.update(face_neighbors(f))
            
        new_faces = new_candidates - total_selection
        
        if new_faces:
            total_selection |= new_faces    
    if iters == max_iters:
        print('max iterations reached')    
    return total_selection

def grow_selection_to_find_face(bme, start_face, stop_face, max_iters = 1000):
    '''
    contemplating indexes vs faces themselves?  will try both ways for speed
    will grow selection iterartively with neighbors until stop face is
    reached.
    '''

    total_selection = set([start_face])
    new_faces = set(face_neighbors(start_face))
    
    if stop_face in new_faces:
        total_selection |= new_faces
        return total_selection
    
    iters = 0
    while iters < max_iters and stop_face not in new_faces:
        iters += 1
        candidates = set()
        for f in new_faces:
            candidates.update(face_neighbors(f))
        
        new_faces = candidates - total_selection   
        if new_faces:
            total_selection |= new_faces
             
    if iters == max_iters:
        print('max iterations reached')
            
    return total_selection


def grow_to_find_mesh_end(bme, start_face, max_iters = 20):
    '''
    will grow selection until a non manifold face is raeched.
    
    geom = dictionary
    
    geom['end'] = BMFace or None, the first non manifold face to be found
    geom['faces'] = list [BMFaces], all the faces encountered on the way
    
    '''

    geom = {}
    
    total_selection = set([start_face])
    new_faces = set(face_neighbors(start_face))
    
    def not_manifold(faces):
        for f in faces:
            if any([not ed.is_manifold for ed in f.edges]):
                return f
        return None
    
    iters = 0
    stop_face = not_manifold(new_faces)
    if stop_face:
        total_selection |= new_faces
        geom['end'] = stop_face
        geom['faces'] = total_selection
        return geom
    
    while new_faces and iters < max_iters and not stop_face:
        iters += 1
        candidates = set()
        for f in new_faces:
            candidates.update(face_neighbors(f))
        
        new_faces = candidates - total_selection   
        if new_faces:
            total_selection |= new_faces
            stop_face = not_manifold(new_faces)
            
    if iters == max_iters:
        print('max iterations reached')
        geom['end'] = None
        
    elif not stop_face:
        print('completely manifold mesh')
        geom['end'] = None
        
    else:
        geom['end'] = stop_face
     
    geom['faces'] = total_selection    
    return geom
    
def edge_loops_from_bmedges(bmesh, bm_edges):
    """
    Edge loops defined by edges (indices)

    Takes [mesh edge indices] or a list of edges and returns the edge loops

    return a list of vertex indices.
    [ [1, 6, 7, 2], ...]

    closed loops have matching start and end values.
    """
    line_polys = []
    edges = bm_edges.copy()

    while edges:
        current_edge = bmesh.edges[edges.pop()]
        vert_e, vert_st = current_edge.verts[:]
        vert_end, vert_start = vert_e.index, vert_st.index
        line_poly = [vert_start, vert_end]

        ok = True
        while ok:
            ok = False
            #for i, ed in enumerate(edges):
            i = len(edges)
            while i:
                i -= 1
                ed = bmesh.edges[edges[i]]
                v_1, v_2 = ed.verts
                v1, v2 = v_1.index, v_2.index
                if v1 == vert_end:
                    line_poly.append(v2)
                    vert_end = line_poly[-1]
                    ok = 1
                    del edges[i]
                    # break
                elif v2 == vert_end:
                    line_poly.append(v1)
                    vert_end = line_poly[-1]
                    ok = 1
                    del edges[i]
                    #break
                elif v1 == vert_start:
                    line_poly.insert(0, v2)
                    vert_start = line_poly[0]
                    ok = 1
                    del edges[i]
                    # break
                elif v2 == vert_start:
                    line_poly.insert(0, v1)
                    vert_start = line_poly[0]
                    ok = 1
                    del edges[i]
                    #break
        line_polys.append(line_poly)

    return line_polys

def walk_non_man_edge(bme, start_edge, stop, max_iters = 5000):
    '''
    bme = BMesh
    start_edge - BMEdge
    stop -  set of verts or edges to stop when reached
    
    return- list of edge loops
    '''
    
    #stop criteria
    # found element in stop set
    # found starting edge (completed loop)
    # found vert with 2 other non manifold edges
    
    def next_pair(prev_ed, prev_vert):
        v_next = prev_ed.other_vert(prev_vert)
        eds = [e for e in v_next.link_edges if not e.is_manifold and e != prev_ed]
        print(eds)
        if len(eds):
            return eds[0], v_next
        else:
            return None, None
    
    chains = []
    for v in start_edge.verts:
        edge_loop = []
        prev_v = start_edge.other_vert(v)
        prev_ed = start_edge
        next_ed, next_v = next_pair(prev_ed, prev_v)
        edge_loop += [next_ed]
        iters = 0
        while next_ed and next_v and not (next_ed in stop or next_v in stop) and iters < max_iters:
            iters += 1
            
            next_ed, next_v = next_pair(next_ed, next_v)
            if next_ed:
                edge_loop += [next_ed]
                
        chains += [edge_loop]
     
    return chains   