"""HTTPS 更新清单、流式下载与必需的安装包 SHA256 校验。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .. import __version__

_VERSION_RE = re.compile(r"v?[0-9]{1,9}(?:\.[0-9]{1,9}){0,3}(?:[-+][A-Za-z0-9.-]{1,64})?")
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")
_MANIFEST_LIMIT = 1 << 20
_DOWNLOAD_ATTEMPTS = 3


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
    mirrors: tuple[str, ...] = ()

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
        mirrors = data.get("mirrors", [])
        if not isinstance(mirrors, (list, tuple)) or len(mirrors) > 8:
            raise ValueError("备用下载地址必须是最多 8 项的 HTTPS 地址列表")
        return cls(_version(data["version"]), notes, _https_url(data["url"]),
                   digest.lower(), minimum, tuple(dict.fromkeys(_https_url(u) for u in mirrors)))


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
    download_status = Signal(str)

    def __init__(self, manifest_url: str, current_version: str = __version__,
                 parent: QObject | None = None, *, cache_dir: Path | None = None) -> None:
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
        self._cache_dir = Path(cache_dir) if cache_dir is not None else None
        self._attempt = 0
        self._attempt_limit = _DOWNLOAD_ATTEMPTS
        self._request_offset = 0
        self._response_checked = False
        self._response_end: int | None = None
        self._response_total: int | None = None
        self._started = 0.0
        self._initial_bytes = 0
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._start_attempt)

    @staticmethod
    def _request(url: str) -> QNetworkRequest:
        request = QNetworkRequest(QUrl(_https_url(url)))
        request.setTransferTimeout(30_000)
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        # Some proxies/CDN routes terminate Qt HTTP/2 streams mid-download.
        # HTTPS and certificate verification remain enabled with HTTP/1.1.
        request.setAttribute(QNetworkRequest.Attribute.Http2AllowedAttribute, False)
        request.setRawHeader(b"User-Agent", f"MdNote/{__version__}".encode("ascii"))
        return request

    @property
    def busy(self) -> bool:
        return self._download_release is not None

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
            # QUrl's display format decodes %20 to spaces, including in GitHub
            # release redirects. Validate the wire URL rather than display text.
            _https_url(reply.url().toString(QUrl.ComponentFormattingOption.FullyEncoded))
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
                "mirrors": self._release.mirrors,
                **({"minVersion": self._release.min_version} if self._release.min_version else {}),
            })
            self._request(release.url)
            suffix = PurePosixPath(urlsplit(release.url).path).suffix.lower()
            # MdNote's Windows installer is an executable; query strings are never filenames.
            if suffix and suffix != ".exe":
                raise ValueError("更新安装包必须是 EXE 文件")
            suffix = suffix or ".exe"
            self._hasher = hashlib.sha256()
            if self._cache_dir is not None:
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                cached = self._cache_dir / (release.sha256 + ".exe")
                if cached.is_file() and self._file_digest(cached) == release.sha256:
                    self._prune_cache(cached)
                    self.download_progress.emit(100)
                    self.download_finished.emit(str(cached))
                    return
                self._remove_temp(str(cached))
                target = self._cache_dir / (release.sha256 + ".part")
                self._tmp_path = str(target)
                self._file = target.open("r+b" if target.exists() else "w+b")
                for chunk in iter(lambda: self._file.read(1 << 20), b""):
                    self._hasher.update(chunk)
            else:
                descriptor, target = tempfile.mkstemp(prefix="mdnote-update-", suffix=suffix)
                self._tmp_path = target
                try:
                    self._file = os.fdopen(descriptor, "w+b")
                except OSError:
                    os.close(descriptor)
                    raise
            self._download_release = release
            self._attempt = 0
            self._attempt_limit = max(_DOWNLOAD_ATTEMPTS, len(release.mirrors) + 1)
            self._started = time.monotonic()
            self._initial_bytes = self._file.tell()
            if self._initial_bytes and self._hasher.hexdigest() == release.sha256:
                self._finish_download()
                return
            self._start_attempt()
        except (OSError, ValueError) as exc:
            self._finish_download(f"无法开始下载：{exc}")

    @staticmethod
    def _file_digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _prune_cache(self, current: Path) -> None:
        """Keep this release and one previous installer; touch only owned names."""
        if self._cache_dir is None:
            return
        try:
            owned = [p for p in self._cache_dir.iterdir()
                     if p.is_file() and re.fullmatch(r"[0-9a-f]{64}\.(?:exe|part)", p.name)]
            previous = sorted((p for p in owned if p.suffix == ".exe" and p != current),
                              key=lambda p: p.stat().st_mtime, reverse=True)
            keep = {current, *previous[:1]}
            for path in owned:
                if path not in keep:
                    self._remove_temp(str(path))
        except OSError:
            pass  # Cache housekeeping cannot prevent a verified update.

    def _start_attempt(self) -> None:
        release = self._download_release
        if release is None or self._file is None:
            return
        try:
            urls = (release.url,) + release.mirrors
            request = self._request(urls[self._attempt % len(urls)])
            request.setTransferTimeout(60_000)  # Inactivity, not a whole-download deadline.
            request.setRawHeader(b"Accept-Encoding", b"identity")
            self._request_offset = self._file.tell()
            if self._request_offset:
                request.setRawHeader(b"Range", f"bytes={self._request_offset}-".encode("ascii"))
            self._response_checked = False
            self._response_end = None
            self._response_total = None
            self._attempt += 1
            reply = self._nam.get(request)
            self._reply = reply
            reply.readyRead.connect(lambda: self._on_ready_read(reply))
            reply.downloadProgress.connect(
                lambda received, total: self._on_progress(received, total, reply))
            reply.finished.connect(lambda: self._on_download_finished(reply))
            self.download_status.emit("正在连接更新服务器…" if not self._request_offset else
                                      f"正在继续下载更新… 已下载 {self._request_offset / (1 << 20):.1f} MB")
        except (OSError, ValueError) as exc:
            self._finish_download(f"无法开始下载：{exc}")

    def _prepare_response(self, reply: QNetworkReply) -> bool:
        if self._response_checked:
            return True
        _https_url(reply.url().toString(QUrl.ComponentFormattingOption.FullyEncoded))
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if status not in (200, 206):
            return False  # Never append redirects or HTTP error pages to the installer.
        if status == 206:
            content_range = bytes(reply.rawHeader("Content-Range"))
            match = re.fullmatch(rb"bytes (\d+)-(\d+)/(\d+)", content_range)
            if not match:
                raise ValueError("服务器返回了无效的续传范围")
            start, end, total = map(int, match.groups())
            if start != self._request_offset or end < start or total <= end:
                raise ValueError("服务器返回的续传位置不匹配，已中止")
            self._response_end = end + 1
            self._response_total = total
        elif self._request_offset:
            # Range is optional for servers. A full 200 response must replace,
            # rather than append to, the partially downloaded executable.
            self._file.seek(0)
            self._file.truncate()
            self._hasher = hashlib.sha256()
            self._request_offset = 0
            self._initial_bytes = 0
        self._response_checked = True
        return True

    def _on_ready_read(self, reply: QNetworkReply | None = None) -> None:
        reply = self._reply if reply is None else reply
        if reply is None or reply is not self._reply or self._file is None:
            return
        try:
            if not self._prepare_response(reply):
                return
            chunk = bytes(reply.readAll())
            if self._file.write(chunk) != len(chunk):
                raise OSError("磁盘未完整写入下载内容")
            self._hasher.update(chunk)
        except OSError as exc:
            self._finish_download(f"安装包写入失败：{exc}")
        except ValueError as exc:
            self._finish_download(str(exc))

    def _on_progress(self, received, total, reply=None) -> None:
        if reply is not None and reply is not self._reply:
            return
        received += self._request_offset
        total = total + self._request_offset if total > 0 else 0
        percent = max(0, min(100, int(received * 100 / total))) if total else 0
        self.download_progress.emit(percent)
        speed = max(0, received - self._initial_bytes) / max(.1, time.monotonic() - self._started)
        amount = f"{received / (1 << 20):.1f} MB"
        if total:
            amount += f" / {total / (1 << 20):.1f} MB"
        rate = f"{speed / (1 << 20):.1f} MB/s" if speed >= 1 << 20 else f"{speed / 1024:.0f} KB/s"
        self.download_status.emit(f"正在下载更新… {percent}% · {amount} · {rate}" if total else
                                  f"正在下载更新… {amount} · {rate}")

    def _retry_download(self, message: str) -> None:
        if self._attempt >= self._attempt_limit:
            self._finish_download(f"{message}（已尝试 {self._attempt} 次，可稍后继续下载）",
                                  preserve_partial=True)
            return
        reply, self._reply = self._reply, None
        if reply is not None:
            reply.abort()
            reply.deleteLater()
        delay = min(1000 * 2 ** (self._attempt - 1), 4000)
        self._retry_timer.start(delay)
        self.download_status.emit(f"连接中断，{delay // 1000} 秒后自动重试（{self._attempt + 1}/{self._attempt_limit}）…")

    def _on_download_finished(self, reply: QNetworkReply | None = None) -> None:
        reply = self._reply if reply is None else reply
        if reply is None or reply is not self._reply:
            return
        try:
            _https_url(reply.url().toString(QUrl.ComponentFormattingOption.FullyEncoded))
        except ValueError as exc:
            self._finish_download(str(exc))
            return
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if status == 416:
            try:
                self._file.seek(0)
                self._file.truncate()
                self._hasher = hashlib.sha256()
                self._initial_bytes = 0
            except OSError as exc:
                self._finish_download(f"安装包写入失败：{exc}")
                return
            self._retry_download("服务器不接受续传，正在重新下载")
            return
        if reply.bytesAvailable() and status in (200, 206):
            self._on_ready_read(reply)
        if reply is not self._reply:  # A final disk write may already have failed.
            return
        if reply.error() != QNetworkReply.NetworkError.NoError or status not in (200, 206):
            transient = reply.error() in {
                QNetworkReply.NetworkError.ConnectionRefusedError,
                QNetworkReply.NetworkError.RemoteHostClosedError,
                QNetworkReply.NetworkError.HostNotFoundError,
                QNetworkReply.NetworkError.TimeoutError,
                QNetworkReply.NetworkError.TemporaryNetworkFailureError,
                QNetworkReply.NetworkError.NetworkSessionFailedError,
                QNetworkReply.NetworkError.UnknownNetworkError,
                QNetworkReply.NetworkError.ProxyConnectionClosedError,
                QNetworkReply.NetworkError.ProxyTimeoutError,
                QNetworkReply.NetworkError.ProtocolFailure,
            } or status in (408, 429, 500, 502, 503, 504)
            message = f"下载失败：{reply.errorString()}" if reply.error() else f"下载失败：HTTP {status}"
            if transient:
                self._retry_download(message)
            else:
                self._finish_download(message)
            return
        try:
            if not self._prepare_response(reply):
                raise ValueError("服务器未返回安装包")
        except (OSError, ValueError) as exc:
            self._finish_download(str(exc))
            return
        if self._response_total is not None and self._file.tell() < self._response_total:
            self._retry_download("安装包未下载完整")
            return
        if self._response_end is not None and self._file.tell() != self._response_end:
            self._finish_download("服务器返回的续传内容长度不匹配，已中止")
            return
        if (self._download_release is None or
                self._hasher.hexdigest() != self._download_release.sha256):
            self._finish_download("安装包校验失败（SHA256 不一致），已中止。")
            return
        self._finish_download()

    def _finish_download(self, error: str | None = None, *, notify: bool = True,
                         preserve_partial: bool = False) -> None:
        self._retry_timer.stop()
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
        if error is None and target and self._cache_dir is not None:
            try:
                cached = self._cache_dir / (self._hasher.hexdigest() + ".exe")
                os.replace(target, cached)
                target = str(cached)
                self._prune_cache(cached)
            except OSError as exc:
                error = f"保存已校验安装包失败：{exc}"
        if error:
            if not (preserve_partial and self._cache_dir is not None):
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
            self._finish_download("下载已取消。", notify=not silent, preserve_partial=True)

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
