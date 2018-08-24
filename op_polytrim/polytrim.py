'''
Created on Oct 8, 2015

@author: Patrick
'''
import bpy

from ..cookiecutter.cookiecutter import CookieCutter
from ..common import ui
from ..common.ui import Drawing

from .polytrim_states        import Polytrim_States
from .polytrim_ui_tools      import Polytrim_UI_Tools
from .polytrim_ui_draw       import Polytrim_UI_Draw
from .polytrim_datastructure import InputNetwork, NetworkCutter


#ModalOperator
class CutMesh_Polytrim(CookieCutter, Polytrim_States, Polytrim_UI_Tools, Polytrim_UI_Draw):
    ''' Cut Mesh Polytrim Modal Editor '''
    ''' Note: the functionality of this operator is split up over multiple base classes '''

    operator_id    = "cut_mesh.polytrim"    # operator_id needs to be the same as bl_idname
                                            # important: bl_idname is mangled by Blender upon registry :(
    bl_idname      = "cut_mesh.polytrim"
    bl_label       = "Polytrim"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    bl_options = {'REGISTER','UNDO'}

    default_keymap = {
        # key: a human-readable label
        # val: a str or a set of strings representing the user action
        'action': {'LEFTMOUSE'},
        'sketch': {'LEFTMOUSE'},
        'add point (disconnected)': {'CTRL+LEFTMOUSE'},
        'cancel': {'ESC', 'RIGHTMOUSE'},
        'grab': 'G',
        'delete': {'RIGHTMOUSE'},
        'delete (disconnect)': {'CTRL+RIGHTMOUSE'},
        'preview cut': 'C',
        'up': 'UP_ARROW',
        'down': 'DOWN_ARROW'
        # ... more
    }

    @classmethod
    def can_start(cls, context):
        ''' Called when tool is invoked to determine if tool can start '''
        if context.mode != 'OBJECT':
            #showErrorMessage('Object Mode please')
            return False
        if not context.object:
            return False
        if context.object.type != 'MESH':
            #showErrorMessage('Must select a mesh object')
            return False
        return True

    def start(self):
        info = self.wm.create_window('PolyTrim Help', {'pos':9, 'movable':True, 'bgcolor':(.3,.6,.3,.6)})
        info.add(ui.UI_Label('Instructions'))

        self.instructions = {
            "add": "Left-click to add a new point",
            "sketch (anywhere)": "Hold left-click and drag to sketch in a line of points",
            "sketch (point)": "Hold left-click and drag from a hovered point to sketch in a line of points"
        }
        self.info_a = info.add(ui.UI_Markdown('', min_size=(200,10)))
        self.info_b = info.add(ui.UI_Markdown('', min_size=(200,10)))
        self.info_c = info.add(ui.UI_Markdown('', min_size=(200,10)))
        self.info_d = info.add(ui.UI_Markdown('', min_size=(200,10)))
        self.info_e = info.add(ui.UI_Markdown('', min_size=(200,10)))
        self.info_f = info.add(ui.UI_Markdown('', min_size=(200,10)))
        self.set_ui_text_no_points()

        exitbuttons = info.add(ui.UI_EqualContainer(margin=0,vertical=False))
        exitbuttons.add(ui.UI_Button('commit', self.done))
        exitbuttons.add(ui.UI_Button('cancel', lambda:self.done(cancel=True)))

        self.cursor_modal_set('CROSSHAIR')

        #self.drawing = Drawing.get_instance()
        self.drawing.set_region(bpy.context.region, bpy.context.space_data.region_3d, bpy.context.window)
        self.mode_pos        = (0, 0)
        self.cur_pos         = (0, 0)
        self.mode_radius     = 0
        self.action_center   = (0, 0)

        self.net_ui_context = self.NetworkUIContext(self.context)

        self.input_net = InputNetwork(self.net_ui_context)
        self.network_cutter = NetworkCutter(self.input_net, self.net_ui_context)

        self.sketcher = self.SketchManager(self.input_net, self.net_ui_context, self.network_cutter)
        self.grabber = self.GrabManager(self.input_net, self.net_ui_context, self.network_cutter)



    def end(self):
        ''' Called when tool is ending modal '''
        self.header_text_set()
        self.cursor_modal_restore()

    def update(self):
        pass