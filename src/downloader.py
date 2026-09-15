"""SoundVolumeView 下载器：多策略下载 + 解压到 soundvolumeview/ 子目录"""
import os
import ssl
import sys
import urllib.request
import zipfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET_DIR = os.path.join(BASE_DIR, "soundvolumeview")
EXE_NAME = "SoundVolumeView.exe"

URL_64_HTTPS = "https://www.nirsoft.net/utils/soundvolumeview-x64.zip"
URL_32_HTTPS = "https://www.nirsoft.net/utils/soundvolumeview.zip"
URL_64_HTTP = "http://www.nirsoft.net/utils/soundvolumeview-x64.zip"
URL_32_HTTP = "http://www.nirsoft.net/utils/soundvolumeview.zip"


def _is_64bit():
    return sys.maxsize > 2 ** 32


def get_official_url():
    return URL_64_HTTPS if _is_64bit() else URL_32_HTTPS


def get_exe_path():
    p = os.path.join(TARGET_DIR, EXE_NAME)
    return p if os.path.isfile(p) else None


def is_installed():
    return get_exe_path() is not None


def _build_urls():
    if _is_64bit():
        return [URL_64_HTTPS, URL_32_HTTPS, URL_64_HTTP, URL_32_HTTP]
    return [URL_32_HTTPS, URL_64_HTTPS, URL_32_HTTP, URL_64_HTTP]


def download_and_install(progress_cb=None, cancel_event=None):
    """下载并解压 SoundVolumeView 到 soundvolumeview/ 子目录。

    返回 (成功: bool, 信息: str)
    progress_cb(downloaded_bytes, total_bytes) — 可选
    cancel_event — 可选，threading.Event，set 后中止
    """
    urls = _build_urls()
    last_err = ""
    for url in urls:
        if cancel_event is not None and cancel_event.is_set():
            return False, "用户已取消"
        try:
            # 宽松 SSL：绕过证书验证（部分网络环境需要）
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                total = int(resp.headers.get("Content-Length", 0) or 0)
                data = bytearray()
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        return False, "用户已取消"
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    data.extend(chunk)
                    if progress_cb:
                        try:
                            progress_cb(len(data), total)
                        except Exception:
                            pass
            if not data:
                last_err = "下载内容为空"
                continue
            os.makedirs(TARGET_DIR, exist_ok=True)
            tmp_zip = os.path.join(TARGET_DIR, "_sv.zip")
            with open(tmp_zip, "wb") as f:
                f.write(data)
            with zipfile.ZipFile(tmp_zip, "r") as z:
                z.extractall(TARGET_DIR)
            try:
                os.remove(tmp_zip)
            except Exception:
                pass
            exe = get_exe_path()
            if exe:
                return True, exe
            # 兜底：递归找 exe
            for root, _dirs, files in os.walk(TARGET_DIR):
                for fn in files:
                    if fn.lower() == EXE_NAME.lower():
                        return True, os.path.join(root, fn)
            last_err = "解压后未找到 SoundVolumeView.exe"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            continue
    return False, f"下载失败（已尝试 {len(urls)} 个地址）\n最后错误：{last_err}"
