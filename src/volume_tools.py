"""SoundVolumeView 音量控制"""
import os
import re
import subprocess


def run_svv_hidden(args_list, timeout=15):
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    try:
        result = subprocess.run(args_list, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, startupinfo=startupinfo,
                                creationflags=creationflags, timeout=timeout,
                                check=False)
        try:
            return (result.returncode,
                    result.stdout.decode('gbk', errors='ignore'),
                    result.stderr.decode('gbk', errors='ignore'))
        except:
            return (result.returncode,
                    result.stdout.decode('utf-8', errors='ignore'),
                    result.stderr.decode('utf-8', errors='ignore'))
    except Exception as e:
        return -1, "", str(e)


def _clean_path_value(p):
    """去掉外层引号（资源管理器"复制为路径"带引号）+ 前后空白"""
    if not p: return ""
    p = str(p).strip()
    # 最多剥 3 层引号
    for _ in range(3):
        if len(p) >= 2 and p[0] == p[-1] and p[0] in ('"', "'"):
            p = p[1:-1].strip()
        else:
            break
    return p


def resolve_sv_path(raw_path):
    raw_path = _clean_path_value(raw_path)
    if not raw_path: return ""
    if os.path.isfile(raw_path): return raw_path
    if os.path.isdir(raw_path):
        candidate = os.path.join(raw_path, "SoundVolumeView.exe")
        if os.path.isfile(candidate): return candidate
    return ""


def get_process_volume(sv_path, exe_path):
    exe_name = os.path.basename(exe_path)
    cmd = [sv_path, "/scomma", ""]
    rc, out, err = run_svv_hidden(cmd, timeout=15)
    if rc != 0: return None
    for line in out.splitlines():
        if exe_name.lower() in line.lower():
            m = re.search(r'(\d+(?:\.\d+)?)\s*%', line)
            if m: return int(float(m.group(1)))
    return None


def set_process_volume(sv_path, exe_path, volume):
    exe_name = os.path.basename(exe_path)
    cmd = [sv_path, "/SetVolume", exe_name, str(volume)]
    rc, out, err = run_svv_hidden(cmd, timeout=15)
    return rc == 0
