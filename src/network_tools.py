"""\u9632\u706b\u5899 + \u7f51\u7edc\u63a5\u53e3\u5de5\u5177"""
import os
import re
import subprocess
import sys

# \u865a\u62df\u7f51\u5361\u5173\u952e\u8bcd
VIRTUAL_KEYWORDS = [
    "vmware", "hyper-v", "virtualbox", "vethernet",
    "bluetooth", "loopback", "tap-", "tun", "vpn",
]


def _run_netsh(args_list, silent_keywords=None):
    """用列表参数直接调 netsh，不经 shell。
    避免：
      · 路径正斜杠 / 被 netsh 拒绝
      · 中文路径被 shell 转码乱掉
      · 特殊字符被 shell 解析
    返回 (returncode, output_text)
    """
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        proc = subprocess.Popen(
            args_list,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            startupinfo=si, creationflags=creationflags,
            shell=False,
        )
        out_bytes, _ = proc.communicate(timeout=15)
        out = ""
        for enc in ('gbk', 'utf-8', 'cp437'):
            try:
                out = out_bytes.decode(enc)
                break
            except Exception:
                continue
        if not out:
            out = out_bytes.decode('utf-8', errors='ignore')
        rc = proc.returncode
        # 输出打印（除非命中 silent）
        for line in out.splitlines():
            if silent_keywords and any(k in line for k in silent_keywords):
                continue
            if line.strip():
                print(line, flush=True)
        return rc, out
    except Exception as e:
        print(f"❌ netsh 调用异常: {e}", flush=True)
        return -1, str(e)


def run_cmd(cmd_str, exit_on_failure=True, ignore_keywords=None,
            silent_keywords=None):
    """\u6267\u884c\u547d\u4ee4\uff0c\u5b9e\u65f6\u6253\u5370\u8f93\u51fa\u3002
    silent_keywords: \u547d\u4e2d\u8fd9\u4e9b\u5173\u952e\u8bcd\u7684\u8f93\u51fa\u884c\u4e0d\u6253\u5370
    """
    try:
        process = subprocess.Popen(cmd_str, shell=True,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT)
        output_lines = []
        for line in iter(process.stdout.readline, b''):
            decoded = None
            for enc in ('gbk', 'utf-8', 'cp437'):
                try:
                    decoded = line.decode(enc).rstrip()
                    break
                except Exception:
                    continue
            if decoded is None:
                decoded = line.decode('utf-8', errors='ignore').rstrip()
            output_lines.append(decoded)
            if silent_keywords and any(k in decoded for k in silent_keywords):
                continue
            print(decoded, flush=True)
        process.stdout.close()
        process.wait()
        full_output = "\n".join(output_lines)
        if process.returncode not in (0, None):
            if ignore_keywords and any(k in full_output for k in ignore_keywords):
                return
            if not exit_on_failure:
                return
            print(f"\u274c \u547d\u4ee4\u5931\u8d25:\n{cmd_str}\n{full_output}",
                  flush=True)
            if exit_on_failure:
                sys.exit(1)
    except Exception as e:
        if not exit_on_failure:
            return
        print(f"\u274c \u547d\u4ee4\u5f02\u5e38: {cmd_str}\n{e}", flush=True)
        sys.exit(1)


def _silent_run(cmd_str):
    try:
        result = subprocess.run(cmd_str, shell=True,
                                capture_output=True, timeout=15)
        return result.returncode
    except Exception:
        return -1


def silent_cmd(cmd_str):
    return _silent_run(cmd_str)


def _read_iface_list():
    try:
        output = subprocess.check_output(
            'netsh interface show interface',
            shell=True, stderr=subprocess.STDOUT)
    except Exception as e:
        print(f"\u26a0 \u8bfb\u53d6\u7f51\u5361\u5217\u8868\u5931\u8d25: {e}", flush=True)
        return ""
    for enc in ('gbk', 'utf-8', 'cp437'):
        try:
            return output.decode(enc)
        except Exception:
            continue
    return output.decode('utf-8', errors='ignore')


def get_active_interfaces(include_virtual=False):
    """\u8fd4\u56de\u6240\u6709\u5df2\u542f\u7528\u7684\u7f51\u5361\u540d\uff08\u9ed8\u8ba4\u8df3\u8fc7\u865a\u62df\u7f51\u5361\uff09"""
    result = []
    text = _read_iface_list()
    if not text:
        return result
    # \u6bcf\u884c\uff1aEnabled  Connected  Dedicated  WLAN 2
    pat = re.compile(
        r'^\s*(Enabled|\u5df2\u542f\u7528)\s+\S+\s+\S+\s+(.+?)\s*$',
        re.IGNORECASE
    )
    for line in text.splitlines():
        m = pat.match(line)
        if not m:
            continue
        name = m.group(2).strip()
        if not name:
            continue
        if not include_virtual:
            name_low = name.lower()
            if any(k in name_low for k in VIRTUAL_KEYWORDS):
                continue
        result.append(name)
    return result


def get_disabled_interfaces():
    """\u8fd4\u56de\u6240\u6709\u5df2\u7981\u7528\u7684\u7f51\u5361\u540d"""
    result = []
    text = _read_iface_list()
    if not text:
        return result
    pat = re.compile(
        r'^\s*(Disabled|\u5df2\u7981\u7528)\s+\S+\s+\S+\s+(.+?)\s*$',
        re.IGNORECASE
    )
    for line in text.splitlines():
        m = pat.match(line)
        if not m:
            continue
        name = m.group(2).strip()
        if name:
            result.append(name)
    return result


