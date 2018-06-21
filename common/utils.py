'''
Copyright (C) 2018 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson, Patrick Moore

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


import bpy
import sys
import traceback


# http://stackoverflow.com/questions/14519177/python-exception-handling-line-number
def get_exception_info():
    exc_type, exc_obj, tb = sys.exc_info()
    
    errormsg = 'EXCEPTION (%s): %s\n' % (exc_type, exc_obj)
    etb = traceback.extract_tb(tb)
    pfilename = None
    for i,entry in enumerate(reversed(etb)):
        filename,lineno,funcname,line = entry
        if filename != pfilename:
            pfilename = filename
            errormsg += '         %s\n' % (filename)
        errormsg += '%03d %04d:%s() %s\n' % (i, lineno, funcname, line.strip())
    return errormsg

def exception_handler():
    errormsg = get_exception_info()
    print(errormsg)
    exception_handler.count = getattr(exception_handler, 'count', 0) + 1
    if exception_handler.count < 10:
        #showErrorMessage(errormsg, wrap=240)
        pass
    return errormsg


StructRNA = bpy.types.bpy_struct
def still_registered(self, oplist):
    if getattr(still_registered, 'is_broken', False): return False
    def is_registered():
        cur = bpy.ops
        for n in oplist:
            if not hasattr(cur, n): return False
            cur = getattr(cur, n)
        try:    StructRNA.path_resolve(self, "properties")
        except:
            print('no properties!')
            return False
        return True
    if is_registered(): return True
    still_registered.is_broken = True
    print('bpy.ops.%s is no longer registered!' % '.'.join(oplist))
    return False

registered_objects = {}
def registered_object_add(self):
    global registered_objects
    opid = self.operator_id
    print('Registering bpy.ops.%s' % opid)
    registered_objects[opid] = (self,opid.split('.'))

def registered_check():
    global registered_objects
    return all(still_registered(s,o) for (s,o) in registered_objects.values())

