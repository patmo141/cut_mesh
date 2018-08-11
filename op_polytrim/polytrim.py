'''
Created on Oct 8, 2015

@author: Patrick
'''

from ..cookiecutter.cookiecutter import CookieCutter
from ..common import ui


from .polytrim_ui            import Polytrim_UI
from .polytrim_states        import Polytrim_States
from .polytrim_ui_tools      import Polytrim_UI_Tools
from .polytrim_ui_draw       import Polytrim_UI_Draw
from .polytrim_datastructure import PolyLineKnife
from .polytrim_ui_tools      import PolyLineManager


#ModalOperator
class CutMesh_Polytrim(CookieCutter, Polytrim_UI, Polytrim_States, Polytrim_UI_Tools, Polytrim_UI_Draw):
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
        'cancel': {'ESC', 'RIGHTMOUSE'},
        'grab': 'G',
        'delete': {'RIGHTMOUSE'},
        'toggle selection': 'A',
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
        opts = {
            'pos': 8,
            'movable': True,
            'bgcolor': (0.2, 0.2, 0.2, 0.8),
            'padding': 0,
            }
        win = self.wm.create_window('test', opts)
        self.lbl = win.add(ui.UI_Label('main'))
        exitbuttons = win.add(ui.UI_Container(margin=0,vertical=False))
        exitbuttons.add(ui.UI_Button('commit', self.done))
        exitbuttons.add(ui.UI_Button('cancel', lambda:self.done(cancel=True)))

        self.stroke_smoothing = 0.75          # 0: no smoothing. 1: no change
        self.mode_pos        = (0, 0)
        self.cur_pos         = (0, 0)
        self.mode_radius     = 0
        self.action_center   = (0, 0)
        self.is_navigating   = False
        self.sketch_curpos   = (0, 0)
        self.sketch          = []

        self.plm = PolyLineManager()
        self.plm.add(PolyLineKnife(self.context, self.context.object))
        self.plm.current = self.plm.polylines[0]

        self.cursor_modal_set('CROSSHAIR')
        self.set_ui_text_main()

    def end(self):
        ''' Called when tool is ending modal '''
        self.header_text_set()
        self.cursor_modal_restore()

    def update(self):
        pass