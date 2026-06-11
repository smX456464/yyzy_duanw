"""
月圆之夜断网工具 v3.4-fix
设计：拖动条显示当前时间，秒按钮居中于底部按钮行，
      点击秒按钮弹出气泡（可触发断网），顶部中心齿轮设置按钮（连续15击更改目标程序）。
功能：自动启动并监控游戏，一键断网/恢复，配置记忆，心跳线条动画。
"""
import ctypes
from ctypes import windll, wintypes
import io
import os
import subprocess
import sys
import time
import json
import math
import tkinter as tk
from tkinter import messagebox, filedialog
from threading import Thread, Event
from datetime import datetime

# ----------------------------- 管理员权限处理 -----------------------------
def is_admin():
    try: return windll.shell32.IsUserAnAdmin()
    except: return False

def run_as_admin():
    windll.shell32.ShellExecuteW(None, "runas", sys.executable, ' '.join([f'"{sys.argv[0]}"'] + sys.argv[1:]), None, 1)

if not is_admin():
    run_as_admin()
    sys.exit()

class SafeWriter:
    def write(self, s): pass
    def flush(self): pass

if sys.stdout is None or sys.stdout.buffer is None:
    sys.stdout = SafeWriter()
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "config.json")

def load_config():
    defaults = {"block_time": 3, "window_x": None, "window_y": None, "exe_path": ""}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f: data = json.load(f)
            defaults.update(data)
        except: pass
    return defaults

def save_config(config):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(config, f, indent=2)
    except: pass

def get_dpi_scale():
    try:
        hdc = windll.user32.GetDC(0)
        dpi_x = windll.gdi32.GetDeviceCaps(hdc, 88)
        windll.user32.ReleaseDC(0, hdc)
        return (dpi_x / 96.0) * 1.2
    except: return 1.2

def is_game_running():
    try:
        cmd = 'tasklist /fi "imagename eq Night of the Full Moon.exe" /fo csv /nh'
        output = subprocess.check_output(cmd, shell=True, encoding='gbk')
        return "Night of the Full Moon.exe" in output
    except: return False

def run_cmd(cmd_str, exit_on_failure=True, ignore_keywords=None):
    try:
        process = subprocess.Popen(cmd_str, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1)
        output_lines = []
        for line in iter(process.stdout.readline, b''):
            decoded = None
            for enc in ('gbk', 'utf-8', 'cp437'):
                try: decoded = line.decode(enc).rstrip(); break
                except: continue
            if decoded is None: decoded = line.decode('utf-8', errors='ignore').rstrip()
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
            if exit_on_failure: sys.exit(1)
    except Exception as e:
        if not exit_on_failure:
            print(f"⚠️ 命令异常但忽略: {e}", flush=True)
            return
        print(f"❌ 命令异常: {cmd_str}\n{e}", flush=True)
        sys.exit(1)

def block_network(rule_name, exe_path):
    for d in ['in', 'out']:
        run_cmd(f'netsh advfirewall firewall add rule name="{rule_name}_{d}" dir={d} action=block program="{exe_path}" enable=yes profile=any')

def unblock_network(rule_name, exit_on_failure=False):
    for d in ['in', 'out']:
        run_cmd(f'netsh advfirewall firewall delete rule name="{rule_name}_{d}"', exit_on_failure=exit_on_failure,
                ignore_keywords=["没有与指定标准相匹配的规则", "No rules match"])

