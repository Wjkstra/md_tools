"""文件夹全文检索：在后台线程遍历目录，返回文件名与正文匹配。"""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

# 不进入检索的目录名
SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules",
    ".venv", "venv", ".idea", ".vscode", "dist", "build",
}

# 默认只检索这些文本类文件
TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
MAX_FILE_BYTES = 2_000_000      # 跳过超大文件
MAX_TOTAL_MATCHES = 200


@dataclass
class SearchHit:
    path: Path
    kind: str          # "name" | "content"
    line: int          # 行号（文件名匹配为 0）
    text: str          # 匹配行片段（文件名匹配为文件名）


def search(
    root: str,
    query: str,
    *,
    suffixes: set[str] | None = None,
    case_sensitive: bool = False,
    max_hits: int = MAX_TOTAL_MATCHES,
) -> list[SearchHit]:
    root_path = Path(root)
    needle = query if case_sensitive else query.lower()
    allowed = suffixes if suffixes is not None else TEXT_SUFFIXES
    hits: list[SearchHit] = []

    def contains(haystack: str) -> bool:
        return needle in (haystack if case_sensitive else haystack.lower())

    def walk(directory: Path) -> None:
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return
        for entry in entries:
            if len(hits) >= max_hits:
                return
            name = entry.name
            if entry.is_dir():
                if name in SKIP_DIRS or name.startswith("."):
                    continue
                walk(entry)
                continue
            if entry.is_file() and entry.suffix.lower() in allowed:
                try:
                    stat = entry.stat()
                except OSError:
                    continue
                # 文件名匹配
                if contains(name):
                    hits.append(SearchHit(entry, "name", 0, name))
                # 正文匹配
                if stat.st_size <= MAX_FILE_BYTES:
                    try:
                        lines = entry.read_text(encoding="utf-8", errors="ignore").splitlines()
                    except OSError:
                        lines = []
                    for i, line_text in enumerate(lines, 1):
                        if len(hits) >= max_hits:
                            break
                        if contains(line_text):
                            hits.append(
                                SearchHit(entry, "content", i, line_text.strip()[:160])
                            )

    if root_path.exists():
        walk(root_path)
    return hits


class SearchWorker(QObject):
    """可放进 QThread 的检索任务，完成后发信号。"""

    finished = Signal(list)

    def __init__(self, root: str, query: str, case_sensitive: bool = False) -> None:
        super().__init__()
        self._root = root
        self._query = query
        self._case = case_sensitive

    def run(self) -> None:
        try:
            hits = search(self._root, self._query, case_sensitive=self._case)
        except Exception:
            hits = []
        # dataclass 不能直接跨线程，转成普通 dict
        payload = [
            {"path": str(h.path), "kind": h.kind, "line": h.line, "text": h.text}
            for h in hits
        ]
        self.finished.emit(payload)


def start_search(
    parent,
    root: str,
    query: str,
    on_done,
    case_sensitive: bool = False,
) -> tuple[QThread, SearchWorker]:
    """启动后台检索；完成回调 on_done(payload)。线程与 worker 由 parent 持有。"""
    thread = QThread(parent)
    worker = SearchWorker(root, query, case_sensitive)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)

    def handle(payload) -> None:
        on_done(payload)
        thread.quit()

    worker.finished.connect(handle)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread, worker
