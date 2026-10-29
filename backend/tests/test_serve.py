"""启动辅助函数测试：端口占用检测。"""

from __future__ import annotations

import socket

from backend.serve import port_available


def test_port_available_detects_listener_and_free_port():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        assert port_available("127.0.0.1", port) is False
    finally:
        listener.close()
    assert port_available("127.0.0.1", port) is True
