"""Windows GUI entry point. Run from this directory with Python 3.11+ x64."""
import sys
import os
import time
import json
import gc
import multiprocessing as mp
from pathlib import Path
from queue import Empty
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parent
from sepan import APP_NAME, __version__


def main(on_ready=None):
    if sys.platform != 'win32':
        raise SystemExit('Live capture requires Windows 11. Use replay.py for offline verification.')
    import ctypes
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    import tkinter as tk
    from tkinter import ttk,messagebox
    import win32gui
    from sepan.config import load,Config,requires_restart
    from sepan.keys import identify
    from sepan.engine import Engine
    from sepan.capture import capture_worker
    from sepan.wininput import input_worker
    from sepan.viewer import ViewerState,ViewerServer
    from sepan.rounds import RoundBuffer,save_round,compare_settings,add_game_rate,refresh_round_image,update_chart
    from sepan.timing import display_result,event_row
    from sepan.event_flow import drain_ordered
    from sepan.result_archive import recorded_time_key

    class App:
        def __init__(self):
            self.root = tk.Tk(); self.root.title(APP_NAME)
            self.root.geometry('860x300');self.root.minsize(820,280)
            self.origin = time.perf_counter_ns()
            self.processes=[]; self.running=False; self.logfile=None; self.jsonfile=None
            self.history=[]; self.cfg=Config()
            self.round_buffer=RoundBuffer();self.round_cutoff=-1;self.round_meta=None
            self.result_since=None
            self.report_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='round-report')
            self.report_jobs=[];self.records_root=ROOT/'records'
            self.records_root.mkdir(exist_ok=True)
            existing=sorted(self.records_root.rglob('summary.json'),key=recorded_time_key) if self.records_root.exists() else []
            self.last_report=existing[-1].parent if existing else None
            self.chart_name=tk.StringVar(value='')
            self.round_status=tk.StringVar(value='결과 화면까지 완료한 판만 저장합니다. F5: 현재 시도 초기화')
            self.viewer_state=ViewerState(self.cfg); self.viewer_server=None
            self.desktop_overlay=None
            self.overlay_visible=tk.BooleanVar(value=True)
            self.reference_status=tk.StringVar(value='화면 기준')
            self.viewer_url=tk.StringVar(value="시각화 초기화 중")
            self.viewer_size=tk.StringVar(value="51 × 301 px")
            self.mode_value=tk.StringVar(value='auto'); self.diagnostics=tk.BooleanVar(value=False)
            self.status=tk.StringVar(value='게임 창을 선택하고 시작을 누르세요.')
            top=ttk.Frame(self.root,padding=(14,14,14,6));top.pack(fill='x');top.columnconfigure(0,weight=1)
            self.windows=ttk.Combobox(top,state='readonly',width=60);self.windows.grid(row=0,column=0,sticky='ew')
            self.refresh_button=ttk.Button(top,text='새로고침',command=self.refresh);self.refresh_button.grid(row=0,column=1,padx=(8,0))
            controls=ttk.Frame(self.root,padding=(14,4));controls.pack(fill='x')
            ttk.Label(controls,text='버튼').pack(side='left',padx=(0,6))
            self.mode_box=ttk.Combobox(controls,textvariable=self.mode_value,values=['auto','4','5','6'],state='readonly',width=5);self.mode_box.pack(side='left',padx=(0,14))
            self.mode_box.bind('<<ComboboxSelected>>',self.choose_mode)
            self.start_button=ttk.Button(controls,text='시작',command=self.start);self.start_button.pack(side='left')
            self.stop_button=ttk.Button(controls,text='정지',command=self.stop);self.stop_button.pack(side='left',padx=(6,20))
            ttk.Checkbutton(controls,text='화면 오버레이',variable=self.overlay_visible,command=self.toggle_overlay).pack(side='left')
            ttk.Button(controls,text='설정',command=self.edit_timing).pack(side='right',padx=6)
            round_bar=ttk.Frame(self.root,padding=(14,12,14,6));round_bar.pack(fill='x')
            ttk.Button(round_bar,text='초기화 (F5)',command=lambda:self.finish_round('F5 재시작')).pack(side='left')
            ttk.Button(round_bar,text='최근 결과',command=self.show_last_report).pack(side='left',padx=6)
            ttk.Button(round_bar,text='기록 폴더',command=self.open_records_folder).pack(side='left')
            ttk.Label(self.root,textvariable=self.status,padding=(14,8,14,2),wraplength=800).pack(fill='x')
            ttk.Label(self.root,textvariable=self.round_status,padding=(14,2,14,8),wraplength=800).pack(fill='x')
            self.logs_visible=False
            self.log_toggle=ttk.Button(self.root,text='진단 로그 보기',command=self.toggle_logs);self.log_toggle.pack(anchor='w',padx=14,pady=4)
            self.log_panel=panel=ttk.Frame(self.root)
            self.text=tk.Text(panel,font=('Consolas',10),wrap='none',state='disabled')
            scrollbar=ttk.Scrollbar(panel,command=self.text.yview);self.text.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side='right',fill='y');self.text.pack(fill='both',expand=True)
            try:
                self.cfg=load(ROOT/'config.ini')
                self.mode_value.set(self.cfg.mode)
                self.mode_box.configure(values=['4','5','6','8'] if self.cfg.noteSkin!='original' else ['auto','4','5','6','8'])
                self.configure_colors()
                self.update_reference_status()
            except Exception as e:self.write(f'CONFIG: {e}')
            try:self.prepare_viewer(self.cfg)
            except Exception as e:
                self.viewer_url.set('시각화 서버 시작 실패')
                self.write(f'VIEWER: {e}. [viewer] port를 변경하고 config.ini 적용을 누르세요.')
            try:
                from sepan.desktop_overlay import DesktopOverlay
                from sepan.fixedsys import label_images
                self.desktop_overlay=DesktopOverlay(self.root,self.viewer_state,ROOT/'desktop-overlay.json',
                                                     labels=label_images()[0],on_error=self.write)
                self.overlay_visible.set(self.desktop_overlay.layout['enabled'])
            except Exception as e:
                self.overlay_visible.set(False)
                self.write(f'오버레이 초기화 실패: {e}')
            self.refresh()
            if self.desktop_overlay and self.desktop_overlay.compaction_migrated and self.desktop_overlay.layout['style']=='gear':
                self.desktop_overlay.gear_bounds=self.overlay_gear_bounds();self.desktop_overlay.place_in_gear()
            self.root.protocol('WM_DELETE_WINDOW',self.close)
            self.root.bind('<F5>',lambda event:self.finish_round('F5 재시작',show=True))
            self.root.after(5,self.poll)

        def prepare_viewer(self,cfg):
            old=self.viewer_server
            new=old
            if old is None or old.port!=cfg.viewer.port:
                # Bind the replacement before closing the working server.
                new=ViewerServer(self.viewer_state,cfg.viewer.port)
                if new.font_warning:self.write("VIEWER: "+new.font_warning)
            self.viewer_state.configure(cfg)
            self.viewer_server=new
            if old is not None and old is not new:old.close()
            self.viewer_url.set(new.url)
            self.viewer_size.set(f'51 × {2*int(cfg.maxWindow)+1} px')

        def copy_viewer_url(self):
            if self.viewer_server:
                self.root.clipboard_clear()
                self.root.clipboard_append(self.viewer_server.url)

        def open_viewer(self):
            if self.viewer_server:os.startfile(self.viewer_server.url)

        def toggle_overlay(self):
            if self.desktop_overlay:self.desktop_overlay.set_enabled(self.overlay_visible.get())

        def overlay_gear_bounds(self):
            import win32api
            index=self.windows.current()
            hwnd=self.targets[index][0] if 0<=index<len(self.targets) else win32gui.GetAncestor(self.root.winfo_id(),2)
            monitor=win32api.GetMonitorInfo(win32api.MonitorFromWindow(hwnd,2))['Monitor']
            return monitor,self.cfg.gearLeft,self.cfg.judgeY

        def edit_overlay(self):
            if self.desktop_overlay:
                self.overlay_visible.set(True)
                self.desktop_overlay.begin_edit(self.overlay_gear_bounds())

        def toggle_logs(self,show=None):
            self.logs_visible=not self.logs_visible if show is None else bool(show)
            if self.logs_visible:
                self.log_panel.pack(fill='both',expand=True,padx=14,pady=(0,12));self.root.geometry('860x620')
            else:self.log_panel.pack_forget();self.root.geometry('860x300')
            self.log_toggle.configure(text='진단 로그 숨기기' if self.logs_visible else '진단 로그 보기')

        def open_records_folder(self):
            self.records_root.mkdir(exist_ok=True);os.startfile(self.records_root)

        def refresh(self):
            selected=None
            if hasattr(self,'targets') and 0<=self.windows.current()<len(self.targets):selected=self.targets[self.windows.current()][0]
            self.targets=[]
            def add(hwnd,_):
                title=win32gui.GetWindowText(hwnd)
                if title and win32gui.IsWindowVisible(hwnd) and hwnd!=self.root.winfo_id():
                    self.targets.append((hwnd,title))
            win32gui.EnumWindows(add,None)
            self.targets.sort(key=lambda x:x[1].lower())
            self.windows['values']=[f'{title} [0x{hwnd:X}]' for hwnd,title in self.targets]
            if self.targets:
                index=next((i for i,(hwnd,_) in enumerate(self.targets) if hwnd==selected),None)
                if index is None:index=next((i for i,(_,title) in enumerate(self.targets) if 'DJMAX' in title.upper()),0)
                self.windows.current(index)

        def configure_colors(self):
            for tag,color in self.cfg.customization.palette().items():
                self.text.tag_configure(tag,foreground=color)
            self.text.configure(state='normal')
            self.text.delete('1.0','end')
            for line,error in self.history:
                tag=self.cfg.customization.tag(error)
                self.text.insert('end',line+'\n',(tag,) if tag else ())
            self.text.see('end');self.text.configure(state='disabled')

        def write(self,line,error_ms=None):
            if line.startswith(('ERROR','CONFIG:','VIEWER:','오버레이 초기화 실패')) and not self.logs_visible:self.toggle_logs(True)
            self.history.append((line,error_ms))
            self.text.configure(state='normal')
            tag=self.cfg.customization.tag(error_ms)
            self.text.insert('end',line+'\n',(tag,) if tag else ())
            if len(self.history)>2000:
                del self.history[:200]
                self.text.delete('1.0','201.0')
            self.text.see('end');self.text.configure(state='disabled')
            print(line,flush=True)
            if self.logfile:self.logfile.write(line+'\n');self.logfile.flush()

        def output(self,results):
            for result in results:
                row=event_row(result,self.cfg)
                shown=display_result(result,self.cfg)
                self.viewer_state.resolve(shown)
                self.write(shown.text(),shown.error_ms)
                self.jsonfile.write(json.dumps(row,ensure_ascii=False)+'\n');self.jsonfile.flush()
                stamp=result.press if result.press is not None else result.due
                if stamp is None or stamp>self.round_cutoff:
                    if self.round_meta is None:self.round_meta=self.round_metadata()
                    self.round_buffer.add(row)

        def round_metadata(self):
            import configparser
            parser=configparser.ConfigParser();parser.read(ROOT/'config.ini',encoding='utf-8-sig')
            mode=int(self.cfg.mode) if self.cfg.mode!='auto' else 4
            section=f'{mode}LANE' if parser.has_section(f'{mode}LANE') else '6LANE'
            key_names=dict(parser[section])
            setting=self.cfg.timing.gameJudgement
            return {'game_judgement':max(-150,min(150,setting)),'chart':self.chart_name.get().strip(),
                    'mode':mode,'profile_revision':self.cfg.profileRevision,'timing_anchor_version':2,'capture_fps':self.cfg.fps,
                    'viewer_offset':self.cfg.globalOffset,'judge_y':self.cfg.judgeY,'note_skin':self.cfg.noteSkin,
                    'note_output_ms':self.cfg.timing.noteOutputMs,'judgement_unit_ms':self.cfg.timing.judgementUnitMs,
                    'reference':self.cfg.timing.reference,'gear_left':self.cfg.gearLeft,'key_names':key_names,
                    'config':asdict(self.cfg),'started_at':time.strftime('%Y-%m-%d %H:%M:%S')}

        def update_reference_status(self):
            t=self.cfg.timing
            reference='게임 보정(추정)' if t.reference=='game' else '화면 기준'
            self.reference_status.set(f'{reference} · 판정 {t.gameJudgement:g} / 출력 {t.noteOutputMs:g}ms')

        def edit_timing(self):
            from sepan.settings_window import open_settings
            return open_settings(self,ROOT)

        def choose_mode(self,event=None):
            import configparser
            parser=configparser.ConfigParser(interpolation=None);parser.optionxform=str;parser.read(ROOT/'config.ini',encoding='utf-8-sig')
            parser.set('general','mode',self.mode_value.get())
            temp=ROOT/'config.pending.ini'
            try:
                with temp.open('w',encoding='utf-8') as out:parser.write(out,space_around_delimiters=False)
                load(temp);temp.replace(ROOT/'config.ini');self.apply_config()
            except Exception as error:messagebox.showerror('버튼 수 변경 실패',str(error),parent=self.root)

        def finish_round(self,reason,cutoff=None,show=False,result_image=None):
            cutoff=(time.perf_counter_ns()-self.origin)/1e6 if cutoff is None else cutoff
            if self.running and hasattr(self,'engine'):
                self.output(self.engine.tick(cutoff))
                self.record_pending(cutoff)
                self.engine.reset()
            metadata=dict(self.round_meta or self.round_metadata());metadata['reason']=reason
            metadata['completed']=reason=='결과 화면 감지'
            if result_image:metadata['result_image']=result_image
            payload=self.round_buffer.finish(cutoff,metadata)
            if payload:payload['summary']['metadata']['excluded_future_observations']=len(self.round_buffer.rows)
            self.round_buffer.rows=[]
            self.round_cutoff=max(self.round_cutoff,cutoff);self.round_meta=None
            self.viewer_state.clear()
            if reason.startswith('F5'):
                self.result_since=None
                if hasattr(self,'restart_probe'):self.restart_probe.set()
                self.history=[];self.configure_colors()
            if payload and metadata['completed']:
                future=self.report_executor.submit(save_round,payload,self.records_root)
                self.report_jobs.append((future,show))
                self.round_status.set('한 판 기록 저장·그래프 생성 중… 다음 플레이는 계속할 수 있습니다.')
                self.write('RECORD — '+reason+' / 원본 기록을 보존하고 새 구간을 시작합니다.')
            elif not self.report_jobs:self.round_status.set('새 판 대기 — 중간 재시도·정지는 결과로 저장하지 않습니다.')
            return 'break'

        def record_pending(self,cutoff):
            for press,lane in self.engine.pending:
                if press<=cutoff:
                    row={'mode':self.engine.mode,'lane':lane,'due':None,'press':press,'note_id':None,'boundary_pending':True}
                    if self.round_meta is None:self.round_meta=self.round_metadata()
                    self.round_buffer.add(row)
                    if self.jsonfile:self.jsonfile.write(json.dumps(row)+'\n');self.jsonfile.flush()

        def check_reports(self):
            pending=[]
            for future,show in self.report_jobs:
                if not future.done():pending.append((future,show));continue
                try:
                    folder=future.result();self.last_report=folder
                    summary=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
                    stats=summary['normal'];mean=stats['mean_ms']
                    mean_text='—' if mean is None else f'{mean:+.1f}ms'
                    self.round_status.set(f"저장 완료 · 일반 입력 {stats['count']}개 · 평균 {mean_text} · 최근 결과에서 그래프 확인")
                    if summary.get('plot_error'):self.write('RECORD — 데이터는 저장됨 / 그래프 오류: '+summary['plot_error'])
                    if show and win32gui.GetForegroundWindow()==win32gui.GetAncestor(self.root.winfo_id(),2):
                        self.show_report(folder)
                except Exception as e:self.write('기록 저장 실패: '+str(e)+' / logs의 원본 기록은 유지됩니다.')
            self.report_jobs=pending

        def show_last_report(self):
            if self.last_report:self.show_report(self.last_report)
            else:self.round_status.set('저장된 결과가 아직 없습니다. 결과 화면까지 완료하면 저장됩니다.')

        def show_report(self,folder):
            from PIL import Image,ImageTk
            from sepan.report_labels import measurement_context,recommendation_lines
            folder=Path(folder);summary=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
            window=tk.Toplevel(self.root);window.title('한 판 판정 리포트 — '+folder.name)
            frame=ttk.Frame(window,padding=12);frame.pack(fill='both',expand=True)
            controls=ttk.Frame(frame);controls.pack(fill='x',pady=(0,8))
            ttk.Button(controls,text='PNG 열기',command=lambda:os.startfile(folder/'timing.png')).pack(side='left')
            if (folder/'game-result.png').exists():
                ttk.Button(controls,text='게임 결과',command=lambda:os.startfile(folder/'game-result.png')).pack(side='left',padx=6)
            ttk.Button(controls,text='기록 폴더',command=lambda:os.startfile(folder)).pack(side='left',padx=6)
            ttk.Label(controls,text='곡/패턴').pack(side='left',padx=(10,4))
            chart=tk.StringVar(value=summary['metadata'].get('chart',''))
            ttk.Entry(controls,textvariable=chart,width=22).pack(side='left')
            difficulty=tk.StringVar(value=summary['metadata'].get('difficulty') or '미확인')
            ttk.Combobox(controls,textvariable=difficulty,values=['NM','HD','MX','SC','미확인'],state='readonly',width=7).pack(side='left',padx=6)
            ttk.Label(controls,text='게임 RATE%(선택)').pack(side='left',padx=(10,4))
            rate=tk.StringVar(value='' if summary['game_rate_percent'] is None else str(summary['game_rate_percent']))
            ttk.Entry(controls,textvariable=rate,width=7).pack(side='left')
            advice=tk.StringVar()
            def recommendation():
                current=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
                compare=compare_settings(self.records_root,current)
                advice.set('\n'.join(recommendation_lines(current,compare)))
            def record_rate():
                nonlocal folder
                try:
                    if rate.get().strip():add_game_rate(folder,rate.get())
                    folder=update_chart(folder,chart.get(),difficulty.get());self.last_report=folder;recommendation()
                    self.report_jobs.append((self.report_executor.submit(refresh_round_image,folder),False))
                except Exception as e:messagebox.showerror('정확도 기록 실패',str(e),parent=window)
            ttk.Button(controls,text='수정 저장',command=record_rate).pack(side='left',padx=6)
            ttk.Label(frame,text=measurement_context(summary,self.cfg)).pack(fill='x',pady=(0,8))
            path=folder/'timing.png'
            if path.exists():
                with Image.open(path) as source:image=source.copy()
                image.thumbnail((min(1100,self.root.winfo_screenwidth()-120),min(790,self.root.winfo_screenheight()-260)))
                photo=ImageTk.PhotoImage(image);label=ttk.Label(frame,image=photo);label.image=photo;label.pack()
            else:ttk.Label(frame,text='원본 데이터는 저장됐지만 그래프를 만들지 못했습니다. 기록 폴더를 확인하세요.').pack(pady=20)
            recommendation();ttk.Label(frame,textvariable=advice,wraplength=1040,justify='left').pack(fill='x',pady=(10,0))

        def apply_config(self):
            try:
                new=load(ROOT/'config.ini')
                self.prepare_viewer(new)
            except Exception as e:
                messagebox.showerror('설정 적용 실패',f'{e}\n기존 설정을 유지합니다.')
                return
            restart=self.running and requires_restart(self.cfg,new)
            if restart:self.stop()
            elif self.running and (self.cfg.globalOffset!=new.globalOffset or self.cfg.bindings!=new.bindings or self.cfg.timing!=new.timing):
                self.finish_round('타이밍·키 설정 변경')
            self.cfg=new
            self.update_reference_status()
            self.mode_value.set(new.mode)
            self.mode_box.configure(values=['4','5','6','8'] if new.noteSkin!='original' else ['auto','4','5','6','8'])
            self.configure_colors()
            if restart:
                self.start(new)
                if self.running:self.write('CONFIG — 설정 적용 완료. 캡처 변경으로 추적을 다시 시작합니다.')
            else:
                if self.running:
                    self.engine.reconfigure(new)
                    stamp=time.perf_counter_ns()
                    (self.session_folder/f'config_applied_{stamp}.ini').write_bytes((ROOT/'config.ini').read_bytes())
                self.write('CONFIG — 설정 적용 완료.')

        def start(self,cfg=None):
            if self.running:return
            try:
                if cfg is None:
                    cfg=load(ROOT/'config.ini');cfg.mode=self.mode_value.get()
                index=self.windows.current()
                if index<0:raise ValueError('게임 창을 선택하세요.')
                self.hwnd=self.targets[index][0]
                self.prepare_viewer(cfg)
                self.cfg=cfg
                self.configure_colors()
                self.engine=Engine(cfg.globalOffset,cfg.maxWindow,cfg.judgeY,cfg.fps,cfg.minSpeed,cfg.maxSpeed,cfg.initialSpeed)
                folder=ROOT/'logs'/(time.strftime('%Y%m%d_%H%M%S')+f'_{time.perf_counter_ns()%1_000_000:06d}')
                self.session_folder=folder
                folder.mkdir(parents=True,exist_ok=True)
                self.logfile=(folder/'events.txt').open('a',encoding='utf-8')
                self.jsonfile=(folder/'events.jsonl').open('a',encoding='utf-8')
                (folder/'config.ini').write_bytes((ROOT/'config.ini').read_bytes())
                (folder/'session.json').write_text(json.dumps({'version':__version__, 'origin_qpc_ns':self.origin,
                    'selected_hwnd':self.hwnd, 'mode_override':cfg.mode, 'python':sys.version},indent=2),encoding='utf-8')
                self.stop_event=mp.Event();self.snapshot_event=mp.Event()
                self.restart_probe=mp.Event()
                self.frame_events=mp.Queue();self.key_events=mp.Queue()
                self.processes=[mp.Process(target=input_worker,args=(self.key_events,self.stop_event,self.hwnd,self.origin),daemon=True),
                    mp.Process(target=capture_worker,args=(self.frame_events,self.stop_event,self.snapshot_event,self.hwnd,self.origin,cfg,str(folder),self.restart_probe,self.desktop_overlay.hwnd if self.desktop_overlay else 0),daemon=True)]
                for p in self.processes:p.start()
                self.running=True;self.last_frame=time.perf_counter();self.key_backlog=[]
                self.start_button.configure(state='disabled');self.windows.configure(state='disabled');self.mode_box.configure(state='disabled');self.refresh_button.configure(state='disabled')
                self.write('START — 게임으로 돌아가면 측정이 시작됩니다.')
                self.status.set('캡처 / 입력 장치 초기화 중')
            except Exception as e:
                self.stop();messagebox.showerror('시작 실패',str(e))

        def stop(self):
            if self.running:self.finish_round('측정 정지')
            if hasattr(self,'stop_event'):self.stop_event.set()
            for p in self.processes:
                if p.pid is None:continue
                p.join(timeout=.35)
                if p.is_alive():p.terminate();p.join(timeout=.35)
            self.processes=[];self.running=False
            for name in ('frame_events','key_events'):
                q=getattr(self,name,None)
                if q is not None:q.close()
            if self.logfile:self.logfile.close();self.logfile=None
            if self.jsonfile:self.jsonfile.close();self.jsonfile=None
            self.start_button.configure(state='normal');self.windows.configure(state='readonly');self.mode_box.configure(state='readonly');self.refresh_button.configure(state='normal')
            self.status.set('정지됨')

        def save_snapshot(self):
            if self.running:
                self.snapshot_event.set();self.write('INFO — 게임으로 돌아가면 다음 프레임의 진단 이미지를 저장합니다.')

        def process_event(self,event):
            kind=event[0]
            if kind=='error':raise RuntimeError(event[1])
            if kind=='info':self.write('INFO — '+event[1])
            elif kind=='result_candidate':
                if event[1]>self.round_cutoff:self.result_since=event[1] if event[2] else None
            elif kind=='result_screen':
                if event[1]>self.round_cutoff:
                    self.finish_round('결과 화면 감지',cutoff=event[1],result_image=event[2])
            elif kind=='inactive':
                self.record_pending(event[1] if len(event)>1 else float('inf'))
                self.engine.reset();self.key_backlog=[]
            elif kind=='frame':
                _,t,mode,notes,cost,age,conf=event
                if t<=self.round_cutoff:return
                now=(time.perf_counter_ns()-self.origin)/1e6
                if now-t>max(500,3000/self.cfg.fps):return
                self.last_frame=time.perf_counter()
                if mode==0 and self.cfg.noteSkin!='original':
                    if self.result_since is None:self.result_since=t
                    # Preserve the last tracks and pending inputs until the
                    # stable result boundary has consumed both input queues.
                    self.status.set('결과 화면 확인 중 — 마지막 입력 보존')
                    return
                self.result_since=None
                self.output(self.engine.frame(t,mode,notes))
                speed='?' if self.engine.velocity is None else f'{self.engine.velocity:.3f}'
                self.status.set(f'{mode or "비플레이"} lane | {speed} px/ms | 인식 {cost:.1f} ms | 프레임 나이 {age:.1f} ms | {self.engine.quality}')
            elif kind=='key':
                _,t,vk,scan=event
                if t<=self.round_cutoff:return
                if vk==0x74:
                    self.finish_round('F5 재시작',cutoff=t);return
                if self.result_since is not None and t>=self.result_since:return
                if self.diagnostics.get():self.write(f'KEY vk{vk:02X} sc{scan:03X} at {t:.3f}ms')
                # The worker already checked game focus at the actual keydown.
                if not self.engine.mode and self.cfg.mode in ('4','5','6','8'):
                    self.engine.reset(int(self.cfg.mode))
                if self.engine.mode:
                    lane=identify(self.cfg.bindings[self.engine.mode],vk,scan)
                    if lane:
                        self.viewer_state.keypress(self.engine.mode,lane,t)
                        self.output(self.engine.press(t,lane))

        def poll(self):
            self.check_reports()
            if self.running:
                try:
                    for event in drain_ordered((self.frame_events,self.key_events)):
                        self.process_event(event)
                    if win32gui.GetForegroundWindow()!=self.hwnd:
                        self.record_pending((time.perf_counter_ns()-self.origin)/1e6)
                        self.engine.reset()
                        self.status.set('게임 비활성 · 결과 미확인, 기록 보류 — 결과 화면으로 돌아오세요.' if self.round_buffer.rows and self.result_since is None else '대기 — 선택한 게임을 활성화하세요.')
                    elif self.result_since is None and time.perf_counter()-self.last_frame>max(.5,3/self.cfg.fps):
                        self.record_pending((time.perf_counter_ns()-self.origin)/1e6)
                        self.engine.reset();self.status.set('대기 — 새 게임 프레임 없음')
                    elif self.result_since is None:self.output(self.engine.tick((time.perf_counter_ns()-self.origin)/1e6))
                    if self.stop_event.is_set():raise RuntimeError('작업 프로세스가 중지됐습니다. 위 오류를 확인하세요.')
                    if any(p.exitcode is not None for p in self.processes):raise RuntimeError('작업 프로세스가 종료됐습니다.')
                except Exception as e:
                    self.write('ERROR — '+str(e));self.stop()
            self.root.after(5,self.poll)

        def collect_gui_garbage(self):
            # Tk Variable/PhotoImage finalizers must run on the GUI thread,
            # including cycles left by closed settings/preset windows.
            gc.collect()
            self.gc_timer=self.root.after(5000,self.collect_gui_garbage)

        def close(self):
            self.stop()
            self.report_executor.shutdown(wait=True)
            if self.desktop_overlay:self.desktop_overlay.close()
            if self.viewer_server:self.viewer_server.close()
            if hasattr(self,'gc_timer'):self.root.after_cancel(self.gc_timer)
            self.root.destroy()

    automatic_gc=gc.isenabled();gc.disable()
    try:
        gc.collect()
        app=App()
        app.gc_timer=app.root.after(5000,app.collect_gui_garbage)
        if on_ready is not None:on_ready(app)
        app.root.mainloop()
    finally:
        gc.collect()
        if automatic_gc:gc.enable()


if __name__=='__main__':
    mp.freeze_support()
    main()
