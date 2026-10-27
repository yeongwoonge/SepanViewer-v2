"""Replay supplied stills or a user-recorded video without a Windows machine."""
import argparse
from pathlib import Path
import json
import time
import cv2
from sepan.vision import Detector,detect_mode
from sepan.engine import Engine
from sepan.config import load


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--video',type=Path)
    parser.add_argument('--config',type=Path,default=Path(__file__).resolve().parent/'config.ini')
    parser.add_argument('--mode',choices=['auto','4','5','6','8'])
    parser.add_argument('--fps',type=int)
    parser.add_argument('--output',type=Path,default=Path('diagnostics'))
    parser.add_argument('--trigger-color',choices=['orange','default'])
    parser.add_argument('--side-color',choices=['teal','default'])
    args=parser.parse_args()
    cfg=load(args.config)
    args.mode=args.mode or cfg.mode
    args.fps=args.fps or cfg.fps
    if not 2 <= args.fps <= 120:parser.error('--fps must be 2..120')
    if cfg.noteSkin!='original' and args.mode=='auto':parser.error('Choose --mode 4, 5, 6 or 8 for note presets')
    args.output.mkdir(parents=True,exist_ok=True)
    cv2.setNumThreads(1)
    detector=Detector(threshold=cfg.noteThreshold,max_y=cfg.maxDetectY,note_skin=cfg.noteSkin,
                      trigger_color=args.trigger_color or cfg.triggerColor,side_color=args.side_color or cfg.sideColor,
                      profile_path=Path(__file__).resolve().parent/cfg.noteProfile if cfg.noteProfile else None)
    if args.video:
        cap=cv2.VideoCapture(str(args.video))
        if not cap.isOpened():raise SystemExit(f'Cannot open {args.video}')
        rate=cap.get(cv2.CAP_PROP_FPS)
        if rate<=0:raise SystemExit('Video has no usable frame rate')
        engine=Engine(fps=args.fps,offset=cfg.globalOffset,window=cfg.maxWindow,judge_y=cfg.judgeY,
                      min_speed=cfg.minSpeed,max_speed=cfg.maxSpeed,initial_speed=cfg.initialSpeed)
        index=0;next_time=0;previous_time=-1
        with (args.output/'video.jsonl').open('w',encoding='utf-8') as out:
            while True:
                ok,im=cap.read()
                if not ok:break
                t=cap.get(cv2.CAP_PROP_POS_MSEC)
                if t<=previous_time:t=index*1000/rate
                previous_time=t;index+=1
                if t+1e-6<next_time:continue
                next_time+=1000/args.fps
                left=cfg.gearLeft if cfg.noteSkin!='original' else 720
                im=cv2.resize(im,(1920,1080),interpolation=cv2.INTER_AREA)[0:900,left:left+480]
                mode,_=detect_mode(im) if args.mode=='auto' else (int(args.mode),1)
                detections=detector.detect(im,mode)
                results=engine.frame(t,mode,detections)+engine.tick(t)
                out.write(json.dumps({'t':t,'mode':mode,'velocity':engine.velocity,
                    'detections':[d.__dict__ for d in detections],
                    'events':[r.text() for r in results]})+'\n')
        cap.release()
        print('Video report:',args.output/'video.jsonl')
        print('Video timestamps are decoder presentation times with a CFR fallback; this is not live keyboard validation.')
        return
    if cfg.noteSkin!='original':parser.error('Supply --video for note presets.')
    engine=Engine();report=[];timings=[]
    root=Path(__file__).resolve().parent
    for i in range(1,5):
        im=cv2.imread(str(root/'examples'/f'ex{i}.png'))[0:900,720:1200]
        start=time.perf_counter();mode,confidence=detect_mode(im)
        detections=detector.detect(im,mode)
        elapsed=(time.perf_counter()-start)*1000;timings.append(elapsed)
        row={'file':f'ex{i}.png','mode':mode,'processing_ms':elapsed,
             'detections':[d.__dict__ for d in detections]}
        report.append(row)
        print(row['file'],f'{mode} lanes, {elapsed:.1f}ms',[(d.lane,round(d.y,2)) for d in detections])
        cv2.imwrite(str(args.output/f'ex{i}_detected.png'),detector.annotate(im,mode,detections))
        if i in (1,2):engine.frame(0 if i==1 else 83.33,mode,detections)
    print(f'Estimated speed: {engine.velocity:.6f} px/ms')
    print('Predicted note times, assuming ex1 is t=0ms and offset=0:')
    predictions=[]
    for n in sorted(engine.notes,key=lambda n:n.due):
        print(f'{n.lane}: {n.due:.3f} ms')
        predictions.append({'lane':n.lane,'due_ms':n.due})
    (args.output/'examples.json').write_text(json.dumps({'frames':report,'speed':engine.velocity,
        'predictions':predictions},indent=2),encoding='utf-8')


if __name__=='__main__':main()
