"""一次性客户端 POC 输入，不注册为 Agent 工具；输入前验证 HWND/PID 与前台。"""
import argparse
import ctypes as c
from ctypes import wintypes as w
import json
import subprocess
import time


class KEY(c.Structure):
    _fields_ = [('vk', w.WORD), ('scan', w.WORD), ('flags', w.DWORD), ('time', w.DWORD), ('extra', c.c_size_t)]


class MOUSE(c.Structure):
    _fields_ = [('x', w.LONG), ('y', w.LONG), ('data', w.DWORD), ('flags', w.DWORD), ('time', w.DWORD), ('extra', c.c_size_t)]


class DATA(c.Union):
    _fields_ = [('key', KEY), ('mouse', MOUSE)]


class INPUT(c.Structure):
    _fields_ = [('type', w.DWORD), ('data', DATA)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['search', 'click'])
    parser.add_argument('--x', type=float, default=.36)
    parser.add_argument('--y', type=float, default=.046)
    args = parser.parse_args()
    user = c.windll.user32
    user.SetThreadDpiAwarenessContext(c.c_void_p(-4))
    user.GetForegroundWindow.restype = w.HWND
    user.WindowFromPoint.restype = w.HWND
    user.GetAncestor.restype = w.HWND
    query = subprocess.run(['powershell', '-NoProfile', '-Command',
        'Get-Process cloudmusic | Where-Object {$_.MainWindowHandle -ne 0} | Select-Object -First 1 Id,@{n="Hwnd";e={$_.MainWindowHandle.ToInt64()}} | ConvertTo-Json -Compress'],
        capture_output=True, text=True, check=True)
    process = json.loads(query.stdout)

    def pid(hwnd):
        out = w.DWORD()
        user.GetWindowThreadProcessId(hwnd, c.byref(out))
        return out.value

    assert pid(user.GetForegroundWindow()) == process['Id'], '网易云必须位于前台，未发送任何输入'
    rect = w.RECT()
    assert user.GetWindowRect(w.HWND(process['Hwnd']), c.byref(rect))
    point = w.POINT(round(rect.left+(rect.right-rect.left)*args.x), round(rect.top+(rect.bottom-rect.top)*args.y))
    assert user.SetCursorPos(point.x, point.y), '输入桌面不可用'
    time.sleep(.08)
    assert pid(user.GetAncestor(user.WindowFromPoint(point), 2)) == process['Id'], '目标位置不属于网易云，未点击'
    user.mouse_event(2, 0, 0, 0, 0)
    user.mouse_event(4, 0, 0, 0, 0)
    if args.action == 'search':
        time.sleep(.15)
        assert pid(user.GetForegroundWindow()) == process['Id'], '前台目标变化，未发送键盘输入'
        user.keybd_event(0x11, 0, 0, 0)
        user.keybd_event(0x41, 0, 0, 0)
        user.keybd_event(0x41, 0, 2, 0)
        user.keybd_event(0x11, 0, 2, 0)
        events = []
        for ch in 'Monody TheFatRat':
            for flag in (4, 6):
                events.append(INPUT(1, DATA(key=KEY(0, ord(ch), flag, 0, 0))))
        inputs = (INPUT*len(events))(*events)
        assert user.SendInput(len(events), inputs, c.sizeof(INPUT)) == len(events)
        user.keybd_event(13, 0, 0, 0)
        user.keybd_event(13, 0, 2, 0)
    print(json.dumps({'action': args.action, 'target': 'cloudmusic.exe', 'input_sent': True}))


if __name__ == '__main__':
    main()
