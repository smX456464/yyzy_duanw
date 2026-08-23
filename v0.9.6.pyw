"""
月圆之夜断网工具 v3.5.2
修复：
- 退出时若处于静音状态，自动恢复目标程序音量（与网络恢复逻辑一致）
- 为 Markdown 文本添加字体颜色和背景颜色配置项
- 其他功能保持
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
import re
import tkinter as tk
from tkinter import messagebox, ttk
from threading import Thread, Event
from datetime import datetime

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

# 单实例互斥体名称
MUTEX_NAME = "Global\\MoonlightBlockerTool_V3.5.2"

def check_single_instance():
    """创建互斥体，返回 (mutex_handle, already_running)"""
    mutex = windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    last_error = windll.kernel32.GetLastError()
    if last_error == 183:  # ERROR_ALREADY_EXISTS
        windll.kernel32.CloseHandle(mutex)
        return None, True
    return mutex, False

class SafeWriter:
    def write(self, s): pass
    def flush(self): pass

if sys.stdout is None or sys.stdout.buffer is None:
    sys.stdout = SafeWriter()
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def resource_path(relative_path):
    """获取资源文件的绝对路径，兼容 PyInstaller 打包"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    else:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "config.json")
DEFAULT_GAME_NAME = "Night of the Full Moon.exe"

def load_config():
    defaults = {
        "block_time": 3,
        "window_width": 160,
        "window_height": 160,
        "bg_color": "#E0E0E0",
        "drag_color": "#D0D0D0",
        "transparent_color": "#00FF00",
        "window_x": None,
        "window_y": None,
        "sound_volume_view_path": "",
        "volume_mute_value": 0,
        "launch_app": "default",
        "block_target": "default",          # 兼容旧配置
        "block_targets": ["default"],       # 新配置：列表
        "ping_target": "qq.com",
        "auto_exit_on_game_exit": True,
        "md_font_family": "微软雅黑",
        "md_font_size": 10,
        "md_font_color": "#000000",         # 新增：MD 字体颜色
        "md_bg_color": "#FFFFFF",           # 新增：MD 背景颜色
        "md_scroll_pos": 0.0,
        "md_window_x": None,
        "md_window_y": None,
        "md_window_width": 400,
        "md_window_height": 300
    }
    if not os.path.exists(CONFIG_FILE):
        print("ℹ️ 配置文件不存在，使用默认配置。", flush=True)
        return defaults

    raw_text = ""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            raw_text = f.read()
    except Exception as e:
        print(f"❌ 读取配置文件失败: {e}，使用默认配置。", flush=True)
        return defaults

    data = None
    try:
        data = json.loads(raw_text)
        print("✅ 配置文件 JSON 解析成功。", flush=True)
    except json.JSONDecodeError:
        print("⚠️ 配置文件 JSON 解析失败，尝试自动修复单反斜杠...", flush=True)
        try:
            fixed_text = raw_text.replace('\\', '\\\\')
            data = json.loads(fixed_text)
            print("✅ 自动修复成功。", flush=True)
        except:
            print("❌ 自动修复失败，使用默认配置。", flush=True)
            data = None

    if data is None:
        return defaults

    # 兼容旧配置：如果 block_target 存在且是字符串，且没有 block_targets，则转换为列表
    if "block_target" in data and isinstance(data["block_target"], str):
        if "block_targets" not in data or not isinstance(data["block_targets"], list):
            data["block_targets"] = [data["block_target"]]
        # 移除旧字段
        data.pop("block_target", None)
    # 确保 block_targets 是列表
    if "block_targets" not in data:
        data["block_targets"] = ["default"]
    elif not isinstance(data["block_targets"], list):
        data["block_targets"] = ["default"]

    for key in defaults:
        if key not in data:
            data[key] = defaults[key]

    sv_path = data.get("sound_volume_view_path", "")
    if sv_path:
        print(f"🔊 SoundVolumeView 路径：{sv_path}", flush=True)
    else:
        print("🔇 未配置 SoundVolumeView 路径（音量控制禁用）。", flush=True)
    return data

def save_config(config):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except:
        pass

def get_dpi_scale():
    try:
        hdc = windll.user32.GetDC(0)
        dpi_x = windll.gdi32.GetDeviceCaps(hdc, 88)
        windll.user32.ReleaseDC(0, hdc)
        return (dpi_x / 96.0) * 1.2
    except:
        return 1.2

def resolve_exe_path(value):
    if value == "default":
        return os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), DEFAULT_GAME_NAME)
    return value

def is_process_running(exe_path):
    if not exe_path:
        return False
    exe_name = os.path.basename(exe_path)
    try:
        cmd = f'tasklist /fi "imagename eq {exe_name}" /fo csv /nh'
        output = subprocess.check_output(cmd, shell=True, encoding='gbk')
        return exe_name in output
    except:
        return False

