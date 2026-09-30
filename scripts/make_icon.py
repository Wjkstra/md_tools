"""生成 MdNote 应用图标：圆角渐变底 + 白色粗体 M。

运行（仓库根目录）： python scripts/make_icon.py
输出：
  mdnote/resources/icon.ico   多尺寸（16~256）
  mdnote/resources/icon.png   256px
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).resolve().parent.parent / "mdnote" / "resources"

MASTER = 1024
RADIUS = 224
TOP = (74, 143, 251)      # 亮蓝
BOTTOM = (10, 88, 220)    # 深蓝
LETTER = "M"
FONT = "C:/Windows/Fonts/segoeuib.ttf"
ICON_SIZES = [16, 24, 32, 48, 64, 128, 256]


def make_master() -> Image.Image:
    # 垂直渐变
    t = np.linspace(0, 1, MASTER, dtype=np.float32)[:, None]
    top = np.array(TOP, dtype=np.float32)
    bottom = np.array(BOTTOM, dtype=np.float32)
    rgb = (top * (1 - t) + bottom * t)
    rgb = np.repeat(rgb[:, None, :], MASTER, axis=1)

    img = Image.fromarray(rgb.astype(np.uint8), "RGB")

    # 圆角蒙版
    mask = Image.new("L", (MASTER, MASTER), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle((0, 0, MASTER - 1, MASTER - 1), radius=RADIUS, fill=255)
    img.putalpha(mask)

    # 顶部内高光（轻微）
    highlight = Image.new("RGBA", (MASTER, MASTER), (0, 0, 0, 0))
    hd = ImageDraw.Draw(highlight)
    hd.rounded_rectangle(
        (24, 18, MASTER - 25, MASTER // 2 - 60), radius=RADIUS - 24,
        outline=(255, 255, 255, 46), width=10,
    )
    img = Image.alpha_composite(img, highlight)

    # 字母 M，光学居中
    layer = Image.new("RGBA", (MASTER, MASTER), (0, 0, 0, 0))
    font = ImageFont.truetype(FONT, 620)
    ld = ImageDraw.Draw(layer)
    bbox = ld.textbbox((0, 0), LETTER, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (MASTER - w) / 2 - bbox[0]
    y = (MASTER - h) / 2 - bbox[1] + 26
    ld.text((x, y), LETTER, font=font, fill=(255, 255, 255, 255))
    return Image.alpha_composite(img, layer)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    master = make_master()
    master.save(OUT_DIR / "icon.png")

    images = [master.resize((s, s), Image.LANCZOS) for s in ICON_SIZES]
    images[-1].save(
        OUT_DIR / "icon.ico",
        sizes=[(s, s) for s in ICON_SIZES],
        append_images=images[:-1],
    )
    print(f"icon written: {OUT_DIR/'icon.ico'} ({', '.join(map(str, ICON_SIZES))})")


if __name__ == "__main__":
    main()
