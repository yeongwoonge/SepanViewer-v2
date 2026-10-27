"""Per-pixel alpha Windows overlay; no browser, OBS, or game hook required."""
import base64
import ctypes as C
from ctypes import wintypes as W
from io import BytesIO
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter
from .lane_labels import lane_label
from . import APP_NAME


GEAR_SIZE_RATIO=.8


def read_layout(path):
    result={'enabled':True,'scale':2,'x':None,'y':None,'style':'vertical','placements':{},'gear_offset_y':-80,'opacity':.45,'compact_version':0}
    try:
        data=json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(data,dict):return result
        if isinstance(data.get('enabled'),bool):result['enabled']=data['enabled']
        if type(data.get('scale')) is int and 1<=data['scale']<=4:result['scale']=data['scale']
        if data.get('style') in ('vertical','gear'):result['style']=data['style']
        if type(data.get('gear_offset_y')) is int and -750<=data['gear_offset_y']<=100:result['gear_offset_y']=data['gear_offset_y']
        if type(data.get('opacity')) in (int,float) and .2<=data['opacity']<=1:result['opacity']=float(data['opacity'])
        if data.get('compact_version')==1:result['compact_version']=1
        if isinstance(data.get('placements'),dict):
            for style,value in data['placements'].items():
                if style in ('vertical','gear') and isinstance(value,dict):
                    if all(type(value.get(key)) is int and abs(value[key])<1_000_000 for key in ('x','y')) and type(value.get('scale')) is int and 1<=value['scale']<=4:
                        result['placements'][style]={key:value[key] for key in ('x','y','scale')}
        for key in ('x','y'):
            if type(data.get(key)) is int and abs(data[key])<1_000_000:result[key]=data[key]
    except (OSError,ValueError,TypeError):pass
    return result


def fit_position(x,y,width,height,workareas):
    """Restore into an attached monitor, including monitors left of primary."""
    candidates=[]
    for left,top,right,bottom in workareas:
        nx=max(left,min(x,right-width))
        ny=max(top,min(y,bottom-height))
        candidates.append(((nx-x)**2+(ny-y)**2,nx,ny))
    return min(candidates)[1:] if candidates else (max(0,x),max(0,y))


def decode_labels(labels):
    return {name:Image.open(BytesIO(base64.b64decode(data['uri'].split(',',1)[1]))).convert('RGBA')
            for name,data in labels.items()}