# ----------------------------- 防火墙工具 -----------------------------
def run_cmd(cmd_str, exit_on_failure=True, ignore_keywords=None):
    try:
        process = subprocess.Popen(cmd_str, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
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

def block_network_for_targets(rule_base, exe_paths):
    """为多个目标添加防火墙规则，规则名使用 rule_base_索引"""
    for idx, exe_path in enumerate(exe_paths):
        if exe_path and os.path.exists(exe_path):
            rule_name = f"{rule_base}_{idx}"
            for d in ['in', 'out']:
                run_cmd(f'netsh advfirewall firewall add rule name="{rule_name}_{d}" dir={d} action=block program="{exe_path}" enable=yes profile=any')

def unblock_network_for_targets(rule_base, count):
    """删除多个目标的防火墙规则"""
    for idx in range(count):
        rule_name = f"{rule_base}_{idx}"
        for d in ['in', 'out']:
            run_cmd(f'netsh advfirewall firewall delete rule name="{rule_name}_{d}"',
                    exit_on_failure=False,
                    ignore_keywords=["没有与指定标准相匹配的规则", "No rules match"])

# ----------------------------- 全局断网 -----------------------------
def get_active_interfaces():
    interfaces = []
    try:
        output = subprocess.check_output('netsh interface show interface', shell=True,
                                         text=True, encoding='gbk')
        for line in output.splitlines():
            if '已启用' in line or 'Enabled' in line:
                if any(kw in line for kw in ['以太网', 'Ethernet', 'WLAN', 'Wi-Fi']):
                    parts = line.split('已启用' if '已启用' in line else 'Enabled')
                    if len(parts) >= 2:
                        name = parts[1].strip()
                        if name:
                            interfaces.append(name)
    except:
        pass
    return interfaces

def disable_all_network():
    for iface in get_active_interfaces():
        silent_cmd(f'netsh interface set interface "{iface}" admin=DISABLE')

def enable_all_network():
    for iface in get_active_interfaces():
        silent_cmd(f'netsh interface set interface "{iface}" admin=ENABLE')
    for name in ['以太网', 'WLAN', 'Wi-Fi', 'Ethernet']:
        silent_cmd(f'netsh interface set interface "{name}" admin=ENABLE')

def silent_cmd(cmd_str):
    try:
        subprocess.run(cmd_str, shell=True, capture_output=True, timeout=10)
    except:
        pass

# ----------------------------- 音量控制 -----------------------------
def run_svv_hidden(args_list, timeout=15):
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    try:
        result = subprocess.run(
            args_list,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=startupinfo,
            creationflags=creationflags,
            timeout=timeout,
            check=False
        )
        try:
            stdout_text = result.stdout.decode('gbk', errors='ignore')
            stderr_text = result.stderr.decode('gbk', errors='ignore')
        except:
            stdout_text = result.stdout.decode('utf-8', errors='ignore')
            stderr_text = result.stderr.decode('utf-8', errors='ignore')
        return result.returncode, stdout_text, stderr_text
    except Exception as e:
        return -1, "", str(e)

def get_process_volume(sv_path, exe_path):
    exe_name = os.path.basename(exe_path)
    cmd = [sv_path, "/scomma", ""]
    print(f"🔍 执行命令：{' '.join(cmd)}", flush=True)
    rc, out, err = run_svv_hidden(cmd, timeout=15)
    print(f"   返回码：{rc}", flush=True)
    if rc != 0:
        print(f"   ❌ 命令返回非零，无法获取音量列表", flush=True)
        return None

    target_line = None
    for line in out.splitlines():
        if exe_name.lower() in line.lower():
            target_line = line
            break
    if not target_line:
        print(f"   ❌ 在音频列表中未找到进程：{exe_name}", flush=True)
        return None

    print(f"   找到目标行：{target_line!r}", flush=True)
    m = re.search(r'(\d+(?:\.\d+)?)\s*%', target_line)
    if m:
        vol = int(float(m.group(1)))
        print(f"   ✅ 解析成功：音量 = {vol}%", flush=True)
        return vol
    else:
        print("   ❌ 无法从行中解析音量百分比", flush=True)
        return None

def set_process_volume(sv_path, exe_path, volume):
    exe_name = os.path.basename(exe_path)
    cmd = [sv_path, "/SetVolume", exe_name, str(volume)]
    print(f"🔍 执行命令：{' '.join(cmd)}", flush=True)
    rc, out, err = run_svv_hidden(cmd, timeout=15)
    print(f"   返回码：{rc}", flush=True)
    return rc == 0

# ----------------------------- 主界面 -----------------------------
class NetworkBlockerApp:
    def __init__(self, root):
        self.root = root
        self.cleanup_done = False
        self.is_running = False
        self.log_window = None
        self.md_window = None
        self.md_text = None
        self.time_dialog = None
        self.time_entry = None
        self.stop_monitor = Event()
        self.stop_ping_event = Event()
        self.rule_base = "Block_App"
        self.block_time = 3
        self.animate_id = None
        self.wave_offset = 0
        self.time_update_id = None

        self.saved_volume = None
        self.is_muted = False
        self.volume_btn = None

        self.ping_timeout_counter = 0
        self.ping_label_id = None

        self.scale = get_dpi_scale()
        self.config = load_config()
        self.block_time = self.config.get("block_time", 3)

        raw_sv = self.config.get("sound_volume_view_path", "")
        self.sv_path = self._resolve_sv_path(raw_sv)
        self.volume_mute_value = self.config.get("volume_mute_value", 0)

        # 解析连带启动
        launch_cfg = self.config.get("launch_app", "default")
        self.launch_exe_path = resolve_exe_path(launch_cfg) if launch_cfg else ""

        # 解析断网目标列表
        raw_targets = self.config.get("block_targets", [])
        if not isinstance(raw_targets, list):
            raw_targets = [raw_targets]
        self.block_targets_config = raw_targets
        self.block_targets_exe = []
        for cfg in self.block_targets_config:
            if cfg == "default":
                resolved = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), DEFAULT_GAME_NAME)
            elif cfg == "":
                resolved = ""
            else:
                resolved = cfg
            self.block_targets_exe.append(resolved)

        # 检查有效目标数量
        self.valid_targets = [p for p in self.block_targets_exe if p and os.path.exists(p)]
        self.is_global_mode = (len(self.valid_targets) == 0)

        self.ping_target = self.config.get("ping_target", "qq.com")
        self.auto_exit_on_game_exit = self.config.get("auto_exit_on_game_exit", True)

        # Markdown 字体设置
        self.md_font_family = self.config.get("md_font_family", "微软雅黑")
        self.md_font_size = self.config.get("md_font_size", 10)
        self.md_font_color = self.config.get("md_font_color", "#000000")
        self.md_bg_color = self.config.get("md_bg_color", "#FFFFFF")

        self.md_scroll_pos = self.config.get("md_scroll_pos", 0.0)

        self.window_width_config = self.config.get("window_width", 120)
        self.window_height_config = self.config.get("window_height", 160)
        self.bg_color = self.config.get("bg_color", "#E0E0E0")
        self.drag_color = self.config.get("drag_color", "#D0D0D0")
        self.transparent_color = self.config.get("transparent_color", "#00FF00")

        self.w = int(self.window_width_config * self.scale)
        self.h = int(self.window_height_config * self.scale)
        self.font_size = int(10 * self.scale)
        self.small_font = int(8 * self.scale)
        self.time_font_size = int(9 * self.scale)

        self.root.overrideredirect(True)
        self.root.attributes('-toolwindow', True)
        self.root.attributes('-topmost', True)
        self.root.configure(bg=self.transparent_color)
        self.root.attributes('-transparentcolor', self.transparent_color)
        self.root.geometry(f"{self.w}x{self.h}")
        self.root.title("月圆之夜断网工具 v3.5.2")

        wx = self.config.get("window_x")
        wy = self.config.get("window_y")
        if wx is not None and wy is not None:
            self.root.geometry(f"+{wx}+{wy}")
        else:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            x = (sw - self.w) // 2
            y = (sh - self.h) // 2
            self.root.geometry(f"+{x}+{y}")

        # 启动时恢复网络
        self.restore_network_on_startup()
        # 启动时如果之前是静音状态，不自动恢复音量（由用户手动或退出时恢复）
        # 这里不做自动恢复，避免意外操作

        # 启动前检查配置，若无效则提示
        self.validate_config_and_prompt()

        # 连带启动应用
        self.launch_app_if_needed()

        self.create_widgets()
        self.add_drag_functionality()
        self.start_game_monitor()
        self.start_ping_monitor()
        self.start_heartbeat_animation()
        self.start_clock_update()

    def _resolve_sv_path(self, raw_path):
        if not raw_path:
            print("🔇 未配置 SoundVolumeView 路径，音量控制禁用。", flush=True)
            return ""
        if os.path.isfile(raw_path):
            print(f"✅ SoundVolumeView 路径有效：{raw_path}", flush=True)
            return raw_path
        elif os.path.isdir(raw_path):
            candidate = os.path.join(raw_path, "SoundVolumeView.exe")
            if os.path.isfile(candidate):
                print(f"✅ 在文件夹 {raw_path} 中找到 SoundVolumeView.exe", flush=True)
                return candidate
            else:
                print(f"⚠️ 在 {raw_path} 中未找到 SoundVolumeView.exe", flush=True)
                return ""
        else:
            print(f"⚠️ 路径不存在：{raw_path}", flush=True)
            return ""

    def restore_network_on_startup(self):
        print("🔄 启动恢复：清理遗留规则 + 启用所有网卡...", flush=True)
        # 删除所有可能的规则（循环多目标）
        unblock_network_for_targets(self.rule_base, len(self.block_targets_exe))
        enable_all_network()

    def validate_config_and_prompt(self):
        invalid_targets = []
        for cfg, resolved in zip(self.block_targets_config, self.block_targets_exe):
            if cfg == "":
                continue
            if not os.path.exists(resolved):
                invalid_targets.append(resolved)
        if self.launch_exe_path and not os.path.exists(self.launch_exe_path):
            invalid_targets.append(self.launch_exe_path)

        if invalid_targets and not self.is_global_mode:
            msg = "以下程序未找到，断网/启动功能可能受限：\n\n"
            for p in invalid_targets[:5]:
                msg += f"• {p}\n"
            msg += "\n是否继续运行？"
            if not messagebox.askyesno("配置警告", msg):
                self.root.after(100, self.safe_exit)
                return
        elif self.is_global_mode and not self.block_targets_exe:
            print("🌐 全局断网模式", flush=True)

    def safe_exit(self):
        self.stop_animation()
        self.stop_clock()
        self.restore_volume_if_needed()
        self.cleanup()
        self.root.destroy()

    def launch_app_if_needed(self):
        if not self.launch_exe_path:
            print("ℹ️ 未配置连带启动应用，跳过。", flush=True)
            return
        if not os.path.exists(self.launch_exe_path):
            print(f"❌ 连带启动应用不存在：{self.launch_exe_path}", flush=True)
            return
        if is_process_running(self.launch_exe_path):
            print(f"✅ 应用已在运行：{os.path.basename(self.launch_exe_path)}", flush=True)
            return
        print(f"🚀 正在启动应用：{self.launch_exe_path}", flush=True)
        try:
            subprocess.Popen([self.launch_exe_path], cwd=os.path.dirname(self.launch_exe_path))
            time.sleep(2)
        except Exception as e:
            print(f"❌ 启动失败: {e}", flush=True)

    def start_game_monitor(self):
        def monitor():
            while not self.stop_monitor.is_set():
                if not self.is_global_mode:
                    all_exited = True
                    for target in self.valid_targets:
                        if is_process_running(target):
                            all_exited = False
                            break
                    if all_exited:
                        print("🛑 所有目标程序均已退出", flush=True)
                        if self.auto_exit_on_game_exit:
                            self.root.after(0, self.cleanup_and_exit)
                            break
                        else:
                            print("ℹ️ 配置为不自动退出，保持运行", flush=True)
                time.sleep(3)
        Thread(target=monitor, daemon=True).start()

    def start_ping_monitor(self):
        if not self.ping_target:
            print("ℹ️ 未配置 ping 目标，禁用 Ping 显示。", flush=True)
            return
        def ping_loop():
            while not self.stop_ping_event.is_set():
                delay = self.get_ping_delay(self.ping_target)
                if delay is None:
                    self.ping_timeout_counter += 1
                    if self.ping_timeout_counter > 999:
                        self.ping_timeout_counter = 999
                    display_text = f"{self.ping_timeout_counter:03d}"
                else:
                    self.ping_timeout_counter = 0
                    display_text = str(delay)
                self.root.after(0, lambda t=display_text: self.update_ping_label(t))
                time.sleep(3)
        Thread(target=ping_loop, daemon=True).start()

    def get_ping_delay(self, target):
        try:
            cmd = f"ping -n 1 {target}"
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=4, encoding='gbk', errors='ignore')
            output = proc.stdout
            match = re.search(r'(?:时间|time)=(\d+)ms', output)
            if match:
                return int(match.group(1))
            else:
                return None
        except:
            return None

    def update_ping_label(self, text):
        if self.ping_label_id and self.canvas:
            self.canvas.itemconfig(self.ping_label_id, text=text)

    def cleanup_and_exit(self):
        self.config["window_x"] = self.root.winfo_x()
        self.config["window_y"] = self.root.winfo_y()
        self.config["block_time"] = self.block_time
        self.config["sound_volume_view_path"] = self.config.get("sound_volume_view_path", "")
        self.config["volume_mute_value"] = self.volume_mute_value
        self.config["launch_app"] = self.config.get("launch_app", "default")
        self.config["block_targets"] = self.block_targets_config
        self.config["ping_target"] = self.ping_target
        self.config["auto_exit_on_game_exit"] = self.auto_exit_on_game_exit
        self.config["md_font_family"] = self.md_font_family
        self.config["md_font_size"] = self.md_font_size
        self.config["md_font_color"] = self.md_font_color
        self.config["md_bg_color"] = self.md_bg_color
        if self.md_window is not None and self.md_window.winfo_exists():
            self.save_md_state()
        save_config(self.config)
        self.stop_animation()
        self.stop_clock()
        self.stop_ping_event.set()
        self.restore_volume_if_needed()
        self.cleanup()
        self.root.destroy()

    def restore_volume_if_needed(self):
        """如果当前处于静音状态，恢复原音量"""
        if self.is_muted and self.saved_volume is not None and self.sv_path and self.valid_targets:
            target_exe = self.valid_targets[0]  # 音量控制只对第一个有效目标
            if os.path.exists(target_exe) and is_process_running(target_exe):
                if set_process_volume(self.sv_path, target_exe, self.saved_volume):
                    print(f"🔊 退出时已恢复目标游戏音量到 {self.saved_volume}%", flush=True)
                else:
                    print(f"⚠️ 退出时恢复音量失败，请手动检查", flush=True)
                self.is_muted = False
                self.saved_volume = None
                if self.volume_btn:
                    self.volume_btn.config(text="🔊", bg='#E0E0E0')
            else:
                print("ℹ️ 目标进程已退出，无需恢复音量", flush=True)

    # ----------------------------- UI 构建 -----------------------------
    def create_widgets(self):
        self.canvas = tk.Canvas(self.root, bg=self.transparent_color, highlightthickness=0, bd=0,
                                width=self.w, height=self.h)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        pad = 10
        btn_common = {
            'bg': '#E0E0E0',
            'activebackground': '#C0C0C0',
            'fg': '#333',
            'font': ("Arial", self.font_size),
            'width': 3, 'height': 1,
            'bd': 0, 'relief': 'flat'
        }
        self.btn_time = tk.Button(self.canvas, text="⏱", command=self.toggle_time_dialog, **btn_common)
        self.btn_clear = tk.Button(self.canvas, text="🗑", command=self.clear_firewall_rules, **btn_common)
        self.btn_log = tk.Button(self.canvas, text="📋", command=self.toggle_log_window, **btn_common)
        self.btn_exit = tk.Button(self.canvas, text="✕", command=self.cleanup_and_exit,
                                  bg='#FFD0D0', activebackground='#FFAAAA', fg='#333',
                                  font=("Arial", self.small_font), width=3, height=1, bd=0)
        self.btn_md = tk.Button(self.canvas, text="📄", command=self.toggle_md_window, **btn_common)

        # 音量按钮：仅当有有效目标且声卡工具路径有效时显示，且作用于第一个有效目标
        self.volume_btn = None
        if self.sv_path and self.valid_targets and os.path.exists(self.sv_path):
            self.volume_btn = tk.Button(self.canvas, text="🔊", command=self.toggle_volume,
                                        bg='#E0E0E0', activebackground='#C0C0C0', fg='#333',
                                        font=("Arial", self.font_size), width=2, height=1,
                                        bd=0, relief='flat', highlightthickness=0)

        self.root.update_idletasks()
        time_btn_width = self.btn_time.winfo_reqwidth()
        drag_height = int(time_btn_width * 2 / 3)
        min_drag_height = int(16 * self.scale)
        if drag_height < min_drag_height:
            drag_height = min_drag_height

        top_pad = 5
        self.rect_left = pad
        self.rect_right = self.w - pad
        drag_top = top_pad
        drag_bottom = top_pad + drag_height
        self.rect_top = drag_bottom
        btn_height = self.btn_log.winfo_reqheight()
        self.rect_bottom = self.h - pad - btn_height - int(2 * self.scale)

        self.bg_rect = self.canvas.create_rectangle(
            self.rect_left, self.rect_top, self.rect_right, self.rect_bottom,
            fill=self.bg_color, outline="", tags="bg"
        )
        self.canvas.tag_bind("bg", "<Button-1>", self.toggle_process)

        self.drag_rect = self.canvas.create_rectangle(
            self.rect_left, drag_top, self.rect_right, drag_bottom,
            fill=self.drag_color, outline="", tags="drag"
        )

        # 时间显示
        self.time_hour = self.canvas.create_text(
            self.rect_left + 15, (drag_top + drag_bottom) // 2,
            text="00", font=("Consolas", self.time_font_size, "bold"), fill="#333", tags="time"
        )
        self.time_sep1 = self.canvas.create_text(
            self.rect_left + 30, (drag_top + drag_bottom) // 2,
            text=":", font=("Arial", self.time_font_size, "bold"), fill="#555", tags="time"
        )
        self.time_min = self.canvas.create_text(
            self.rect_left + 45, (drag_top + drag_bottom) // 2,
            text="00", font=("Consolas", self.time_font_size, "bold"), fill="#333", tags="time"
        )
        self.time_sep2 = self.canvas.create_text(
            self.rect_left + 60, (drag_top + drag_bottom) // 2,
            text=":", font=("Arial", self.time_font_size, "bold"), fill="#555", tags="time"
        )
        self.time_sec = self.canvas.create_text(
            self.rect_left + 75, (drag_top + drag_bottom) // 2,
            text="00", font=("Consolas", self.time_font_size, "bold"), fill="#333", tags="time"
        )

        # Ping 标签
        if self.ping_target:
            sep_x = self.rect_left + 85
            self.canvas.create_text(
                sep_x, (drag_top + drag_bottom) // 2,
                text="-", font=("Arial", self.time_font_size, "bold"), fill="#555", tags="time"
            )
            ping_x = self.rect_right - 10
            self.ping_label_id = self.canvas.create_text(
                ping_x, (drag_top + drag_bottom) // 2,
                text="000", font=("Consolas", self.time_font_size, "bold"), fill="#333", tags="time",
                anchor="e"
            )

        # 第二行按钮
        self.canvas.create_window(self.rect_left, self.rect_top, window=self.btn_time, anchor="nw")
        if self.volume_btn:
            self.canvas.create_window(self.rect_right, self.rect_top, window=self.btn_clear, anchor="ne")
            center_x = (self.rect_left + self.rect_right) // 2
            self.canvas.create_window(center_x, self.rect_top, window=self.volume_btn, anchor="n")
        else:
            self.canvas.create_window(self.rect_right, self.rect_top, window=self.btn_clear, anchor="ne")

        # 底部按钮行
        self.canvas.create_window(self.rect_left, self.rect_bottom, window=self.btn_log, anchor="sw")
        self.canvas.create_window(self.rect_right, self.rect_bottom, window=self.btn_exit, anchor="se")
        center_x_bottom = (self.rect_left + self.rect_right) // 2
        self.canvas.create_window(center_x_bottom, self.rect_bottom, window=self.btn_md, anchor="s")

        # 拖动事件绑定
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
        x = event.x_root - self.x
        y = event.y_root - self.y
        self.root.geometry(f"+{x}+{y}")

    # ----------------------------- 音量控制 -----------------------------
    def toggle_volume(self):
        if not self.sv_path or not self.valid_targets or not os.path.exists(self.sv_path):
            messagebox.showerror("错误", "音量控制不可用。")
            return
        target_exe = self.valid_targets[0]
        if not os.path.exists(target_exe):
            messagebox.showerror("错误", "目标游戏不存在，无法静音。")
            return
        if not is_process_running(target_exe):
            messagebox.showerror("错误", "目标游戏未运行，无法静音。")
            return

        if not self.is_muted:
            current_vol = get_process_volume(self.sv_path, target_exe)
            if current_vol is None:
                messagebox.showerror("错误", "无法获取当前音量，详细日志请查看日志窗口。")
                return
            self.saved_volume = current_vol
            target_volume = int(self.volume_mute_value)
            set_process_volume(self.sv_path, target_exe, target_volume)
            self.is_muted = True
            if self.volume_btn:
                self.volume_btn.config(text="🔇", bg="#FFD0D0")
            print(f"🔇 已将目标游戏音量调整为 {target_volume}%，原音量 {self.saved_volume}%", flush=True)
        else:
            if self.saved_volume is None:
                messagebox.showerror("错误", "没有保存的原始音量，无法恢复。")
                return
            set_process_volume(self.sv_path, target_exe, self.saved_volume)
            self.is_muted = False
            self.saved_volume = None
            if self.volume_btn:
                self.volume_btn.config(text="🔊", bg='#E0E0E0')
            print("🔊 音量已恢复", flush=True)

    # ----------------------------- 时间设置对话框 -----------------------------
    def toggle_time_dialog(self):
        if self.time_dialog is not None and self.time_dialog.winfo_exists():
            self.save_time_from_dialog()
            self.time_dialog.destroy()
            self.time_dialog = None
            self.time_entry = None
            return

        dlg = tk.Toplevel(self.root)
        dlg.overrideredirect(True)
        dlg.attributes('-topmost', True)
        dlg.configure(bg='white')
        dlg_w, dlg_h = int(180 * self.scale), int(50 * self.scale)

        x, y = self.calculate_dialog_position(dlg_w, dlg_h)
        dlg.geometry(f"{dlg_w}x{dlg_h}+{x}+{y}")

        tk.Label(dlg, text="断网秒数 (1-3600):", bg='white', font=("", self.small_font)).pack(pady=2)
        entry = tk.Entry(dlg, width=8, font=("", self.small_font))
        entry.pack(pady=2)
        entry.insert(0, str(self.block_time))
        entry.focus_set()

        self.time_dialog = dlg
        self.time_entry = entry

        def on_close():
            self.save_time_from_dialog()
            dlg.destroy()
            self.time_dialog = None
            self.time_entry = None

        tk.Button(dlg, text="确定", command=on_close, font=("", self.small_font), width=5).pack(side=tk.LEFT, padx=2)
        tk.Button(dlg, text="取消", command=on_close, font=("", self.small_font), width=5).pack(side=tk.LEFT, padx=2)

    def calculate_dialog_position(self, dlg_w, dlg_h):
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        main_x = self.root.winfo_x()
        main_y = self.root.winfo_y()
        main_w = self.w
        main_h = self.h

        margin = 5
        left_space = main_x
        right_space = screen_w - (main_x + main_w)

        if left_space >= dlg_w + margin:
            x = main_x - dlg_w - margin
        elif right_space >= dlg_w + margin:
            x = main_x + main_w + margin
        else:
            x = max(0, min(screen_w - dlg_w, main_x + main_w // 2 - dlg_w // 2))

        y = main_y
        if y + dlg_h > screen_h:
            y = screen_h - dlg_h - margin
        if y < 0:
            y = margin
        return x, y

    def save_time_from_dialog(self):
        if self.time_entry is not None:
            s = self.time_entry.get()
            if s.isdigit():
                t = int(s)
                if 1 <= t <= 3600:
                    self.block_time = t
                    print(f"✅ 断网时间已设为 {t} 秒", flush=True)
                else:
                    print("❌ 请输入1~3600之间的数字，保留原值", flush=True)
            else:
                print("❌ 输入无效，保留原值", flush=True)

    # ----------------------------- 日志窗口 -----------------------------
    def toggle_log_window(self):
        if self.log_window is not None and self.log_window.winfo_exists():
            if self.log_window.state() == 'withdrawn':
                self.log_window.deiconify()
                self.log_window.lift()
            else:
                self.log_window.withdraw()
            return
        self.log_window = tk.Toplevel(self.root)
        self.log_window.title("月圆之夜断网工具 - 日志")
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

    # ----------------------------- Markdown 查看窗口 -----------------------------
    def toggle_md_window(self):
        md_file_external = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "文本.md")
        md_file_builtin = resource_path("内置文本.md")
        if os.path.exists(md_file_external):
            md_file = md_file_external
        elif os.path.exists(md_file_builtin):
            md_file = md_file_builtin
        else:
            return

        if self.md_window is not None and self.md_window.winfo_exists():
            if self.md_window.state() == 'withdrawn':
                self.md_window.deiconify()
                self.md_window.lift()
            else:
                self.save_md_state()
                self.md_window.withdraw()
            return

        self.md_window = tk.Toplevel(self.root)
        self.md_window.title("文本.md")
        width = self.config.get("md_window_width", int(400 * self.scale))
        height = self.config.get("md_window_height", int(300 * self.scale))
        x = self.config.get("md_window_x")
        y = self.config.get("md_window_y")
        if x is not None and y is not None:
            self.md_window.geometry(f"{width}x{height}+{x}+{y}")
        else:
            self.md_window.geometry(f"{width}x{height}")
        self.md_window.protocol("WM_DELETE_WINDOW", self.hide_md_window)

        frame = tk.Frame(self.md_window)
        frame.pack(fill=tk.BOTH, expand=True)
        scroll = tk.Scrollbar(frame)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 使用配置的字体、大小、颜色
        md_font = (self.md_font_family, self.md_font_size)
        self.md_text = tk.Text(frame, wrap=tk.WORD, font=md_font,
                               fg=self.md_font_color, bg=self.md_bg_color,
                               yscrollcommand=scroll.set)
        self.md_text.pack(fill=tk.BOTH, expand=True)
        scroll.config(command=self.md_text.yview)

        try:
            with open(md_file, "r", encoding="utf-8") as f:
                content = f.read()
            self.md_text.insert("1.0", content)
            self.md_text.config(state=tk.DISABLED)
            self.md_text.yview_moveto(self.md_scroll_pos)
        except Exception as e:
            messagebox.showerror("错误", f"无法读取 {md_file}:\n{e}")

    def save_md_state(self):
        if self.md_window is not None and self.md_window.winfo_exists():
            self.config["md_scroll_pos"] = self.md_text.yview()[0] if self.md_text else self.config.get("md_scroll_pos", 0.0)
            self.config["md_window_x"] = self.md_window.winfo_x()
            self.config["md_window_y"] = self.md_window.winfo_y()
            self.config["md_window_width"] = self.md_window.winfo_width()
            self.config["md_window_height"] = self.md_window.winfo_height()
            save_config(self.config)

    def hide_md_window(self):
        self.save_md_state()
        if self.md_window:
            self.md_window.withdraw()

    # ----------------------------- 核心操作 -----------------------------
    def toggle_process(self, event=None):
        if not self.is_running:
            self.is_running = True
            self.canvas.itemconfig(self.bg_rect, fill="#F44336")
            self.thread = Thread(target=self.run_block_once, args=(self.block_time,), daemon=True)
            self.thread.start()
        else:
            self.is_running = False
            self.canvas.itemconfig(self.bg_rect, fill=self.bg_color)

    def clear_firewall_rules(self):
        try:
            print("🧹 手动清除防火墙规则并恢复网络...", flush=True)
            unblock_network_for_targets(self.rule_base, len(self.block_targets_exe))
            enable_all_network()
            self.is_running = False
            self.canvas.itemconfig(self.bg_rect, fill=self.bg_color)
            print("✅ 网络已恢复", flush=True)
        except Exception as e:
            print(f"清除规则出错: {e}", flush=True)

    def cleanup(self):
        if self.cleanup_done:
            return
        print("正在清理资源...", flush=True)
        self.is_running = False
        self.stop_monitor.set()
        self.stop_ping_event.set()
        try:
            unblock_network_for_targets(self.rule_base, len(self.block_targets_exe))
            enable_all_network()
            print("✅ 已恢复网络", flush=True)
        except Exception as e:
            print(f"清理防火墙规则时出错: {e}", flush=True)
        self.cleanup_done = True

    def run_block_once(self, block_time):
        try:
            if self.is_global_mode:
                print(f"🌐 全局断网：禁用所有网卡，持续 {block_time} 秒", flush=True)
                disable_all_network()
                print(f"✅ 全局断网已生效", flush=True)
            else:
                print(f"🛑 添加防火墙规则：阻断 {block_time} 秒 (目标数量: {len(self.valid_targets)})", flush=True)
                block_network_for_targets(self.rule_base, self.valid_targets)
                print(f"✅ 应用断网已开始，持续 {block_time} 秒", flush=True)

            start = time.time()
            while time.time() - start < block_time:
                if not self.is_running:
                    print("⏹ 用户中断，提前恢复网络", flush=True)
                    break
                time.sleep(0.1)

            if self.is_global_mode:
                print("🔄 正在启用所有网卡，恢复网络", flush=True)
                enable_all_network()
            else:
                print("🔄 正在删除防火墙规则，恢复网络", flush=True)
                unblock_network_for_targets(self.rule_base, len(self.valid_targets))
            print("✅ 网络已恢复", flush=True)

        except Exception as e:
            print(f"❌ 发生错误: {e}", flush=True)
        finally:
            if self.is_running:
                self.is_running = False
                self.root.after(0, lambda: self.canvas.itemconfig(self.bg_rect, fill=self.bg_color))

    # ----------------------------- 时钟与动画 -----------------------------
    def start_clock_update(self):
        self.update_clock()

    def stop_clock(self):
        if self.time_update_id:
            self.root.after_cancel(self.time_update_id)
            self.time_update_id = None

    def update_clock(self):
        now = datetime.now()
        self.canvas.itemconfig(self.time_hour, text=now.strftime("%H"))
        self.canvas.itemconfig(self.time_min, text=now.strftime("%M"))
        self.canvas.itemconfig(self.time_sec, text=now.strftime("%S"))
        self.time_update_id = self.root.after(200, self.update_clock)

    def start_heartbeat_animation(self):
        self.update_wave()

    def stop_animation(self):
        if self.animate_id:
            self.root.after_cancel(self.animate_id)
            self.animate_id = None

    def update_wave(self):
        canvas = self.canvas
        left = self.rect_left + 10
        right = self.rect_right - 10
        top = self.rect_top + 20
        bottom = self.rect_bottom - 20
        w = right - left
        h = bottom - top
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

class TextRedirector(object):
    def __init__(self, widget, tag="stdout"):
        self.widget = widget
        self.tag = tag
    def write(self, s):
        self.widget.configure(state="normal")
        self.widget.insert("end", s)
        self.widget.see("end")
        self.widget.configure(state="disabled")
        self.widget.update()
    def flush(self):
        pass

def main():
    if os.name != 'nt':
        messagebox.showerror("错误", "此脚本仅支持 Windows 系统")
        sys.exit(1)

    # 单实例互斥检查（提权前）
    mutex, already = check_single_instance()
    if already:
        try:
            hwnd = windll.user32.FindWindowW(None, "月圆之夜断网工具 v3.5.2")
            if hwnd:
                windll.user32.ShowWindow(hwnd, 9)
                windll.user32.SetForegroundWindow(hwnd)
        except:
            pass
        sys.exit(0)

    # 提权（如果需要）
    if not is_admin():
        run_as_admin()
        sys.exit()

    root = tk.Tk()
    app = NetworkBlockerApp(root)
    try:
        root.mainloop()
    except SystemExit:
        pass
    except Exception as e:
        print(f"程序发生错误: {e}", flush=True)
        app.cleanup()
    finally:
        if 'app' in locals() and not getattr(app, 'cleanup_done', True):
            app.cleanup()
        try:
            root.destroy()
        except tk.TclError:
            pass
        if mutex:
            windll.kernel32.CloseHandle(mutex)

if __name__ == "__main__":
    main()