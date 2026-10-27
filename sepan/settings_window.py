"""Small user settings: game timing, gear preset, and press-to-bind keys."""
import configparser
import time
import tkinter as tk
from tkinter import ttk,messagebox
from .config import load
from .keys import key_label,DEFAULT_8_BINDINGS
from .key_capture import KeyCapture
from .lane_labels import lane_label

GEAR_PRESETS={'왼쪽':125,'가운데':720,'오른쪽':1325}


def open_settings(app,root_path):
    parser=configparser.ConfigParser(interpolation=None);parser.optionxform=str
    parser.read(root_path/'config.ini',encoding='utf-8-sig')
    window=tk.Toplevel(app.root);window.title('설정');window.resizable(False,False)
    frame=ttk.Frame(window,padding=16);frame.pack(fill='both',expand=True)
    judgement=tk.StringVar(value=f'{app.cfg.timing.gameJudgement:g}')
    ttk.Label(frame,text='게임 판정 타이밍').grid(row=0,column=0,sticky='w',padx=(0,14),pady=4)
    ttk.Spinbox(frame,from_=-150,to=150,textvariable=judgement,width=8).grid(row=0,column=1,sticky='w')
    initial=next((name for name,x in GEAR_PRESETS.items() if x==app.cfg.gearLeft),'사용자 설정')
    position=tk.StringVar(value=initial)
    ttk.Label(frame,text='기어 위치').grid(row=1,column=0,sticky='w',pady=6)
    options=list(GEAR_PRESETS)+( ['사용자 설정'] if initial=='사용자 설정' else [])
    ttk.Combobox(frame,textvariable=position,values=options,state='readonly',width=12).grid(row=1,column=1,sticky='w')
    hint=tk.StringVar(value='키 칸을 클릭한 다음 사용할 키를 누르세요. Esc: 취소')
    from .profile_window import open_profile_editor
    ttk.Button(frame,text='노트·색 프리셋',command=lambda:open_profile_editor(app,root_path,window)).grid(row=2,column=0,sticky='w',pady=(12,4))
    ttk.Button(frame,text='오버레이 스타일·위치',command=app.edit_overlay).grid(row=2,column=1,sticky='w',pady=(12,4))
    ttk.Label(frame,textvariable=hint).grid(row=3,column=0,columnspan=2,sticky='w',pady=(10,6))
    keys={};buttons={};waiting={'target':None,'block_until':0}
    def reset_waiting():
        target=waiting['target']
        if target in buttons:buttons[target].configure(text=key_label(keys[target].get()))
        waiting['target']=None
    def capture_error(message):
        reset_waiting();hint.set('키 입력을 읽지 못했습니다. 다시 클릭해 주세요.')
    capture=KeyCapture(window,capture_error);window.key_capture=capture
    def choose(target):
        reset_waiting();waiting['target']=target
        buttons[target].configure(text='키를 누르세요');buttons[target].focus_set()
        hint.set('키를 누르세요. 스페이스·좌우 Alt·숫자패드도 지정할 수 있습니다.')
        def bound(name):
            if name is not None and name!='F5':keys[target].set(name)
            waiting['block_until']=time.perf_counter()+.25
            reset_waiting()
            hint.set('F5는 기록 재시작용입니다. 다른 키를 지정하세요.' if name=='F5' else '키 칸을 클릭한 다음 사용할 키를 누르세요. Esc: 취소')
        try:capture.arm(bound)
        except Exception as error:capture_error(str(error))
    def suppress_key(event):
        if capture.armed or waiting['target'] is not None or time.perf_counter()<waiting['block_until']:return 'break'
    notebook=ttk.Notebook(frame);notebook.grid(row=4,column=0,columnspan=2,sticky='ew',pady=(0,12))
    for mode in (4,5,6,8):
        key_frame=ttk.Frame(notebook,padding=10);notebook.add(key_frame,text=f'{mode}B')
        source=f'{mode}LANE' if parser.has_section(f'{mode}LANE') else '6LANE'
        normal=(('1','2','3a','3b','4','5') if parser.has_option(source,'3a') else ('1','2','3','4','5')) if mode==5 else tuple(str(i) for i in range(1,(6 if mode==8 else mode)+1))
        lanes=('A',)+normal+('B',) if mode!=8 else ('A','1','2','3','L','R','4','5','6','B')
        for i,lane in enumerate(lanes):
            col=i%5;row=(i//5)*2
            text=lane_label(lane)
            ttk.Label(key_frame,text=text).grid(row=row,column=col,padx=5,pady=(8,4))
            target=(mode,lane);keys[target]=tk.StringVar(value=parser.get(source,lane,fallback='F13' if lane=='L' else 'F14'))
            button=ttk.Button(key_frame,text=key_label(keys[target].get()),width=14,command=lambda target=target:choose(target))
            button.grid(row=row+1,column=col,padx=5,pady=(0,6));buttons[target]=button
            capture.attach(button)
            button.bind('<KeyPress>',suppress_key);button.bind('<KeyRelease>',suppress_key)
        if mode==8:
            def restore_eight():
                capture.cancel();reset_waiting()
                for lane,name in DEFAULT_8_BINDINGS.items():
                    keys[(8,lane)].set(name);buttons[(8,lane)].configure(text=key_label(name))
            ttk.Button(key_frame,text='8B 기본키 복원',command=restore_eight).grid(row=4,column=0,columnspan=5,sticky='w',padx=5,pady=(4,0))
    window.binding_keys=keys;window.binding_buttons=buttons;window.gear_position=position
    def close():capture.close();window.destroy()
    def apply():
        try:
            capture.cancel();reset_waiting()
            parser=configparser.ConfigParser(interpolation=None);parser.optionxform=str
            parser.read(root_path/'config.ini',encoding='utf-8-sig')
            if not parser.has_section('timing'):parser.add_section('timing')
            parser.set('timing','gameJudgement',judgement.get())
            parser.set('timing','reference','game')
            parser.set('general','gearLeft',str(GEAR_PRESETS.get(position.get(),app.cfg.gearLeft)))
            for mode in (4,5,6,8):
                section=f'{mode}LANE'
                if parser.has_section(section):parser.remove_section(section)
                parser.add_section(section)
            for (mode,lane),value in keys.items():parser.set(f'{mode}LANE',lane,value.get())
            temp=root_path/'config.pending.ini'
            with temp.open('w',encoding='utf-8') as out:parser.write(out,space_around_delimiters=False)
            load(temp);temp.replace(root_path/'config.ini')
            app.apply_config();close()
        except Exception as error:messagebox.showerror('설정 적용 실패',str(error),parent=window)
    footer=ttk.Frame(frame);footer.grid(row=5,column=0,columnspan=2,sticky='ew')
    ttk.Button(footer,text='닫기',command=close).pack(side='right')
    ttk.Button(footer,text='적용',command=apply).pack(side='right',padx=6)
    ttk.Button(footer,text='진단·고급',command=lambda:open_advanced(app,root_path,window)).pack(side='left')
    window.protocol('WM_DELETE_WINDOW',close)
    window.bind('<Destroy>',lambda event:capture.close() if event.widget==window else None)
    return window


def open_advanced(app,root_path,parent):
    import os
    window=tk.Toplevel(parent);window.title('진단·고급');window.resizable(False,False)
    frame=ttk.Frame(window,padding=14);frame.pack()
    for index,(label,command) in enumerate([
        ('진단 로그 보기',lambda:app.toggle_logs(True)),('진단 이미지 저장',app.save_snapshot),
        ('config.ini 열기',lambda:os.startfile(root_path/'config.ini')),('config.ini 적용',app.apply_config),
        ('브라우저 뷰어 열기',app.open_viewer),('브라우저 주소 복사',app.copy_viewer_url),
        ('프로그램 폴더',lambda:os.startfile(root_path))]):
        ttk.Button(frame,text=label,command=command,width=23).grid(row=index//2,column=index%2,padx=4,pady=4)
    ttk.Checkbutton(frame,text='키 코드 확인',variable=app.diagnostics).grid(row=4,column=0,sticky='w',pady=6)
    return window
