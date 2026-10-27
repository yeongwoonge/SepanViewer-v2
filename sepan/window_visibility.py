"""Conservative visibility check before sampling an unfocused game window."""


def overlaps(a,b):
    return a[0]<b[2] and b[0]<a[2] and a[1]<b[3] and b[1]<a[3]


def _cloaked(hwnd):
    import ctypes as C
    from ctypes import wintypes as W
    value=W.DWORD()
    api=C.WinDLL('dwmapi').DwmGetWindowAttribute
    api.argtypes=[W.HWND,W.DWORD,C.c_void_p,W.DWORD];api.restype=C.c_long
    return api(hwnd,14,C.byref(value),C.sizeof(value))==0 and bool(value.value)


def regions_visible(hwnd,rects):
    import win32gui as gui
    import win32con
    try:
        if not gui.IsWindow(hwnd) or not gui.IsWindowVisible(hwnd) or gui.IsIconic(hwnd):return False
        game=gui.GetWindowRect(hwnd)
        if not all(game[0]<=l and game[1]<=t and r<=game[2] and b<=game[3] for l,t,r,b in rects):return False
        above=gui.GetWindow(hwnd,win32con.GW_HWNDPREV);seen=set()
        while above:
            if above in seen:return False
            seen.add(above)
            if gui.IsWindowVisible(above) and any(overlaps(gui.GetWindowRect(above),r) for r in rects) and not _cloaked(above):return False
            above=gui.GetWindow(above,win32con.GW_HWNDPREV)
        return True
    except (gui.error,OSError):return False
