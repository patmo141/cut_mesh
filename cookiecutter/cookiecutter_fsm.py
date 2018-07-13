'''
Copyright (C) 2018 CG Cookie

https://github.com/CGCookie/retopoflow

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

class CookieCutter_FSM:
    class FSM_State:
        @staticmethod
        def get_state(state, substate):
            return '%s__%s' % (state, substate)
        def __init__(self, state, substate='main'):
            self.state = state
            self.substate = substate
        def __call__(self, fn):
            self.fn = fn
            self.fnname = fn.__name__
            def run(*args, **kwargs):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    print('Caught exception in function "%s" ("%s")' % (
                        self.fnname, self.fsmstate
                    ))
                    print(e)
                    return
            run.fnname = self.fnname
            run.fsmstate = CookieCutter_FSM.FSM_State.get_state(self.state, self.substate)
            return run
    
    def fsm_init(self):
        self._state_prev = None
        self._state = 'main'
        self._fsm_states = {}
        for (m,fn) in self.find_fns('fsmstate'):
            assert m not in self._fsm_states, 'Duplicate states registered!'
            self._fsm_states[m] = fn
    
    def _fsm_call(self, state, substate='main', fail_if_not_exist=False):
        s = CookieCutter_FSM.FSM_State.get_state(state, substate)
        if s not in self._fsm_states:
            assert not fail_if_not_exist
            return
        try:
            return self._fsm_states[s](self)
        except Exception as e:
            print('Caught exception in state ("%s")' % (s))
            print(e)
            return
        
    
    def fsm_update(self):
        if self._state != self._state_prev:
            if self._state_prev:
                self._fsm_call(self._state_prev, substate='exit')
            self._fsm_call(self._state, substate='enter')
            self._state_prev = self._state
        nmode = self._fsm_call(self._state, fail_if_not_exist=True)
        if nmode: self._state = nmode
    


