"""CYTUS 4B heads, normalized to the original 480px centered playfield."""
from pathlib import Path
import cv2
import numpy as np
from .vision import Detection
from .template_match import peaks


class Cytus4Detector:
    def __init__(self, assets, threshold=.82, max_y=610,profile_path=None):
        self.threshold, self.max_y = threshold, max_y
        self.templates = []
        self.anchors = [0.,0.]
        self.base_lane_width=120;self.colors=None;self.scaled={}
        if profile_path:
            from .note_profile import load_detector_profile
            self.templates,self.base_lane_width,self.colors,self.anchors=load_detector_profile(profile_path)
            return
        for color in ('blue', 'pink'):
            path = Path(assets) / f'cytus4_{color}.png'
            template = cv2.imread(str(path))
            if template is None:
                raise FileNotFoundError(f'Missing CYTUS template: {path}')
            # This rectangle sits entirely inside the lower semicircle. Avoiding
            # a large masked correlation makes 30fps practical on the CPU.
            template = cv2.cvtColor(template[:40,20:89], cv2.COLOR_BGR2GRAY)
            self.templates.append(template)

    def detect(self, roi, mode):
        if mode not in (4,5,6,8):raise ValueError('Select mode 4, 5, 6 or 8.')
        lanes=6 if mode==8 else mode
        scale=(480/lanes)/self.base_lane_width
        if lanes not in self.scaled:
            self.scaled[lanes]=[cv2.resize(template,(max(7,round(template.shape[1]*scale)),max(4,round(template.shape[0]*scale))),interpolation=cv2.INTER_AREA)
                                if abs(scale-1)>.001 else template for template in self.templates]
        gray = cv2.cvtColor(roi[:750,:480],cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(roi[:750,:480],cv2.COLOR_BGR2HSV)
        colored = None if self.colors else cv2.inRange(hsv,(75,85,125),(179,255,255))>0
        if self.colors:
            from .note_profile import color_mask
        notes = []
        for lane in range(lanes):
            center = round(480*(lane+.5)/lanes)
            candidates = []
            for template_index,(template,anchor) in enumerate(zip(self.scaled[lanes],self.anchors)):
                h, w = template.shape[:2]
                x0 = round(center-(w-1)/2)-3
                band = gray[:min(750, self.max_y+h+2), x0:x0+w+6]
                for score,precise_y in peaks(band,template,self.threshold):
                    y=round(precise_y)
                    if 1 <= y <= self.max_y:
                        sample_w=max(7,round(20*480/lanes/120));sample_h=max(8,round(25*480/lanes/120))
                        if self.colors:
                            patch=hsv[y:y+sample_h,center-sample_w:center+sample_w]
                            support=(color_mask(patch,self.colors['normal1'])|color_mask(patch,self.colors['normal2'])).mean()
                        else:support=colored[y:y+sample_h,center-sample_w:center+sample_w].mean()
                        if support < (.35 if self.colors else .4):
                            continue
                        actual_scale=h/self.templates[template_index].shape[0]
                        candidates.append((score,precise_y+(anchor+.5)*actual_scale-.5))
            selected = []
            for score,y in sorted(candidates, reverse=True):
                if all(abs(y-d.y)>55*480/lanes/120 for d in selected):
                    selected.append(Detection(str(lane+1),float(y),score))
            notes.extend(selected)
        notes.extend(self._sides(roi,hsv=hsv))
        if mode==8:notes.extend(self._sides(roi,trigger=True,hsv=hsv))
        return sorted(notes,key=lambda d:(d.lane,d.y))

    def _sides(self, roi,trigger=False,hsv=None):
        if hsv is None:hsv=cv2.cvtColor(roi[:750,:480],cv2.COLOR_BGR2HSV)
        mask=cv2.inRange(hsv,(20,140,130),(38,255,255))>0
        envelope=cv2.inRange(hsv,(15,90,85),(40,255,255))>0
        if trigger or self.colors:
            from .note_profile import color_mask
            color=self.colors['trigger' if trigger else 'side'] if self.colors else '#00F63B'
            mask=color_mask(hsv,color,10);envelope=color_mask(hsv,color,15)
        lane_names=('L','R') if trigger else ('A','B')
        notes=[]
        for side in range(2):
            x0,x1=side*240+5,side*240+235
            m=mask[:,x0:x1]
            cs=np.vstack([np.zeros((1,m.shape[1]),dtype=np.int16),np.cumsum(m,axis=0,dtype=np.int16)])
            sums=cs[3:]-cs[:-3]
            support=((sums[:-3]>=2)&(sums[3:]<=1)).mean(axis=1)
            for idx in np.flatnonzero(support>=.32):
                bottom=int(idx)+3
                y=bottom-(13 if trigger else 10)
                if not 0<y<=self.max_y:
                    continue
                below=envelope[bottom+4:bottom+13,x0:x1]
                if not below.size or below.mean()>.32:
                    continue
                same=[d for d in notes if d.lane==lane_names[side] and abs(d.y-y)<8]
                d=Detection(lane_names[side],float(y),float(support[idx]),'trigger' if trigger else 'side')
                if not same:
                    notes.append(d)
                elif d.confidence>same[0].confidence:
                    notes.remove(same[0]);notes.append(d)
        return notes
