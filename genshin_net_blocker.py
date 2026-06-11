import ctypes
import io
import os
import subprocess
import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from threading import Thread


# 检查是否管理员权限
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


# 提权重启脚本
def run_as_admin():
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, ' '.join([sys.argv[0]] + sys.argv[1:]),
        None, 1
    )


# 自动提权
if not is_admin():
    print("⏫ 正在尝试以管理员身份重新运行脚本...")
    run_as_admin()
    sys.exit()

# 设置 stdout 编码为 UTF-8，防止输出乱码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


# 运行系统命令
def run_cmd(cmd_str, ignore_keywords=None):
    try:
        print(f"\n🧾 执行命令：{cmd_str}", flush=True)
        process = subprocess.Popen(
            cmd_str,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1
        )

        output_lines = []
        for line in iter(process.stdout.readline, b''):
            decoded = line.decode('gbk', errors='ignore').rstrip()
            output_lines.append(decoded)
            print(decoded, flush=True)

        process.stdout.close()
        process.wait()

        full_output = "\n".join(output_lines)

        if process.returncode not in (0, None):
            if ignore_keywords and any(
                    k in full_output for k in ignore_keywords):
                print("⚠️ 命令非0退出码，但包含可忽略内容，继续执行。", flush=True)
                return
            messagebox.showerror("❌ 错误",
                                 f"命令执行失败:\n{cmd_str}\n\n输出信息:\n{full_output}")
            sys.exit(1)

    except Exception as e:
        messagebox.showerror("❌ 异常", f"执行命令异常:\n{cmd_str}\n\n{e}")
        sys.exit(1)


# 选择游戏 EXE 文件
def select_exe_file():
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(
        title="请选择 YuanShen.exe",
        filetypes=[("可执行文件", "*.exe")],
    )
    root.destroy()
    if not file_path:
        messagebox.showinfo("取消", "未选择任何文件，程序已退出。")
        sys.exit(0)
    return file_path


# 添加防火墙规则（入 + 出）
def block_network(rule_name, exe_path):
    for direction in ['in', 'out']:
        run_cmd(
            f'netsh advfirewall firewall add rule name="{rule_name}_{direction}" '
            f'dir={direction} action=block program="{exe_path}" enable=yes profile=any'
        )


# 删除防火墙规则
def unblock_network(rule_name):
    for direction in ['in', 'out']:
        run_cmd(
            f'netsh advfirewall firewall delete rule name="{rule_name}_{direction}"',
            ignore_keywords=["没有与指定标准相匹配的规则", "No rules match"]
        )


# 检查规则是否成功添加
def check_firewall_rule(rule_name):
    for direction in ['in', 'out']:
        print(f"\n🔍 检查规则是否存在：{rule_name}_{direction}")
        run_cmd(
            f'netsh advfirewall firewall show rule name="{rule_name}_{direction}"',
            ignore_keywords=["没有与指定标准相匹配的规则", "No rules match"]
        )


class NetworkBlockerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("原神断网工具")
        self.root.geometry("500x400")
        self.root.resizable(False, False)
        
        # 绑定窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.exe_path = ""
        self.is_running = False
        self.rule_name = "Block_YuanShen"
        self.cleanup_done = False
        
        self.setup_ui()
    
    def setup_ui(self):
        # 文件选择区域
        file_frame = ttk.LabelFrame(self.root, text="游戏执行文件", padding=10)
        file_frame.pack(fill="x", padx=10, pady=5)
        
        self.path_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self.path_var, state='readonly').pack(side="left", fill="x", expand=True, padx=(0, 5))
        ttk.Button(file_frame, text="选择文件", command=self.select_file).pack(side="right")
        
        # 参数设置区域
        param_frame = ttk.LabelFrame(self.root, text="断网设置", padding=10)
        param_frame.pack(fill="x", padx=10, pady=5)
        
        # 断网时间（秒）
        ttk.Label(param_frame, text="断网时间（秒）:").grid(row=0, column=0, sticky="w", pady=2)
        self.block_time = ttk.Spinbox(param_frame, from_=1, to=3600, width=8)
        self.block_time.set("17")
        self.block_time.grid(row=0, column=1, sticky="w", pady=2, padx=5)
        
        # 联网时间（秒）
        ttk.Label(param_frame, text="联网时间（秒）:").grid(row=1, column=0, sticky="w", pady=2)
        self.unblock_time = ttk.Spinbox(param_frame, from_=1, to=3600, width=8)
        self.unblock_time.set("3")
        self.unblock_time.grid(row=1, column=1, sticky="w", pady=2, padx=5)
        
        # 总运行时间（分钟）
        ttk.Label(param_frame, text="总运行时间（分钟）:").grid(row=2, column=0, sticky="w", pady=2)
        self.total_time = ttk.Spinbox(param_frame, from_=1, to=1440, width=8)
        self.total_time.set("4")
        self.total_time.grid(row=2, column=1, sticky="w", pady=2, padx=5)
        
        # 开始/停止按钮（放在参数设置区域右侧）
        btn_frame = ttk.Frame(param_frame)
        btn_frame.grid(row=0, column=2, rowspan=3, padx=20, sticky="ns")
        
        # 开始/停止按钮
        self.start_btn = ttk.Button(btn_frame, text="开始", command=self.toggle_process, width=10)
        self.start_btn.pack(pady=5)
        
        # 清除规则按钮
        self.clear_btn = ttk.Button(btn_frame, text="清除规则", command=self.clear_firewall_rules, width=10)
        self.clear_btn.pack(pady=5)
        
        # 清空日志按钮
        self.clear_log_btn = ttk.Button(btn_frame, text="清空日志", command=self.clear_log, width=10)
        self.clear_log_btn.pack(pady=5)
        
        # 日志区域
        log_frame = ttk.LabelFrame(self.root, text="运行日志", padding=10)
        log_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        # 创建带滚动条的日志文本框
        log_scroll = ttk.Scrollbar(log_frame)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.log_text = tk.Text(log_frame, height=10, wrap=tk.WORD, yscrollcommand=log_scroll.set)
        self.log_text.pack(fill="both", expand=True)
        log_scroll.config(command=self.log_text.yview)
        
        # 设置日志文本样式
        self.log_text.tag_config("DEBUG", foreground="gray")
        self.log_text.tag_config("INFO", foreground="black")
        self.log_text.tag_config("WARNING", foreground="orange")
        self.log_text.tag_config("ERROR", foreground="red")
        
        # 设置控件样式
        style = ttk.Style()
        style.configure('Accent.TButton', font=('微软雅黑', 10, 'bold'))
        
        # 重定向输出到日志
        sys.stdout = TextRedirector(self.log_text, "stdout")
    
    def select_file(self):
        file_path = filedialog.askopenfilename(
            title="请选择 YuanShen.exe",
            filetypes=[("可执行文件", "*.exe")],
        )
        if file_path:
            self.exe_path = file_path.replace('/', '\\')
            self.path_var.set(self.exe_path)
    
    def log(self, message, level="INFO"):
        """
        记录日志信息
        :param message: 日志消息
        :param level: 日志级别 (DEBUG, INFO, WARNING, ERROR)
        """
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        log_entry = f"[{timestamp}] [{level}] {message}\n"
        
        # 根据日志级别设置颜色
        colors = {
            "DEBUG": "gray",
            "INFO": "black",
            "WARNING": "orange",
            "ERROR": "red"
        }
        
        # 插入带颜色的日志
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, log_entry, (level,))
        self.log_text.tag_config(level, foreground=colors.get(level, "black"))
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        
        # 同时输出到控制台
        print(log_entry, end="")
        self.root.update()
    
    def clear_firewall_rules(self):
        """清除防火墙规则"""
        try:
            self.log("正在清除防火墙规则...", "INFO")
            unblock_network(self.rule_name)
            self.log("✅ 防火墙规则已成功清除", "INFO")
            messagebox.showinfo("成功", "防火墙规则已清除")
        except Exception as e:
            error_msg = f"清除防火墙规则失败: {str(e)}"
            self.log(error_msg, "ERROR")
            messagebox.showerror("错误", error_msg)
    
    def on_closing(self):
        """处理窗口关闭事件"""
        if not self.cleanup_done:
            self.cleanup()
        self.root.destroy()
    
    def cleanup(self):
        """清理资源"""
        if self.cleanup_done:
            return
            
        self.log("正在清理资源...", "INFO")
        self.is_running = False
        
        # 确保网络恢复
        try:
            unblock_network(self.rule_name)
            self.log("✅ 已清理防火墙规则", "INFO")
        except Exception as e:
            self.log(f"清理防火墙规则时出错: {str(e)}", "ERROR")
        
        self.cleanup_done = True
    
    def clear_log(self):
        """清空日志"""
        self.log_text.delete(1.0, tk.END)
    
    def toggle_process(self):
        if not self.is_running:
            if not self.exe_path or not os.path.exists(self.exe_path):
                messagebox.showerror("错误", "请先选择游戏执行文件！")
                return
            
            self.is_running = True
            self.start_btn.config(text="停止")
            
            # 获取参数
            block_time = int(self.block_time.get())
            unblock_time = int(self.unblock_time.get())
            total_duration = int(self.total_time.get()) * 60  # 转换为秒
            
            # 在新线程中运行断网循环
            self.thread = Thread(
                target=self.run_block_cycle,
                args=(block_time, unblock_time, total_duration),
                daemon=True
            )
            self.thread.start()
        else:
            self.is_running = False
            self.start_btn.config(state="disabled")
            self.log("正在停止...")
    
    def run_block_cycle(self, block_time, unblock_time, total_duration):
        try:
            elapsed = 0
            self.log(f"🚀 开始断网/联网循环", "INFO")
            self.log(f"断网时间: {block_time}秒, 联网时间: {unblock_time}秒, 总时长: {total_duration}秒", "DEBUG")
            
            while elapsed < total_duration and self.is_running:
                # 断网
                self.log(f"🛑 正在添加防火墙规则：断网 {block_time}秒", "INFO")
                block_network(self.rule_name, self.exe_path)
                check_firewall_rule(self.rule_name)
                self.log(f"✅ 防火墙规则已添加，开始断网", "INFO")
                
                # 等待断网时间
                for _ in range(block_time):
                    if not self.is_running:
                        break
                    time.sleep(1)
                    elapsed += 1
                    if elapsed >= total_duration:
                        break
                
                if not self.is_running or elapsed >= total_duration:
                    break
                
                # 恢复网络
                self.log(f"🔄 正在删除防火墙规则：恢复网络 {unblock_time}秒", "INFO")
                unblock_network(self.rule_name)
                self.log("✅ 防火墙规则已删除，网络已恢复", "INFO")
                
                # 等待联网时间
                for _ in range(unblock_time):
                    if not self.is_running:
                        break
                    time.sleep(1)
                    elapsed += 1
                    if elapsed >= total_duration:
                        break
            
            # 确保最后恢复网络
            self.log("🧹 正在执行最终清理...", "INFO")
            unblock_network(self.rule_name)
            self.log("✅ 最终清理完成，所有防火墙规则已移除", "INFO")
            self.log(f"✅ 脚本执行完成，总运行时间: {elapsed}秒", "INFO")
            
        except Exception as e:
            error_msg = f"发生错误: {str(e)}"
            self.log(error_msg, "ERROR")
            import traceback
            self.log(traceback.format_exc(), "DEBUG")
            messagebox.showerror("错误", error_msg)
        finally:
            self.is_running = False
            self.root.after(0, lambda: self.start_btn.config(text="开始", state="normal"))


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
        print("❌ 此脚本仅支持 Windows 系统")
        sys.exit(1)
    
    root = tk.Tk()
    app = NetworkBlockerApp(root)
    
    try:
        root.mainloop()
    except KeyboardInterrupt:
        # 处理Ctrl+C中断
        app.cleanup()
    except Exception as e:
        print(f"程序发生错误: {str(e)}", file=sys.stderr)
        app.cleanup()
    finally:
        # 确保资源被清理
        if 'app' in locals() and not app.cleanup_done:
            app.cleanup()
        root.destroy()


# 启动入口
if __name__ == "__main__":
    if os.name != 'nt':
        print("❌ 此脚本仅支持 Windows 系统", flush=True)
        sys.exit(1)
    main()
