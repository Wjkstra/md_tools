"""图片导入服务：源文件复制 / base64 落盘到文档图片目录，返回 Markdown 引用。

对齐 Electron 版 src/main/fs-service.ts 的 importImage / saveImageBuffer。
"""

import base64
import re
import time
from pathlib import Path
from shutil import copyfile


def _unique_path(target: Path) -> Path:
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    n = 1
    while True:
        candidate = target.with_name(f"{stem}-{n}{suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def _normalize_ext(ext: str) -> str:
    ext = ext.lower()
    if ext in (".jpeg", ".jpg"):
        return ".jpg"
    return ext if ext.startswith(".") else f".{ext}"


def import_image(
    *,
    src_path: str | None = None,
    data_url: str | None = None,
    file_name: str | None = None,
    doc_path: str | None = None,
    folder: str = "assets",
    path_type: str = "relative",
) -> str:
    """落盘一张图片，返回 ![](引用)。

    优先使用本地源路径（复制），否则解析 dataURL（base64 解码写入）。
    """
    doc_dir = Path(doc_path).resolve().parent if doc_path else Path.cwd()
    target_dir = (doc_dir / folder).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    if src_path:
        src = Path(src_path)
        stem, ext = src.stem, _normalize_ext(src.suffix or ".png")
        target = _unique_path(target_dir / f"{stem}{ext}")
        copyfile(str(src), str(target))
    elif data_url:
        m = re.match(r"data:image/([\w+]+);base64,(.*)", data_url, re.DOTALL)
        if m:
            ext = _normalize_ext(m.group(1))
            payload = base64.b64decode(m.group(2))
        else:
            # 无头部的纯 base64
            ext = ".png"
            payload = base64.b64decode(data_url)
        stem = file_name or f"image-{time.strftime('%Y%m%d%H%M%S')}"
        target = _unique_path(target_dir / f"{stem}{ext}")
        target.write_bytes(payload)
    else:
        raise ValueError("import_image 需要 src_path 或 data_url")

    if path_type == "absolute":
        ref = target.as_posix()
    else:
        ref = target.relative_to(doc_dir).as_posix()
    return f"![]({ref})"
