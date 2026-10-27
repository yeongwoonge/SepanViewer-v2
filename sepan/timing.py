"""Explicit visual vs estimated-game references; no hidden game memory reads."""
from .engine import Result


def correction_ms(cfg):
    # Positive judgment asks for earlier hits; positive note output delays the
    # visual note against chart time. Convert captured visual time only once.
    if cfg.timing.reference=='screen':return 0.
    return cfg.timing.gameJudgement*cfg.timing.judgementUnitMs+cfg.timing.noteOutputMs


def display_result(result,cfg):
    due=None if result.due is None else result.due-correction_ms(cfg)
    return Result(result.mode,result.lane,due,result.press,result.note_id)


def event_row(result,cfg):
    from dataclasses import asdict
    row=asdict(result)
    if result.due is not None and result.press is not None:
        base=result.press-result.due
        row['screen_error_ms']=base+cfg.globalOffset
        row['viewer_error_ms']=base
        row['game_estimated_error_ms']=base+cfg.timing.gameJudgement*cfg.timing.judgementUnitMs+cfg.timing.noteOutputMs
        row['analysis_error_ms']=base+correction_ms(cfg)
        row['analysis_printed_error_ms']=display_result(result,cfg).error_ms
    return row
