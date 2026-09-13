"""防火墙 + 网络接口工具"""
import subprocess
import sys


def run_cmd(cmd_str, exit_on_failure=True, ignore_keywords=None):
    try:
        process = subprocess.Popen(cmd_str, shell=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output_lines = []
        for line in iter(process.stdout.readline, b''):
            decoded = None
            for enc in ('gbk', 'utf-8', 'cp437'):
                try:
                    decoded = line.decode(enc).rstrip(); break
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
                return
            if not exit_on_failure: return
            print(f"❌ 命令失败:\n{cmd_str}\n{full_output}", flush=True)
            if exit_on_failure: sys.exit(1)
    except Exception as e:
        if not exit_on_failure: return
        print(f"❌ 命令异常: {cmd_str}\n{e}", flush=True)
        sys.exit(1)


def block_network_for_targets(rule_base, exe_paths):
    import os
    for idx, exe_path in enumerate(exe_paths):
        if exe_path and os.path.exists(exe_path):
            rule_name = f"{rule_base}_{idx}"
            for d in ['in', 'out']:
                run_cmd(f'netsh advfirewall firewall add rule name="{rule_name}_{d}" '
                        f'dir={d} action=block program="{exe_path}" enable=yes profile=any')


def unblock_network_for_targets(rule_base, count):
    for idx in range(count):
        rule_name = f"{rule_base}_{idx}"
        for d in ['in', 'out']:
            run_cmd(f'netsh advfirewall firewall delete rule name="{rule_name}_{d}"',
                    exit_on_failure=False,
                    ignore_keywords=["没有与指定标准相匹配的规则", "No rules match"])


def get_active_interfaces():
    interfaces = []
    try:
        output = subprocess.check_output('netsh interface show interface',
                                         shell=True, text=True, encoding='gbk')
        for line in output.splitlines():
            if '已启用' in line or 'Enabled' in line:
                if any(kw in line for kw in ['以太网', 'Ethernet', 'WLAN', 'Wi-Fi']):
                    parts = line.split('已启用' if '已启用' in line else 'Enabled')
                    if len(parts) >= 2:
                        name = parts[1].strip()
                        if name: interfaces.append(name)
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
