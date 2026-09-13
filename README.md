# 信号变频 · 月圆之夜断网工具

> 版本 1.0 · 项目主页：https://github.com/smX456464

为《月圆之夜》(Night of the Full Moon) 设计的 OCR 辅助断网工具。通过识别游戏画面文字，按规则自动触发短暂断网，辅助游戏机制运行。

---

## 工作原理

屏幕截图 (mss) → OCR 识别 (RapidOCR) → 规则匹配 (白/黑名单) → 防火墙阻断 (netsh)

命中白名单且未命中黑名单时，短暂断网 N 秒后自动恢复。

---

## 功能特性

核心能力

- OCR 文字识别（RapidOCR + ONNX Runtime，离线运行）
- 白名单触发断网 / 黑名单抑制断网
- 按游戏客户区尺寸分开存储规则（多分辨率支持）
- 三种匹配模式：正则 / 包含 / 完全相等
- 否定词过滤（如"12赛季"排除）
- 连续帧防抖 + 触发冷却

交互设计

- 无边框主窗口，拖动条 + 时钟 + Ping 显示
- 每个按钮支持长短按双功能
- 长按视觉反馈（浅黄 → 橙 → 红 → 绿）
- 规则可视化编辑器（游戏上直接拖动 / 缩放 ROI）
- 调试叠加框（白名单绿框，黑名单蓝框）
- 命中高亮 + 命中历史面板

辅助功能

- 音量控制（集成 SoundVolumeView）
- SoundVolumeView 一键下载
- 日志系统（环形缓冲）
- 内置使用手册（短按 📄 打开）
- 配置热重载（长按 ✕ 3 秒）

---

## 环境要求

| 项目 | 要求 |
|---|---|
| 操作系统 | Windows 10 1809+ |
| Python | 3.11+ |
| 权限 | 管理员（修改防火墙） |

---

## 快速开始

从源码运行：

    git clone https://github.com/smX456464/yyzy_duanw.git
    cd yyzy_duanw
    python -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt
    python main.pyw

使用打包好的 exe：从 Releases 下载 → 解压 → 双击 信号变频.exe（允许 UAC）。

---

## 界面速览

    顶部：14:32 - 28        （时钟 + Ping）
    中间：▶ 播放             （点击切换断网）
    第二行：⏱  🔊  👁  🗑
    底部：📋  📄  ✕

| 按钮 | 短按 | 长按 |
|---|---|---|
| ⏱ | 设置断网秒数 / 显示调试框 | — |
| 🔊 | 静音 / 恢复游戏音量 | 打开音量设置 |
| 👁 | 切换 OCR 监控开 / 关 | 打开规则管理 |
| 🗑 | 清除防火墙规则 | — |
| 📋 | 打开日志窗口 | — |
| 📄 | 打开使用手册 | 设置窗口字体 / 配色 |
| ✕ | 退出 | 重载配置 |

---

## 目录结构

信号变频/
├── main.pyw                   入口
├── requirements.txt           Python 依赖
├── README.md                  本文件
├── 内置文本.md                使用手册
├── config/                    配置目录（自动生成）
│   ├── config.toml
│   ├── templates.toml
│   └── state.toml
├── src/                       源码包
│   ├── main_window.py         主类（Mixin 组合）
│   ├── mw_ui.py               UI 构建 + 时钟 + 动画
│   ├── mw_drag.py             拖动 + 长按交互
│   ├── mw_monitor.py          后台监控 + 高亮 + 音量
│   ├── mw_dialogs.py          对话框 + 日志 / 文本窗口
│   ├── template_watcher.py    OCR 监控线程
│   ├── ocr_engine.py          RapidOCR 封装
│   ├── capture.py             屏幕截图 + 内存裁剪
│   ├── rule_manager.py        规则管理对话框
│   ├── roi_editor.py          ROI 编辑器
│   ├── roi_overlay.py         调试叠加框
│   ├── region_selector.py     鼠标框选器
│   ├── network_tools.py       防火墙 + 网卡
│   ├── volume_tools.py        SoundVolumeView 封装
│   ├── volume_settings.py     音量设置 + 下载向导
│   ├── downloader.py          SoundVolumeView 下载器
│   ├── md_settings.py         文本窗口设置
│   ├── config_manager.py      配置读写
│   ├── win_utils.py           Windows API 封装
│   └── log_buffer.py          日志系统
└── 参考/                      历史版本归档
    ├── README.md
    ├── genshin_net_blocker.py
    └── 月圆之夜_*.pyw

---

## 架构设计

NetworkBlockerApp 通过多重继承组合四个 Mixin：

| Mixin | 职责 | 文件 |
|---|---|---|
| MainWindowUI | 界面构建、时钟、动画 | mw_ui.py |
| MainWindowDrag | 拖动、长短按交互 | mw_drag.py |
| MainWindowMonitor | OCR 监控、防火墙、音量、高亮 | mw_monitor.py |
| MainWindowDialogs | 对话框、日志 / 文本窗口 | mw_dialogs.py |

关键设计

- 一次截图 + 内存裁剪：抓一次整个客户区，用 numpy 切片在内存裁剪各 ROI
- OCR 结果哈希缓存：用 crop 内容哈希作 key，LRU 缓存最近 100 条结果
- 调试叠加框捕获排除：SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)
- 规则按分辨率精确匹配：按 f"{cw}x{ch}" 分开存储，不做兜底

---

## 打包

onedir 模式（推荐，秒开）：

    python -m PyInstaller --noconfirm --clean --windowed --uac-admin --name "信号变频" --icon "laptop-signal.ico" --collect-all rapidocr_onnxruntime --collect-all onnxruntime --collect-all mss --collect-all tomlkit --hidden-import PIL._tkinter_finder --hidden-import numpy main.pyw

输出：dist\信号变频\ 文件夹

onefile 模式（单文件，启动慢 5~10 秒）：加 --onefile 和 --add-data "内置文本.md;."。

---

## 常见问题

Q: OCR 一直识别但从不断网？
打开日志（短按 📋），看 "👁 检测 ... got='xxx'"。got 空 → ROI 不对；有值但不匹配 → 把实际文字复制到规则里。

Q: 音量功能不可用？
长按 🔊 → 点「⬇ 自动下载 SoundVolumeView」，或手动放到 soundvolumeview\ 目录。

Q: 改了 config.toml 没生效？
长按 ✕ 3 秒重载。

Q: 窗口被遮挡，跳过检测？
监控要求游戏窗口完全可见。把游戏切到前台。

---

## 开发坑点

Tkinter

- 字体正负值：正数 = 点（DPI 二次放大），负数 = 像素
- DPI 感知：必须在 tk.Tk() 之前调 SetProcessDpiAwareness(2)
- 透明色：用 #00FF00 或 #FE01FE

OCR

- 正则 [...]* 会匹配空，用 +
- 中文字符类 [歌声] 只匹配单字，词组用 |

文件编码

- 读 .py / .toml：utf-8-sig
- 写 .py / .toml：utf-8（不带 BOM），否则 tomlkit 报 EmptyKeyError

---

## 许可

MIT License。

第三方组件：RapidOCR (Apache 2.0)、ONNX Runtime (MIT)、mss (MIT)、tomlkit (MIT)、SoundVolumeView (NirSoft Freeware)。

---

项目主页：https://github.com/smX456464