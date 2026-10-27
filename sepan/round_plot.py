"""Shareable PNG report. All numbers come from saved measurements."""
from pathlib import Path
from .lane_labels import lane_label


def plot_round(rows,summary,path):
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.font_manager import FontProperties
    import numpy as np
    from .rounds import normal_lanes
    lanes=normal_lanes(int(summary['metadata'].get('mode',4)))
    font_path=Path('C:/Windows/Fonts/malgun.ttf')
    font=FontProperties(fname=str(font_path)) if font_path.exists() else FontProperties()
    bg='#10151F';surface='#171F2C';ink='#F0F3FA';muted='#A8B6CA';early='#65B5FF';late='#FF829A'
    fig=Figure(figsize=(12,8.6),dpi=150,facecolor=bg);FigureCanvasAgg(fig)
    matched=[r for r in rows if r.get('press') is not None and r.get('due') is not None and r['lane'] in lanes]
    errors=np.array([r.get('analysis_error_ms',r['press']-r['due']) for r in matched])
    first=min(((r['press'] if r.get('press') is not None else r.get('due',0)) for r in rows),default=0)
    t=np.array([(r['press']-first)/1000 for r in matched])
    meta=summary['metadata'];stats=summary['normal']
    text=lambda x,y,s,**kw:fig.text(x,y,s,fontproperties=font,color=kw.pop('color',ink),**kw)
    chart=meta.get('chart','').strip() or '곡·패턴 미입력'
    title=f"{meta.get('mode',4)}K {meta.get('difficulty') or '미확인'} {chart}"
    text(.06,.95,title[:75],fontsize=22 if len(title)<48 else 15,weight='bold')
    text(.94,.915,f"측정 당시 게임 판정 {meta.get('game_judgement',0):g}",ha='right',fontsize=10,color=muted)
    def fmt(value):return '—' if value is None else f'{value:+.1f}ms'
    for x,title,value in [(.06,'평균 입력차',fmt(stats['mean_ms'])),(.28,'중앙값',fmt(stats['median_ms'])),
                          (.49,'표준편차','—' if stats['std_ms'] is None else f"{stats['std_ms']:.1f}ms"),(.71,'측정된 일반 입력',str(stats['count']))]:
        text(x,.86,title,fontsize=10,color=muted);text(x,.825,value,fontsize=20,weight='bold')
    text(.06,.78,f"얼리 {stats['early']}   ·   퍼펙 {stats['perfect']}   ·   레이트 {stats['late']}",fontsize=11,color=muted)
    from .report_labels import recommendation_caption
    caption=recommendation_caption(summary)
    text(.06,.75,caption,fontsize=10,color=muted)
    def axis(rect):
        ax=fig.add_axes(rect,facecolor=surface)
        ax.tick_params(colors=muted,labelsize=8)
        for spine in ax.spines.values():spine.set_color('#344157')
        ax.grid(color='#2A3648',linewidth=.5,alpha=.7)
        return ax
    time_ax=axis([.08,.46,.86,.24]);time_ax.set_title('타이밍',fontproperties=font,color=ink,loc='left',fontsize=11,pad=12)
    if len(errors):
        colors=np.where(errors < -42,early,np.where(errors > 42,late,ink))
        time_ax.scatter(t,errors,s=8,c=colors,alpha=.65,linewidths=0,rasterized=True)
        time_ax.axhline(float(np.median(errors)),color='#D9C183',linewidth=1,linestyle='--')
    else:time_ax.text(.5,.5,'매칭된 일반 입력 없음',fontproperties=font,color=muted,ha='center',transform=time_ax.transAxes)
    limit=max(50,float(np.max(abs(errors)))+8) if len(errors) else 50
    time_ax.set_ylim(limit,-limit);time_ax.axhline(0,color=ink,linewidth=.8)
    time_ax.axhspan(-21,21,color='#B8C9DB',alpha=.055,zorder=0)
    for bound,color,alpha in ((21,'#C4D2E2',.3),(42,'#83ACD5',.85)):
        for sign in (-1,1):time_ax.axhline(sign*bound,color=color,linewidth=.8,linestyle='--',alpha=alpha)
    time_ax.set_ylabel('ms',color=muted);time_ax.set_xlabel('sec',color=muted)
    hist=axis([.08,.16,.47,.22]);hist.set_title('판정 분포',fontproperties=font,color=ink,loc='left',fontsize=11,pad=12)
    if len(errors):
        bins=np.unique(np.r_[np.linspace(-limit,limit,41),-42,42]);counts,edges=np.histogram(errors,bins)
        histogram_samples=int(counts.sum())
        mids=(edges[:-1]+edges[1:])/2
        hist.bar(mids,counts,width=np.diff(edges)*.88,color=np.where(mids < -42,early,np.where(mids > 42,late,'#B8C9DB')),linewidth=0)
    else:histogram_samples=0
    hist.axvline(0,color=ink,linewidth=.8);hist.set_xlim(-limit,limit);hist.set_xlabel('EARLY ← ms → LATE',color=muted,fontsize=9)
    hist.axvspan(-21,21,color='#B8C9DB',alpha=.055,zorder=0)
    for bound,color,alpha in ((21,'#C4D2E2',.3),(42,'#83ACD5',.85)):
        for sign in (-1,1):hist.axvline(sign*bound,color=color,linewidth=.8,linestyle='--',alpha=alpha)
    key=axis([.65,.16,.29,.22]);key.set_title('레인별 분포',fontproperties=font,color=ink,loc='left',fontsize=11,pad=12)
    data=[];labels=[]
    for lane,label in [(lane,lane_label(lane)) for lane in lanes+('A','B','L','R')]:
        values=[r.get('analysis_error_ms',r['press']-r['due']) for r in rows if r['lane']==lane and r.get('press') is not None and r.get('due') is not None]
        if values:data.append(values);labels.append(f'{label}  n={len(values)}')
    if data:
        boxes=key.boxplot(data,orientation='horizontal',tick_labels=labels,patch_artist=True,showfliers=False,whis=(10,90),widths=.5)
        for patch in boxes['boxes']:patch.set(facecolor='#365574',edgecolor='#81B4DC')
        for kind in ('whiskers','caps','medians'):
            for item in boxes[kind]:item.set_color(ink)
        key.invert_yaxis()
    key_limit=max(limit,max((max(abs(v) for v in values)+8 for values in data),default=50))
    key.axvline(0,color=ink,linewidth=.8);key.set_xlim(-key_limit,key_limit);key.set_xlabel('10–90% · ms',color=muted)
    target=Path(path);pending=target.with_name(target.stem+'.pending.png')
    try:
        # Photos can keep the old PNG memory-mapped. Replace a completed file
        # rather than truncating the image the user currently has open.
        fig.savefig(pending,facecolor=bg,dpi=150)
        pending.replace(target)
    finally:fig.clear()
    return {'scatter_samples':len(errors),'histogram_samples':histogram_samples,
            'normal_limits_ms':[-limit,limit],'key_limits_ms':[-key_limit,key_limit],
            'guides_ms':[21,42],'personal_key_labels_included':False,'estimated_percentage_included':False,
            'recommendation_caption':caption}
