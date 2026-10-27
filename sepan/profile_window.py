"""Paste/import a HUD preset, drag note samples, and edit their colors."""
from pathlib import Path
import configparser
import tkinter as tk
from tkinter import ttk,filedialog,messagebox,colorchooser
from PIL import Image,ImageTk,ImageGrab
from .note_profile import load_editor_profile,image_from_hud,DEFAULT_RECTS,DEFAULT_COLORS,dominant_color,save_profile,note_center


class ProfileEditor:
    def __init__(self,app,root_path,parent):
        self.app,self.root_path=app,Path(root_path)
        self.window=tk.Toplevel(parent);self.window.title('노트·색 프리셋');self.window.resizable(False,False)
        self.window.profile_editor=self
        frame=ttk.Frame(self.window,padding=14);frame.pack(fill='both',expand=True)
        row=ttk.Frame(frame);row.pack(fill='x')
        ttk.Button(row,text='이미지 불러오기',command=self.open_file).pack(side='left')
        ttk.Button(row,text='붙여넣기 (Ctrl+V)',command=self.paste).pack(side='left',padx=6)
        ttk.Label(row,text='사진 속 일반 레인').pack(side='left',padx=(18,4))
        self.lanes=tk.StringVar(value='6')
        ttk.Combobox(row,textvariable=self.lanes,values=['4','5','6'],state='readonly',width=4).pack(side='left')
        row=ttk.Frame(frame);row.pack(fill='x',pady=10)
        self.target=tk.StringVar(value='normal1')
        for key,label in [('field','기어 폭'),('normal1','노트 1'),('normal2','노트 2'),('side','사이드 색'),('trigger','트리거 색')]:
            ttk.Radiobutton(row,text=label,value=key,variable=self.target).pack(side='left',padx=(0,12))
        self.canvas=tk.Canvas(frame,highlightthickness=0,bg='#10151F');self.canvas.pack()
        self.canvas.bind('<ButtonPress-1>',self.down);self.canvas.bind('<B1-Motion>',self.drag);self.canvas.bind('<ButtonRelease-1>',self.up)
        self.hint=tk.StringVar(value='노트 1·2는 테두리까지 드래그하세요. 십자는 측정 기준 중심입니다. 사이드·트리거는 색을 고르세요.')
        ttk.Label(frame,textvariable=self.hint,wraplength=750).pack(fill='x',pady=8)
        self.swatches={};row=ttk.Frame(frame);row.pack(fill='x')
        for key,label in [('normal1','노트 1'),('normal2','노트 2'),('side','사이드'),('trigger','트리거')]:
            ttk.Label(row,text=label).pack(side='left',padx=(0,4))
            button=tk.Button(row,width=9,command=lambda key=key:self.choose_color(key));button.pack(side='left',padx=(0,12));self.swatches[key]=button
        row=ttk.Frame(frame);row.pack(fill='x',pady=(12,0))
        ttk.Button(row,text='기본으로 복원',command=self.restore).pack(side='left')
        ttk.Button(row,text='닫기',command=self.window.destroy).pack(side='right')
        ttk.Button(row,text='프리셋 적용',command=self.apply).pack(side='right',padx=6)
        self.image,self.data=load_editor_profile(root_path);self.lanes.set(str(self.data['preview_lanes']))
        self.start=None;self.redraw()
        self.window.bind('<Control-v>',lambda event:self.paste())
        self.window.bind('<Control-V>',lambda event:self.paste())
    def redraw(self):
        thumb=self.image.copy();thumb.thumbnail((760,420));self.scale=thumb.width/self.image.width
        self.photo=ImageTk.PhotoImage(thumb);self.canvas.configure(width=thumb.width,height=thumb.height)
        self.canvas.delete('all');self.canvas.create_image(0,0,image=self.photo,anchor='nw')
        for key,rect in self.data['rects'].items():
            color='#FFFFFF' if key=='field' else self.data['colors'][key]
            coords=[round(value*self.scale) for value in rect]
            self.canvas.create_rectangle(*coords,outline=color,width=2,dash=(4,3) if key=='field' else ())
            if key in ('normal1','normal2'):
                try:
                    x,y=note_center(self.image,rect,color);x*=self.scale;y*=self.scale
                    self.canvas.create_line(x-7,y,x+7,y,fill='white',width=1)
                    self.canvas.create_line(x,y-7,x,y+7,fill='white',width=1)
                except ValueError:pass
        for key,button in self.swatches.items():
            color=self.data['colors'][key];brightness=sum(int(color[i:i+2],16) for i in (1,3,5))
            button.configure(bg=color,activebackground=color,fg='black' if brightness>420 else 'white',text=color)
    def set_image(self,image):
        if image.width*image.height>25_000_000:raise ValueError('이미지를 5000×5000 이하 크기로 줄여 주세요.')
        candidate=image_from_hud(image)
        if candidate.width<200 or candidate.height<140:raise ValueError('노트와 기어가 보이는 더 큰 이미지를 불러오세요.')
        self.image=candidate;sx,sy=self.image.width/520,self.image.height/490
        self.data={'preview_lanes':6,'colors':dict(DEFAULT_COLORS),
                   'rects':{key:[round(value*(sx if index%2==0 else sy)) for index,value in enumerate(rect)] for key,rect in DEFAULT_RECTS.items()}}
        missing=[]
        for key in self.data['colors']:
            try:self.data['colors'][key]=dominant_color(self.image.crop(self.data['rects'][key]))
            except ValueError:missing.append(key)
        self.lanes.set('6');self.redraw()
        self.hint.set('이미지를 불러왔습니다. 기어 폭과 노트 1·2 영역을 확인한 뒤 적용하세요.' if not missing else '노트가 없는 영역이 있습니다. 해당 노트·색 부분을 다시 드래그하세요.')
    def open_file(self):
        path=filedialog.askopenfilename(parent=self.window,title='플레이 HUD 프리셋 화면',filetypes=[('이미지','*.png *.jpg *.jpeg *.bmp *.webp')])
        if path:
            try:
                with Image.open(path) as image:self.set_image(image)
            except (OSError,ValueError) as error:messagebox.showerror('이미지 열기 실패',str(error),parent=self.window)
    def paste(self):
        try:
            data=ImageGrab.grabclipboard()
            if isinstance(data,list) and data:
                with Image.open(data[0]) as image:self.set_image(image)
            elif isinstance(data,Image.Image):self.set_image(data)
            else:self.hint.set('클립보드에 이미지가 없습니다. 스크린샷이나 이미지 파일을 복사하세요.')
        except (OSError,ValueError) as error:self.hint.set('붙여넣기 실패: '+str(error))
        return 'break'
    def point(self,event):
        return (max(0,min(self.image.width,round(event.x/self.scale))),max(0,min(self.image.height,round(event.y/self.scale))))
    def down(self,event):self.start=self.point(event)
    def drag(self,event):
        if self.start is None:return
        end=self.point(event);self.canvas.delete('selection')
        self.canvas.create_rectangle(self.start[0]*self.scale,self.start[1]*self.scale,end[0]*self.scale,end[1]*self.scale,outline='white',width=2,tags='selection')
    def up(self,event):
        if self.start is None:return
        x,y=self.point(event);sx,sy=self.start;self.start=None
        rect=[min(sx,x),min(sy,y),max(sx,x),max(sy,y)];target=self.target.get()
        if target=='field':rect[1]=0;rect[3]=self.image.height
        if rect[2]-rect[0]<4 or rect[3]-rect[1]<4:return
        self.data['rects'][target]=rect
        if target!='field':
            try:self.data['colors'][target]=dominant_color(self.image.crop(rect))
            except ValueError as error:self.hint.set(str(error))
        self.redraw()
    def choose_color(self,key):
        color=colorchooser.askcolor(self.data['colors'][key],parent=self.window,title='노트 색')[1]
        if color:self.data['colors'][key]=color.upper();self.redraw()
    def write_config(self,skin,revision=0):
        parser=configparser.ConfigParser(interpolation=None);parser.optionxform=str;parser.read(self.root_path/'config.ini',encoding='utf-8-sig')
        parser.set('general','noteSkin',skin);parser.set('general','noteProfile','profiles/current/profile.json' if skin=='custom' else '')
        parser.set('general','profileRevision',str(revision))
        temp=self.root_path/'config.pending.ini'
        with temp.open('w',encoding='utf-8') as out:parser.write(out,space_around_delimiters=False)
        from .config import load
        load(temp);temp.replace(self.root_path/'config.ini');self.app.apply_config()
    def apply(self):
        try:
            self.data['preview_lanes']=int(self.lanes.get());manifest=save_profile(self.root_path,self.image,self.data)
            self.write_config('custom',manifest['revision']);self.window.destroy()
        except Exception as error:messagebox.showerror('프리셋 적용 실패',str(error),parent=self.window)
    def restore(self):self.write_config('cytus4');self.window.destroy()


def open_profile_editor(app,root_path,parent):return ProfileEditor(app,root_path,parent).window
