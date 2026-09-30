"""插件加载器测试：python tests/test_plugin_loader.py

使用临时插件目录，不触碰用户数据。
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mdnote.services.plugin_loader import discover, load_enabled  # noqa: E402
from mdnote.services.markdown_engine import MarkdownEngine  # noqa: E402

PASS = 0
FAIL = 0


def ok(cond, name):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"FAIL {name}")


GOOD_PLUGIN = '''
from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor
import xml.etree.ElementTree as etree

class P(InlineProcessor):
    def handleMatch(self, m, data):
        span = etree.Element("span")
        span.text = "REPLACED"
        return span, m.start(0), m.end(0)

class E(Extension):
    def extendMarkdown(self, md):
        md.inlinePatterns.register(P(r"TOK", md), "tok", 200)

def makeExtension(**kwargs):
    return E()
'''

BAD_PLUGIN = 'def makeExtension(**kwargs):\n    raise RuntimeError("boom")\n'

NO_FACTORY = "x = 1\n"


with tempfile.TemporaryDirectory() as tmp:
    d = Path(tmp)
    (d / "good.py").write_text(GOOD_PLUGIN, encoding="utf-8")
    (d / "bad.py").write_text(BAD_PLUGIN, encoding="utf-8")
    (d / "nofactory.py").write_text(NO_FACTORY, encoding="utf-8")
    pkg = d / "pkg_ext"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(GOOD_PLUGIN, encoding="utf-8")
    (d / "_ignored.py").write_text("x=1", encoding="utf-8")

    found = discover(d)
    names = sorted(p.name for p in found)
    ok(names == ["bad", "good", "nofactory", "pkg_ext"], f"discover 结果 {names}")
    ok(next(p for p in found if p.name == "pkg_ext").kind == "package", "识别包形式插件")

    instances, errors = load_enabled(["good", "bad", "nofactory", "missing", "pkg_ext"], d)
    ok(len(instances) == 2, f"成功实例化 2 个（实际 {len(instances)}）")

    err_map = dict(errors)
    ok("bad" in err_map and "boom" in err_map["bad"], f"bad 插件报错 {err_map.get('bad')}")
    ok("nofactory" in err_map, "无 makeExtension 报错")
    ok(err_map.get("missing") == "未找到该插件", f"缺失插件 {err_map.get('missing')}")

    # 用加载到的扩展构建引擎，验证它确实参与渲染
    engine = MarkdownEngine(instances[:1])
    out = engine.render("a TOK b")
    ok("REPLACED" in out, f"插件影响渲染：{out}")
    ok("TOK" not in out, "原标记被替换")

print(f"\n{'='*40}")
print(f"结果：{PASS} 通过，{FAIL} 失败")
if FAIL:
    sys.exit(1)