def check_firewall_rule(rule_name):
    for d in ['in', 'out']:
        print(f"\n🔍 检查规则是否存在：{rule_name}_{d}")
        run_cmd(f'netsh advfirewall firewall show rule name="{rule_name}_{d}"', exit_on_failure=False,
                ignore_keywords=["没有与指定标准相匹配的规则", "No rules match"])

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
        self.wave_offset = 0
        self.time_update_id = None
        self.bubbles = []
        self.bubble_limit = 50
        self.last_bubble_time = 0
        self.bubble_interval = 0.3
        self.setting_click_count = 0
        self.setting_reset_timer = None

        self.scale = get_dpi_scale()
        self.config = load_config()
        self.block_time = self.config.get("block_time", 3)

        # 优先使用配置中的exe路径
        configured_exe = self.config.get("exe_path", "")
        if configured_exe and os.path.exists(configured_exe):
            self.exe_path = configured_exe
        else:
            self.exe_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "Night of the Full Moon.exe")

        self.w = int(120 * self.scale)
        self.h = int(160 * self.scale)
        self.font_size = int(10 * self.scale)
        self.small_font = int(8 * self.scale)
        self.time_font_size = int(9 * self.scale)

        self.root.overrideredirect(True)
        self.root.attributes('-toolwindow', True)
        self.root.attributes('-topmost', True)
        self.root.configure(bg='#00FF00')
        self.root.attributes('-transparentcolor', '#00FF00')
        self.root.geometry(f"{self.w}x{self.h}")

        wx = self.config.get("window_x"); wy = self.config.get("window_y")
        if wx is not None and wy is not None:
            self.root.geometry(f"+{wx}+{wy}")
        else:
            sw = self.root.winfo_screenwidth(); sh = self.root.winfo_screenheight()
            x = (sw - self.w) // 2; y = (sh - self.h) // 2
            self.root.geometry(f"+{x}+{y}")

        if not os.path.exists(self.exe_path):
            messagebox.showerror("未找到游戏程序",
                                 f"未找到目标程序：{self.exe_path}\n请将本工具与游戏放在同一目录，或在设置中指定。")
            self.root.after(100, self.safe_exit)
            return

        self.launch_game_if_not_running()
        self.create_widgets()
        self.add_drag_functionality()
        self.start_game_monitor()
        self.start_heartbeat_animation()
        self.start_clock_update()

    def safe_exit(self):
        self.stop_animation(); self.stop_clock(); self.cleanup(); self.root.destroy()

    def launch_game_if_not_running(self):
        if not is_game_running():
            print("🎮 游戏未运行，正在启动...")
            try:
                subprocess.Popen([self.exe_path], cwd=os.path.dirname(self.exe_path))
                time.sleep(2)
            except Exception as e: print(f"启动游戏失败: {e}")

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
        self.config["window_x"] = self.root.winfo_x(); self.config["window_y"] = self.root.winfo_y()
        self.config["block_time"] = self.block_time
        self.config["exe_path"] = self.exe_path
        save_config(self.config)
        self.stop_animation(); self.stop_clock(); self.cleanup(); self.root.destroy()

    # ----------------------------- 自适应布局 -----------------------------
    def create_widgets(self):
        self.canvas = tk.Canvas(self.root, bg='#00FF00', highlightthickness=0, bd=0, width=self.w, height=self.h)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        pad = 10
        btn_common = {'bg': '#E0E0E0', 'activebackground': '#C0C0C0', 'fg': '#333', 'font': ("Arial", self.font_size),
                      'width': 3, 'height': 1, 'bd': 0, 'relief': 'flat'}
        self.btn_time = tk.Button(self.canvas, text="⏱", command=self.set_block_time, **btn_common)
        self.btn_clear = tk.Button(self.canvas, text="🗑", command=self.clear_firewall_rules, **btn_common)
        self.btn_log = tk.Button(self.canvas, text="📋", command=self.toggle_log_window, **btn_common)
        self.btn_exit = tk.Button(self.canvas, text="✕", command=self.cleanup_and_exit,
                                  bg='#FFD0D0', activebackground='#FFAAAA', fg='#333',
                                  font=("Arial", self.small_font), width=3, height=1, bd=0)
        self.btn_sec = tk.Button(self.canvas, text="00",
                                 bg='#E0E0E0', activebackground='#D0D0D0', fg='#333',
                                 font=("Arial", self.font_size), width=3, height=1,
                                 bd=0, relief='flat', command=self.on_sec_click)
        # 齿轮设置按钮：尺寸稍小 (width=2, height=1)，背景颜色与其他一致
        self.btn_settings = tk.Button(self.canvas, text="⚙", command=lambda: self.on_settings_click(None),
                                      bg='#E0E0E0', activebackground='#C0C0C0', fg='#333',
                                      font=("Arial", self.font_size), width=2, height=1,
                                      bd=0, relief='flat', highlightthickness=0)

        self.root.update_idletasks()
        time_btn_width = self.btn_time.winfo_reqwidth()
        drag_height = max(int(time_btn_width * 2 / 3), int(16 * self.scale))
        top_pad = 5
        self.rect_left = pad; self.rect_right = self.w - pad
        drag_top = top_pad; drag_bottom = top_pad + drag_height
        self.rect_top = drag_bottom
        btn_height = self.btn_log.winfo_reqheight()
        self.rect_bottom = self.h - pad - btn_height - int(2 * self.scale)

        # 背景矩形
        self.bg_rect = self.canvas.create_rectangle(self.rect_left, self.rect_top, self.rect_right, self.rect_bottom,
                                                    fill="#E0E0E0", outline="", tags="bg")
        self.canvas.tag_bind("bg", "<Button-1>", self.toggle_process)

        # 拖动条及时间
        self.drag_rect = self.canvas.create_rectangle(self.rect_left, drag_top, self.rect_right, drag_bottom,
                                                      fill="#D0D0D0", outline="", tags="drag")
        self.time_hour = self.canvas.create_text(self.rect_left + 15, (drag_top + drag_bottom) // 2,
                                                 text="00", font=("Consolas", self.time_font_size, "bold"), fill="#333", tags="time")
        self.time_sep = self.canvas.create_text((self.rect_left + self.rect_right) // 2, (drag_top + drag_bottom) // 2,
                                                text="≡", font=("Arial", self.time_font_size, "bold"), fill="#555", tags="time")
        self.time_min = self.canvas.create_text(self.rect_right - 15, (drag_top + drag_bottom) // 2,
                                                text="00", font=("Consolas", self.time_font_size, "bold"), fill="#333", tags="time")

        # 顶部按钮行：时间(左)、清除(右)、齿轮(居中)
        self.canvas.create_window(self.rect_left, self.rect_top, window=self.btn_time, anchor="nw")
        self.canvas.create_window(self.rect_right, self.rect_top, window=self.btn_clear, anchor="ne")
        # 齿轮放在顶部正中央，与时间、清除同高度（基准y = rect_top）
        settings_x = (self.rect_left + self.rect_right) // 2
        settings_y = self.rect_top
        self.canvas.create_window(settings_x, settings_y, window=self.btn_settings, anchor="n")

        # 底部按钮行：日志(左)、退出(右)、秒(居中)
        self.canvas.create_window(self.rect_left, self.rect_bottom, window=self.btn_log, anchor="sw")
        self.canvas.create_window(self.rect_right, self.rect_bottom, window=self.btn_exit, anchor="se")
        sec_x = (self.rect_left + self.rect_right) // 2
        self.canvas.create_window(sec_x, self.rect_bottom, window=self.btn_sec, anchor="s")

        # 拖动绑定
        self.canvas.tag_bind("drag", "<Button-1>", self.start_move)
        self.canvas.tag_bind("drag", "<B1-Motion>", self.on_move)
        self.canvas.tag_bind("time", "<Button-1>", self.start_move)
        self.canvas.tag_bind("time", "<B1-Motion>", self.on_move)

        self.canvas.tag_raise("window")

    def add_drag_functionality(self):
        self.canvas.bind("<Button-1>", self.start_move)
        self.canvas.bind("<B1-Motion>", self.on_move)

    def start_move(self, event):
        self.x = event.x_root - self.root.winfo_x()
        self.y = event.y_root - self.root.winfo_y()

    def on_move(self, event):
        x = event.x_root - self.x; y = event.y_root - self.y
        self.root.geometry(f"+{x}+{y}")

    # ----------------------------- 设置目标程序 -----------------------------
    def on_settings_click(self, event=None):
        self.setting_click_count += 1
        if self.setting_reset_timer:
            self.root.after_cancel(self.setting_reset_timer)
        self.setting_reset_timer = self.root.after(1500, self.reset_settings_click)

        if self.setting_click_count >= 15:
            self.reset_settings_click()
            self.change_exe_path()

    def reset_settings_click(self):
        self.setting_click_count = 0
        if self.setting_reset_timer:
            self.root.after_cancel(self.setting_reset_timer)
            self.setting_reset_timer = None

    def change_exe_path(self):
        messagebox.showinfo("更改断网对象", "请选择新的目标程序（.exe）")
        new_exe = filedialog.askopenfilename(
            title="选择目标程序",
            filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")]
        )
        if new_exe and os.path.exists(new_exe):
            self.exe_path = new_exe
            self.config["exe_path"] = new_exe
            save_config(self.config)
            messagebox.showinfo("成功", f"断网对象已更改为：\n{new_exe}\n\n请重启工具以使新设置生效。")
            print(f"✅ 断网对象已更新为：{new_exe}")
        else:
            messagebox.showwarning("取消", "未选择有效程序，保持原有设置。")

    # ----------------------------- 秒按钮动画 -----------------------------
    def on_sec_click(self):
        now = time.time()
        if now - self.last_bubble_time < self.bubble_interval: return
        self.last_bubble_time = now

        if len(self.bubbles) >= self.bubble_limit:
            old = self.bubbles.pop(0)
            self.canvas.delete(old["id"])
            if old["timer"]: self.root.after_cancel(old["timer"])

        second = self.btn_sec.cget("text")
        btn_height = self.btn_sec.winfo_reqheight()
        start_x = (self.rect_left + self.rect_right) // 2
        start_y = self.rect_bottom
        move_dist = btn_height * 2
        target_y = start_y - move_dist
        target_color = self.canvas.itemcget(self.bg_rect, "fill")

        bubble_id = self.canvas.create_text(start_x, start_y, text=second,
                                            font=("Consolas", self.time_font_size, "bold"),
                                            fill="#555555", anchor="s")
        self.canvas.tag_bind(bubble_id, "<Button-1>", self.toggle_process)

        bubble = {
            "id": bubble_id,
            "start_y": start_y, "target_y": target_y,
            "second_text": second,
            "start_time": now,
            "move_duration": 1.5, "fade_duration": 1.0,
            "timer": None,
            "target_color": target_color
        }
        self.bubbles.append(bubble)
        self.animate_bubble(bubble)

    def animate_bubble(self, bubble):
        now = time.time()
        elapsed = now - bubble["start_time"]
        total_duration = bubble["move_duration"] + bubble["fade_duration"]

        if elapsed >= total_duration:
            self.canvas.delete(bubble["id"])
            if bubble in self.bubbles: self.bubbles.remove(bubble)
            return

        r1, g1, b1 = 0x55, 0x55, 0x55
        target = bubble["target_color"]
        r2 = int(target[1:3], 16); g2 = int(target[3:5], 16); b2 = int(target[5:7], 16)
        progress = elapsed / total_duration
        r = int(r1 + (r2 - r1) * progress); g = int(g1 + (g2 - g1) * progress); b = int(b1 + (b2 - b1) * progress)
        color = f"#{r:02x}{g:02x}{b:02x}"

        if elapsed < bubble["move_duration"]:
            move_progress = elapsed / bubble["move_duration"]
            eased = 1 - math.pow(1 - move_progress, 3)
            current_y = bubble["start_y"] + (bubble["target_y"] - bubble["start_y"]) * eased
        else:
            current_y = bubble["target_y"]

        self.canvas.coords(bubble["id"], (self.rect_left + self.rect_right) // 2, current_y)
        self.canvas.itemconfig(bubble["id"], text=bubble["second_text"], fill=color)

        bubble["timer"] = self.root.after(30, lambda: self.animate_bubble(bubble))

    # ----------------------------- 时钟更新 -----------------------------
    def start_clock_update(self): self.update_clock()
    def stop_clock(self):
        if self.time_update_id: self.root.after_cancel(self.time_update_id); self.time_update_id = None

    def update_clock(self):
        now = datetime.now()
        self.canvas.itemconfig(self.time_hour, text=now.strftime("%H"))
        self.canvas.itemconfig(self.time_min, text=now.strftime("%M"))
        self.btn_sec.config(text=now.strftime("%S"))
        self.time_update_id = self.root.after(200, self.update_clock)

    # ----------------------------- 心跳波 -----------------------------
    def start_heartbeat_animation(self): self.update_wave()
    def stop_animation(self):
        if self.animate_id: self.root.after_cancel(self.animate_id); self.animate_id = None

    def update_wave(self):
        canvas = self.canvas
        left = self.rect_left + 10; right = self.rect_right - 10
        top = self.rect_top + 20; bottom = self.rect_bottom - 20
        w = right - left; h = bottom - top
        if w < 20 or h < 20:
            self.animate_id = self.root.after(1000, self.update_wave)
            return
        mid_y = top + h // 2
        step = 8
        amplitude = int(15 * self.scale) if not self.is_running else 0
        self.wave_offset = (self.wave_offset + 1) % step

        canvas.delete("wave")
        for x in range(-step, w + step, step):
            draw_x = left + x + self.wave_offset
            if left <= draw_x <= right:
                rel = ((draw_x - left) / w) * 4 * math.pi
                y = mid_y
                if not self.is_running:
                    if 0.4 * w < (draw_x - left) < 0.6 * w or (draw_x - left) > 0.9 * w:
                        phase = (draw_x - left - 0.5 * w) / (0.1 * w)
                        y = mid_y - int(amplitude * math.exp(-phase**2) * math.cos(phase * 3))
                    else:
                        y = mid_y + int(amplitude * 0.2 * math.sin(rel))
                canvas.create_oval(draw_x-2, y-2, draw_x+2, y+2, fill="#FFFFFF", outline="", tags="wave")
        self.canvas.tag_raise("wave")
        self.animate_id = self.root.after(1000, self.update_wave)

    # ----------------------------- 核心操作 -----------------------------
    def toggle_process(self, event=None):
        if not self.is_running:
            if not os.path.exists(self.exe_path):
                print("❌ 目标程序不存在，无法断网")
                return
            self.is_running = True
            self.canvas.itemconfig(self.bg_rect, fill="#F44336")
            Thread(target=self.run_block_once, args=(self.block_time,), daemon=True).start()
        else:
            self.is_running = False
            self.canvas.itemconfig(self.bg_rect, fill="#E0E0E0")

    def set_block_time(self):
        dlg = tk.Toplevel(self.root); dlg.overrideredirect(True); dlg.attributes('-topmost', True); dlg.configure(bg='white')
        dlg_w, dlg_h = int(180 * self.scale), int(50 * self.scale)
        x = self.root.winfo_x() + self.w // 2 - dlg_w // 2; y = self.root.winfo_y() + self.h + 5
        dlg.geometry(f"{dlg_w}x{dlg_h}+{x}+{y}")
        tk.Label(dlg, text="断网秒数 (1-3600):", bg='white', font=("", self.small_font)).pack(pady=2)
        entry = tk.Entry(dlg, width=8, font=("", self.small_font)); entry.pack(pady=2)
        entry.insert(0, str(self.block_time)); entry.focus_set()
        def save():
            s = entry.get()
            if s.isdigit() and 1 <= int(s) <= 3600:
                self.block_time = int(s)
                print(f"✅ 断网时间已设为 {self.block_time} 秒")
            dlg.destroy()
        tk.Button(dlg, text="确定", command=save, font=("", self.small_font), width=5).pack(side=tk.LEFT, padx=2)
        tk.Button(dlg, text="取消", command=dlg.destroy, font=("", self.small_font), width=5).pack(side=tk.LEFT, padx=2)
        dlg.wait_window()

    def clear_firewall_rules(self):
        try:
            print("🧹 手动清除防火墙规则...")
            unblock_network(self.rule_name, exit_on_failure=False)
            print("✅ 防火墙规则已手动清除")
        except Exception as e: print(f"清除规则出错: {e}")

    def toggle_log_window(self):
        if self.log_window and self.log_window.winfo_exists():
            self.log_window.deiconify(); self.log_window.lift(); return
        self.log_window = tk.Toplevel(self.root)
        self.log_window.title("月圆之夜断网工具 v3.4-fix - 日志")
        self.log_window.geometry(f"{int(400 * self.scale)}x{int(300 * self.scale)}")
        self.log_window.protocol("WM_DELETE_WINDOW", self.hide_log_window)
        frame = tk.Frame(self.log_window); frame.pack(fill=tk.BOTH, expand=True)
        scroll = tk.Scrollbar(frame); scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text = tk.Text(frame, wrap=tk.WORD, font=("Consolas", self.small_font), yscrollcommand=scroll.set)
        self.log_text.pack(fill=tk.BOTH, expand=True); scroll.config(command=self.log_text.yview)
        tk.Button(self.log_window, text="清空日志", command=self.clear_log, font=("", self.small_font)).pack(pady=2)
        sys.stdout = TextRedirector(self.log_text, "stdout")

    def hide_log_window(self):
        if self.log_window: self.log_window.withdraw()

    def clear_log(self):
        if hasattr(self, 'log_text'):
            self.log_text.config(state=tk.NORMAL); self.log_text.delete(1.0, tk.END); self.log_text.config(state=tk.DISABLED)

    def cleanup(self):
        if self.cleanup_done: return
        print("正在清理资源...")
        self.is_running = False; self.stop_monitor.set()
        try:
            unblock_network(self.rule_name, exit_on_failure=False)
            print("✅ 已恢复网络")
        except Exception as e: print(f"清理防火墙规则时出错: {e}")
        self.cleanup_done = True

    def run_block_once(self, block_time):
        try:
            print(f"🛑 添加防火墙规则：阻断 {block_time} 秒")
            block_network(self.rule_name, self.exe_path)
            check_firewall_rule(self.rule_name)
            print(f"✅ 断网已开始，持续 {block_time} 秒")
            for _ in range(block_time):
                if not self.is_running: break
                time.sleep(1)
            print("🔄 正在删除防火墙规则，恢复网络")
            unblock_network(self.rule_name, exit_on_failure=False)
            print("✅ 网络已恢复")
            if self.is_running:
                self.is_running = False
                self.root.after(0, lambda: self.canvas.itemconfig(self.bg_rect, fill="#E0E0E0"))
        except Exception as e: print(f"发生错误: {e}")
        finally:
            if self.is_running:
                self.is_running = False
                self.root.after(0, lambda: self.canvas.itemconfig(self.bg_rect, fill="#E0E0E0"))

class TextRedirector:
    def __init__(self, widget, tag="stdout"): self.widget = widget; self.tag = tag
    def write(self, s):
        self.widget.configure(state="normal"); self.widget.insert("end", s)
        self.widget.see("end"); self.widget.configure(state="disabled"); self.widget.update()
    def flush(self): pass

def main():
    if os.name != 'nt':
        messagebox.showerror("错误", "此脚本仅支持 Windows 系统"); sys.exit(1)
    root = tk.Tk()
    app = NetworkBlockerApp(root)
    try: root.mainloop()
    except SystemExit: pass
    except Exception as e:
        print(f"程序发生错误: {e}")
        app.cleanup()
    finally:
        if 'app' in locals() and not getattr(app, 'cleanup_done', True): app.cleanup()
        try: root.destroy()
        except tk.TclError: pass

if __name__ == "__main__": main()