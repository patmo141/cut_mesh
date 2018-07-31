'''
Copyright (C) 2014 Plasmasolutions
software@plasmasolutions.de

Created by Thomas Beck
Donated to CGCookie and the world

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

'''
Note: not all of the following code was provided by Plasmasolutions
TODO: split into separate files?
'''

# System imports
import os
import sys
import inspect
import math
import time
import itertools
from mathutils import Vector, Matrix, Quaternion
from .common.blender import bversion
from .common.debug import vector_angle_between

# from lib import common_drawing

# Blender imports
import bpy
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d, region_2d_to_location_3d, region_2d_to_origin_3d

class AddonLocator(object):
    def __init__(self, f=None):
        self.fullInitPath = f if f else __file__
        self.FolderPath = os.path.dirname(self.fullInitPath)
        self.FolderName = os.path.basename(self.FolderPath)
    
    def AppendPath(self):
        sys.path.append(self.FolderPath)
        print("Addon path has been registered into system path for this session")

def get_matrices(ob):
    ''' obtain blender object matrices '''
    mx = ob.matrix_world
    imx = mx.inverted()
    return [mx, imx]

def vector_angle_between_near_parallel(v0, v1, vcross):
    a = v0.angle(v1)
    d = v0.cross(v1).dot(vcross)
    return a if d>0 else 2*math.pi - a

def delta_angles(vec_about, l_vecs):
    '''
    will find the difference betwen each element and the next element in the list
    this is a foward difference.  Eg delta[n] = item[n+1] - item[n]
    
    deltas should add up to 2*pi
    '''
    
    v0 = l_vecs[0]
    l_angles = [0] + [vector_angle_between(v0,v1,vec_about) for v1 in l_vecs[1:]]
    
    L = len(l_angles)
    
    deltas = [l_angles[n + 1] - l_angles[n] for n in range(0, L-1)] + [2*math.pi - l_angles[-1]]
    return deltas
