// close_intercept.cpp - 空实现（已按用户要求停用）。
//
// 背景：本工具注入游戏后，关闭游戏时 Unity 可能弹出一闪而过的提示窗。
//       这是注入带来的已知现象，属于正常表现，此前尝试过多种"退出前撤回注入"
//       的方案（模块钉住 / detach 停手 / 拦截 DestroyWindow / 窗口守卫线程等），
//       要么无效、要么反而让游戏卡住退不出来。
//       现按用户决定：**不再做任何干预**，让游戏按自身流程自然退出。
#include "yyzyhook.h"

void CloseInterceptStart() {
    // 不再启动任何监视线程：保持"无干预"。
}

void CloseInterceptMarkClosing() {
    // 不再处理：游戏自然退出即可。
}

void CloseInterceptRequestUnload() {
    // 不再处理自卸载。
}
