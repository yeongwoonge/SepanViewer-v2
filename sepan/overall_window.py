"""On-demand aggregate reports; file reads and plotting stay off the GUI thread."""
from copy import deepcopy
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import os

from .overall import build_overall_report


def open_overall_window(app,root_path):
    from PIL import Image,ImageTk
    root_path=Path(root_path)
    window=tk.Toplevel(app.root);window.title('전체 통계');window.geometry('1000x730')
    window.minsize(760,580)
    frame=ttk.Frame(window,padding=14);frame.pack(fill='both',expand=True)
    controls=ttk.Frame(frame);controls.pack(fill='x')
    ttk.Label(controls,text='버튼').pack(side='left',padx=(0,6))
    mode=tk.StringVar(value=app.cfg.mode if app.cfg.mode in ('4','5','6','8') else '4')
    selector=ttk.Combobox(controls,textvariable=mode,values=['4','5','6','8'],state='readonly',width=5)
    selector.pack(side='left',padx=(0,8))
    status=tk.StringVar(value='저장된 완료 기록을 집계합니다.')
    path_state={'path':None,'future':None,'closed':False,'timer':None,'resize_timer':None,'data':None}
    image_label=ttk.Label(frame,anchor='center')
    def show_image():
        if path_state['path'] is None:return
        with Image.open(path_state['path']) as source:image=source.copy()
        image.thumbnail((max(300,image_label.winfo_width()),max(200,image_label.winfo_height())))
        photo=ImageTk.PhotoImage(image,master=window)
        image_label.configure(image=photo,text='');image_label.image=photo
    def poll():
        if path_state['closed']:return
        future=path_state['future']
        if not future.done():path_state['timer']=window.after(100,poll);return
        try:
            data,path=future.result();path_state.update(path=path,data=data)
            window.overall_data=data
            if data['round_count']:
                details=f"{mode.get()}키 · {data['round_count']}판 · 추천 집계 {data['recommendation_rounds']}판"
                if data['skipped_records']:details+=f" · 읽기 실패 {data['skipped_records']}개"
                if data['empty_records']:details+=f" · 입력 없는 기록 {data['empty_records']}개"
                status.set(details)
                show_image();open_png.configure(state='normal')
            else:
                image_label.configure(image='',text='이 버튼 수로 집계할 수 있는 일반 입력이 없습니다.');image_label.image=None
                status.set(f"집계할 입력 없음 · 읽기 실패 {data['skipped_records']} / 입력 없는 기록 {data['empty_records']}")
                open_png.configure(state='disabled')
        except Exception as error:
            status.set('통계 생성 실패: '+str(error));open_png.configure(state='disabled')
            image_label.configure(image='',text='전체 통계 내기를 눌러 다시 시도하세요.');image_label.image=None
        finally:
            refresh.configure(state='normal');selector.configure(state='readonly')
    def refresh_report(event=None):
        if path_state['closed']:return
        refresh.configure(state='disabled');selector.configure(state='disabled');open_png.configure(state='disabled')
        status.set('완료 기록 집계·그래프 생성 중… 플레이는 계속할 수 있습니다.')
        path_state['future']=app.report_executor.submit(build_overall_report,app.records_root,int(mode.get()),deepcopy(app.cfg),root_path/'statistics')
        path_state['timer']=window.after(100,poll)
    refresh=ttk.Button(controls,text='전체 통계 내기',command=refresh_report);refresh.pack(side='left')
    open_png=ttk.Button(controls,text='PNG 열기',state='disabled',command=lambda:os.startfile(path_state['path']))
    open_png.pack(side='left',padx=6)
    def open_folder():
        folder=root_path/'statistics';folder.mkdir(exist_ok=True);os.startfile(folder)
    ttk.Button(controls,text='통계 폴더',command=open_folder).pack(side='left')
    status_label=ttk.Label(frame,textvariable=status,wraplength=940)
    status_label.pack(fill='x',pady=(12,6))
    image_label.pack(fill='both',expand=True)
    footer=ttk.Label(frame,text='입력 전체 평균은 노트 수를 반영합니다. 추천은 측정 조건이 같은 기록만 현재 판정값으로 맞춰 다시 계산합니다.',wraplength=940)
    footer.pack(fill='x',pady=(6,0))
    def close(event=None):
        if event is not None and event.widget!=window:return
        path_state['closed']=True
        for name in ('timer','resize_timer'):
            if path_state[name] is not None:
                try:window.after_cancel(path_state[name])
                except tk.TclError:pass
        if path_state['future'] is not None:path_state['future'].cancel()
    window.bind('<Destroy>',close)
    def resized(event):
        if event.widget!=window or path_state['closed']:return
        width=max(300,frame.winfo_width()-4)
        status_label.configure(wraplength=width);footer.configure(wraplength=width)
        if image_label.image is None:return
        if path_state['resize_timer'] is not None:window.after_cancel(path_state['resize_timer'])
        path_state['resize_timer']=window.after(150,show_image)
    image_label.image=None
    window.bind('<Configure>',resized)
    selector.bind('<<ComboboxSelected>>',refresh_report)
    window.overall_mode=mode;window.overall_state=path_state;window.overall_refresh=refresh_report
    refresh_report()
    return window
