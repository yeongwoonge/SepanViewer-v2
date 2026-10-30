"""Read completed archives without changing records or averaging recommendations."""
import json
import math
import statistics
from pathlib import Path

from .rounds import error_stats,normal_lanes
from .recommendation import recommend_window,recommendation_status
from .result_archive import recorded_time_key


def same_measurement_conditions(meta,cfg):
    expected={'profile_revision':cfg.profileRevision,'viewer_offset':cfg.globalOffset,
              'judge_y':cfg.judgeY,'note_skin':cfg.noteSkin,'note_output_ms':cfg.timing.noteOutputMs,
              'judgement_unit_ms':cfg.timing.judgementUnitMs,'reference':'game',
              'gear_left':cfg.gearLeft,'timing_anchor_version':2}
    saved_config=meta.get('config') or {}
    fps=meta.get('capture_fps',saved_config.get('fps',30))
    return cfg.timing.reference=='game' and fps==cfg.fps and all(meta.get(key)==value for key,value in expected.items())


def collect_overall(records_root,mode,cfg):
    mode=int(mode)
    if mode not in (4,5,6,8):raise ValueError('지원하지 않는 버튼 수입니다.')
    lanes=normal_lanes(mode);errors=[];per_round=[];eligible_errors=[];eligible_rounds=0;eligible_groups=[]
    skipped=0;empty=0;invalid_rows=0
    for path in sorted(Path(records_root).rglob('summary.json')):
        try:
            summary=json.loads(path.read_text(encoding='utf-8'));meta=summary['metadata']
            if int(meta.get('mode',4))!=mode:continue
            completed=meta.get('completed')
            if completed is not True and not (completed is None and meta.get('reason')=='결과 화면 감지'):continue
            round_errors=[];observed=0;bad=0
            with path.with_name('events.jsonl').open(encoding='utf-8-sig') as stream:
                for line in stream:
                    if not line.strip():continue
                    row=json.loads(line)
                    if row.get('lane') not in lanes:continue
                    if not row.get('boundary_pending'):observed+=1
                    if row.get('press') is None or row.get('due') is None:continue
                    value=row.get('analysis_error_ms')
                    if value is None:
                        correction=float(meta.get('game_judgement',0))*float(meta.get('judgement_unit_ms',1))+float(meta.get('note_output_ms',0)) if meta.get('reference')=='game' else 0
                        value=float(row['press'])-float(row['due'])+correction
                    try:value=float(value)
                    except (TypeError,ValueError):bad+=1;continue
                    if not math.isfinite(value):bad+=1;continue
                    round_errors.append(value)
            if not round_errors:empty+=1;continue
            mean=statistics.mean(round_errors)
            compatible=same_measurement_conditions(meta,cfg)
            usable=len(round_errors)/max(1,observed)>=.8 and statistics.pstdev(round_errors)<=30
            adjusted=[]
            if compatible and usable:
                shift=(cfg.timing.gameJudgement-float(meta.get('game_judgement',0)))*cfg.timing.judgementUnitMs
                if math.isfinite(shift):adjusted=[error+shift for error in round_errors]
            stamp=recorded_time_key(path)
        except (OSError,ValueError,TypeError,KeyError,AttributeError):skipped+=1;continue
        errors.extend(round_errors);invalid_rows+=bad
        per_round.append({'order':stamp,'recorded_at':summary.get('saved_at',path.parent.name),
                          'count':len(round_errors),'mean_ms':mean,
                          'game_judgement':meta.get('game_judgement',0)})
        if adjusted:eligible_errors.extend(adjusted);eligible_rounds+=1;eligible_groups.append((stamp,adjusted))
    per_round.sort(key=lambda item:item['order'])
    windows={}
    if eligible_rounds>=2 and len(eligible_errors)>=100 and statistics.pstdev(eligible_errors)<=30:
        groups=[group for stamp,group in sorted(eligible_groups,key=lambda item:item[0])]
        windows={name:recommend_window(groups,int(cfg.timing.gameJudgement),width,cfg.timing.judgementUnitMs)
                 for name,width in (('normal',42),('hard',21))}
    return {'schema':2,'mode':mode,'round_count':len(per_round),'normal':error_stats(errors),
            'per_round_mean_ms':statistics.mean(item['mean_ms'] for item in per_round) if per_round else None,
            'errors':errors,'per_round':per_round,'skipped_records':skipped,'empty_records':empty,
            'invalid_rows':invalid_rows,'recommendation_rounds':eligible_rounds,
            'recommendation_samples':len(eligible_errors),'current_setting':cfg.timing.gameJudgement,
            'recommendations':windows}


