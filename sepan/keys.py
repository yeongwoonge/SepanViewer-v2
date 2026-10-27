"""AHK-style names, with explicit Windows VK/scan-code escape hatches."""
from dataclasses import dataclass
import re

DEFAULT_8_BINDINGS={'A':'LShift','1':'A','2':'S','3':'D','L':'Space','R':'RAlt',
                    '4':'K','5':'L','6':';','B':'RShift'}


@dataclass(frozen=True)
class Binding:
    kind: str
    code: int

    def matches(self, vk, scan):
        return (vk if self.kind == 'vk' else scan) == self.code


VK = {
    'hangeul':0x15,'hangul':0x15,'kana':0x15,'hanja':0x19,
    'space':0x20,'tab':9,'escape':27,'esc':27,'backspace':8,
    'capslock':0x14,'numlock':0x90,'scrolllock':0x91,
    'printscreen':0x2c,'pause':0x13,
}
SC = {
    'enter':0x01c,'numpadenter':0x11c,
    'lalt':0x038,'ralt':0x138,'lctrl':0x01d,'rctrl':0x11d,
    'lshift':0x02a,'rshift':0x036,'lwin':0x15b,'rwin':0x15c,
    'up':0x148,'down':0x150,'left':0x14b,'right':0x14d,
    'home':0x147,'end':0x14f,'pgup':0x149,'pgdn':0x151,
    'insert':0x152,'delete':0x153,
    'numpad0':0x052,'numpad1':0x04f,'numpad2':0x050,'numpad3':0x051,
    'numpad4':0x04b,'numpad5':0x04c,'numpad6':0x04d,'numpad7':0x047,
    'numpad8':0x048,'numpad9':0x049,'numpadadd':0x04e,
    'numpadsub':0x04a,'numpadmult':0x037,'numpaddiv':0x135,'numpaddot':0x053,
    "'":0x028,';':0x027,',':0x033,'.':0x034,'/':0x035,
    '[':0x01a,']':0x01b,'\\':0x02b,'-':0x00c,'=':0x00d,'`':0x029,
}


def parse_key(name):
    s = name.strip().lower()
    if s in SC: return Binding('sc', SC[s])
    if s in VK: return Binding('vk', VK[s])
    if re.fullmatch(r'[a-z0-9]',s): return Binding('vk',ord(s.upper()))
    if re.fullmatch(r'f(?:[1-9]|1[0-9]|2[0-4])',s): return Binding('vk',0x6f+int(s[1:]))
    if re.fullmatch(r'vk[0-9a-f]{2}',s): return Binding('vk',int(s[2:],16))
    if re.fullmatch(r'sc[0-9a-f]{3}',s): return Binding('sc',int(s[2:],16))
    raise ValueError(f'Unknown key name: {name}. Use Right, RAlt, NumpadAdd, Hangeul, vk15 or sc138.')


def identify(mapping,vk,scan):
    lanes = [lane for lane,b in mapping.items() if b.matches(vk,scan)]
    if len(lanes)>1:
        raise ValueError(f'Overlapping bindings for vk{vk:02X}/sc{scan:03X}: {lanes}')
    return lanes[0] if lanes else None


def name_from_raw(vk,scan):
    """Physical special keys first, so NumLock/left-right modifiers stay distinct."""
    specials={0x01c:'Enter',0x11c:'NumpadEnter',0x038:'LAlt',0x138:'RAlt',
              0x01d:'LCtrl',0x11d:'RCtrl',0x02a:'LShift',0x036:'RShift',0x15b:'LWin',0x15c:'RWin',
              0x148:'Up',0x150:'Down',0x14b:'Left',0x14d:'Right',0x147:'Home',0x14f:'End',
              0x149:'PgUp',0x151:'PgDn',0x152:'Insert',0x153:'Delete',
              0x052:'Numpad0',0x04f:'Numpad1',0x050:'Numpad2',0x051:'Numpad3',
              0x04b:'Numpad4',0x04c:'Numpad5',0x04d:'Numpad6',0x047:'Numpad7',
              0x048:'Numpad8',0x049:'Numpad9',0x04e:'NumpadAdd',0x04a:'NumpadSub',
              0x037:'NumpadMult',0x135:'NumpadDiv',0x053:'NumpadDot'}
    if vk==0x13:return 'Pause'
    if scan in specials:return specials[scan]
    if 0x30<=vk<=0x39 or 0x41<=vk<=0x5a:return chr(vk)
    if 0x70<=vk<=0x87:return f'F{vk-0x6f}'
    names={0x20:'Space',0x09:'Tab',0x1b:'Escape',0x08:'Backspace',0x14:'CapsLock',
           0x90:'NumLock',0x91:'ScrollLock',0x2c:'PrintScreen',0x15:'Hangeul',0x19:'Hanja'}
    if vk in names:return names[vk]
    for name,code in SC.items():
        if code==scan:return name
    return f'vk{vk:02X}'


def key_label(name):
    friendly={'Space':'스페이스','LAlt':'왼쪽 Alt','RAlt':'오른쪽 Alt','LShift':'왼쪽 Shift',
              'RShift':'오른쪽 Shift','LCtrl':'왼쪽 Ctrl','RCtrl':'오른쪽 Ctrl','Enter':'Enter',
              'NumpadEnter':'숫자패드 Enter','Hangeul':'한/영','Hanja':'한자'}
    return friendly.get(name,name)
