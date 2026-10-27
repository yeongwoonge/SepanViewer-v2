"""Screenshot presets are prepared once; gameplay uses small local templates."""
from pathlib import Path
import json
import time
from functools import lru_cache
import numpy as np
import cv2
from PIL import Image

DEFAULT_RECTS={'field':[20,0,500,490],'normal1':[421,152,498,228],
               'normal2':[341,192,418,268],'side':[30,35,225,80],'trigger':[32,325,55,340]}
DEFAULT_COLORS={'normal1':'#06D8F4','normal2':'#FF279D','side':'#FFEE00','trigger':'#00F63B'}


def image_from_hud(image):
    image=image.convert('RGB')
    if image.width>=1280 and abs(image.width/image.height-16/9)<.04:
        return image.resize((1920,1080),Image.Resampling.LANCZOS).crop((1180,240,1700,730))
    if image.width>2400 or image.height>1800:
        image.thumbnail((2400,1800))
    return image


def dominant_color(image):
    rgb=np.asarray(image.convert('RGB'));hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    foreground=hsv[:,:,2]>110
    if not np.any(foreground):raise ValueError('밝은 노트 부분이 없습니다. 노트가 들어오도록 영역을 다시 지정하세요.')
    valid=foreground&(hsv[:,:,1]>70)
    if valid.sum()<foreground.sum()*.45:
        selected=rgb[foreground&(hsv[:,:,1]<=70)]
        return '#'+''.join(f'{int(c):02X}' for c in np.median(selected,axis=0))
    histogram=np.bincount(hsv[:,:,0][valid],minlength=180)
    hue=int(np.argmax(histogram));distance=np.minimum(abs(hsv[:,:,0].astype(int)-hue),180-abs(hsv[:,:,0].astype(int)-hue))
    selected=rgb[valid&(distance<=6)]
    return '#'+''.join(f'{int(c):02X}' for c in np.median(selected,axis=0))


@lru_cache(maxsize=128)
def _color_ranges(color,tolerance):
    rgb=np.array([[[int(color[i:i+2],16) for i in (1,3,5)]]],np.uint8)
    h,s,v=map(int,cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)[0,0])
    if s<45:return (((0,0,int(max(100,v*.55))+1),(179,99,255)),)
    low_s=int(max(50,s*.35))+1;low_v=int(max(70,v*.4))+1
    lo=h-tolerance;hi=h+tolerance
    hues=((0,hi),(180+lo,179)) if lo<0 else (((lo,179),(0,hi-180)) if hi>=180 else ((lo,hi),))
    return tuple(((int(a),low_s,low_v),(int(b),255,255)) for a,b in hues)


def color_mask(hsv,color,tolerance=18):
    ranges=_color_ranges(color,tolerance)
    mask=cv2.inRange(hsv,*ranges[0])
    for bounds in ranges[1:]:mask=cv2.bitwise_or(mask,cv2.inRange(hsv,*bounds))
    return mask>0


def load_editor_profile(root,use_saved=True):
    path=Path(root)/'profiles/current/profile.json'
    if use_saved and path.exists():
        try:
            data=json.loads(path.read_text(encoding='utf-8'))
            with Image.open(path.parent/'image.png') as source:image=source.convert('RGB')
            return image,data
        except (OSError,ValueError,KeyError):pass
    with Image.open(Path(root)/'assets/preset_example.png') as source:image=source.convert('RGB')
    return image,{'rects':{key:list(value) for key,value in DEFAULT_RECTS.items()},
                  'colors':dict(DEFAULT_COLORS),'preview_lanes':6}


def note_center(image,rect,color):
    """Find the sampled note, rather than treating selection padding as timing."""
    left,top,right,bottom=map(int,rect)
    sample=np.asarray(image.crop((left,top,right,bottom)).convert('RGB'))
    # Color gradients and animated highlights need not be centered. Use the
    # silhouette on the black playfield; close small gaps in patterned borders.
    # Gameplay color edits must not move the timing origin of this picture.
    mask=(sample.max(axis=2)>110).astype(np.uint8)
    mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    count,labels,stats,centers=cv2.connectedComponentsWithStats(mask)
    candidates=[s for s in stats[1:] if s[4]>=12 and s[2]>=4 and s[3]>=2]
    if not candidates:raise ValueError('선택한 노트 색을 찾지 못했습니다. 노트 영역과 색을 확인하세요.')
    x,y,w,h,area=max(candidates,key=lambda s:int(s[4]))
    return float(left+x+(w-1)/2),float(top+y+(h-1)/2)


