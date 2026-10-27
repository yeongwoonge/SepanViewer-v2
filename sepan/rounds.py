"""Per-play immutable records; visual timing estimates are not game RATE%."""
from datetime import datetime,timezone,timedelta
import json
import math
from pathlib import Path
import statistics
from bisect import bisect_left,bisect_right


def timing_stats(rows,error_key='analysis_error_ms'):
    matched=[r for r in rows if r.get('press') is not None and r.get('due') is not None]
    errors=[r.get(error_key,r['press']-r['due']) for r in matched]
    perfect=sum(abs(error)<=42 for error in errors)
    result={'count':len(errors),'mean_ms':None,'median_ms':None,'trimmed_mean_ms':None,'std_ms':None,
            'early':sum(e < -42 for e in errors),'perfect':perfect,'just':perfect,
            'late':sum(e > 42 for e in errors),'classification_window_ms':42}
    if errors:
        ordered=sorted(errors);trim=len(errors)//10
        central=ordered[trim:len(ordered)-trim] if trim else ordered
        result.update(mean_ms=statistics.mean(errors),median_ms=statistics.median(errors),
                      trimmed_mean_ms=statistics.mean(central),std_ms=statistics.pstdev(errors))
    return result


def maximum_window_candidate(errors,current,half_window_ms,unit_ms=1):
    """Count the densest judgement window over legal integer settings."""
    if not errors or not math.isfinite(unit_ms) or unit_ms<=0:return None
    ordered=sorted(errors)
    if not all(math.isfinite(error) for error in ordered):return None
    def inside(setting):
        shift=(setting-current)*unit_ms
        return bisect_right(ordered,half_window_ms-shift+1e-9)-bisect_left(ordered,-half_window_ms-shift-1e-9)
    candidate=max(range(-150,151),key=lambda setting:(inside(setting),-abs(setting-current),-abs(setting)))
    return {'recommended_setting':candidate,'current_setting':current,'half_window_ms':half_window_ms,
            'inside_current':inside(current),'inside_candidate':inside(candidate),'samples':len(ordered),
            'shift_ms':(candidate-current)*unit_ms}


def normal_lanes(mode):
    return tuple(str(i) for i in range(1,(6 if mode==8 else mode)+1))+(('3a','3b') if mode==5 else ())


def summarize(rows,metadata):
    lanes=normal_lanes(int(metadata.get('mode',4)))
    normal=[r for r in rows if r['lane'] in lanes]
    stats=timing_stats(normal)
    counts={
        'matched':sum(r.get('due') is not None and r.get('press') is not None for r in rows),
        'no_input':sum(r.get('due') is not None and r.get('press') is None for r in rows),
        'unmatched_input':sum(r.get('due') is None and r.get('press') is not None and not r.get('boundary_pending') for r in rows),
        'boundary_pending':sum(bool(r.get('boundary_pending')) for r in rows),
    }
    observed=sum(not r.get('boundary_pending') for r in normal)
    coverage=stats['count']/observed if observed else 0
    current=int(metadata.get('game_judgement',0))
    quality='insufficient' if stats['count']<100 else ('unstable' if coverage<.8 or stats['std_ms']>30 else 'usable_for_comparison')
    windows={}
    if quality=='usable_for_comparison' and metadata.get('reference')=='game':
        unit=float(metadata.get('judgement_unit_ms',1))
        errors=[r.get('analysis_error_ms',r['press']-r['due']) for r in normal
                if r.get('press') is not None and r.get('due') is not None]
        windows={name:maximum_window_candidate(errors,current,width,unit) for name,width in (('normal',42),('hard',21))}
    candidates={current-1,current,current+1}|{value['recommended_setting'] for value in windows.values() if value}
    return {'schema':3,'metadata':metadata,'counts':counts,'normal':stats,'all':timing_stats(rows),
            'normal_screen':timing_stats(normal,'screen_error_ms'),
            'normal_game_estimated':timing_stats(normal,'game_estimated_error_ms'),
            'lanes':{lane:timing_stats([r for r in rows if r['lane']==lane]) for lane in lanes+('A','B','L','R')},
            'observed_match_fraction':coverage,'quality':quality,
            'advice':{'recommended_setting':None,'current_setting':current,
                      'model_candidate_unverified':None,'window_candidates_unverified':windows,
                      'comparison_candidates':sorted(set(max(-150,min(150,value)) for value in candidates)),
                      'text':'보정된 ms도 게임 내부 판정을 직접 읽은 값은 아닙니다. 현재 설정을 기준으로 '
                             'F10 내장 조정으로 기준을 확인하고, 같은 곡·패턴을 후보값에서 반복 비교하세요. '
                             '게임 RATE%를 추가하면 동일 조건의 실제 정확도를 비교해 추천합니다.'},
            'game_rate_percent':None,
            'note':'일반·롱 노트 시작 입력을 화면상 추정 판정선 기준으로 측정합니다. 롱 노트 떼기는 측정하지 않습니다. 게임 FAST/SLOW·RATE%·실제 BREAK와 다를 수 있습니다.'}


class RoundBuffer:
    def __init__(self):self.rows=[]
    def add(self,row):
        # Copy so later engine/config changes cannot rewrite a past record.
        self.rows.append(dict(row))
    def finish(self,cutoff,metadata):
        selected=[];future=[]
        for row in self.rows:
            timestamp=row['press'] if row.get('press') is not None else row.get('due')
            (selected if timestamp is None or timestamp<=cutoff else future).append(row)
        self.rows=future
        if not selected and not metadata.get('result_image'):return None
        return {'rows':selected,'summary':summarize(selected,dict(metadata))}


