"""文件夹全文检索：在后台线程遍历目录，返回文件名与正文匹配。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot

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
    cancelled: Callable[[], bool] | None = None,
) -> list[SearchHit]:
    if not query or max_hits <= 0:
        return []
    root_path = Path(root)
    needle = query if case_sensitive else query.lower()
    allowed = suffixes if suffixes is not None else TEXT_SUFFIXES
    hits: list[SearchHit] = []
    visited: set[Path] = set()
    should_stop = cancelled or (lambda: False)

    def contains(haystack: str) -> bool:
        return needle in (haystack if case_sensitive else haystack.lower())

    def walk(directory: Path) -> None:
        if should_stop():
            return
        try:
            resolved = directory.resolve()
            if resolved in visited:
                return
            visited.add(resolved)
            entries = sorted(directory.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return
        for entry in entries:
            if should_stop() or len(hits) >= max_hits:
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
                        with entry.open(encoding="utf-8", errors="ignore") as stream:
                            for i, line_text in enumerate(stream, 1):
                                if should_stop() or len(hits) >= max_hits:
                                    break
                                if contains(line_text):
                                    hits.append(
                                        SearchHit(entry, "content", i, line_text.strip()[:160])
                                    )
                    except OSError:
                        continue

    if root_path.exists():
        walk(root_path)
    return hits


class SearchWorker(QThread):
    """一次后台检索；只通过信号把结果交给主线程。"""

    results = Signal(int, list)

    def __init__(self, parent, request_id: int, root: str, query: str,
                 case_sensitive: bool = False) -> None:
        super().__init__(parent)
        self.request_id = request_id
        self._root = root
        self._query = query
        self._case = case_sensitive

    def run(self) -> None:
        try:
            hits = search(self._root, self._query, case_sensitive=self._case,
                          cancelled=self.isInterruptionRequested)
        except Exception:
            hits = []
        payload = [
            {"path": str(h.path), "kind": h.kind, "line": h.line, "text": h.text}
            for h in hits
        ]
        self.results.emit(self.request_id, payload)


class SearchController(QObject):
    """串行执行检索，取消过期请求，仅发布最新请求的结果。"""

    results = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._request_id = 0
        self._worker: SearchWorker | None = None
        self._pending: tuple | None = None

    def cancel(self) -> None:
        self._request_id += 1
        self._pending = None
        if self._worker is not None:
            self._worker.requestInterruption()

    def request(self, root: str, query: str, case_sensitive: bool = False) -> None:
        self.cancel()
        if not query:
            return
        self._pending = (self._request_id, root, query, case_sensitive)
        if self._worker is None:
            self._start_pending()

    def _start_pending(self) -> None:
        if self._pending is None:
            return
        worker = SearchWorker(self, *self._pending)
        self._pending = None
        self._worker = worker
        worker.results.connect(self._on_results)
        worker.finished.connect(self._on_finished)
        worker.start()

    @Slot(int, list)
    def _on_results(self, request_id: int, payload: list) -> None:
        if request_id == self._request_id:
            self.results.emit(payload)

    @Slot()
    def _on_finished(self) -> None:
        worker = self.sender()
        if worker is not self._worker:
            return
        self._worker = None
        worker.deleteLater()
        self._start_pending()

    def shutdown(self, timeout_ms: int = 2000) -> bool:
        """取消任务并等待退出；超时返回 False，调用者须保留对象。"""
        self.cancel()
        if self._worker is None:
            return True
        worker = self._worker
        if not worker.wait(timeout_ms):
            return False
        self._worker = None
        worker.deleteLater()
        return True
