"""应用自动更新：检查远程版本、下载安装包并启动安装。

更新清单（``latest.json``）由发布页提供，例如：

```json
{
  "version": "0.2.0",
  "notes": "更新说明（纯文本或 Markdown）",
  "url": "https://.../MdNote-Setup-0.2.0.exe",
  "sha256": "安装包 SHA256（十六进制，推荐填写）",
  "minVersion": "0.1.0"
}
```

``minVersion`` 可选：当前版本低于它时属于建议强制更新。

实现方式：QNetworkAccessManager 在主线程发起请求（Qt 网络本身异步），
通过 reply 的信号驱动，不额外占用线程；下载为流式写临时文件并可报告进度。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .. import __version__


@dataclass
class ReleaseInfo:
    version: str
    notes: str
    url: str
    sha256: str
    min_version: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "ReleaseInfo":
        missing = [k for k in ("version", "url") if not data.get(k)]
        if missing:
            raise ValueError(f"更新清单缺少字段: {', '.join(missing)}")
        return cls(
            version=str(data["version"]).strip(),
            notes=str(data.get("notes", "")),
            url=str(data["url"]).strip(),
            sha256=str(data.get("sha256", "")).strip().lower(),
            min_version=(str(data["minVersion"]).strip()
                         if data.get("minVersion") else None),
        )


def parse_manifest(raw: str | bytes) -> ReleaseInfo:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return ReleaseInfo.from_dict(json.loads(raw))


def _parse_version(v: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in v.strip().lstrip("v").split("."):
        digits = ""
        for ch in piece:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def compare_versions(remote: str, current: str) -> bool:
    """remote 是否比 current 新。"""
    a, b = _parse_version(remote), _parse_version(current)
    n = max(len(a), len(b))
    a = a + (0,) * (n - len(a))
    b = b + (0,) * (n - len(b))
    return a > b


class UpdateManager(QObject):
    """检查更新、下载安装包的编排器，UI 通过信号获得结果。"""

    update_available = Signal(object)    # ReleaseInfo
    check_failed = Signal(str)
    download_progress = Signal(int)     # 0~100
    download_finished = Signal(str)     # 本地安装包路径
    download_failed = Signal(str)

    def __init__(
        self,
        manifest_url: str,
        current_version: str = __version__,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._url = manifest_url
        self._current = current_version
        self._nam = QNetworkAccessManager(self)
        self._release: ReleaseInfo | None = None
        self._reply: QNetworkReply | None = None
        self._file = None
        self._tmp_path: str | None = None
        self._hasher = hashlib.sha256()

    # ---------------- 检查 ----------------

    def check(self, *, silent: bool = False) -> None:
        """silent=True 时失败不发信号（用于启动后的后台检查）。"""
        reply = self._nam.get(QNetworkRequest(QUrl(self._url)))
        reply.finished.connect(lambda: self._on_check_finished(reply, silent))

    def _on_check_finished(self, reply: QNetworkReply, silent: bool) -> None:
        if reply.error() != QNetworkReply.NetworkError.NoError:
            message = f"网络错误：{reply.errorString()}"
            reply.deleteLater()
            if not silent:
                self.check_failed.emit(message)
            return
        data = bytes(reply.readAll())
        reply.deleteLater()
        try:
            release = parse_manifest(data)
        except Exception as e:
            if not silent:
                self.check_failed.emit(f"更新清单无效：{e}")
            return
        if compare_versions(release.version, self._current):
            self._release = release
            self.update_available.emit(release)

    # ---------------- 下载 ----------------

    def download(self) -> None:
        if self._release is None:
            return
        suffix = Path(self._release.url).suffix or ".exe"
        fd, path = tempfile.mkstemp(prefix="mdnote-update-", suffix=suffix)
        self._tmp_path = path
        self._file = os.fdopen(fd, "wb")
        self._hasher = hashlib.sha256()

        self._reply = self._nam.get(QNetworkRequest(QUrl(self._release.url)))
        self._reply.readyRead.connect(self._on_ready_read)
        self._reply.downloadProgress.connect(self._on_progress)
        self._reply.finished.connect(self._on_download_finished)

    def _on_ready_read(self) -> None:
        if self._reply is None or self._file is None:
            return
        chunk = bytes(self._reply.readAll())
        self._file.write(chunk)
        self._hasher.update(chunk)

    def _on_progress(self, received, total) -> None:
        if total > 0:
            self.download_progress.emit(int(received * 100 / total))

    def _on_download_finished(self) -> None:
        reply = self._reply
        error = reply.error() if reply else QNetworkReply.NetworkError.NoError

        # 读完残留数据
        if reply is not None and reply.bytesAvailable():
            self._on_ready_read()
        if self._file is not None:
            self._file.close()
            self._file = None

        if error != QNetworkReply.NetworkError.NoError:
            self._cleanup_temp()
            message = f"下载失败：{reply.errorString()}" if reply else "下载失败"
            self.download_failed.emit(message)
            if reply is not None:
                reply.deleteLater()
            self._reply = None
            return

        if self._release is not None and self._release.sha256:
            digest = self._hasher.hexdigest()
            if digest != self._release.sha256:
                self._cleanup_temp()
                self.download_failed.emit("安装包校验失败（SHA256 不一致），已中止。")
                if reply is not None:
                    reply.deleteLater()
                self._reply = None
                return

        path = self._tmp_path or ""
        if reply is not None:
            reply.deleteLater()
        self._reply = None
        self.download_finished.emit(path)

    # ---------------- 工具 ----------------

    def _cleanup_temp(self) -> None:
        if self._tmp_path:
            try:
                os.unlink(self._tmp_path)
            except OSError:
                pass
            self._tmp_path = None

    @property
    def release(self) -> ReleaseInfo | None:
        return self._release

    def required(self) -> bool:
        """当前版本是否低于清单要求的 minVersion。"""
        return bool(
            self._release
            and self._release.min_version
            and compare_versions(self._release.min_version, self._current)
        )
