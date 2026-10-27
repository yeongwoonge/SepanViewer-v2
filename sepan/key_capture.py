"""One-shot binding through Tk events; no native window callback in the GUI."""
import time
import ctypes as C
from .keys import name_from_raw


def name_from_tk(event):
    names={'Shift_L':'LShift','Shift_R':'RShift','Control_L':'LCtrl','Control_R':'RCtrl',
           'Alt_L':'LAlt','Alt_R':'RAlt','ISO_Level3_Shift':'RAlt','Meta_L':'LWin','Meta_R':'RWin',
           'Super_L':'LWin','Super_R':'RWin','Win_L':'LWin','Win_R':'RWin',
           'space':'Space','Return':'Enter','KP_Enter':'NumpadEnter','Escape':'Escape','BackSpace':'Backspace',
           'Tab':'Tab','ISO_Left_Tab':'Tab','Caps_Lock':'CapsLock','Num_Lock':'NumLock','Scroll_Lock':'ScrollLock',
           'Print':'PrintScreen','Pause':'Pause','Hangul':'Hangeul','Hangul_Hanja':'Hanja',
           'KP_Add':'NumpadAdd','KP_Subtract':'NumpadSub','KP_Multiply':'NumpadMult','KP_Divide':'NumpadDiv',
           'KP_Decimal':'NumpadDot','KP_Delete':'NumpadDot','KP_Insert':'Numpad0','KP_End':'Numpad1',
           'KP_Down':'Numpad2','KP_Next':'Numpad3','KP_Left':'Numpad4','KP_Begin':'Numpad5',
           'KP_Right':'Numpad6','KP_Home':'Numpad7','KP_Up':'Numpad8','KP_Prior':'Numpad9'}
    sym=str(event.keysym)
    vk=int(event.keycode)
    modifier={0x10:(0xa0,0xa1,'Shift'),0x11:(0xa2,0xa3,'Ctrl'),0x12:(0xa4,0xa5,'Alt')}.get(vk)
    if modifier:
        left,right,prefix=modifier;user=C.WinDLL('user32')
        if user.GetAsyncKeyState(right)&0x8000:return 'R'+prefix
        if user.GetAsyncKeyState(left)&0x8000:return 'L'+prefix
    sided={0xa0:'LShift',0xa1:'RShift',0xa2:'LCtrl',0xa3:'RCtrl',0xa4:'LAlt',0xa5:'RAlt'}
    if vk in sided:return sided[vk]
    if sym in names:return names[sym]
    if sym.startswith('KP_') and sym[3:].isdigit():return 'Numpad'+sym[3:]
    if vk in (0x10,0x11,0x12):
        # Side-specific VK states are read in this ordinary Tk callback.
        user=C.WinDLL('user32')
        left,right,prefix={0x10:(0xa0,0xa1,'Shift'),0x11:(0xa2,0xa3,'Ctrl'),0x12:(0xa4,0xa5,'Alt')}[vk]
        return ('R' if user.GetAsyncKeyState(right)&0x8000 else 'L')+prefix
    if 0x60<=vk<=0x69:return 'Numpad'+str(vk-0x60)
    if sym in ('Up','Down','Left','Right','Home','End','Insert','Delete'):return sym
    if sym in ('Prior','Next'):return 'PgUp' if sym=='Prior' else 'PgDn'
    scan=C.WinDLL('user32').MapVirtualKeyW(vk,0)
    return name_from_raw(vk,scan)


class KeyCapture:
    def __init__(self,window,on_error):
        self.window=window;self.on_error=on_error
        self.armed=False;self.registered=False;self.closed=False;self.callback=None
        self.deferred=None;self.block_until=0
        self.tag=f'SepanKeyBind_{id(self)}';self.attached=[]
        self.press_binding=window.bind_class(self.tag,'<KeyPress>',self._on_key)
        self.release_binding=window.bind_class(self.tag,'<KeyRelease>',self._on_release)
    def attach(self,widget):
        widget.bindtags((self.tag,)+tuple(tag for tag in widget.bindtags() if tag!=self.tag))
        self.attached.append(widget)
    def arm(self,callback):
        self.cancel();self.callback=callback;self.armed=True;self.registered=True
    def cancel(self):
        self.armed=False;self.registered=False;self.callback=None
        if self.deferred is not None:
            try:self.window.after_cancel(self.deferred)
            except Exception:pass
            self.deferred=None
    def _deliver(self,name):
        if not self.armed:return
        if self.deferred is not None:self.window.after_cancel(self.deferred);self.deferred=None
        callback=self.callback
        def finish():
            self.deferred=None
            if self.closed:return
            self.cancel();self.block_until=time.perf_counter()+.25
            if callback:callback(name)
        # Let an AltGr sequence replace its provisional Ctrl event.
        if name in ('LCtrl','RCtrl'):self.deferred=self.window.after(40,finish)
        else:self.armed=False;self.deferred=self.window.after_idle(finish)
    def accept(self,vk,scan):
        self._deliver(None if vk==27 else name_from_raw(vk,scan))
    def _on_key(self,event):
        if self.closed:return
        if self.armed:
            try:self._deliver(None if event.keysym=='Escape' else name_from_tk(event))
            except Exception as error:self.cancel();self.on_error(str(error))
            return 'break'
        if time.perf_counter()<self.block_until:return 'break'
    def _on_release(self,event):
        if self.armed or time.perf_counter()<self.block_until:return 'break'
    def close(self):
        if self.closed:return
        self.cancel();self.closed=True
        for widget in self.attached:
            try:widget.bindtags(tuple(tag for tag in widget.bindtags() if tag!=self.tag))
            except Exception:pass
        self.window.unbind_class(self.tag,'<KeyPress>');self.window.unbind_class(self.tag,'<KeyRelease>')
        for command in (self.press_binding,self.release_binding):
            try:self.window._root().deletecommand(command)
            except Exception:pass
