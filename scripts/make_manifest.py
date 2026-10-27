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
from urllib.parse import urlsplit

try:
    from .prepare_installer import read_app_version
except ImportError:
    from prepare_installer import read_app_version


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", required=True, type=Path)
    parser.add_argument("--version", default=read_app_version(),
                        help="Defaults to mdnote.__version__; must match it")
    parser.add_argument("--url", required=True)
    parser.add_argument("--mirror", action="append", default=[],
                        help="Optional publisher-controlled HTTPS mirror; repeat for multiple sources")
    parser.add_argument("--notes", default="")
    parser.add_argument(
        "--notes-file", default=None, type=Path,
        help="从 UTF-8 文件读取更新说明（避免命令行中文编码问题）",
    )
    parser.add_argument("--min-version", default=None)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.version != read_app_version():
        parser.error("--version must match mdnote.__version__; update that source first")

    try:
        if len(args.mirror) > 8:
            raise ValueError("too many mirrors")
        for url in [args.url, *args.mirror]:
            address = urlsplit(url)
            if (address.scheme.lower() != "https" or not address.hostname or
                    address.username is not None or address.password is not None or
                    any(ord(character) < 33 for character in url)):
                raise ValueError("invalid HTTPS URL")
            address.port
    except ValueError:
        parser.error("--url / --mirror must be HTTPS URLs without embedded credentials (at most 8 mirrors)")

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
    if args.mirror:
        manifest["mirrors"] = list(dict.fromkeys(args.mirror))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"manifest written: {args.out}")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
