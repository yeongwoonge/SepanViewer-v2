"""Allowlisted result pixels and local, one-shot title OCR after a round."""
from pathlib import Path
import json
import os
import re
import subprocess
import tempfile
import unicodedata
from functools import lru_cache
from datetime import datetime,timedelta,timezone

# 1080p reference rectangles. Never sample the player profile or right panels.
RESULT_RECTS=((775,10,1400,52),(705,83,802,108),(85,225,435,640),
              (770,680,1150,803),(890,600,1025,640),(1090,530,1230,602))
TITLE_BOX=(180,26,805,68)
DIFFICULTY_BOX=(180,72,277,97)
RESULT_SIZE=(1000,640)


def compose_result(patches,mode=4):
    from PIL import Image,ImageDraw,ImageFont
    import numpy as np
    if len(patches)!=len(RESULT_RECTS):raise ValueError('Missing safe result regions')
    canvas=Image.new('RGB',RESULT_SIZE,'#10151F');draw=ImageDraw.Draw(canvas)
    font_path=Path('C:/Windows/Fonts/malgun.ttf')
    font=ImageFont.truetype(str(font_path),30) if font_path.exists() else ImageFont.load_default()
    draw.text((30,22),f'{mode}K',font=font,fill='#F0F3FA')
    images=[Image.fromarray(np.ascontiguousarray(patch[:,:,::-1])) for patch in patches]
    canvas.paste(images[0],TITLE_BOX[:2]);canvas.paste(images[1],(180,72))
    canvas.paste(images[2],(30,155));canvas.paste(images[3],(440,170))
    small=ImageFont.truetype(str(font_path),18) if font_path.exists() else font
    draw.text((440,355),'GAME RATE',font=small,fill='#A8B6CA')
    canvas.paste(images[4],(440,395));canvas.paste(images[5],(710,370))
    return canvas


def redact_legacy_result(image,mode=4):
    """Import an old full screenshot through exactly the same allowlist."""
    import numpy as np
    from PIL import Image,ImageOps
    if image.size==RESULT_SIZE:return image.copy()
    normalized=image.convert('RGB').resize((1920,1080),Image.Resampling.LANCZOS)
    return compose_result([np.asarray(normalized.crop(rect))[:,:,::-1] for rect in RESULT_RECTS],mode)


def normalize_difficulty(text):
    value=re.sub('[^A-Z0-9]','',str(text).upper())
    return {'NORMAL':'NM','NM':'NM','HARD':'HD','HD':'HD','MAXIMUM':'MX','MX':'MX',
            'MAX1MUM':'MX','MAXIMUN':'MX','SC':'SC','5C':'SC'}.get(value,'')


def badge_mask(image):
    import numpy as np
    from PIL import Image
    pixels=np.asarray(image.convert('RGB'))[3:-3,3:-3].astype(np.int16)
    high=pixels.max(axis=2);low=pixels.min(axis=2)
    return Image.fromarray(np.where((high>120)&((high-low>45)|(low>180)),255,0).astype(np.uint8))


@lru_cache(maxsize=1)
def _difficulty_templates():
    import cv2
    root=Path(__file__).resolve().parents[1]/'assets'
    return [(name,cv2.imread(str(root/f'difficulty_{name.lower()}.png'),0)) for name in ('SC','MX')]


def match_difficulty_badge(image):
    import cv2,numpy as np
    mask=np.asarray(badge_mask(image))
    if not np.any(mask):return ''
    padded=cv2.copyMakeBorder(mask,2,2,2,2,cv2.BORDER_CONSTANT,value=0)
    scores=[]
    for name,template in _difficulty_templates():
        if template is None or template.shape!=mask.shape:continue
        scores.append((float(cv2.minMaxLoc(cv2.matchTemplate(padded,template,cv2.TM_CCOEFF_NORMED))[1]),name))
    scores.sort(reverse=True)
    return scores[0][1] if scores and scores[0][0]>=.88 and (len(scores)==1 or scores[0][0]-scores[1][0]>.12) else ''


