from __future__ import annotations

import gzip
import json
import struct
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import uuid
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import app  # noqa: E402
import core  # noqa: E402


def nbt_name(text: str) -> bytes:
    raw = text.encode("utf-8")
    return struct.pack(">H", len(raw)) + raw


def minimal_level_dat() -> bytes:
    nbt = (
        b"\x0a"
        + nbt_name("")
        + b"\x0a"
        + nbt_name("Data")
        + b"\x08"
        + nbt_name("untouched")
        + nbt_name("keep-me")
        + b"\x0b"
        + nbt_name("singleplayer_uuid")
        + struct.pack(">i4i", 4, 1, 2, 3, 4)
        + b"\x00\x00"
    )
    return gzip.compress(nbt)


class RelayFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=PROJECT_ROOT)
        self.root = Path(self.temporary.name)
        self.minecraft = self.root / ".minecraft"
        self.version = self.minecraft / "versions" / "26.1-test"
        self.save = self.root / "saves" / "RelayWorld"
        self.player_uuid = uuid.UUID("069a79f4-44e9-4726-a5be-fca90e38aaf5")
        (self.save / "players" / "data").mkdir(parents=True)
        self.version.mkdir(parents=True)
        (self.save / "level.dat").write_bytes(minimal_level_dat())
        (self.save / "players" / "data" / f"{self.player_uuid}.dat").write_bytes(b"player")
        (self.version / "usercache.json").write_text(
            json.dumps([{"name": "Notch", "uuid": str(self.player_uuid)}]),
            encoding="utf-8",
        )
        self.config = {
            "minecraft_path": str(self.minecraft),
            "saves_path": str(self.root / "saves"),
            "associations": {"RelayWorld": "26.1-test"},
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()


class CoreTests(RelayFixture):
    def test_player_mapping_and_replace(self) -> None:
        players = core.list_players(self.config, "RelayWorld", "26.1-test")["players"]
        self.assertEqual([item["name"] for item in players], ["Notch"])
        progress = []
        core.replace_owner(
            self.config,
            "RelayWorld",
            "26.1-test",
            players[0]["uid"],
            lambda value, message: progress.append((value, message)),
        )
        target = self.version / "saves" / "RelayWorld"
        self.assertTrue((target / "level.dat").is_file())
        self.assertEqual(progress[-1][0], 100)

    def test_import_overwrite_and_delete(self) -> None:
        incoming = self.root / "incoming" / "AddedWorld"
        incoming.mkdir(parents=True)
        (incoming / "level.dat").write_bytes(minimal_level_dat())
        (incoming / "new.txt").write_text("first", encoding="utf-8")

        progress = []
        name, warning = core.import_save(
            self.config, str(incoming), False, lambda value, message: progress.append((value, message))
        )
        destination = self.root / "saves" / "AddedWorld"
        self.assertEqual(name, "AddedWorld")
        self.assertIsNone(warning)
        self.assertTrue((destination / "new.txt").is_file())

        (destination / "old-only.txt").write_text("remove me", encoding="utf-8")
        (incoming / "new.txt").write_text("second", encoding="utf-8")
        core.import_save(self.config, str(incoming), True, lambda _value, _message: None)
        self.assertFalse((destination / "old-only.txt").exists())
        self.assertEqual((destination / "new.txt").read_text(encoding="utf-8"), "second")

        core.delete_save(self.config, "AddedWorld", lambda _value, _message: None)
        self.assertFalse(destination.exists())


class HttpApiTests(RelayFixture):
    def setUp(self) -> None:
        super().setUp()
        app.STORE = core.ConfigStore(self.root / "config.json")
        self.server = app.RelayServer(("127.0.0.1", 0), app.RequestHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def request(self, path: str, method: str = "GET", body: dict | None = None):
        encoded = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.base + path, data=encoded, method=method)
        if encoded is not None:
            request.add_header("Content-Type", "application/json")
            request.add_header("Origin", self.base)
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_settings_players_and_replace_job(self) -> None:
        status, configured = self.request(
            "/api/settings",
            "POST",
            {"minecraftPath": str(self.minecraft), "savesPath": str(self.root / "saves")},
        )
        self.assertEqual(status, 200)
        self.assertTrue(configured["ready"])
        self.request(
            "/api/association",
            "POST",
            {"save": "RelayWorld", "version": "26.1-test"},
        )
        _, players = self.request("/api/players?save=RelayWorld&version=26.1-test")
        uid = players["players"][0]["uid"]
        status, started = self.request(
            "/api/jobs/replace",
            "POST",
            {"save": "RelayWorld", "version": "26.1-test", "uid": uid},
        )
        self.assertEqual(status, 202)
        job = {}
        for _ in range(100):
            _, job = self.request(f"/api/jobs/{started['jobId']}")
            if job["status"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(job["status"], "success", job)
        self.assertTrue((self.version / "saves" / "RelayWorld" / "level.dat").is_file())


if __name__ == "__main__":
    unittest.main()