def disable_all_network():
    """\u7981\u7528\u6240\u6709\u7269\u7406\u7f51\u5361\uff08\u6574\u673a\u65ad\u7f51\uff09
    \u8fd4\u56de\u5b9e\u9645\u88ab\u7981\u7528\u7684\u7f51\u5361\u540d\u5217\u8868
    """
    ifaces = get_active_interfaces()
    if not ifaces:
        print("\u26a0 \u672a\u627e\u5230\u53ef\u7528\u7684\u7269\u7406\u7f51\u5361\uff08\u53ef\u80fd\u5df2\u5168\u90e8\u7981\u7528\uff09",
              flush=True)
        return []
    print(f"\U0001f50c \u5373\u5c06\u7981\u7528 {len(ifaces)} \u4e2a\u7f51\u5361\uff1a",
          flush=True)
    disabled = []
    for name in ifaces:
        rc = _silent_run(f'netsh interface set interface "{name}" admin=DISABLE')
        if rc == 0:
            print(f"   \u2713 \u5df2\u7981\u7528\uff1a{name}", flush=True)
            disabled.append(name)
        else:
            print(f"   \u2717 \u7981\u7528\u5931\u8d25\uff1a{name}\uff08\u8fd4\u56de\u7801 {rc}\uff09",
                  flush=True)
    if not disabled:
        print("\u26a0 \u6240\u6709\u7f51\u5361\u7981\u7528\u5931\u8d25\uff08\u53ef\u80fd\u9700\u8981\u7ba1\u7406\u5458\u6743\u9650\uff09",
              flush=True)
    else:
        print(f"\U0001f50c \u5df2\u7981\u7528 {len(disabled)} \u4e2a\u7f51\u5361",
              flush=True)
    return disabled


def enable_all_network(only=None):
    """\u542f\u7528\u7f51\u5361
    only=None  \u2192 \u517c\u5bb9\u6a21\u5f0f\uff08\u542f\u7528\u5e38\u89c1\u540d\u5b57 + \u6240\u6709\u5df2\u7981\u7528\u7684\uff09
    only=[...] \u2192 \u53ea\u542f\u7528\u5217\u8868\u91cc\u7684
    """
    if only is not None:
        if not only:
            print("\u2139 \u65e0\u9700\u6062\u590d\u7f51\u5361", flush=True)
            return
        print(f"\U0001f50c \u5373\u5c06\u542f\u7528 {len(only)} \u4e2a\u7f51\u5361\uff1a",
              flush=True)
        for name in only:
            rc = _silent_run(f'netsh interface set interface "{name}" admin=ENABLE')
            if rc == 0:
                print(f"   \u2713 \u5df2\u542f\u7528\uff1a{name}", flush=True)
            else:
                print(f"   \u2717 \u542f\u7528\u5931\u8d25\uff1a{name}\uff08\u8fd4\u56de\u7801 {rc}\uff09",
                      flush=True)
        return

    # \u517c\u5bb9\u6a21\u5f0f
    common = ['\u4ee5\u592a\u7f51', 'WLAN', 'Wi-Fi', 'WLAN 2', 'WLAN 3',
              'Ethernet', 'Ethernet 2', '\u672c\u5730\u8fde\u63a5',
              'VMware Network Adapter VMnet1',
              'VMware Network Adapter VMnet8']
    for name in common:
        _silent_run(f'netsh interface set interface "{name}" admin=ENABLE')
    for name in get_disabled_interfaces():
        _silent_run(f'netsh interface set interface "{name}" admin=ENABLE')


def block_network_for_targets(rule_base, exe_paths):
    """添加防火墙阻断规则。
    路径统一转成 Windows 反斜杠格式。
    """
    for idx, exe_path in enumerate(exe_paths):
        if not exe_path:
            continue
        if not os.path.exists(exe_path):
            print(f"⚠ 目标不存在，跳过：{exe_path}", flush=True)
            continue
        # 关键：转成反斜杠 + 绝对路径
        norm_path = os.path.normpath(os.path.abspath(exe_path))
        rule_name = f"{rule_base}_{idx}"
        print(f"🛡 添加防火墙规则：{rule_name}", flush=True)
        print(f"   目标：{norm_path}", flush=True)
        for d in ['in', 'out']:
            args = [
                'netsh', 'advfirewall', 'firewall', 'add', 'rule',
                f'name={rule_name}_{d}',
                f'dir={d}',
                'action=block',
                f'program={norm_path}',
                'enable=yes',
                'profile=any',
            ]
            rc, out = _run_netsh(args, silent_keywords=["确定。", "Ok."])
            if rc == 0:
                print(f"   ✓ {d} 规则已添加", flush=True)
            else:
                print(f"   ✗ {d} 规则添加失败（返回码 {rc}）",
                      flush=True)




def unblock_network_for_targets(rule_base, count):
    """删除防火墙规则"""
    for idx in range(count):
        rule_name = f"{rule_base}_{idx}"
        for d in ['in', 'out']:
            args = [
                'netsh', 'advfirewall', 'firewall', 'delete', 'rule',
                f'name={rule_name}_{d}',
            ]
            _run_netsh(args, silent_keywords=[
                "没有与指定标准相匹配的规则",
                "No rules match",
                "确定。",
                "Ok.",
            ])
