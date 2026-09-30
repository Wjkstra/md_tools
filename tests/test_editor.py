"""编辑器变换的完整回归测试：覆盖所有块类型的回车 / 退格合并 / 缩进 / 空格触发。

运行：python tests/test_editor.py
（纯函数测试，无需 GUI / Qt）
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mdnote.editor import transforms as T  # noqa: E402

PASS = 0
FAIL = 0


def check(name, got, want):
    """got/want 为 dict，比较其中声明的字段。"""
    global PASS, FAIL
    bad = {k: (got.get(k) if isinstance(got, dict) else getattr(got, k, None))
           for k in want if (got.get(k) if isinstance(got, dict) else getattr(got, k, None)) != want[k]}
    if bad:
        FAIL += 1
        print(f"FAIL {name}: want {want} mismatch {bad}")
    else:
        PASS += 1


# ---------------- 段落：任意位置回车 ----------------

r = T.split_at("ABCDEF", "paragraph", 6)
check("段落末尾回车", r, {"text": "ABCDEF\n", "caret": 7})

r = T.split_at("ABCDEF", "paragraph", 3)
check("段落中间回车-截断", r, {"text": "ABC\nDEF", "caret": 4})

r = T.split_at("ABCDEF", "paragraph", 0)
check("段落开头回车", r, {"text": "\nABCDEF", "caret": 1})

# ---------------- 标题：回车产生普通段落 ----------------

r = T.split_at("# 标题", "heading", 4)
check("标题末尾回车-新段落", r, {"caret": 5})
check("标题末尾回车-无井号", r, {"text": "# 标题\n"})

# 标题中间回车：前半保留标题，后半变普通段落
r = T.split_at("# 甲乙", "heading", 3)
check("标题中间回车-后半变段落", r,
      {"text": "# 甲\n乙", "caret": 4})

# ---------------- 无序列表 ----------------

r = T.split_at("- 甲", "list", 3)
check("列表项后回车-新增标记", r, {"text": "- 甲\n- ", "caret": 6})

r = T.split_at("- 甲\n- ", "list", 6)
check("空列表项回车-取消格式", r, {"text": "- 甲\n", "caret": 4})

# 加号 / 星号标记
r = T.split_at("* 甲", "list", 3)
check("星号列表续行", r, {"text": "* 甲\n* ", "caret": 6})

# 嵌套缩进
r = T.split_at("  - 嵌套", "list", 5)
check("嵌套列表中间回车-截断并保持缩进", r,
      {"text": "  - 嵌\n  - 套", "caret": 10})

# 列表中间回车：后半段进入新项
r = T.split_at("- 甲乙", "list", 3)
check("列表中间回车-后半段成新项", r,
      {"text": "- 甲\n- 乙", "caret": 6})

# 有序列表中间：序号递增且后半段下移
r = T.split_at("1. 甲乙", "list", 4)
check("有序列表中间回车", r,
      {"text": "1. 甲\n2. 乙", "caret": 8})

# ---------------- 有序列表：自动递增 ----------------

r = T.split_at("1. 甲", "list", 4)
check("有序列表续行递增", r, {"text": "1. 甲\n2. ", "caret": 8})

r = T.split_at("3) 甲", "list", 4)
check("右括号序号续行", r, {"text": "3) 甲\n4) ", "caret": 8})

r = T.split_at("9. 甲", "list", 4)
check("序号9进位10", r, {"text": "9. 甲\n10. ", "caret": 9})

# 空有序项取消
r = T.split_at("1. 甲\n2. ", "list", 8)
check("空有序项取消格式", r, {"text": "1. 甲\n", "caret": 5})

# ---------------- 引用块 ----------------

r = T.split_at("> 引用", "blockquote", 4)
check("引用后续行", r, {"text": "> 引用\n> ", "caret": 7})

# 引用中间回车：后半段进入新引用行
r = T.split_at("> 甲乙", "blockquote", 3)
check("引用中间回车-截断", r,
      {"text": "> 甲\n> 乙", "caret": 6})

r = T.split_at("> 引用\n> ", "blockquote", 7)
check("空引用回车取消", r, {"text": "> 引用\n", "caret": 5})

# ---------------- 代码 / 数学：回车在块内插入换行 ----------------

r = T.split_at("```\nab\n```", "code", 4)
check("代码块内回车-插入换行", r, {"text": "```\n\nab\n```", "caret": 5})

r = T.split_at("$$\nab\n$$", "math", 3)
check("数学块内回车-插入换行", r, {"text": "$$\n\nab\n$$", "caret": 4})

# ---------------- 退格：行首合并 ----------------

r = T.merge_with("上一段", "这一段")
check("退格合并", r, {"text": "上一段\n这一段", "caret": 4})

# ---------------- Tab 缩进 ----------------

r = T.indent_line("- 甲", 3, 2, False)
check("Tab 增加缩进", r, {"text": "  - 甲"})

r = T.indent_line("  - 甲", 5, 2, True)
check("Shift+Tab 减少缩进", r, {"text": "- 甲"})

# ---------------- 空格触发 ----------------

r = T.detect_space_trigger("# ", 2)
check("空格触发-标题标记", r, {"text": "# "})

r = T.detect_space_trigger("- ", 2)
check("空格触发-列表标记", r, {"text": "- "})

r = T.detect_space_trigger("> ", 2)
check("空格触发-引用标记", r, {"text": "> "})

r = T.detect_space_trigger("普通文字", 4)
if r is None:
    PASS += 1
else:
    FAIL += 1
    print("FAIL 普通文本无触发: 应返回 None")

# 代码围栏触发
r = T.detect_space_trigger("```js", 5)
check("围栏触发成块", r, {"caret": 6})

# ---------------- 选区包裹 ----------------

r, s, e = T.wrap_selection("abc", 0, 3, "**")
check("选区加粗", r, {"text": "**abc**", "caret": 7})

r, s, e = T.wrap_selection("abc", 3, 3, "**")
check("无选区插入占位", r, {"text": "abc****"})

# ---------------- 插入 ----------------

r = T.insert_at("ab", 1, "X")
check("插入文本", r, {"text": "aXb", "caret": 2})

# ---------------- 块模型：解析 → 序列化 往返一致 ----------------

from mdnote.editor.block_model import build_model, serialize  # noqa: E402

sample = (
    "# 标题\n\n普通**段落**。\n\n- 甲\n- 乙\n\n"
    "> 引用\n\n```js\nconst a = 1\n```\n\n$$\nx\n$$\n"
)
if serialize(build_model(sample)) == sample:
    PASS += 1
else:
    FAIL += 1
    print("FAIL 块模型序列化往返不一致")


def main():
    print(f"\n{'='*40}")
    print(f"结果：{PASS} 通过，{FAIL} 失败")
    if FAIL:
        sys.exit(1)


if __name__ == "__main__":
    main()