def plot_overall(data,path):
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.font_manager import FontProperties
    import numpy as np
    bg='#10151F';surface='#171F2C';ink='#F0F3FA';muted='#A8B6CA'
    font_path=Path('C:/Windows/Fonts/malgun.ttf')
    font=FontProperties(fname=str(font_path)) if font_path.exists() else FontProperties()
    fig=Figure(figsize=(12,7),dpi=150,facecolor=bg);FigureCanvasAgg(fig)
    text=lambda x,y,s,**kw:fig.text(x,y,s,fontproperties=font,color=kw.pop('color',ink),**kw)
    stats=data['normal'];errors=np.asarray(data['errors'])
    fmt=lambda n:'—' if n is None else f'{n:+.1f}ms'
    text(.06,.94,f"{data['mode']}K 전체 통계",fontsize=23,weight='bold')
    text(.94,.94,f"{data['round_count']}판 · 일반 입력 {stats['count']:,}개",fontsize=11,ha='right',color=muted)
    text(.06,.89,'전체 기록 · 측정 당시 오차 기준',fontsize=10,color=muted)
    for x,label,value in ((.06,'입력 전체 평균',fmt(stats['mean_ms'])),(.29,'판별 평균의 평균',fmt(data['per_round_mean_ms'])),
                          (.53,'중앙값',fmt(stats['median_ms'])),(.75,'표준편차','—' if stats['std_ms'] is None else f"{stats['std_ms']:.1f}ms")):
        text(x,.81,label,fontsize=11,color=muted);text(x,.76,value,fontsize=23)
    text(.06,.69,f"얼리 {stats['early']:,}   ·   퍼펙 {stats['perfect']:,}   ·   레이트 {stats['late']:,}",fontsize=12,color=muted)
    def axis(rect,title):
        ax=fig.add_axes(rect,facecolor=surface)
        ax.set_title(title,fontproperties=font,color=ink,loc='left',fontsize=12,pad=14)
        ax.tick_params(colors=muted,labelsize=9)
        for spine in ax.spines.values():spine.set_color('#344157')
        ax.grid(color='#2A3648',linewidth=.5,alpha=.7)
        return ax
    hist=axis([.08,.24,.49,.35],'전체 입력 분포')
    limit=max(60,float(np.max(abs(errors)))+5) if len(errors) else 60
    if len(errors):
        edges=np.unique(np.r_[np.linspace(-limit,limit,49),-42,-21,0,21,42])
        counts,edges=np.histogram(errors,edges);mids=(edges[:-1]+edges[1:])/2
        hist.bar(mids,counts,width=np.diff(edges)*.88,color=np.where(mids < -42,'#65B5FF',np.where(mids > 42,'#FF829A','#B8C9DB')))
    hist.axvspan(-21,21,color='#B8C9DB',alpha=.055)
    hist.axvline(0,color=ink,linewidth=1)
    for width,alpha in ((21,.35),(42,.85)):
        for sign in (-1,1):hist.axvline(sign*width,color='#83ACD5',alpha=alpha,linestyle='--',linewidth=1)
    hist.set_xlim(-limit,limit);hist.set_xlabel('EARLY ← ms → LATE',color=muted)
    trend=axis([.66,.24,.28,.35],'판별 평균 입력차')
    means=[item['mean_ms'] for item in data['per_round']]
    if means:trend.plot(range(1,len(means)+1),means,color='#B8C9DB',marker='o',markersize=3,linewidth=1)
    trend.axhline(0,color=ink,linewidth=1)
    if stats['mean_ms'] is not None:trend.axhline(stats['mean_ms'],color='#E2CA8A',linestyle='--',linewidth=1)
    trend.set_xlabel('플레이 순서',fontproperties=font,color=muted);trend.set_ylabel('ms',color=muted)
    text(.06,.14,f"현재 조건 추천 · 집계 {data['recommendation_rounds']}판 / 전체 {data['round_count']}판 · 기준 판정 {data['current_setting']:g}",fontsize=11,color=muted)
    parts=[]
    for key,label in (('normal','노말 ±42ms'),('hard','하드 ±21ms')):
        candidate=data['recommendations'].get(key)
        if candidate:parts.append(f"{label} {candidate['recommended_setting']} · {recommendation_status(candidate)} ({candidate['inside_current']:,} → {candidate['inside_candidate']:,}개)")
    if parts:
        for i,part in enumerate(parts):text(.06,.09-i*.04,part,fontsize=12)
    else:text(.06,.09,'추천 보류 · 현재 조건에서 안정적인 2판·100입력 이상 필요',fontsize=12)
    target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
    pending=target.with_name(target.stem+'.pending.png')
    try:fig.savefig(pending,facecolor=bg);pending.replace(target)
    finally:fig.clear()
    return target


def build_overall_report(records_root,mode,cfg,output_root):
    data=collect_overall(records_root,mode,cfg)
    root=Path(output_root);root.mkdir(parents=True,exist_ok=True)
    path=plot_overall(data,root/f'{mode}K-overall.png')
    payload={key:value for key,value in data.items() if key!='errors'}
    target=path.with_suffix('.json');pending=target.with_suffix('.pending.json')
    pending.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');pending.replace(target)
    return data,path
