'''
Created on Oct 8, 2015

@author: Patrick
'''
from ..modaloperator import ModalOperator
from .polystrips_ui            import Polytrim_UI
from .polystrips_ui_modalwait  import Polytrim_UI_ModalWait
from .polystrips_ui_tools      import Polytrim_UI_Tools
from .polystrips_ui_draw       import Polytrim_UI_Draw

from .polystrips_datastructure import Polytrim


class CGC_Polytrim(ModalOperator, Polytrim_UI, Polytrim_UI_ModalWait, Polytrim_UI_Tools, Polytrim_UI_Draw):
    ''' CG Cookie Polytrim Modal Editor '''
    ''' Note: the functionality of this operator is split up over multiple base classes '''
    
    bl_idname      = "cgcookie.polytrim"
    bl_label       = "Polytrim"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    
    def __init__(self):
        FSM = {}
        FSM['sketch']  = self.modal_sketching
        FSM['grab']    = self.modal_grab_tool
        FSM['inner']   = self.modal_inner

        ModalOperator.initialize(self, FSM)
        self.initialize_ui()
    
    def start_poll(self, context):
        ''' Called when tool is invoked to determine if tool can start '''
                
        if context.mode != 'OBJECT' and self.settings.source_object == '' and not context.active_object:
            #showErrorMessage('Object Mode please')
            return False
        
        if context.object.type != 'MESH':
            #showErrorMessage('Must select a mesh object')
            return False
        
        return True
    
    def start(self, context):
        ''' Called when tool is invoked '''
        self.start_ui(context)
    
    def end(self, context):
        ''' Called when tool is ending modal '''
        self.end_ui(context)
    
    def end_commit(self, context):
        ''' Called when tool is committing '''
        self.cleanup(context, 'commit')
        self.create_mesh(context)
    
    def end_cancel(self, context):
        ''' Called when tool is canceled '''
        self.cleanup(context, 'cancel')
        pass
    
    def update(self, context):
        pass