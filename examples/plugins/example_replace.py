"""示例插件：将 -> / <- / :ok: 替换为箭头与标记。

安装：把本文件复制到插件目录（设置面板中显示路径），
即复制为 ``<插件目录>/example_replace.py``，然后在 设置 → 插件 中勾选启用。
"""

import xml.etree.ElementTree as etree

from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor


class ReplaceProcessor(InlineProcessor):
    REPLACEMENTS = {
        "->": "→",
        "<-": "←",
        ":ok:": "✅",
    }

    def handleMatch(self, match, data):
        key = match.group(1)
        if key not in self.REPLACEMENTS:
            return None, match.start(0), match.end(0)
        span = etree.Element("span")
        span.text = self.REPLACEMENTS[key]
        return span, match.start(0), match.end(0)


class ExampleReplaceExtension(Extension):
    PATTERN = r"(:ok:|->|<-)"

    def extendMarkdown(self, md):
        md.inlinePatterns.register(
            ReplaceProcessor(self.PATTERN, md), "short-replace", 175
        )


def makeExtension(**kwargs):  # noqa: N802（Python-Markdown 固定入口名）
    return ExampleReplaceExtension(**kwargs)
