"""Low-rate Windows GDI sampler for two small result labels only."""
import ctypes as C
from ctypes import wintypes as W
import cv2
import numpy as np


def scale_regions(rects,monitor):
    left,top,right,bottom=monitor;w,h=right-left,bottom-top
    return [(left+round(x0*w/1920),top+round(y0*h/1080),
             left+round(x1*w/1920),top+round(y1*h/1080)) for x0,y0,x1,y1 in rects]


class ScreenRegionSampler:
    def __init__(self,rects,monitor,source_dc=None):
        import win32gui
        self.gui=win32gui;self.dc=self.bitmap=self.old=None;self.screen=None
        self.owns_screen=source_dc is None
        self.rects=list(rects);self.native=scale_regions(rects,monitor)
        self.width=sum(r-l for l,t,r,b in self.native);self.height=max(b-t for l,t,r,b in self.native)
        g=self.g=C.WinDLL('gdi32',use_last_error=True)
        class BIH(C.Structure):
            _fields_=[('size',W.DWORD),('width',W.LONG),('height',W.LONG),('planes',W.WORD),
                      ('bitcount',W.WORD),('compression',W.DWORD),('image_size',W.DWORD),
                      ('xppm',W.LONG),('yppm',W.LONG),('colors_used',W.DWORD),('colors_important',W.DWORD)]
        g.CreateCompatibleDC.argtypes=[W.HDC];g.CreateCompatibleDC.restype=W.HDC
        g.CreateDIBSection.argtypes=[W.HDC,C.POINTER(BIH),W.UINT,C.POINTER(C.c_void_p),W.HANDLE,W.DWORD]
        g.CreateDIBSection.restype=W.HANDLE
        g.SelectObject.argtypes=[W.HDC,W.HANDLE];g.SelectObject.restype=W.HANDLE
        g.BitBlt.argtypes=[W.HDC,C.c_int,C.c_int,C.c_int,C.c_int,W.HDC,C.c_int,C.c_int,W.DWORD]
        g.BitBlt.restype=W.BOOL
        g.GdiFlush.argtypes=[];g.GdiFlush.restype=W.BOOL
        g.DeleteObject.argtypes=[W.HANDLE];g.DeleteObject.restype=W.BOOL
        g.DeleteDC.argtypes=[W.HDC];g.DeleteDC.restype=W.BOOL
        try:
            self.screen=win32gui.GetDC(None) if self.owns_screen else source_dc
            self.dc=g.CreateCompatibleDC(self.screen)
            if not self.dc:raise C.WinError(C.get_last_error())
            self.bits=C.c_void_p()
            header=BIH(C.sizeof(BIH),self.width,-self.height,1,32,0,self.width*self.height*4,0,0,0,0)
            self.bitmap=g.CreateDIBSection(self.dc,C.byref(header),0,C.byref(self.bits),None,0)
            if not self.bitmap or not self.bits.value:raise C.WinError(C.get_last_error())
            self.old=g.SelectObject(self.dc,self.bitmap)
        except Exception:
            self.close();raise
    def capture(self,normalize=True):
        x=0
        for left,top,right,bottom in self.native:
            w,h=right-left,bottom-top
            if not self.g.BitBlt(self.dc,x,0,w,h,self.screen,left,top,0x00CC0020):raise C.WinError(C.get_last_error())
            x+=w
        self.g.GdiFlush()
        pixels=np.ctypeslib.as_array((C.c_ubyte*(self.width*self.height*4)).from_address(self.bits.value)).reshape(self.height,self.width,4)
        patches=[];x=0
        for native,reference in zip(self.native,self.rects):
            left,top,right,bottom=native;w,h=right-left,bottom-top
            rl,rt,rr,rb=reference
            patch=pixels[:h,x:x+w,:3].copy();x+=w
            patches.append(cv2.resize(patch,(rr-rl,rb-rt),interpolation=cv2.INTER_AREA) if normalize else patch)
        return patches
    def close(self):
        if self.dc and self.old:self.g.SelectObject(self.dc,self.old)
        if self.bitmap:self.g.DeleteObject(self.bitmap);self.bitmap=None
        if self.dc:self.g.DeleteDC(self.dc);self.dc=None
        if self.screen and self.owns_screen:self.gui.ReleaseDC(None,self.screen)
        self.screen=None
