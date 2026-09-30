"""字数 / 字符 / 行数 / 阅读时长统计。"""

from dataclasses import dataclass
import re


@dataclass
class DocStats:
    words: int
    chars: int
    lines: int
    reading_minutes: int


def count_stats(text: str) -> DocStats:
    chars = len(text)
    # 中英文混排：中文字符各计 1 字，英文按单词计
    cjk = len(re.findall(r"[一-鿿]", text))
    en_words = len(re.findall(r"[A-Za-z0-9_]+", text))
    words = cjk + en_words
    lines = len(text.splitlines()) if text else 0
    reading = max(1, round(words / 400)) if words else 1
    return DocStats(words=words, chars=chars, lines=lines, reading_minutes=reading)
