"""搜索服务测试：python tests/test_search_service.py"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mdnote.services.search_service import search, SearchHit  # noqa: E402

PASS = 0
FAIL = 0


def ok(cond, name):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"FAIL {name}")


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    (root / "alpha.md").write_text(
        "# Alpha\nhello needle world\nanother line\n", encoding="utf-8"
    )
    sub = root / "sub"
    sub.mkdir()
    (sub / "beta.md").write_text("needle here too\n", encoding="utf-8")
    # 应被跳过的目录
    git = root / ".git"
    git.mkdir()
    (git / "x.md").write_text("needle in git\n", encoding="utf-8")
    # 非文本后缀，默认不检索
    (root / "pic.png").write_text("needle", encoding="utf-8")

    hits = search(str(root), "needle")
    content_hits = [h for h in hits if h.kind == "content"]

    ok(len(hits) == 2, f"找到 2 处正文匹配（实际 {len(hits)}）")
    ok(all(isinstance(h, SearchHit) for h in hits), "返回 SearchHit")
    first = next(h for h in hits if h.path.name == "alpha.md")
    ok(first.line == 2, f"alpha 命中行号为 2（实际 {first.line}）")
    ok("needle" in first.text, "命中行文本包含关键词")
    ok(any(h.path.name == "beta.md" for h in hits), "递归搜索子目录")
    ok(all(".git" not in str(h.path) for h in hits), "跳过 .git")
    ok(all(h.path.suffix != ".png" for h in hits), "默认跳过非文本后缀")

    # 大小写：默认不敏感
    ok(bool(search(str(root), "NEEDLE")), "默认大小写不敏感")
    ok(not search(str(root), "NEEDLE", case_sensitive=True), "大小写敏感时不匹配")

    # 文件名匹配
    name_hits = search(str(root), "alpha")
    ok(any(h.kind == "name" for h in name_hits), "识别文件名匹配")

    # 上限
    limited = search(str(root), "needle", max_hits=1)
    ok(len(limited) == 1, "遵守 max_hits 上限")

print(f"\n{'='*40}")
print(f"结果：{PASS} 通过，{FAIL} 失败")
if FAIL:
    sys.exit(1)