def read_result_identity(result_path):
    """No network, service, persistent OCR worker, or full-screen OCR."""
    from PIL import Image,ImageOps
    exe=Path(os.environ.get('SystemRoot','C:/Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        with Image.open(result_path) as source:known_difficulty=match_difficulty_badge(source.crop(DIFFICULTY_BOX))
    except OSError:return {'chart':'','difficulty':''}
    empty={'chart':'','difficulty':known_difficulty}
    if not exe.exists():return empty
    try:
        with tempfile.TemporaryDirectory(prefix='SepanTitle_') as directory:
            path=Path(directory)/'title.png'
            badge_path=Path(directory)/'difficulty.png'
            with Image.open(result_path) as image:
                title=image.crop(TITLE_BOX).convert('L').point(lambda value:0 if value>205 else 255)
                bounds=ImageOps.invert(title).getbbox()
                if bounds is not None:title=title.crop(bounds)
                title=title.resize((title.width*2,title.height*2))
                ImageOps.expand(title,border=40,fill=255).convert('RGB').save(path)
                badge=ImageOps.invert(badge_mask(image.crop(DIFFICULTY_BOX)))
                bounds=ImageOps.invert(badge).getbbox()
                if bounds is not None:badge=badge.crop(bounds)
                badge=badge.resize((badge.width*3,badge.height*3))
                ImageOps.expand(badge,border=40,fill=255).convert('RGB').save(badge_path)
            process=subprocess.run([str(exe),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
                                    '-File',str(Path(__file__).with_name('result_title.ps1')),'-ImagePath',str(path),'-BadgePath','' if known_difficulty else str(badge_path)],
                                   stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=12,
                                   creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if process.returncode:return empty
            fields=json.loads(process.stdout.decode('utf-8-sig').strip())
            return {'chart':' '.join(str(fields.get('title','')).split()),
                    'difficulty':known_difficulty or normalize_difficulty(fields.get('difficulty',''))}
    except (OSError,ValueError,subprocess.TimeoutExpired):return empty


def read_title(result_path):return read_result_identity(result_path)['chart']


def safe_title(title):
    title=unicodedata.normalize('NFC',str(title))
    title=re.sub(r'[<>:"/\\|?*\x00-\x1f]',' ',title)
    return re.sub(r'\s+',' ',title).strip(' .')[:90].rstrip(' .') or '곡명미확인'


def record_stem(mode,title,difficulty=''):
    return f'{mode}K {normalize_difficulty(difficulty) or "미확인"} {safe_title(title)}'


def record_sort_key(name):
    """Match Explorer's natural number ordering, including 2 before 10."""
    return tuple((0,int(part)) if part.isdecimal() else (1,part.casefold()) for part in re.split(r'(\d+)',str(name)))


def recorded_time_key(summary_path):
    path=Path(summary_path)
    for fmt in ('%Y-%m-%d_%H-%M-%S','%Y-%m-%d_%H-%M-%S.%f'):
        try:return datetime.strptime(path.parent.name,fmt).replace(tzinfo=timezone(timedelta(hours=9))).timestamp()
        except ValueError:pass
    try:return datetime.fromisoformat(json.loads(path.read_text(encoding='utf-8'))['saved_at']).timestamp()
    except (OSError,ValueError,KeyError):return path.stat().st_mtime


def next_record_folder(root,mode,title,difficulty='',saved_at=None):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    stem=record_stem(mode,title,difficulty)
    parent=root/stem;parent.mkdir(exist_ok=True)
    stamp=datetime.fromisoformat(saved_at) if saved_at else datetime.now(timezone(timedelta(hours=9)))
    name=stamp.strftime('%Y-%m-%d_%H-%M-%S')
    while True:
        folder=parent/name
        try:folder.mkdir(exist_ok=False);return folder
        except FileExistsError:
            name=stamp.strftime('%Y-%m-%d_%H-%M-%S.%f');stamp+=timedelta(microseconds=1)
