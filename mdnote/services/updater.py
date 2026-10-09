"""HTTPS 更新清单、流式下载与必需的安装包 SHA256 校验。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .. import __version__

_VERSION_RE = re.compile(r"v?[0-9]{1,9}(?:\.[0-9]{1,9}){0,3}(?:[-+][A-Za-z0-9.-]{1,64})?")
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")
_MANIFEST_LIMIT = 1 << 20


def _https_url(value: str) -> str:
    """Updates execute code, so local/HTTP URLs and embedded credentials are rejected."""
    if not isinstance(value, str) or any(ord(ch) < 33 for ch in value):
        raise ValueError("更新地址必须是有效的 HTTPS URL")
    try:
        parts = urlsplit(value)
        valid = (parts.scheme.lower() == "https" and bool(parts.hostname)
                 and parts.username is None and parts.password is None)
        parts.port  # Validate malformed ports as well.
    except ValueError as exc:
        raise ValueError("更新地址必须是有效的 HTTPS URL") from exc
    if not valid:
        raise ValueError("更新地址必须使用 HTTPS，且不能含用户名或密码")
    return value


def _version(value: str) -> str:
    if not isinstance(value, str) or not _VERSION_RE.fullmatch(value):
        raise ValueError("更新版本号格式无效")
    return value


@dataclass
class ReleaseInfo:
    version: str
    notes: str
    url: str
    sha256: str
    min_version: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "ReleaseInfo":
        if not isinstance(data, dict):
            raise ValueError("更新清单必须是 JSON 对象")
        missing = [key for key in ("version", "url", "sha256") if not data.get(key)]
        if missing:
            raise ValueError(f"更新清单缺少字段: {', '.join(missing)}")
        digest = data["sha256"]
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise ValueError("安装包 SHA256 必须是 64 位十六进制摘要")
        minimum = data.get("minVersion")
        if minimum is not None:
            minimum = _version(minimum)
        notes = data.get("notes", "")
        if not isinstance(notes, str):
            raise ValueError("更新说明必须是文本")
        return cls(_version(data["version"]), notes, _https_url(data["url"]),
                   digest.lower(), minimum)


def parse_manifest(raw: str | bytes) -> ReleaseInfo:
    if len(raw) > _MANIFEST_LIMIT:
        raise ValueError("更新清单超过大小限制")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig")
    return ReleaseInfo.from_dict(json.loads(raw))


def _parse_version(value: str) -> tuple[int, ...]:
    value = _version(value).lstrip("v")
    value = re.split(r"[-+]", value, maxsplit=1)[0]
    return tuple(int(piece) for piece in value.split("."))


def compare_versions(remote: str, current: str) -> bool:
    """remote 是否比 current 新。"""
    a, b = _parse_version(remote), _parse_version(current)
    count = max(len(a), len(b))
    return a + (0,) * (count - len(a)) > b + (0,) * (count - len(b))


class UpdateManager(QObject):
    """One manifest request and one download at a time; stale replies are ignored."""

    update_available = Signal(object)
    check_failed = Signal(str)
    check_finished = Signal(bool)  # Successful check: True means a newer version exists.
    download_progress = Signal(int)
    download_finished = Signal(str)
    download_failed = Signal(str)

    def __init__(self, manifest_url: str, current_version: str = __version__,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._url = manifest_url
        self._current = current_version
        self._nam = QNetworkAccessManager(self)
        self._release: ReleaseInfo | None = None
        self._check_reply: QNetworkReply | None = None
        self._reply: QNetworkReply | None = None
        self._download_release: ReleaseInfo | None = None
        self._file = None
        self._tmp_path: str | None = None
        self._hasher = hashlib.sha256()

    @staticmethod
    def _request(url: str) -> QNetworkRequest:
        request = QNetworkRequest(QUrl(_https_url(url)))
        request.setTransferTimeout(30_000)
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        return request

    @property
    def busy(self) -> bool:
        return self._reply is not None

    @property
    def checking(self) -> bool:
        return self._check_reply is not None

    def set_manifest_url(self, url: str) -> None:
        if url == self._url:
            return
        self._url = url
        self._release = None
        reply, self._check_reply = self._check_reply, None
        if reply is not None:
            reply.abort()
            reply.deleteLater()

    def check(self, *, silent: bool = False) -> None:
        if self.checking or self.busy:
            return
        try:
            request = self._request(self._url)
        except ValueError as exc:
            if not silent:
                self.check_failed.emit(str(exc))
            return
        reply = self._nam.get(request)
        self._check_reply = reply
        reply.finished.connect(lambda: self._on_check_finished(reply, silent))

    def _on_check_finished(self, reply: QNetworkReply, silent: bool) -> None:
        if reply is not self._check_reply:
            return
        self._check_reply = None
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                raise ValueError(f"网络错误：{reply.errorString()}")
            _https_url(reply.url().toString())
            release = parse_manifest(bytes(reply.readAll()))
            newer = compare_versions(release.version, self._current)
        except (ValueError, UnicodeError, TypeError) as exc:
            if not silent:
                self.check_failed.emit(f"更新清单无效：{exc}")
            return
        finally:
            reply.deleteLater()
        self._release = release if newer else None
        if newer:
            self.update_available.emit(release)
        self.check_finished.emit(newer)

    def download(self) -> None:
        if self._release is None or self.busy:
            return
        try:
            # Revalidate even ReleaseInfo instances supplied by callers.
            release = ReleaseInfo.from_dict({
                "version": self._release.version, "notes": self._release.notes,
                "url": self._release.url, "sha256": self._release.sha256,
                **({"minVersion": self._release.min_version} if self._release.min_version else {}),
            })
            request = self._request(release.url)
            suffix = PurePosixPath(urlsplit(release.url).path).suffix.lower()
            # MdNote's Windows installer is an executable; query strings are never filenames.
            if suffix and suffix != ".exe":
                raise ValueError("更新安装包必须是 EXE 文件")
            suffix = suffix or ".exe"
            descriptor, target = tempfile.mkstemp(prefix="mdnote-update-", suffix=suffix)
            self._tmp_path = target
            try:
                self._file = os.fdopen(descriptor, "wb")
            except OSError:
                os.close(descriptor)
                raise
            self._hasher = hashlib.sha256()
            self._download_release = release
            reply = self._nam.get(request)
            self._reply = reply
            reply.readyRead.connect(lambda: self._on_ready_read(reply))
            reply.downloadProgress.connect(
                lambda received, total: self._on_progress(received, total, reply))
            reply.finished.connect(lambda: self._on_download_finished(reply))
        except (OSError, ValueError) as exc:
            self._finish_download(f"无法开始下载：{exc}")

    def _on_ready_read(self, reply: QNetworkReply | None = None) -> None:
        reply = self._reply if reply is None else reply
        if reply is None or reply is not self._reply or self._file is None:
            return
        try:
            chunk = bytes(reply.readAll())
            if self._file.write(chunk) != len(chunk):
                raise OSError("磁盘未完整写入下载内容")
            self._hasher.update(chunk)
        except OSError as exc:
            self._finish_download(f"安装包写入失败：{exc}")

    def _on_progress(self, received, total, reply=None) -> None:
        if reply is not None and reply is not self._reply:
            return
        if total > 0:
            self.download_progress.emit(max(0, min(100, int(received * 100 / total))))

    def _on_download_finished(self, reply: QNetworkReply | None = None) -> None:
        reply = self._reply if reply is None else reply
        if reply is None or reply is not self._reply:
            return
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._finish_download(f"下载失败：{reply.errorString()}")
            return
        try:
            _https_url(reply.url().toString())
        except ValueError as exc:
            self._finish_download(str(exc))
            return
        if reply.bytesAvailable():
            self._on_ready_read(reply)
        if reply is not self._reply:  # A final disk write may already have failed.
            return
        if (self._download_release is None or
                self._hasher.hexdigest() != self._download_release.sha256):
            self._finish_download("安装包校验失败（SHA256 不一致），已中止。")
            return
        self._finish_download()

    def _finish_download(self, error: str | None = None, *, notify: bool = True) -> None:
        reply, self._reply = self._reply, None
        stream, self._file = self._file, None
        target, self._tmp_path = self._tmp_path, None
        self._download_release = None
        if stream is not None:
            try:
                if error is None:
                    stream.flush()
                    os.fsync(stream.fileno())
                stream.close()
            except OSError as exc:
                error = error or f"安装包写入失败：{exc}"
                try:
                    stream.close()
                except OSError:
                    pass
        if reply is not None:
            if error:
                reply.abort()
            reply.deleteLater()
        if error:
            self._remove_temp(target)
            if notify:
                self.download_failed.emit(error)
        elif target:
            self.download_finished.emit(target)

    @staticmethod
    def _remove_temp(target: str | None) -> None:
        if target:
            try:
                os.unlink(target)
            except OSError:
                pass

    def _cleanup_temp(self) -> None:
        target, self._tmp_path = self._tmp_path, None
        self._remove_temp(target)

    def cancel_download(self, *, silent: bool = False) -> None:
        if self.busy:
            self._finish_download("下载已取消。", notify=not silent)

    def shutdown(self) -> None:
        reply, self._check_reply = self._check_reply, None
        if reply is not None:
            reply.abort()
            reply.deleteLater()
        self.cancel_download(silent=True)

    @property
    def release(self) -> ReleaseInfo | None:
        return self._release

    def required(self) -> bool:
        return bool(self._release and self._release.min_version and
                    compare_versions(self._release.min_version, self._current))
