"""QApplication 启动 + 单实例守护。"""

from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from . import config
from .ui.main_window import MainWindow

_INSTANCE_NAME = "mdnote-py-single-instance"


def _acquire_single_instance() -> bool:
    socket = QLocalSocket()
    socket.connectToServer(_INSTANCE_NAME)
    if socket.waitForConnected(100):
        socket.close()
        return False  # 已有实例
    QLocalServer.removeServer(_INSTANCE_NAME)
    server = QLocalServer()
    server.listen(_INSTANCE_NAME)
    server.__keep_alive = server  # 防止 GC
    QApplication.instance()._single_server = server
    return True


def run() -> int:
    app = QApplication([])
    app.setApplicationName("MdNote")
    app.setOrganizationName("MdNote")
    app.setWindowIcon(QIcon(str(config.icon_file())))

    if not _acquire_single_instance():
        return 0

    window = MainWindow()
    window.show()
    return app.exec()
