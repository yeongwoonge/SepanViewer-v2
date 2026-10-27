"""Locate candidate heads cheaply, then measure each at full resolution."""
import cv2
import numpy as np


def peaks(band,template,threshold):
    h,w=template.shape
    small=cv2.resize(template,(max(2,round(w/2)),max(2,round(h/2))),interpolation=cv2.INTER_AREA)
    # Fine striped skins can lose all contrast when reduced. Keep the exact
    # search for those rather than making their detection unreliable.
    reduced_contrast=float(small.std())
    if reduced_contrast<5 or reduced_contrast<float(template.std())*.65:
        spans=[(0,band.shape[0]-h+1)]
    else:
        reduced=cv2.resize(band,(max(small.shape[1],round(band.shape[1]/2)),max(small.shape[0],round(band.shape[0]/2))),interpolation=cv2.INTER_AREA)
        coarse=cv2.matchTemplate(reduced,small,cv2.TM_CCOEFF_NORMED)
        scores=np.nan_to_num(coarse,nan=-1,posinf=-1,neginf=-1).max(axis=1)
        maxima=(scores>=max(.3,threshold-.2))&(scores==cv2.dilate(scores[:,None],np.ones((7,1),np.uint8))[:,0])
        scale=band.shape[0]/reduced.shape[0]
        spans=[]
        for y in np.flatnonzero(maxima):
            origin=round(y*scale)
            lo=max(0,origin-6);hi=min(band.shape[0]-h+1,origin+7)
            if hi<=lo:continue
            if spans and lo<=spans[-1][1]:spans[-1]=(spans[-1][0],max(hi,spans[-1][1]))
            else:spans.append((lo,hi))
    found=[]
    for lo,hi in spans:
        result=cv2.matchTemplate(band[lo:hi+h-1],template,cv2.TM_CCOEFF_NORMED)
        scores=np.nan_to_num(result,nan=-1,posinf=-1,neginf=-1).max(axis=1)
        maxima=(scores>=threshold)&(scores==cv2.dilate(scores[:,None],np.ones((15,1),np.uint8))[:,0])
        for y in np.flatnonzero(maxima):
            # A refinement-window edge is not an established local maximum.
            if (y==0 and lo>0) or (y==len(scores)-1 and hi<band.shape[0]-h+1):continue
            delta=0.
            if 0<y<len(scores)-1:
                a,b,c=map(float,scores[y-1:y+2]);den=a-2*b+c
                if den< -1e-6:delta=float(np.clip(.5*(a-c)/den,-.5,.5))
            found.append((float(scores[y]),lo+y+delta))
    return found
