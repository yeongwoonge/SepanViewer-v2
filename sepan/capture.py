import time
import traceback
import statistics
from collections import deque
from pathlib import Path


def capture_worker(events,stop,snapshot,target_hwnd,origin_ns,cfg,session_dir,restart_probe=None,overlay_hwnd=0):
    import ctypes
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    import cv2
    import dxcam
    import win32gui
    import win32api
    from .vision import Detector,detect_mode
    from .overlay_mask import mask_overlay,outside_overlay
    from .window_visibility import regions_visible
    cv2.setNumThreads(1)
    camera = None
    probe = None
    try:
        camera = dxcam.create(device_idx=cfg.deviceIndex,output_idx=cfg.outputIndex,
                              backend='dxgi',output_color='BGR',max_buffer_len=4)
        # DXcam 0.3.0 has no public monitor-name accessor. This guarded access is
        # intentionally isolated here, and the dependency is pinned accordingly.
        name = camera._output.devicename
        monitor = win32api.MonitorFromWindow(target_hwnd,2)
        info = win32api.GetMonitorInfo(monitor)
        if info['Device'].lower() != name.lower():
            raise RuntimeError(f'Wrong DXcam output: {name}; game is on {info["Device"]}. '
                               'Set deviceIndex/outputIndex in config.ini.\n'+dxcam.output_info())
        left,top,right,bottom = info['Monitor']
        w,h = right-left,bottom-top
        if abs(w/h-16/9) > .01:
            raise RuntimeError('This version needs a 16:9 monitor / borderless game.')
        def check_window():
            if not win32gui.IsWindow(target_hwnd): raise RuntimeError('Selected game window was closed.')
            rect = win32gui.GetClientRect(target_hwnd)
            pos = win32gui.ClientToScreen(target_hwnd,(0,0))
            if abs(pos[0]-left)>2 or abs(pos[1]-top)>2 or abs(rect[2]-w)>2 or abs(rect[3]-h)>2:
                raise RuntimeError('Use borderless fullscreen on the selected monitor, then restart.')
        check_window()
        personal=cfg.noteSkin!='original'
        roi_h = 900 if cfg.mode == 'auto' else 750
        roi_w = 480
        lane_left=cfg.gearLeft if personal else 720
        region = (round(w*lane_left/1920),0,round(w*(lane_left+480)/1920),round(h*roi_h/1080))
        capture_rect=(left+region[0],top+region[1],left+region[2],top+region[3])
        is_result=False;pending_result_image=''
        if personal:
            from .result_screen import ResultScreenDetector,ResultLatch,ProbeSchedule,ANCHORS
            from .screen_regions import ScreenRegionSampler
            try:
                result_detector=ResultScreenDetector();result_latch=ResultLatch()
                probe_schedule=ProbeSchedule(cfg.resultPollHz)
                probe=ScreenRegionSampler([rect for _,rect in ANCHORS],info['Monitor'])
                events.put(('info',f'Result probe: 2 small regions, {cfg.resultPollHz:g} Hz; no full-screen analysis'))
            except Exception as error:
                events.put(('info',f'결과 자동 감지 사용 불가: {error}. 완료 결과만 저장하므로 자동 기록이 중지됩니다.'))
        def capture_regions_allowed(rects):
            return not win32gui.IsIconic(target_hwnd) and (win32gui.GetForegroundWindow()==target_hwnd or regions_visible(target_hwnd,rects))
        def cache_result_image(t):
            shot=None
            try:
                from .result_archive import RESULT_RECTS,compose_result
                shot=ScreenRegionSampler(RESULT_RECTS,info['Monitor'])
                if not capture_regions_allowed(shot.native):return ''
                pixels=shot.capture()
                if not capture_regions_allowed(shot.native):return ''
                path=Path(session_dir)/f'game_result_{round(t):09d}.png'
                compose_result(pixels,int(cfg.mode) if cfg.mode!='auto' else 4).save(path)
                return str(path)
            except Exception as error:
                events.put(('info',f'게임 결과 이미지 저장 실패: {error}. 통계는 저장합니다.'))
                return ''
            finally:
                if shot is not None:shot.close()
        profile_path=Path(__file__).resolve().parents[1]/cfg.noteProfile if cfg.noteProfile else None
        detector = Detector(threshold=cfg.noteThreshold,max_y=cfg.maxDetectY,trigger_color=cfg.triggerColor,side_color=cfg.sideColor,note_skin=cfg.noteSkin,profile_path=profile_path)
        camera.start(region=region,target_fps=cfg.fps,video_mode=True)
        events.put(('info',f'DXGI ready: {name}, ROI {region}, {cfg.fps} fps'))
        previous_ts = None
        recent=deque();last_metrics=time.perf_counter()
        while not stop.is_set():
            packet = camera.get_latest_frame(with_timestamp=True)
            if packet is None: continue
            frame,ts = packet
            start = time.perf_counter()
            clock=time.perf_counter()
            active=win32gui.GetForegroundWindow()==target_hwnd and not win32gui.IsIconic(target_hwnd)
            if probe is not None:
                if restart_probe is not None and restart_probe.is_set():
                    restart_probe.clear();is_result=False;pending_result_image='';result_latch=ResultLatch();probe_schedule.defer(clock)
                if not active and pending_result_image and not result_latch.saved and not capture_regions_allowed(probe.native) and result_latch.finish_cached((time.perf_counter_ns()-origin_ns)/1e6,True):
                    events.put(('result_screen',result_latch.since,pending_result_image))
                    events.put(('info','RESULT — 알트탭 전에 확보한 결과 화면으로 저장 완료 처리'))
                if probe_schedule.due(clock) and capture_regions_allowed(probe.native):
                    try:
                        probe_t=(time.perf_counter_ns()-origin_ns)/1_000_000
                        old_result=is_result
                        patches=probe.capture()
                        if not capture_regions_allowed(probe.native):continue
                        is_result=result_detector.detect_patches(patches)
                        if is_result!=old_result:events.put(('result_candidate',probe_t,is_result))
                        if is_result and result_latch.since is None:
                            pending_result_image=cache_result_image(probe_t)
                        elif not is_result:pending_result_image=''
                        if result_latch.observe(probe_t,is_result):
                            # Keep the ordinary settled result image when it is
                            # visible; the earlier copy is only a focus-loss fallback.
                            settled_image=cache_result_image(probe_t) or pending_result_image
                            events.put(('result_screen',result_latch.since,settled_image))
                    except Exception as error:
                        probe.close();probe=None;is_result=False
                        events.put(('result_candidate',(time.perf_counter_ns()-origin_ns)/1e6,False))
                        events.put(('info',f'결과 자동 감지 중지: {error}. 완료 결과만 저장하므로 자동 기록이 중지됩니다.'))
            if not active:
                events.put(('inactive',(time.perf_counter_ns()-origin_ns)/1_000_000))
                continue
            check_window()
            # Result probes also run on static frames with repeated timestamps.
            if ts is None or ts <= 0 or ts == previous_ts: continue
            if abs(time.perf_counter()-ts) > 10:
                raise RuntimeError('DXGI and QPC timestamps disagree; timing measurement stopped.')
            previous_ts = ts
            t = ts*1000-origin_ns/1_000_000
            roi = cv2.resize(frame,(roi_w,roi_h),interpolation=cv2.INTER_AREA) if frame.shape[:2] != (roi_h,roi_w) else frame
            overlay_rect=None
            if overlay_hwnd and win32gui.IsWindow(overlay_hwnd) and win32gui.IsWindowVisible(overlay_hwnd):
                try:overlay_rect=win32gui.GetWindowRect(overlay_hwnd)
                except win32gui.error:pass
            roi,masked_rect=mask_overlay(roi,overlay_rect,capture_rect)
            mode,confidence = detect_mode(roi) if cfg.mode == 'auto' else (int(cfg.mode),1.0)
            if is_result:mode=0
            notes = detector.detect(roi,mode) if mode else []
            notes=[note for note in notes if outside_overlay(note,masked_rect,mode)]
            elapsed = (time.perf_counter()-start)*1000
            age = (time.perf_counter_ns()-origin_ns)/1_000_000-t
            events.put(('frame',t,mode,notes,elapsed,age,confidence))
            recent.append((t,elapsed))
            while recent and t-recent[0][0]>2000:recent.popleft()
            if clock-last_metrics>=10 and len(recent)>1:
                actual=(len(recent)-1)*1000/(recent[-1][0]-recent[0][0])
                costs=sorted(value for stamp,value in recent)
                p95=costs[min(len(costs)-1,int((len(costs)-1)*.95))]
                events.put(('info',f'CAPTURE — actual {actual:.1f} / target {cfg.fps} fps; processing median {statistics.median(costs):.1f}ms / p95 {p95:.1f}ms'))
                last_metrics=clock
            if snapshot.is_set():
                snapshot.clear()
                path = Path(session_dir)/f'frame_{round(t):09d}'
                cv2.imwrite(str(path.with_suffix('.png')),roi)
                cv2.imwrite(str(path)+'_detected.png',detector.annotate(roi,mode,notes))
                import json
                path.with_suffix('.json').write_text(json.dumps({'time_ms':t,'mode':mode,
                    'detections':[d.__dict__ for d in notes]},indent=2),encoding='utf-8')
                events.put(('info',f'Snapshot saved: {path.name}'))
    except Exception:
        events.put(('error','Capture: '+traceback.format_exc()))
        stop.set()
    finally:
        if probe is not None:probe.close()
        if camera is not None: camera.release()
