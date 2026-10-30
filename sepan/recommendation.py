"""Round-balanced window search with independent-round stability checks.

This evaluates saved visual timing estimates, not game-internal judgments.
No fitted model, external service, or extra capture work is involved.
"""
import math
import numpy as np


def _validation_summary(gains,settings):
    if not gains:return {'rounds':0,'mean_gain_per_1000':None,'lower_gain_per_1000':None,'settings':[]}
    gains=np.asarray(gains,dtype=float)
    # Resample whole held-out rounds. Individual notes are not independent trials.
    rng=np.random.default_rng(0)
    samples=gains[rng.integers(0,len(gains),(1024,len(gains)))].mean(axis=1)
    return {'rounds':len(gains),'mean_gain_per_1000':float(gains.mean()*1000),
            'lower_gain_per_1000':float(np.quantile(samples,.05)*1000),
            'improved_rounds':int(np.count_nonzero(gains>1e-12)),
            'worse_rounds':int(np.count_nonzero(gains < -1e-12)),
            'settings':[int(s) for s in settings]}


def recommend_window(groups,current,half_window_ms,unit_ms=1):
    if not math.isfinite(unit_ms) or unit_ms<=0 or not math.isfinite(half_window_ms) or half_window_ms<=0:return None
    if not math.isfinite(current) or current!=int(current) or not -150<=current<=150:return None
    arrays=[np.sort(np.asarray(group,dtype=float)) for group in groups if len(group)]
    if not arrays or any(not np.isfinite(group).all() for group in arrays):return None
    current=int(current);settings=np.arange(-150,151);current_index=current+150
    shifts=(settings-current)*unit_ms
    counts=[];margins=[]
    for errors in arrays:
        lo=np.searchsorted(errors,-half_window_ms-shifts-1e-9,side='left')
        hi=np.searchsorted(errors,half_window_ms-shifts+1e-9,side='right')
        count=hi-lo;counts.append(count)
        left=errors[np.minimum(lo,len(errors)-1)]+shifts
        right=errors[np.maximum(hi-1,0)]+shifts
        # Among equally successful settings, keep accepted notes away from edges.
        margins.append(np.where(count>0,half_window_ms-np.maximum(abs(left),abs(right)),np.inf))
    counts=np.asarray(counts);margins=np.asarray(margins)
    sizes=np.asarray([len(g) for g in arrays]);rates=counts/sizes[:,None]
    prefix_rates=np.cumsum(rates,axis=0);prefix_counts=np.cumsum(counts,axis=0)
    prefix_margins=np.minimum.accumulate(margins,axis=0)
    suffix_margins=np.minimum.accumulate(margins[::-1],axis=0)[::-1]
    def choose(scores,hits,safety):
        if hits.max()==0:return current
        # Do not trade away total measured perfects merely to balance rounds.
        feasible=hits>=hits[current_index]
        best=float(scores[feasible].max())
        indices=np.flatnonzero(feasible&(scores>=best-1e-12))
        best_margin=float(safety[indices].max())
        indices=[i for i in indices if safety[i]>=best_margin-1e-9]
        return int(min((settings[i] for i in indices),key=lambda s:(abs(s-current),abs(s))))
    proposed=choose(prefix_rates[-1]/len(arrays),prefix_counts[-1],prefix_margins[-1])
    n=len(arrays);loo_gains=[];loo_settings=[];future_gains=[];future_settings=[]
    if n>=3:
        for i in np.unique(np.linspace(0,n-1,min(n,24),dtype=int)):
            safety=np.full(301,np.inf)
            if i:safety=np.minimum(safety,prefix_margins[i-1])
            if i+1<n:safety=np.minimum(safety,suffix_margins[i+1])
            setting=choose((prefix_rates[-1]-rates[i])/(n-1),prefix_counts[-1]-counts[i],safety)
            loo_settings.append(setting)
            loo_gains.append(float(rates[i,setting+150]-rates[i,current_index]))
    # Only earlier rounds choose a setting for the next, unseen round.
    for i in range(max(3,n-24),n):
        setting=choose(prefix_rates[i-1]/i,prefix_counts[i-1],prefix_margins[i-1])
        future_settings.append(setting)
        future_gains.append(float(rates[i,setting+150]-rates[i,current_index]))
    loo=_validation_summary(loo_gains,loo_settings)
    forward=_validation_summary(future_gains,future_settings)
    recommended=proposed
    if n==1:status='single_round'
    elif n<6:status='provisional'
    else:
        positive=loo['mean_gain_per_1000'] is not None and loo['mean_gain_per_1000']>0 and forward['mean_gain_per_1000'] is not None and forward['mean_gain_per_1000']>0
        supported=positive and forward['lower_gain_per_1000']>0
        status=('supported' if supported else 'provisional') if positive and proposed!=current else 'hold'
        if status=='hold':recommended=current
    all_counts=prefix_counts[-1]
    return {'recommended_setting':recommended,'candidate_setting':proposed,'current_setting':current,
            'half_window_ms':half_window_ms,'inside_current':int(all_counts[current_index]),
            'inside_candidate':int(all_counts[recommended+150]),'proposed_inside':int(all_counts[proposed+150]),
            'samples':int(sizes.sum()),'rounds':n,'shift_ms':float((recommended-current)*unit_ms),
            'status':status,'method':'equal-round-window-and-margin-v1',
            'leave_one_round_out':loo,'walk_forward':forward}


def recommendation_status(candidate):
    return {'single_round':'한 판 후보','provisional':'잠정 후보',
            'supported':'반복 기록 지지','hold':'현재 유지'}.get(candidate.get('status'),'추정 후보')
