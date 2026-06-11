"""
月圆之夜断网工具 v1.1
功能：自动启动并监控游戏，一键断网/恢复，透明悬浮按钮，配置记忆，
      播放键居中且带动态呼吸/闪烁动画，无全屏提示。
运行环境：Windows 10/11，已打包为 exe 或直接用 Python 运行。
使用方法：将本 exe/脚本 与 Night of the Full Moon.exe 放在同一目录，双击运行。
"""
import ctypes
from ctypes import windll, wintypes
import io
import os
import subprocess
import sys
import time
import json
import tkinter as tk
from tkinter import messagebox
from threading import Thread, Event

# ----------------------------- 管理员权限处理 -----------------------------
def is_admin():
    try:
        return windll.shell32.IsUserAnAdmin()
    except:
        return False

def run_as_admin():
    windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, ' '.join([f'"{sys.argv[0]}"'] + sys.argv[1:]),
        None, 1
    )

if not is_admin():
    run_as_admin()
    sys.exit()

# 安全处理标准输出
class SafeWriter:
    def write(self, s): pass
    def flush(self): pass

if sys.stdout is None or sys.stdout.buffer is None:
    sys.stdout = SafeWriter()
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ----------------------------- 配置文件处理 -----------------------------
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "config.json")

def load_config():
    defaults = {"block_time": 3, "window_x": None, "window_y": None}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            defaults.update(data)
        except:
            pass
    return defaults

def save_config(config):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except:
        pass

# ----------------------------- DPI 缩放（放大20%） -----------------------------
def get_dpi_scale():
    try:
        hdc = windll.user32.GetDC(0)
        dpi_x = windll.gdi32.GetDeviceCaps(hdc, 88)
        windll.user32.ReleaseDC(0, hdc)
        return (dpi_x / 96.0) * 1.2
    except:
        return 1.2

# ----------------------------- 进程检测 -----------------------------
def is_game_running():
    try:
        cmd = 'tasklist /fi "imagename eq Night of the Full Moon.exe" /fo csv /nh'
        output = subprocess.check_output(cmd, shell=True, encoding='gbk')
        return "Night of the Full Moon.exe" in output
    except:
        return False

# ----------------------------- 防火墙工具 -----------------------------
def run_cmd(cmd_str, exit_on_failure=True, ignore_keywords=None):
    try:
        process = subprocess.Popen(
            cmd_str, shell=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, bufsize=1
        )
        output_lines = []
        for line in iter(process.stdout.readline, b''):
            decoded = None
            for enc in ('gbk', 'utf-8', 'cp437'):
                try:
                    decoded = line.decode(enc).rstrip()
                    break
                except:
                    continue
            if decoded is None:
                decoded = line.decode('utf-8', errors='ignore').rstrip()
            output_lines.append(decoded)
            print(decoded, flush=True)

        process.stdout.close()
        process.wait()
        full_output = "\n".join(output_lines)

        if process.returncode not in (0, None):
            if ignore_keywords and any(k in full_output for k in ignore_keywords):
                print("⚠️ 命令非0退出码，但包含可忽略内容，继续执行。", flush=True)
                return
            if not exit_on_failure:
                print("⚠️ 命令执行失败，但忽略继续运行。", flush=True)
                return
            print(f"❌ 命令执行失败:\n{cmd_str}\n\n输出信息:\n{full_output}", flush=True)
            if exit_on_failure:
                sys.exit(1)
    except Exception as e:
        if not exit_on_failure:
            print(f"⚠️ 命令异常但忽略: {e}", flush=True)
            return
        print(f"❌ 命令异常: {cmd_str}\n{e}", flush=True)
        sys.exit(1)

def block_network(rule_name, exe_path):
    for direction in ['in', 'out']:
        run_cmd(
            f'netsh advfirewall firewall add rule name="{rule_name}_{direction}" '
            f'dir={direction} action=block program="{exe_path}" enable=yes profile=any'
        )

def unblock_network(rule_name, exit_on_failure=False):
    for direction in ['in', 'out']:
        run_cmd(
            f'netsh advfirewall firewall delete rule name="{rule_name}_{direction}"',
            exit_on_failure=exit_on_failure,
            ignore_keywords=["没有与指定标准相匹配的规则", "No rules match"]
        )