def build_caps(image,data):
    rects=data['rects'];lanes=int(data['preview_lanes'])
    if lanes not in (4,5,6):raise ValueError('사진 속 레인 수는 4·5·6 중에서 고르세요.')
    field=rects['field'];lane_width=(field[2]-field[0])/lanes
    if lane_width<15:raise ValueError('기어 안쪽의 좌우 폭을 먼저 지정하세요.')
    caps=[];anchors=[]
    for name in ('normal1','normal2'):
        left,top,right,bottom=map(int,rects[name])
        if left<0 or top<0 or right>image.width or bottom>image.height or right-left<12 or bottom-top<8:
            raise ValueError('노트 1·2의 테두리까지 포함해 영역을 지정하세요.')
        if right-left>lane_width*1.5:raise ValueError('노트 한 개만 포함하도록 영역을 좁혀 주세요.')
        # The physical note center is independent of empty selection margins.
        # Keep its fractional position explicitly: template top need not be it.
        cx,cy=note_center(image,rects[name],data['colors'][name])
        trim=max(1,round((right-left)*.18));middle=int(np.floor(cy))
        padding=max(2,round(lane_width*.075))
        cap=np.asarray(image.crop((left+trim,middle,right-trim,min(image.height,bottom+padding))))
        if cv2.cvtColor(cap,cv2.COLOR_RGB2GRAY).std()<5:
            raise ValueError('노트의 테두리와 모양이 포함되도록 영역을 다시 지정하세요.')
        caps.append(cap);anchors.append(cy-middle)
    return caps,anchors,lane_width


def save_profile(root,image,data):
    root=Path(root);folder=root/'profiles/current';folder.mkdir(parents=True,exist_ok=True)
    caps,anchors,lane_width=build_caps(image,data)
    pending=[]
    for name,cap in zip(('normal1','normal2'),caps):
        target=folder/(name+'.png');temp=folder/(name+'.pending.png')
        Image.fromarray(cap).save(temp);pending.append((temp,target))
    image.save(folder/'image.pending.png')
    for temp,target in pending:temp.replace(target)
    (folder/'image.pending.png').replace(folder/'image.png')
    manifest={**data,'base_lane_width':lane_width,'revision':time.time_ns(),
              'caps':['normal1.png','normal2.png'],'anchor_policy':'foreground-center-v1',
              'cap_anchor_y':anchors}
    temp=folder/'profile.pending.json';temp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(folder/'profile.json')
    return manifest


def load_detector_profile(path):
    path=Path(path);data=json.loads(path.read_text(encoding='utf-8'))
    # Older profiles stored a rectangle midpoint as the template's origin.
    # Rebuild locally at startup without overwriting a user's saved profile.
    if data.get('anchor_policy')!='foreground-center-v1' and (path.parent/'image.png').exists():
        with Image.open(path.parent/'image.png') as source:
            caps,anchors,lane_width=build_caps(source.convert('RGB'),data)
        return [cv2.cvtColor(cap,cv2.COLOR_RGB2GRAY) for cap in caps],lane_width,data['colors'],anchors
    templates=[]
    for name in data['caps']:
        if Path(name).name!=name:raise ValueError('Invalid note template filename')
        image=cv2.imread(str(path.parent/name),0)
        if image is None or image.size<20:raise ValueError('노트 프리셋 이미지가 없습니다.')
        templates.append(image)
    anchors=data.get('cap_anchor_y',[0.]*len(templates))
    if len(anchors)!=len(templates) or any(not np.isfinite(y) or y<0 or y>=template.shape[0] for y,template in zip(anchors,templates)):
        raise ValueError('Invalid note timing anchors')
    return templates,float(data['base_lane_width']),data['colors'],anchors
