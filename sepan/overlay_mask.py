"""Hide our own window from recognition without blocking screen recorders."""
import math


def mask_overlay(roi,window_rect,capture_rect):
    if window_rect is None:return roi,None
    left,top,right,bottom=capture_rect
    x0,y0,x1,y1=window_rect
    if right<=left or bottom<=top:return roi,None
    h,w=roi.shape[:2]
    x0=max(0,math.floor((x0-left)*w/(right-left)))
    y0=max(0,math.floor((y0-top)*h/(bottom-top)))
    x1=min(w,math.ceil((x1-left)*w/(right-left)))
    y1=min(h,math.ceil((y1-top)*h/(bottom-top)))
    if x1<=x0 or y1<=y0:return roi,None
    masked=roi.copy();masked[y0:y1,x0:x1]=0
    return masked,(x0,y0,x1,y1)


def outside_overlay(note,rect,mode):
    if rect is None:return True
    x0,y0,x1,y1=rect
    # Blacking out a broad side/trigger body must not create a false head at
    # the mask edge. Existing confirmed tracks can bridge the hidden section.
    margin=16 if note.kind in ('side','trigger') else 0
    if not y0-margin<=note.y<=y1+margin:return True
    if note.lane.isdigit():
        lanes=6 if mode==8 else mode
        left=(int(note.lane)-1)*480/lanes;right=int(note.lane)*480/lanes
    else:left,right=(0,240) if note.lane in ('A','L') else (240,480)
    return right<=x0 or left>=x1