def check_firewall_rule(rule_name):
    for direction in ['in', 'out']:
        print(f"\n🔍 检查规则是否存在：{rule_name}_{direction}")
        run_cmd(
            f'netsh advfirewall firewall show rule name="{rule_name}_{direction}"',
            exit_on_failure=False,
            ignore_keywords=["没有与指定标准相匹配的规则", "No rules match"]
        )

# ----------------------------- 主界面 -----------------------------
class NetworkBlockerApp:
    def __init__(self, root):
        self.root = root
        self.cleanup_done = False
        self.is_running = False
        self.log_window = None
        self.stop_monitor = Event()
        self.rule_name = "Block_FullMoon"
        self.block_time = 3
        self.animate_id = None

        self.scale = get_dpi_scale()
        self.config = load_config()
        self.block_time = self.config.get("block_time", 3)

        self.base_w = int(100 * self.scale)
        self.base_h = int(100 * self.scale)
        self.font_size = int(10 * self.scale)
        self.small_font = int(8 * self.scale)
        self.big_font = int(14 * self.scale)

        self.root.overrideredirect(True)
        self.root.attributes('-toolwindow', True)
        self.root.attributes('-topmost', True)
        self.root.configure(bg='#00FF00')
        self.root.attributes('-transparentcolor', '#00FF00')
        self.root.geometry(f"{self.base_w}x{self.base_h}")

        wx = self.config.get("window_x")
        wy = self.config.get("window_y")
        if wx is not None and wy is not None:
            self.root.geometry(f"+{wx}+{wy}")
        else:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            x = (sw - self.base_w) // 2
            y = (sh - self.base_h) // 2
            self.root.geometry(f"+{x}+{y}")

        self.exe_path = os.path.join(
            os.path.dirname(os.path.abspath(sys.argv[0])),
            "Night of the Full Moon.exe"
        )

        if not os.path.exists(self.exe_path):
            messagebox.showerror(
                "未找到游戏程序",
                f"未找到 Night of the Full Moon.exe\n\n"
                f"请将本工具与 Night of the Full Moon.exe 放在同一个文件夹下，然后重新运行。\n\n"
                f"当前目录：{os.path.dirname(os.path.abspath(sys.argv[0]))}"
            )
            self.root.after(100, self.safe_exit)
            return

        self.launch_game_if_not_running()
        self.setup_ui()
        self.add_drag_functionality()
        self.start_game_monitor()
        self.start_play_animation()  # 启动空闲动画

    def safe_exit(self):
        self.stop_animation()
        self.cleanup()
        self.root.destroy()

    def launch_game_if_not_running(self):
        if not is_game_running():
            print("🎮 游戏未运行，正在启动...")
            try:
                subprocess.Popen([self.exe_path], cwd=os.path.dirname(self.exe_path))
                time.sleep(2)
            except Exception as e:
                print(f"启动游戏失败: {e}")

    def start_game_monitor(self):
        def monitor():
            while not self.stop_monitor.is_set():
                if not is_game_running() and not self.is_running:
                    print("🛑 游戏已退出，本工具即将关闭")
                    self.root.after(0, self.cleanup_and_exit)
                    break
                time.sleep(3)
        Thread(target=monitor, daemon=True).start()

    def cleanup_and_exit(self):
        self.config["window_x"] = self.root.winfo_x()
        self.config["window_y"] = self.root.winfo_y()
        self.config["block_time"] = self.block_time
        save_config(self.config)
        self.stop_animation()
        self.cleanup()
        self.root.destroy()

    def setup_ui(self):
        # 拖动条
        drag_bar = tk.Label(self.root, text="≡", bg='#E0E0E0', fg='#555', font=("", self.small_font))
        drag_bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=1, pady=1)
        drag_bar.bind("<Button-1>", self.start_move)
        drag_bar.bind("<B1-Motion>", self.on_move)

        # 普通按钮样式
        btn_common = {
            'bg': '#E0E0E0',
            'activebackground': '#C0C0C0',
            'fg': '#333',
            'bd': 0,
            'font': ("Arial", self.font_size),
            'width': 3,
            'height': 1,
            'relief': 'flat',
            'highlightthickness': 0,
            'anchor': 'center',
            'compound': 'center'
        }

        # 上方辅助按钮
        self.btn_time = tk.Button(self.root, text="⏱", command=self.set_block_time, **btn_common)
        self.btn_time.grid(row=1, column=0, padx=1, pady=1)

        self.btn_clear = tk.Button(self.root, text="🗑", command=self.clear_firewall_rules, **btn_common)
        self.btn_clear.grid(row=1, column=1, padx=1, pady=1)

        # 中心播放键（初始背景与普通按钮相同，动画凸显）
        self.btn_start = tk.Button(self.root, text="▶️", command=self.toggle_process,
                                   bg='#E0E0E0', activebackground='#C0C0C0',
                                   fg='#333', font=("Arial", self.big_font, "bold"),
                                   width=6, height=2,
                                   bd=0, relief='flat', highlightthickness=0,
                                   anchor='center', compound='center')
        self.btn_start.grid(row=2, column=0, columnspan=2, padx=1, pady=1, sticky="nsew")
        self.root.grid_rowconfigure(2, weight=1)

        # 下方辅助按钮
        self.btn_log = tk.Button(self.root, text="📋", command=self.toggle_log_window, **btn_common)
        self.btn_log.grid(row=3, column=0, padx=1, pady=1)

        self.btn_exit = tk.Button(self.root, text="✕", command=self.cleanup_and_exit,
                                  bg='#FFD0D0', activebackground='#FFAAAA', fg='#333',
                                  bd=0, font=("Arial", self.small_font), width=3, height=1)
        self.btn_exit.grid(row=3, column=1, padx=1, pady=1)

    def add_drag_functionality(self):
        self.root.bind("<Button-1>", self.start_move)
        self.root.bind("<B1-Motion>", self.on_move)

    def start_move(self, event):
        self.x = event.x
        self.y = event.y

    def on_move(self, event):
        deltax = event.x - self.x
        deltay = event.y - self.y
        x = self.root.winfo_x() + deltax
        y = self.root.winfo_y() + deltay
        self.root.geometry(f"+{x}+{y}")

    # ----------------------------- 播放键动画 -----------------------------
    def start_play_animation(self):
        """启动动画循环"""
        self.animate_play_btn()

    def stop_animation(self):
        if self.animate_id:
            self.root.after_cancel(self.animate_id)
            self.animate_id = None

    def animate_play_btn(self):
        """根据状态执行不同动画，然后递归调度"""
        if self.is_running:
            # 运行中：红白快速闪烁 (200ms 间隔)
            current = self.btn_start.cget("bg")
            next_color = "#FFCDD2" if current != "#FFCDD2" else "#FF8A80"
            self.btn_start.config(bg=next_color, activebackground=next_color)
            self.animate_id = self.root.after(200, self.animate_play_btn)
        else:
            # 空闲呼吸：在浅灰 #E0E0E0 和稍深 #D0D0D0 之间慢速切换 (600ms)
            current = self.btn_start.cget("bg")
            next_color = "#D0D0D0" if current == "#E0E0E0" else "#E0E0E0"
            self.btn_start.config(bg=next_color, activebackground="#C0C0C0")
            self.animate_id = self.root.after(600, self.animate_play_btn)

    # ----------------------------- 核心操作 -----------------------------
    def toggle_process(self):
        if not self.is_running:
            if not os.path.exists(self.exe_path):
                print("❌ 目标程序不存在，无法断网")
                return
            self.is_running = True
            self.btn_start.config(text="⏸", fg="white")  # 文字变白更醒目
            # 动画会立即在下次 animate 调用中反映（背景由动画控制）
            self.thread = Thread(target=self.run_block_once, args=(self.block_time,), daemon=True)
            self.thread.start()
        else:
            self.is_running = False
            self.btn_start.config(text="▶️", fg="#333")
            # 手动停止时动画会自动切换为空闲呼吸

    def set_block_time(self):
        dlg = tk.Toplevel(self.root)
        dlg.overrideredirect(True)
        dlg.attributes('-topmost', True)
        dlg.configure(bg='white')
        w, h = int(180 * self.scale), int(50 * self.scale)
        x = self.root.winfo_x() + self.base_w // 2 - w // 2
        y = self.root.winfo_y() + self.base_h + 5
        dlg.geometry(f"{w}x{h}+{x}+{y}")
        tk.Label(dlg, text="断网秒数 (1-3600):", bg='white', font=("", self.small_font)).pack(pady=2)
        entry = tk.Entry(dlg, width=8, font=("", self.small_font))
        entry.pack(pady=2)
        entry.insert(0, str(self.block_time))
        entry.focus_set()

        def save_time():
            s = entry.get()
            if s.isdigit():
                t = int(s)
                if 1 <= t <= 3600:
                    self.block_time = t
                    print(f"✅ 断网时间已设为 {t} 秒")
                else:
                    print("❌ 请输入1~3600之间的数字")
            dlg.destroy()
        def cancel():
            dlg.destroy()

        btn_frame = tk.Frame(dlg, bg='white')
        btn_frame.pack()
        tk.Button(btn_frame, text="确定", command=save_time, font=("", self.small_font), width=5).pack(side=tk.LEFT, padx=2)
        tk.Button(btn_frame, text="取消", command=cancel, font=("", self.small_font), width=5).pack(side=tk.LEFT, padx=2)
        dlg.wait_window()

    def clear_firewall_rules(self):
        try:
            print("🧹 手动清除防火墙规则...")
            unblock_network(self.rule_name, exit_on_failure=False)
            print("✅ 防火墙规则已手动清除")
        except Exception as e:
            print(f"清除规则出错: {e}")

    def toggle_log_window(self):
        if self.log_window and self.log_window.winfo_exists():
            self.log_window.deiconify()
            self.log_window.lift()
            return
        self.log_window = tk.Toplevel(self.root)
        self.log_window.title("月圆之夜断网工具 v1.1 - 日志")
        self.log_window.geometry(f"{int(400 * self.scale)}x{int(300 * self.scale)}")
        self.log_window.protocol("WM_DELETE_WINDOW", self.hide_log_window)

        frame = tk.Frame(self.log_window)
        frame.pack(fill=tk.BOTH, expand=True)
        scroll = tk.Scrollbar(frame)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text = tk.Text(frame, wrap=tk.WORD, font=("Consolas", self.small_font), yscrollcommand=scroll.set)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        scroll.config(command=self.log_text.yview)

        clear_btn = tk.Button(self.log_window, text="清空日志", command=self.clear_log, font=("", self.small_font))
        clear_btn.pack(pady=2)

        sys.stdout = TextRedirector(self.log_text, "stdout")

    def hide_log_window(self):
        if self.log_window:
            self.log_window.withdraw()

    def clear_log(self):
        if hasattr(self, 'log_text'):
            self.log_text.config(state=tk.NORMAL)
            self.log_text.delete(1.0, tk.END)
            self.log_text.config(state=tk.DISABLED)

    def cleanup(self):
        if self.cleanup_done:
            return
        print("正在清理资源...")
        self.is_running = False
        self.stop_monitor.set()
        try:
            unblock_network(self.rule_name, exit_on_failure=False)
            print("✅ 已恢复网络")
        except Exception as e:
            print(f"清理防火墙规则时出错: {e}")
        self.cleanup_done = True

    def run_block_once(self, block_time):
        try:
            print(f"🛑 添加防火墙规则：阻断 {block_time} 秒")
            block_network(self.rule_name, self.exe_path)
            check_firewall_rule(self.rule_name)
            print(f"✅ 断网已开始，持续 {block_time} 秒")
            for _ in range(block_time):
                if not self.is_running:
                    break
                time.sleep(1)
            print("🔄 正在删除防火墙规则，恢复网络")
            unblock_network(self.rule_name, exit_on_failure=False)
            print("✅ 网络已恢复")
            # 正常结束时，如果 is_running 仍为 True，则自动切换回停止状态
            if self.is_running:
                self.is_running = False
                self.root.after(0, lambda: self.btn_start.config(text="▶️", fg="#333"))
        except Exception as e:
            print(f"发生错误: {e}")
        finally:
            # 异常情况也确保状态恢复
            if self.is_running:
                self.is_running = False
                self.root.after(0, lambda: self.btn_start.config(text="▶️", fg="#333"))

class TextRedirector(object):
    def __init__(self, widget, tag="stdout"):
        self.widget = widget
        self.tag = tag

    def write(self, str):
        self.widget.configure(state="normal")
        self.widget.insert("end", str, (self.tag,))
        self.widget.see("end")
        self.widget.configure(state="disabled")
        self.widget.update()

    def flush(self):
        pass

def main():
    if os.name != 'nt':
        messagebox.showerror("错误", "此脚本仅支持 Windows 系统")
        sys.exit(1)

    root = tk.Tk()
    app = NetworkBlockerApp(root)
    try:
        root.mainloop()
    except SystemExit:
        pass
    except Exception as e:
        print(f"程序发生错误: {e}")
        app.cleanup()
    finally:
        if 'app' in locals() and not getattr(app, 'cleanup_done', True):
            app.cleanup()
        try:
            root.destroy()
        except tk.TclError:
            pass

if __name__ == "__main__":
    main()