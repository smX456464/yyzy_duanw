# 月圆之夜 · 自动跳过回合（托盘版）

进对局后，检测到屏幕上出现「开始战斗」字样时自动断网，跳过战斗开场。

## 使用

直接运行：

    release\AutoSkip\月圆之夜自动跳过.exe

- 无主窗口，仅驻留**系统托盘**（任务栏右下角）
- **右键托盘图标** → 菜单：
  - 自动跳过回合（可勾选开关）
  - 立即跳过一次
  - 查看状态 / 打开日志 / 设置… / 退出
- 游戏**自动启动并自动注入**；游戏退出后本工具**自动退出**

### 手动跳过热键

默认 `CTRL+B`，可在「设置…」里改成 `F9`、`CTRL+ALT+A` 等；留空表示不注册。

## 设置项

| 项 | 说明 |
|---|---|
| 游戏进程名 | 默认 `Night of the Full Moon.exe` |
| 游戏路径 | 留空自动获取 |
| 同步启动路径 | 留空则不同步启动。**若该程序已在运行则不会重复启动** |
| 手动跳过热键 | 默认 `CTRL+B` |
| 自动断网时长 | `0` = 彻底切断（推荐）；`2~5` = 静默丢包 N 秒后恢复 |
| 手动断网时长 | 同上，独立配置 |
| 战斗开始关键字 | 逗号分隔，默认 `开始战斗,开始对决` |
| 自动触发阈值 | 倒计时 ≤ 此值就断网（默认 2 秒） |
| ☑ 自动跳过回合 | 总开关 |
| ☑ 彻底断开 | 关闭全部套接字（最快） |

日志文件：`%TEMP%\yyzy_tray.log`

## 已知现象

关闭游戏时可能出现**一闪而过的 Unity 提示窗**。这是本工具注入导致的已知现象，
属于正常表现，**无需担心**，不会影响账号、存档与对局数据。游戏窗口真正关闭后，
本工具会自动退出。

## 目录结构

    tools_hook\
      release\AutoSkip\        ← 编译好的成品（直接用这个）
        月圆之夜自动跳过.exe
        yyzyhook.dll
        app.ico
        tray_config.json
      python\                  ← 源码
        yyzy_tray.py           托盘主程序（UI / 注入 / 断网调度）
        hook_client.py         管道通信 / 注入 / 热键
        input_synth.py         外部鼠标键盘模拟
        close_watcher.py       窗口关闭辅助
      src\                     ← DLL 源码（C++）
        dllmain.cpp            入口
        ws2hook.cpp            ws2_32 钩子（断网实现）
        pipe.cpp               命名管道命令处理
        il2cppui.cpp           Unity 反射层（读游戏文字）
        unityapi_impl.h        Unity API 封装
        seh_guard.cpp          异常护栏
        close_intercept.cpp    退出相关（当前为空实现）
      minhook-1.3.3\           ← 编译依赖
      build.bat                ← 编译 DLL
      app.ico                 ← 图标源文件

## 重新构建

编译 DLL（需要 VS Build Tools 2022）：

    build.bat

打包 exe（需要 PyInstaller）：

    pyinstaller --noconfirm --clean --distpath out yyzy_tray.spec

## 工作原理

1. 托盘程序把 `yyzyhook.dll` 注入游戏进程（远程 `LoadLibrary`，失败退回 `SetWindowsHookEx`）
2. DLL 内一个线程每 250ms 遍历游戏里所有激活的 `TextMeshProUGUI`，读 `m_text` 内容
3. 一旦文本包含关键字（如「开始战斗」），立即置位断网标志
4. 断网动作：钩住 `ws2_32` 的 `send`/`recv`，标志置位时**关闭全部套接字**
   —— 因为战斗连接早已建立，只有在进程内的数据通路上才能掐断
5. 游戏检测到连接断开，回到商店，战斗开场被跳过
