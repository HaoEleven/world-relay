"""World Relay 的 Windows 桌面入口。"""

from __future__ import annotations

import ctypes
import logging
import tempfile
import threading
import traceback
from pathlib import Path

import webview

import app
import app_info


def configure_logging() -> Path:
    """把桌面版日志写到用户数据目录，便于排查无控制台窗口的错误。"""
    candidates = [
        app.user_data_root() / "logs",
        Path(tempfile.gettempdir()) / "WorldRelay" / "logs",
    ]
    for log_dir in candidates:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "world-relay.log"
            logging.basicConfig(
                filename=log_path,
                level=logging.INFO,
                format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                encoding="utf-8",
                force=True,
            )
            return log_path
        except OSError:
            continue
    raise OSError("无法创建 World Relay 日志目录。")


def show_fatal_error(message: str, log_path: Path) -> None:
    """在桌面入口无法创建窗口时显示可见错误。"""
    detail = f"{message}\n\n详细日志：{log_path}"
    ctypes.windll.user32.MessageBoxW(0, detail, f"{app_info.APP_NAME} - 启动失败", 0x10)


def run_desktop() -> int:
    log_path = configure_logging()
    server: app.RelayServer | None = None
    server_thread: threading.Thread | None = None
    try:
        server = app.RelayServer(("127.0.0.1", 0), app.RequestHandler)
        server_thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.2},
            name="world-relay-local-server",
            daemon=True,
        )
        server_thread.start()
        url = f"http://127.0.0.1:{server.server_port}"
        logging.info("Starting %s at %s", app_info.DISPLAY_VERSION, url)

        webview.create_window(
            f"{app_info.APP_NAME} · {app_info.DISPLAY_VERSION}",
            url=url,
            width=1280,
            height=820,
            min_size=(960, 640),
            resizable=True,
            confirm_close=True,
            background_color="#17241f",
            text_select=False,
        )
        webview.start(
            private_mode=False,
            storage_path=str(app.user_data_root() / "webview"),
        )
        return 0
    except BaseException as exc:
        logging.exception("Desktop startup failed")
        show_fatal_error(str(exc) or exc.__class__.__name__, log_path)
        return 1
    finally:
        if server is not None and server_thread is not None and server_thread.is_alive():
            server.shutdown()
        if server is not None:
            server.server_close()
        if server_thread is not None and server_thread.is_alive():
            server_thread.join(timeout=2)
        logging.shutdown()


if __name__ == "__main__":
    try:
        raise SystemExit(run_desktop())
    except SystemExit:
        raise
    except BaseException:
        # 仅作为最外层兜底；正常错误会在 run_desktop 中记录并展示。
        traceback.print_exc()
        raise