def save_round(payload,root):
    summary=payload['summary'];meta=summary['metadata']
    if not meta.get('completed'):return None
    from .result_archive import next_record_folder,read_result_identity,normalize_difficulty
    result_image=meta.get('result_image')
    if result_image and (not meta.get('chart','').strip() or not meta.get('difficulty')):
        identity=read_result_identity(result_image)
        if not meta.get('chart','').strip():
            meta['chart']=identity['chart'];meta['title_source']='local_ocr' if meta['chart'] else 'unrecognized'
        if not meta.get('difficulty'):meta['difficulty']=identity['difficulty']
    meta['difficulty']=normalize_difficulty(meta.get('difficulty',''))
    mode=int(meta.get('mode',4))
    summary['saved_at']=summary.get('saved_at') or datetime.now(timezone(timedelta(hours=9))).isoformat()
    folder=next_record_folder(root,mode,meta.get('chart',''),meta['difficulty'],summary['saved_at'])
    (folder/'events.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in payload['rows']),encoding='utf-8')
    if result_image and Path(result_image).is_file():
        import shutil
        shutil.copyfile(result_image,folder/'game-result.png')
    # Preserve data and summary even if plotting is unavailable or fails.
    (folder/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        from .round_plot import plot_round
        summary['render_audit']=plot_round(payload['rows'],summary,folder/'timing.png')
        (folder/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    except Exception as error:
        summary['plot_error']=str(error)
        (folder/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    return folder


def update_chart(folder,chart,difficulty=None):
    """Correct an OCR title and keep the human-readable folder name in sync."""
    from .result_archive import record_stem,normalize_difficulty
    folder=Path(folder);path=folder/'summary.json'
    summary=json.loads(path.read_text(encoding='utf-8'));meta=summary['metadata']
    chart=chart.strip()
    if not chart:raise ValueError('곡명을 입력하세요.')
    if difficulty is not None:meta['difficulty']=normalize_difficulty(difficulty)
    stem=record_stem(meta.get('mode',4),chart,meta.get('difficulty',''))
    parent=folder.parent.parent/stem
    if folder.parent.name!=stem:
        parent.mkdir(exist_ok=True)
        previous_parent=folder.parent
        folder=folder.rename(parent/folder.name)
        if not any(previous_parent.iterdir()):previous_parent.rmdir()
    meta['chart']=chart;meta['title_source']='manual'
    path=folder/'summary.json';temp=path.with_suffix('.json.tmp')
    temp.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
    return folder


def refresh_round_image(folder):
    folder=Path(folder)
    summary=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
    rows=[json.loads(line) for line in (folder/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    fresh=summarize(rows,summary['metadata'])
    for key in ('saved_at','game_rate_percent'):
        if key in summary:fresh[key]=summary[key]
    summary=fresh
    from .round_plot import plot_round
    summary['render_audit']=plot_round(rows,summary,folder/'timing.png')
    path=folder/'summary.json';temp=path.with_suffix('.json.tmp')
    temp.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
    return folder


def compare_settings(records_root,current_summary):
    """Recommend from user-entered in-game accuracy, never estimated RATE%."""
    meta=current_summary['metadata'];label=meta.get('chart','').strip()
    if not label:return None
    groups={}
    signature=lambda m:(m.get('chart','').strip(),m.get('difficulty',''),m.get('mode',4),m.get('profile_revision',0),m.get('viewer_offset'),m.get('judge_y'),m.get('note_skin'),
                        m.get('note_output_ms'),m.get('judgement_unit_ms'),m.get('reference'),m.get('gear_left'),m.get('timing_anchor_version',1),m.get('capture_fps',m.get('config',{}).get('fps',30)))
    for path in Path(records_root).rglob('summary.json'):
        try:record=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):continue
        if signature(record.get('metadata',{}))!=signature(meta):continue
        if record.get('quality')!='usable_for_comparison':continue
        rate=record.get('game_rate_percent')
        if rate is None:continue
        groups.setdefault(int(record['metadata']['game_judgement']),[]).append(float(rate))
    # Repeated same-chart trials under at least two settings, including current.
    groups={setting:values for setting,values in groups.items() if len(values)>=2}
    current=int(meta['game_judgement'])
    if current not in groups or len(groups)<2:return None
    means={setting:statistics.mean(values) for setting,values in groups.items()}
    best=max(means,key=lambda setting:means[setting])
    if means[best]-means[current]<.01:best=current
    return {'recommended_setting':best,'rates_by_setting':means,'trials_by_setting':{k:len(v) for k,v in groups.items()},
            'basis':'같은 곡·패턴과 뷰어 조건에서 각 설정 2판 이상, 직접 입력한 게임 RATE%의 평균 비교. 반복 실험 후보 추천이며 확정 최적값이 아닙니다.'}


def add_game_rate(folder,rate,chart=None):
    rate=float(rate)
    if not math.isfinite(rate) or not 0<=rate<=100:raise ValueError('게임 RATE는 0~100 사이 숫자입니다.')
    path=Path(folder)/'summary.json'
    summary=json.loads(path.read_text(encoding='utf-8'));summary['game_rate_percent']=rate
    if chart is not None:summary['metadata']['chart']=chart.strip()
    temp=path.with_suffix('.json.tmp');temp.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
    return summary