def render_overlay(state,scale=2,labels=None,editing=False):
    """Use the same geometry and input-age opacity as the browser viewer."""
    width,height,center=51,state['height'],state['centerY']
    image=Image.new('RGBA',(width,height),(0,0,0,0))
    draw=ImageDraw.Draw(image)
    draw.rectangle((25,0,25,height-1),fill='#C0C0C0')
    for offset in range(-(center//10)*10,center+1,10):
        draw.line((22,center+offset,28,center+offset),fill='#C0C0C0')
    for line in state['thresholds']:
        y=round(center+line['error'])
        if 0<=y<height:draw.line((0,y,50,y),fill=line['color'])
    draw.line((0,center,50,center),fill='white')
    # A backstroke keeps the reference lines visible over bright gameplay.
    backstroke=Image.new('RGBA',image.size,'black')
    backstroke.putalpha(image.getchannel('A').filter(ImageFilter.MaxFilter(3)))
    image=Image.alpha_composite(backstroke,image)
    if editing:
        image=Image.alpha_composite(Image.new('RGBA',image.size,(18,22,28,225)),image)
    for marker in state['markers']:
        if not 0<=marker['y']<height:continue
        group=Image.new('RGBA',image.size)
        ink=ImageDraw.Draw(group)
        y=round(marker['y']);left=marker['side']=='left'
        tip,base=(23,18) if left else (27,32)
        indicator='#FF4646' if marker.get('late',False) else ('#4696FF' if marker.get('early',False) else '#E0E0E0')
        ink.polygon([(tip,y),(base,y-4),(base,y+4)],fill=indicator,outline='black',width=1)
        label=(labels or {}).get(marker['lane'])
        if label is not None:
            x=18-label.width if left else 33
            top=max(0,min(height-label.height,y-label.height//2))
            group.alpha_composite(label,(x,top))
        else:
            x=17 if left else 34
            ink.text((x,max(8,min(height-8,y))),lane_label(marker['lane']),font=ImageFont.load_default(size=14),
                     anchor='rm' if left else 'lm',fill='white',stroke_width=1,stroke_fill='black')
        opacity=max(0.,min(1.,marker['opacity']))
        group.putalpha(group.getchannel('A').point(lambda a:round(a*opacity)))
        image=Image.alpha_composite(image,group)
    if editing:
        ImageDraw.Draw(image).rectangle((0,0,50,height-1),outline='#A9C5E8')
    return image.resize((width*scale,height*scale),Image.Resampling.NEAREST)


def render_gear_overlay(state,scale=2,editing=False):
    """A compact horizontal error bar for the judgement-line area."""
    half=max(1,state['centerY']);width=2*half+1;height=50
    image=Image.new('RGBA',(width,height),(0,0,0,0));draw=ImageDraw.Draw(image)
    if editing:draw.rectangle((0,0,width-1,height-1),fill=(16,21,30,190),outline=(169,197,232,255))
    draw.line((0,30,width-1,30),fill=(0,0,0,220),width=3)
    draw.line((0,30,width-1,30),fill=(160,166,176,210))
    for bound,alpha in ((21,100),(42,210)):
        for sign in (-1,1):
            x=half+sign*bound
            if 0<=x<width:draw.line((x,23,x,38),fill=(175,180,190,alpha))
    draw.line((half,19,half,41),fill=(0,0,0,255),width=3)
    draw.line((half,19,half,41),fill=(255,255,255,255))
    latest=None
    for marker in state['markers']:
        error=marker['error']
        if abs(error)>half:continue
        x=round(half+error);latest=marker
        color=(255,70,70) if marker.get('late',error>42) else ((70,150,255) if marker.get('early',error < -42) else (215,220,228))
        group=Image.new('RGBA',image.size);ink=ImageDraw.Draw(group)
        alpha=round(255*max(0,min(1,marker['opacity'])))
        ink.line((x,24,x,37),fill=(*color,alpha),width=1)
        image=Image.alpha_composite(image,group)
    if latest is not None:
        x=round(half+latest['error']);draw=ImageDraw.Draw(image)
        indicator='#FF4646' if latest.get('late',latest['error']>42) else ('#4696FF' if latest.get('early',latest['error'] < -42) else '#D7DCE4')
        draw.polygon(((x,23),(x-3,18),(x+3,18)),fill=indicator,outline='black')
    return image.resize((max(1,round(width*scale)),max(1,round(height*scale))),Image.Resampling.NEAREST)


def apply_display_opacity(image,opacity):
    result=image.copy();result.putalpha(result.getchannel('A').point(lambda alpha:round(alpha*opacity)))
    return result


class DesktopOverlay:
    def __init__(self,root,state,path,labels=None,on_error=None):
        import win32api,win32con,win32gui
        self.api,self.con,self.gui=win32api,win32con,win32gui
        self.root,self.state,self.path=root,state,Path(path)
        self.labels=decode_labels(labels or {})
        self.on_error=on_error or (lambda message:None)
        self.layout=read_layout(path)
        self.compaction_migrated=self.layout['compact_version']==0
        self.gear_bounds=None
        self.editing=False;self.editor=None;self.closed=False;self.timer=None
        self.presented=False
        self.last_revision=-1;self.dirty=True;self.poll_count=0
        self.class_name=f'SepanDesktopOverlay_{id(self)}'
        wc=win32gui.WNDCLASS();wc.hInstance=win32api.GetModuleHandle(None)
        wc.lpszClassName=self.class_name;wc.lpfnWndProc=self._wndproc
        wc.hCursor=win32gui.LoadCursor(None,win32con.IDC_SIZEALL)
        self.atom=win32gui.RegisterClass(wc)
        style=win32con.WS_EX_LAYERED|win32con.WS_EX_TRANSPARENT|win32con.WS_EX_TOOLWINDOW|win32con.WS_EX_NOACTIVATE
        self.hwnd=win32gui.CreateWindowEx(style,self.class_name,f'{APP_NAME} 판정 오버레이',win32con.WS_POPUP,
                                         0,0,1,1,None,None,wc.hInstance,None)
        if self.layout['x'] is None:
            self.layout['x']=win32api.GetSystemMetrics(0)-51*self.layout['scale']-64
        if self.layout['y'] is None:self.layout['y']=max(40,win32api.GetSystemMetrics(1)//5)
        if self.layout['compact_version']==0:
            base_width=2*self.state.snapshot()['centerY']+1
            def compact_position(position):
                scale=position['scale'];position['x']+=round(base_width*scale*(1-GEAR_SIZE_RATIO)/2)
                position['y']+=round(50*scale*(1-GEAR_SIZE_RATIO)/2)
            if 'gear' in self.layout['placements']:compact_position(self.layout['placements']['gear'])
            if self.layout['style']=='gear':compact_position(self.layout)
            self.layout['compact_version']=1;self._save()
        self._poll()
        user=C.WinDLL('user32',use_last_error=True)
        user.SetWindowDisplayAffinity.argtypes=[W.HWND,W.DWORD];user.SetWindowDisplayAffinity.restype=W.BOOL
        # WDA_EXCLUDEFROMCAPTURE can stop NVIDIA desktop recording entirely.
        # Our capture worker masks this window locally instead.
        self.capture_excluded=False
        if not user.SetWindowDisplayAffinity(self.hwnd,0):
            self.on_error('오버레이 녹화 허용 설정 실패')

    def _wndproc(self,hwnd,msg,wp,lp):
        c=self.con
        if msg==c.WM_MOUSEACTIVATE:return c.MA_NOACTIVATE
        if msg==c.WM_NCHITTEST and self.editing:return c.HTCAPTION
        if msg==c.WM_EXITSIZEMOVE:
            self._remember_position();self._save()
            return 0
        return self.gui.DefWindowProc(hwnd,msg,wp,lp)

    def _save(self):
        try:
            self.layout['placements'][self.layout['style']]={key:self.layout[key] for key in ('x','y','scale')}
            self.path.write_text(json.dumps(self.layout,indent=2),encoding='utf-8')
        except OSError as error:self.on_error(f'오버레이 위치 저장 실패: {error}')

    def _remember_position(self):
        if self.presented and not self.dirty and self.gui.IsWindow(self.hwnd):
            self.layout['x'],self.layout['y']=self.gui.GetWindowRect(self.hwnd)[:2]

    def _present(self,image):
        import numpy as np
        g=C.WinDLL('gdi32',use_last_error=True)
        class BIH(C.Structure):
            _fields_=[('size',W.DWORD),('width',W.LONG),('height',W.LONG),('planes',W.WORD),
                      ('bitcount',W.WORD),('compression',W.DWORD),('image_size',W.DWORD),
                      ('xppm',W.LONG),('yppm',W.LONG),('colors_used',W.DWORD),('colors_important',W.DWORD)]
        g.CreateCompatibleDC.argtypes=[W.HDC];g.CreateCompatibleDC.restype=W.HDC
        g.CreateDIBSection.argtypes=[W.HDC,C.POINTER(BIH),W.UINT,C.POINTER(C.c_void_p),W.HANDLE,W.DWORD]
        g.CreateDIBSection.restype=W.HANDLE
        g.SelectObject.argtypes=[W.HDC,W.HANDLE];g.SelectObject.restype=W.HANDLE
        g.DeleteObject.argtypes=[W.HANDLE];g.DeleteObject.restype=W.BOOL
        g.DeleteDC.argtypes=[W.HDC];g.DeleteDC.restype=W.BOOL
        width,height=image.size
        areas=[self.api.GetMonitorInfo(monitor)['Work'] for monitor,_,_ in self.api.EnumDisplayMonitors()]
        x,y=fit_position(self.layout['x'],self.layout['y'],width,height,areas)
        self.layout.update(x=x,y=y)
        pixels=np.array(image,dtype=np.uint16)
        pixels[:,:,:3]=(pixels[:,:,:3]*pixels[:,:,3:4]+127)//255
        raw=pixels[:,:,[2,1,0,3]].astype(np.uint8).tobytes()
        dc=bitmap=old=None
        try:
            dc=g.CreateCompatibleDC(None)
            if not dc:raise C.WinError(C.get_last_error())
            bits=C.c_void_p()
            header=BIH(C.sizeof(BIH),width,-height,1,32,0,width*height*4,0,0,0,0)
            bitmap=g.CreateDIBSection(dc,C.byref(header),0,C.byref(bits),None,0)
            if not bitmap or not bits.value:raise C.WinError(C.get_last_error())
            old=g.SelectObject(dc,bitmap)
            C.memmove(bits,raw,len(raw))
            self.gui.UpdateLayeredWindow(self.hwnd,None,(x,y),(width,height),dc,(0,0),0,(0,0,255,1),2)
            self.presented=True
        finally:
            if dc and old:g.SelectObject(dc,old)
            if bitmap:g.DeleteObject(bitmap)
            if dc:g.DeleteDC(dc)

    def _poll(self):
        if self.closed:return
        try:
            if self.layout['enabled']:
                snapshot=self.state.snapshot()
                if self.dirty or snapshot['revision']!=self.last_revision:
                    image=render_gear_overlay(snapshot,self.layout['scale']*GEAR_SIZE_RATIO,self.editing) if self.layout['style']=='gear' else render_overlay(snapshot,self.layout['scale'],self.labels,self.editing)
                    self._present(apply_display_opacity(image,self.layout['opacity']))
                    self.last_revision=snapshot['revision'];self.dirty=False
                if self.poll_count%30==0:
                    c=self.con
                    self.gui.SetWindowPos(self.hwnd,c.HWND_TOPMOST,0,0,0,0,
                        c.SWP_NOMOVE|c.SWP_NOSIZE|c.SWP_NOACTIVATE|c.SWP_SHOWWINDOW)
            self.poll_count+=1
        except Exception as error:
            self.on_error(f'오버레이 표시 실패: {error}')
            self.layout['enabled']=False
            self.gui.ShowWindow(self.hwnd,self.con.SW_HIDE)
        self.timer=self.root.after(33,self._poll)

    def set_enabled(self,enabled):
        if not enabled:self.finish_edit()
        self.layout['enabled']=bool(enabled);self.dirty=True;self.poll_count=0
        if not enabled:self.gui.ShowWindow(self.hwnd,self.con.SW_HIDE)
        self._save()

    def set_style(self,style):
        if style not in ('vertical','gear'):raise ValueError(style)
        if style==self.layout['style']:return
        self._remember_position()
        self.layout['placements'][self.layout['style']]={key:self.layout[key] for key in ('x','y','scale')}
        self.layout['style']=style
        saved=self.layout['placements'].get(style)
        if saved:self.layout.update(saved)
        elif style=='gear':self.place_in_gear()
        self.dirty=True;self._save()

    def place_in_gear(self):
        if self.layout['style']!='gear':self.set_style('gear')
        if self.gear_bounds:
            monitor,lane_left,judge_y=self.gear_bounds
        else:
            monitor=self.api.GetMonitorInfo(self.api.MonitorFromPoint((0,0),2))['Monitor'];lane_left=720;judge_y=750
        left,top,right,bottom=monitor;w,h=right-left,bottom-top
        width=2*self.state.snapshot()['centerY']+1
        scale=max(1,min(4,int(480*w/1920/width)))
        self.layout.update(scale=scale,x=round(left+(lane_left+240)*w/1920-width*scale*GEAR_SIZE_RATIO/2),
                           y=round(top+judge_y*h/1080-50*scale*GEAR_SIZE_RATIO-16+self.layout['gear_offset_y']*h/1080))
        self.dirty=True;self._save()

    def begin_edit(self,gear_bounds=None):
        import tkinter as tk
        from tkinter import ttk
        self.set_enabled(True)
        if gear_bounds:self.gear_bounds=gear_bounds
        if self.editor is not None:
            self.editor.lift();return
        self.editing=True;self.dirty=True
        style=self.gui.GetWindowLong(self.hwnd,self.con.GWL_EXSTYLE)&~self.con.WS_EX_TRANSPARENT
        self.gui.SetWindowLong(self.hwnd,self.con.GWL_EXSTYLE,style)
        self.editor=tk.Toplevel(self.root);self.editor.title('오버레이 스타일·위치')
        self.editor.resizable(False,False);self.editor.attributes('-topmost',True)
        frame=ttk.Frame(self.editor,padding=16);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='화면의 판정 막대를 드래그해 옮기세요.').grid(row=0,column=0,columnspan=3,sticky='w',pady=(0,12))
        ttk.Label(frame,text='스타일').grid(row=1,column=0,sticky='w',padx=(0,8))
        styles={'세로형':'vertical','기어 안 가로형':'gear'}
        selected=tk.StringVar(value=next(name for name,value in styles.items() if value==self.layout['style']))
        style_combo=ttk.Combobox(frame,textvariable=selected,values=list(styles),state='readonly',width=16)
        style_combo.grid(row=1,column=1,sticky='w',pady=(0,8))
        ttk.Label(frame,text='크기').grid(row=2,column=0,sticky='w',padx=(0,8))
        scale=tk.StringVar(value=str(self.layout['scale']))
        combo=ttk.Combobox(frame,textvariable=scale,values=['1','2','3','4'],state='readonly',width=5)
        combo.grid(row=2,column=1,sticky='w')
        def change_style(_):self.set_style(styles[selected.get()]);scale.set(str(self.layout['scale']))
        style_combo.bind('<<ComboboxSelected>>',change_style)
        def fit():
            self.place_in_gear();selected.set('기어 안 가로형');scale.set(str(self.layout['scale']))
        ttk.Button(frame,text='기어에 맞춤',command=fit).grid(row=1,column=2,padx=(24,0),pady=(0,8))
        def change(_):
            self._remember_position();self.layout['scale']=int(scale.get());self.dirty=True
        combo.bind('<<ComboboxSelected>>',change)
        ttk.Button(frame,text='완료',command=self.finish_edit).grid(row=2,column=2,padx=(24,0))
        ttk.Label(frame,text='가로형 높이').grid(row=3,column=0,sticky='w',pady=(14,0))
        offset=tk.DoubleVar(value=self.layout['gear_offset_y'])
        def move_vertical(value):
            previous=self.layout['gear_offset_y'];current=round(float(value));self.layout['gear_offset_y']=current
            if self.layout['style']=='gear':
                monitor=self.gear_bounds[0] if self.gear_bounds else self.api.GetMonitorInfo(self.api.MonitorFromPoint((0,0),2))['Monitor']
                self._remember_position();self.layout['y']+=round((current-previous)*(monitor[3]-monitor[1])/1080)
                self.dirty=True
            self._save()
        height=ttk.Frame(frame);height.grid(row=3,column=1,columnspan=2,sticky='ew',pady=(14,0))
        ttk.Label(height,text='위').pack(side='left')
        ttk.Scale(height,from_=-750,to=100,variable=offset,command=move_vertical,length=210).pack(side='left',padx=6)
        ttk.Label(height,text='아래').pack(side='left')
        ttk.Label(frame,text='표시 진하기').grid(row=4,column=0,sticky='w',pady=(12,0))
        strength=tk.DoubleVar(value=self.layout['opacity']*100)
        def change_strength(value):
            self.layout['opacity']=round(float(value)/100,3);self.dirty=True;self._save()
        opacity_row=ttk.Frame(frame);opacity_row.grid(row=4,column=1,columnspan=2,sticky='ew',pady=(12,0))
        ttk.Label(opacity_row,text='연하게').pack(side='left')
        ttk.Scale(opacity_row,from_=20,to=100,variable=strength,command=change_strength,length=190).pack(side='left',padx=6)
        ttk.Label(opacity_row,text='진하게').pack(side='left')
        ttk.Label(frame,text='완료하면 마우스 입력이 게임으로 통과합니다.').grid(row=5,column=0,columnspan=3,sticky='w',pady=(12,0))
        self.editor.protocol('WM_DELETE_WINDOW',self.finish_edit)

    def finish_edit(self):
        self._remember_position()
        self.editing=False;self.dirty=True
        style=self.gui.GetWindowLong(self.hwnd,self.con.GWL_EXSTYLE)|self.con.WS_EX_TRANSPARENT
        self.gui.SetWindowLong(self.hwnd,self.con.GWL_EXSTYLE,style)
        if self.editor is not None:
            editor=self.editor;self.editor=None;editor.destroy()
        self._save()

    def close(self):
        if self.closed:return
        self.finish_edit();self.closed=True
        if self.timer is not None:self.root.after_cancel(self.timer)
        self.gui.DestroyWindow(self.hwnd)
        self.gui.UnregisterClass(self.class_name,self.api.GetModuleHandle(None))
