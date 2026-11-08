"""World Relay 本地 Web 应用入口。"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import parse_qs, unquote, urlparse

import app_info
import core


def resource_root() -> Path:
    """返回源码目录或 PyInstaller 解包后的资源目录。"""
    bundled = getattr(sys, "_MEIPASS", None)
    return Path(bundled).resolve() if bundled else Path(__file__).resolve().parent


def user_data_root() -> Path:
    """返回可持久写入的用户数据目录。"""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "WorldRelay"
    return Path.home() / ".world-relay"


APP_ROOT = resource_root()
STATIC_ROOT = APP_ROOT / "static"
CONFIG_PATH = user_data_root() / "world_relay_config.json"
STORE = core.ConfigStore(CONFIG_PATH)


class Job:
    def __init__(self, kind: str, title: str) -> None:
        self.id = uuid.uuid4().hex
        self.kind = kind
        self.title = title
        self.status = "running"
        self.progress = 0
        self.message = "任务已创建"
        self.warning = ""
        self.error = ""
        self.steps: list[Dict[str, Any]] = []
        self.created_at = time.time()
        self._lock = threading.Lock()

    def update(self, progress: int, message: str) -> None:
        with self._lock:
            self.progress = max(self.progress, min(100, progress))
            self.message = message
            self.steps.append({"progress": self.progress, "message": message})

    def complete(self, warning: str = "") -> None:
        with self._lock:
            self.status = "success"
            self.progress = 100
            self.warning = warning
            if warning:
                self.message = "操作完成，但有一项清理提示"

    def fail(self, error: str) -> None:
        with self._lock:
            self.status = "error"
            self.error = error
            self.message = "操作未完成"

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "id": self.id,
                "kind": self.kind,
                "title": self.title,
                "status": self.status,
                "progress": self.progress,
                "message": self.message,
                "warning": self.warning,
                "error": self.error,
                "steps": list(self.steps),
            }


class JobManager:
    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, title: str, task: Callable[[Job], Optional[str]]) -> Job:
        job = Job(kind, title)
        with self._lock:
            self._jobs[job.id] = job

        def runner() -> None:
            try:
                warning = task(job) or ""
                job.complete(warning)
            except Exception as exc:  # 错误会通过进度弹窗展示给用户。
                traceback.print_exc()
                job.fail(str(exc) or exc.__class__.__name__)

        threading.Thread(target=runner, name=f"world-relay-{kind}", daemon=True).start()
        return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise core.RelayError("找不到该任务，可能已经失效。")
        return job


JOBS = JobManager()


def bootstrap_state() -> Dict[str, Any]:
    config = STORE.load()
    ready = bool(config["minecraft_path"] and config["saves_path"])
    versions = []
    saves = []
    error = ""
    if ready:
        try:
            versions = core.discover_versions(config)
            saves = core.discover_saves(config)
        except core.RelayError as exc:
            error = str(exc)
            ready = False
    return {
        "app": {
            "name": app_info.APP_NAME,
            "version": app_info.VERSION,
            "displayVersion": app_info.DISPLAY_VERSION,
        },
        "settings": {
            "minecraftPath": config["minecraft_path"],
            "savesPath": config["saves_path"],
        },
        "associations": config["associations"],
        "versions": versions,
        "saves": saves,
        "ready": ready,
        "error": error,
    }


def choose_directory(initial: str = "", title: str = "选择文件夹") -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        raise core.RelayError("当前 Python 环境没有 Tk 文件选择器，请手动填写路径。") from exc
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askdirectory(
            parent=root,
            title=title,
            initialdir=initial if initial and Path(initial).is_dir() else None,
            mustexist=True,
        )
        return selected or ""
    finally:
        root.destroy()


class RelayServer(ThreadingHTTPServer):
    daemon_threads = True


class RequestHandler(BaseHTTPRequestHandler):
    server_version = f"WorldRelay/{app_info.VERSION}"

    def log_message(self, format_string: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format_string % args}")

    def _security_headers(self) -> None:
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")

    def _json(self, payload: Any, status: int = 200) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(encoded)

    def _error(self, status: int, message: str) -> None:
        self._json({"error": message}, status)

    def _body(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise core.RelayError("请求长度无效。") from exc
        if length <= 0 or length > 2_000_000:
            raise core.RelayError("请求内容为空或过大。")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise core.RelayError("请求不是有效的 JSON。") from exc
        if not isinstance(value, dict):
            raise core.RelayError("请求内容必须是 JSON 对象。")
        return value

    def _check_origin(self) -> None:
        origin = self.headers.get("Origin")
        expected = f"http://127.0.0.1:{self.server.server_port}"
        if origin and origin != expected:
            raise core.RelayError("请求来源不受信任。")

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/bootstrap":
                self._json(bootstrap_state())
                return
            if parsed.path == "/api/players":
                query = parse_qs(parsed.query)
                save_name = query.get("save", [""])[0]
                version_name = query.get("version", [""])[0]
                self._json(core.list_players(STORE.load(), save_name, version_name))
                return
            if parsed.path.startswith("/api/jobs/"):
                job_id = parsed.path.rsplit("/", 1)[-1]
                self._json(JOBS.get(job_id).snapshot())
                return
            self._serve_static(parsed.path)
        except core.RelayError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except OSError as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_POST(self) -> None:  # noqa: N802
        try:
            self._check_origin()
            path = urlparse(self.path).path
            body = self._body()
            if path == "/api/settings":
                STORE.update_settings(
                    str(body.get("minecraftPath", "")), str(body.get("savesPath", ""))
                )
                self._json(bootstrap_state())
                return
            if path == "/api/pick-folder":
                selected = choose_directory(
                    str(body.get("initial", "")), str(body.get("title", "选择文件夹"))
                )
                self._json({"path": selected})
                return
            if path == "/api/association":
                STORE.set_association(str(body.get("save", "")), str(body.get("version", "")))
                self._json(bootstrap_state())
                return
            if path == "/api/owner-allowlist/verify-add":
                save_name = str(body.get("save", ""))
                version_name = str(body.get("version", ""))
                player_uuid = str(body.get("uuid", ""))
                config = STORE.load()
                candidate = core.get_player_candidate(
                    config, save_name, version_name, player_uuid
                )
                profile = core.verify_official_profile(player_uuid)
                STORE.add_allowed_owner(
                    save_name,
                    profile["uuid"],
                    profile["name"],
                    str(candidate.get("cachedName", "")),
                    profile["verifiedAt"],
                )
                self._json({"profile": profile})
                return
            if path == "/api/owner-allowlist/remove":
                save_name = str(body.get("save", ""))
                player_uuid = str(body.get("uuid", ""))
                STORE.remove_allowed_owner(save_name, player_uuid)
                self._json({"removed": True})
                return
            if path == "/api/import/check":
                self._json(core.import_conflict(STORE.load(), str(body.get("sourcePath", ""))))
                return
            if path == "/api/jobs/replace":
                config = STORE.load()
                save_name = str(body.get("save", ""))
                version_name = str(body.get("version", ""))
                player_uuid = str(body.get("uuid", ""))
                job = JOBS.start(
                    "replace",
                    "修改服主并覆盖存档",
                    lambda item: core.replace_owner(
                        config, save_name, version_name, player_uuid, item.update
                    ),
                )
                self._json({"jobId": job.id}, HTTPStatus.ACCEPTED)
                return
            if path == "/api/jobs/import":
                config = STORE.load()
                source_path = str(body.get("sourcePath", ""))
                overwrite = bool(body.get("overwrite", False))

                def import_task(item: Job) -> Optional[str]:
                    save_name, warning = core.import_save(
                        config, source_path, overwrite, item.update
                    )
                    STORE.clear_owner_allowlist(save_name)
                    item.message = f"存档“{save_name}”已添加"
                    return warning

                job = JOBS.start("import", "添加存档", import_task)
                self._json({"jobId": job.id}, HTTPStatus.ACCEPTED)
                return
            if path == "/api/jobs/delete":
                config = STORE.load()
                save_name = str(body.get("save", ""))

                def delete_task(item: Job) -> Optional[str]:
                    core.delete_save(config, save_name, item.update)
                    STORE.remove_save_metadata(save_name)
                    return None

                job = JOBS.start("delete", "删除存档", delete_task)
                self._json({"jobId": job.id}, HTTPStatus.ACCEPTED)
                return
            self._error(HTTPStatus.NOT_FOUND, "接口不存在。")
        except core.ProfileNotFoundError as exc:
            self._error(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc))
        except core.ProfileServiceError as exc:
            self._error(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
        except core.RelayError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except OSError as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else unquote(request_path.lstrip("/"))
        candidate = (STATIC_ROOT / relative).resolve()
        try:
            candidate.relative_to(STATIC_ROOT.resolve())
        except ValueError:
            self._error(HTTPStatus.FORBIDDEN, "无权访问该文件。")
            return
        if not candidate.is_file():
            self._error(HTTPStatus.NOT_FOUND, "页面不存在。")
            return
        data = candidate.read_bytes()
        mime_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{mime_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(data)


def main() -> int:
    parser = argparse.ArgumentParser(description="启动 World Relay 本地存档管理器")
    parser.add_argument("--port", type=int, default=0, help="监听端口；默认自动选择")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    args = parser.parse_args()

    server = RelayServer(("127.0.0.1", args.port), RequestHandler)
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"World Relay 已启动：{url}")
    print("按 Ctrl+C 停止。")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        print("\nWorld Relay 已停止。")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
