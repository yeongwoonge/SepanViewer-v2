"""Keep recorded settings, current settings, and unapplied candidates distinct."""


def measurement_context(summary,cfg):
    meta=summary['metadata']
    recorded=f"측정 당시: 게임 판정 {meta.get('game_judgement',0):g} · 뷰어 보정 {meta.get('viewer_offset',0):+g}ms"
    current=f"현재 설정: 게임 판정 {cfg.timing.gameJudgement:g} · 뷰어 보정 {cfg.globalOffset:+g}ms"
    return recorded+'    |    '+current


def recommendation_lines(summary,comparison=None):
    from .recommendation import recommendation_status
    lines=[]
    for name,label in (('normal','노말 ±42ms'),('hard','하드 ±21ms')):
        candidate=summary['advice'].get('window_candidates_unverified',{}).get(name)
        if candidate:
            lines.append(f"{label}: 게임 판정 예상 후보 {candidate['recommended_setting']} · {recommendation_status(candidate)} · 범위 내 {candidate['inside_current']} → {candidate['inside_candidate']} / {candidate['samples']}개")
    if comparison:lines.append(f"실제 RATE 비교 후보 {comparison['recommended_setting']}")
    return lines or ['예상 후보: 측정 데이터 부족 또는 불안정']


def recommendation_caption(summary):
    candidates=summary.get('advice',{}).get('window_candidates_unverified',{})
    parts=[]
    for name,label in (('normal','노말 ±42ms'),('hard','하드 ±21ms')):
        candidate=candidates.get(name)
        if candidate is not None and candidate.get('recommended_setting') is not None:
            parts.append(f"{label} {candidate['recommended_setting']}")
    return '게임 판정 추천 후보(추정)   ·   '+'   /   '.join(parts) if parts else '게임 판정 추천 보류 · 데이터 부족 또는 불안정'
