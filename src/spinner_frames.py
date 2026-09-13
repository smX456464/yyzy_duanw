"""跑马灯式加载动画：3 个伪 3D 方块，颜色池洗牌后循环滚动
- 3 个固定位置的方块
- 每个独立上跳，相位错开 1/3 周期
- 每 5 帧颜色池前进一格
"""
import math
import random
from PIL import Image, ImageDraw, ImageTk


DEFAULT_COLORS = [
    (244, 67, 54),   # 红
    (233, 30, 99),   # 粉
    (156, 39, 176),  # 紫
    (103, 58, 183),  # 深紫
    (63, 81, 181),   # 靛蓝
    (33, 150, 243),  # 蓝
    (0, 188, 212),   # 青
    (0, 150, 136),   # 蓝绿
    (76, 175, 80),   # 绿
    (139, 195, 74),  # 浅绿
    (255, 193, 7),   # 黄
    (255, 87, 34),   # 深橙
]


def _draw_3d_block(draw, x, y, w, color):
    """伪 3D 方块：顶亮 + 主色 + 底暗"""
    r, g, b = color
    top = (min(255, r + 60), min(255, g + 60), min(255, b + 60), 255)
    mid = (r, g, b, 255)
    bot = (max(0, r - 60), max(0, g - 60), max(0, b - 60), 255)
    h3 = max(2, w // 3)
    draw.rectangle([x, y, x + w - 1, y + h3 - 1], fill=top)
    draw.rectangle([x, y + h3, x + w - 1, y + 2 * h3 - 1], fill=mid)
    draw.rectangle([x, y + 2 * h3, x + w - 1, y + w - 1], fill=bot)


def make_spinner_frames(size=64, frames=30, block=10, gap=6,
                        colors=None, seed=None):
    """生成跑马灯式加载动画帧（PIL Image 列表）"""
    if colors is None:
        colors = list(DEFAULT_COLORS)
    if seed is not None:
        random.seed(seed)
    pool = list(colors)
    random.shuffle(pool)
    pool_len = len(pool)

    total_w = block * 3 + gap * 2
    left = (size - total_w) // 2
    base_y = (size - block) // 2

    jump_period = 5          # 一次跳跃/滚动占 5 帧
    phase_shift = 3          # 3 个方块相位各错开 3/5 周期

    frames_list = []
    for f in range(frames):
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        base_idx = f // jump_period   # 每 5 帧颜色前进一格

        for i in range(3):
            # 每个方块独立上跳，相位错开
            phase_f = (f + i * phase_shift) % jump_period
            t = phase_f / jump_period              # 0 ~ 0.8
            jump_h = int(math.sin(t * math.pi) * (block * 1.2))

            color = pool[(base_idx + i) % pool_len]
            bx = left + i * (block + gap)
            by = base_y - jump_h
            _draw_3d_block(draw, bx, by, block, color)

        frames_list.append(img)
    return frames_list


def make_tk_spinner_frames(master, **kwargs):
    """生成 tkinter PhotoImage 帧列表（用 master 持有引用防止 GC）"""
    pil_frames = make_spinner_frames(**kwargs)
    return [ImageTk.PhotoImage(f, master=master) for f in pil_frames]
