'''
Copyright (C) 2015 Patrick Moore
patrick.moore.bu@gmail.com


Created by Patrick Moore

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

bl_info = {
    "name":        "Cut Mesh",
    "description": "Tools for cutting and trimming mesh objects",
    "author":      "Patrick Moore",
    "version":     (0, 0, 1),
    "blender":     (2, 7, 6),
    "location":    "View 3D > Tool Shelf",
    "warning":     "",  # used for warning icon and text in addons panel
    "wiki_url":    "",
    "tracker_url": "https://github.com/patmo141/cut_mesh/issues",
    "category":    "3D View"
    }

# Blender imports
import bpy

#TODO Preferences
#TODO Menu

#Tools
from .op_polytrim.polytrim_modal import CGC_Polytrim
from .op_geopath.geopath_modal import CGC_Geopath
from .op_slice.slice_modal import CGC_Slice


def register(): 
    #bpy.utils.register_class(CutMeshPreferences) #TODO
    #bpy.utils.register_class(CutMesh_panel)  #TODO
    #bpy.utils.register_class(CutMesh_menu)  #TODO
    bpy.utils.register_class(CGC_Polytrim)
    bpy.utils.register_class(CGC_Geopath)
    bpy.utils.register_class(CGC_Slice)
    
def unregister():
    #bpy.utils.register_class(CutMeshPreferences)  #TODO
    #bpy.utils.register_class(CutMesh_panel)  #TODO
    #bpy.utils.register_class(CutMesh_menu)  #TODO
    bpy.utils.unregister_class(CGC_Polytrim)
    bpy.utils.unregister_class(CGC_Geopath)
    bpy.utils.unregister_class(CGC_Slice)