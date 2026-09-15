"""月圆之夜断网工具 - 入口"""
import os
import sys
import ctypes

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from src.log_buffer import setup_stdout
setup_stdout()

from src.win_utils import _user32


MUTEX_NAME = "Global\\MoonlightBlockerTool_V4.8.0"
            

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def run_as_admin():
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable,
        ' '.join([f'"{sys.argv[0]}"'] + sys.argv[1:]),
        None, 1)
        


def check_single_instance():
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    last_error = ctypes.windll.kernel32.GetLastError()
    if last_error == 183:
        ctypes.windll.kernel32.CloseHandle(mutex)
        return None, True
    return mutex, False


def main():
    if os.name != 'nt':
        ctypes.windll.user32.MessageBoxW(0, "此脚本仅支持 Windows 系统",
                                          "错误", 0x10)
        sys.exit(1)

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    mutex, already = check_single_instance()
    if already:
        try:
            hwnd = ctypes.windll.user32.FindWindowW(
                None, "月圆之夜断网工具 v4.8.0")
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 9)
                ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass
        sys.exit(0)

    if not is_admin():
        run_as_admin()
        sys.exit()

    import tkinter as tk
    from src.main_window import NetworkBlockerApp

    root = tk.Tk()
    try:
        dpi = _user32.GetDpiForWindow(root.winfo_id()) or 96
        root.tk.call('tk', 'scaling', dpi / 72.0)
    except Exception:
        pass

    app = NetworkBlockerApp(root)
    try:
        root.mainloop()
    except SystemExit:
        pass
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"程序错误: {e}", flush=True)
        try:
            app.cleanup()
        except Exception:
            pass
    finally:
        if 'app' in locals() and not getattr(app, 'cleanup_done', True):
            try: app.cleanup()
            except Exception: pass
        try: root.destroy()
        except Exception: pass
        if mutex:
            ctypes.windll.kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    main()
