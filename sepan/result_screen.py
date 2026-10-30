"""Two text anchors from the user's result UI; no idle-time song guessing."""
from pathlib import Path
import cv2
import numpy as np

ANCHORS=(('result_judgement.png',(85,225,345,277)),('result_score.png',(768,670,885,730)))


class ResultScreenDetector:
    def __init__(self,assets=None):
        root=Path(assets or Path(__file__).resolve().parents[1]/'assets')
        self.anchors=[]
        for filename,rect in ANCHORS:
            image=cv2.imread(str(root/filename),0)
            if image is None:raise FileNotFoundError(root/filename)
            self.anchors.append((image,rect))
    def detect(self,wide_roi):
        if wide_roi.shape[0]<730 or wide_roi.shape[1]<885:return False
        patches=[wide_roi[top:bottom,left:right] for _,(left,top,right,bottom) in self.anchors]
        return self.detect_patches(patches)
    def detect_patches(self,patches):
        if len(patches)!=len(self.anchors):return False
        for (template,_),patch in zip(self.anchors,patches):
            if patch.shape[0]<template.shape[0] or patch.shape[1]<template.shape[1]:return False
            region=cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY)
            _,score,_,_=cv2.minMaxLoc(cv2.matchTemplate(region,template,cv2.TM_CCOEFF_NORMED))
            if score<.84:return False
        return True


class ResultLatch:
    def __init__(self,stable_ms=700):self.stable_ms=stable_ms;self.since=None;self.saved=False;self.last_seen=None
    def observe(self,t,is_result,ready=True):
        if not is_result:self.since=None;self.saved=False;self.last_seen=None;return False
        self.last_seen=t
        if self.since is None:self.since=t
        if ready and not self.saved and t-self.since>=self.stable_ms:
            self.saved=True;return True
        return False

    def finish_cached(self,t,has_snapshot,max_age_ms=1000):
        # Only a result already seen and safely captured in this attempt may
        # finish on focus loss. Inactivity alone never completes a round.
        if has_snapshot and self.since is not None and not self.saved and self.last_seen is not None and 0<=t-self.last_seen<=max_age_ms:
            self.saved=True;return True
        return False


def result_brightness(patches):
    """Follow the bright lettering, not the animated background average."""
    values=[]
    for patch in patches:
        gray=cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY) if patch.ndim==3 else patch
        pixels=gray.reshape(-1)
        if not len(pixels):return 0.
        count=min(64,len(pixels))
        values.append(float(np.partition(pixels,len(pixels)-count)[-count:].mean()))
    return min(values) if values else 0.


class ResultAppearance:
    """Wait for the fade to settle using the existing two small probes."""
    def __init__(self,min_age_ms=1000,stable_ms=400,max_wait_ms=2500):
        self.min_age_ms=min_age_ms;self.stable_ms=stable_ms;self.max_wait_ms=max_wait_ms
        self.reset()
    def reset(self):self.since=None;self.stable_since=None;self.baseline=None;self.level=0.
    def observe(self,t,is_result,patches):
        if not is_result:self.reset();return False
        self.level=result_brightness(patches)
        if self.since is None:self.since=t
        if self.baseline is None or abs(self.level-self.baseline)>3:
            self.baseline=self.level;self.stable_since=t
        age=t-self.since
        return age>=self.max_wait_ms or (age>=self.min_age_ms and t-self.stable_since>=self.stable_ms)


class ProbeSchedule:
    """Bound probe work independently of the gameplay capture FPS."""
    def __init__(self,hz=2):self.interval=1/hz;self.next=0
    def due(self,now):
        if now<self.next:return False
        self.next=now+self.interval;return True
    def defer(self,now):self.next=now+self.interval
