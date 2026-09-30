"""发布辅助：根据安装包生成 latest.json 更新清单。

用法（仓库根目录）：

    python scripts/make_manifest.py \
        --installer MdNote-Setup-0.2.0.exe \
        --version 0.2.0 \
        --url https://gitee.com/<用户>/<仓库>/releases/download/v0.2.0/MdNote-Setup-0.2.0.exe \
        --notes "修复若干问题\n新增…" \
        --out dist/latest.json

计算安装包 SHA256 并写入清单；把生成的 latest.json 上传到仓库（或发布页），
其 raw 地址即应用里配置的「更新清单 URL」。
"""

import argparse
import hashlib
import json
from pathlib import Path


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--notes", default="")
    parser.add_argument(
        "--notes-file", default=None, type=Path,
        help="从 UTF-8 文件读取更新说明（避免命令行中文编码问题）",
    )
    parser.add_argument("--min-version", default=None)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    if not args.installer.exists():
        raise SystemExit(f"安装包不存在：{args.installer}")

    notes = args.notes
    if args.notes_file is not None:
        notes = args.notes_file.read_text(encoding="utf-8").strip()

    manifest = {
        "version": args.version,
        "notes": notes,
        "url": args.url,
        "sha256": sha256_of(args.installer),
    }
    if args.min_version:
        manifest["minVersion"] = args.min_version

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"manifest written: {args.out}")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
