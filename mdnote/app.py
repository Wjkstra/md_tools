"""QApplication 启动：启动文件参数、单实例守护与跨进程文件转发。

Windows「打开方式」/ 文件关联会以 ``MdNote.exe "D:\\path\\doc.md"`` 启动
进程，路径在 ``sys.argv[1:]`` 里。第二个实例不能直接退出，否则已运行的
窗口永远收不到这份路径，因此通过 QLocalServer 把文件列表转发给首实例。
"""

import json
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from . import config
from .ui.main_window import MainWindow

_INSTANCE_NAME = "mdnote-py-single-instance"


def requested_paths(argv):
    """文件参数中真实存在的文件（绝对、去重、保序）。

    忽略开关项与失效路径；相对路径按启动它的 Shell 工作目录解析。
    """
    paths = []
    for raw in argv:
        if not raw or raw.startswith("-"):
            continue
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        try:
            resolved = candidate.resolve(strict=False)
            if resolved.is_file():
                paths.append(str(resolved))
        except OSError:
            continue
    return list(dict.fromkeys(paths))


def encode_open_request(paths) -> bytes:
    """一行一个 JSON 数组，以换行结尾。"""
    return (json.dumps(list(paths), ensure_ascii=False) + "\n").encode("utf-8")


def decode_open_request(data: bytes) -> list[str]:
    paths = []
    # 按行先切字节再解码：单行出现非法字节不应丢弃整批请求。
    for raw_line in bytes(data).splitlines():
        try:
            line = raw_line.decode("utf-8").strip()
        except UnicodeDecodeError:
            continue
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, list):
            paths.extend(p for p in value if isinstance(p, str) and p)
    return paths


def _forward_to_running_instance(paths) -> bool:
    socket = QLocalSocket()
    socket.connectToServer(_INSTANCE_NAME)
    if not socket.waitForConnected(300):
        socket.abort()
        return False
    # 空数组也是一次“唤起”请求，首实例收到后会把窗口带到前台。
    socket.write(encode_open_request(paths))
    socket.flush()
    socket.waitForBytesWritten(2000)
    socket.disconnectFromServer()
    socket.waitForDisconnected(1000)
    return True


def _serve_open_requests(server: QLocalServer, window: MainWindow) -> None:
    connection = server.nextPendingConnection()
    if connection is None:
        return

    def read() -> None:
        # 数据可能分块到达，按换行拆出完整请求后再解析。
        try:
            incoming = bytes(connection.readAll())
        except RuntimeError:
            return  # 连接已销毁（窗口关闭过程中的残余信号）
        buffer = getattr(connection, "_mdnote_buffer", b"")
        buffer += incoming
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            paths = decode_open_request(line)
            if paths:
                window.open_external_files(paths)
        connection._mdnote_buffer = buffer

    connection.readyRead.connect(read)

    def finish() -> None:
        try:
            connection.disconnected.disconnect(finish)
            read()  # 断开时可能还有最后一批数据
            connection.deleteLater()
        except RuntimeError:
            pass  # 连接已随 server 关闭而销毁

    connection.disconnected.connect(finish)
    # 数据（readyRead 不再补发），也可能数据要到下一轮事件循环才可取，
    # 因此立即读一次并排队再读一次（行级缓冲保证不会重复处理）。
    if connection.bytesAvailable():
        read()
    QTimer.singleShot(0, read)


def run(argv=None) -> int:
    if argv is None:
        argv = sys.argv
    paths = requested_paths(argv[1:])

    app = QApplication([])
    app.setApplicationName("MdNote")
    app.setOrganizationName("MdNote")
    app.setWindowIcon(QIcon(str(config.icon_file())))

    if _forward_to_running_instance(paths):
        return 0  # 已运行的实例会打开这些文件

    QLocalServer.removeServer(_INSTANCE_NAME)
    server = QLocalServer()
    server.listen(_INSTANCE_NAME)
    server.__keep_alive = server  # 防止 GC
    app._single_server = server

    window = MainWindow(open_paths=paths)
    server.newConnection.connect(
        lambda: _serve_open_requests(server, window))
    window.show()
    return app.exec()
