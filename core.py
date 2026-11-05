"""World Relay 的文件与 Minecraft NBT 核心逻辑。

本模块只使用 Python 标准库。所有写操作均限制在用户配置的 saves 根目录，
或指定 Minecraft 版本的 saves 子目录中。
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import struct
import tempfile
import threading
import uuid
import zlib
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple


ProgressCallback = Callable[[int, str], None]
TARGET_NBT_PATH = (b"Data", b"singleplayer_uuid")


class RelayError(Exception):
    """可以直接展示给用户的业务错误。"""


class NBTFormatError(RelayError):
    """NBT 文件格式错误。"""


class ConfigStore:
    """线程安全的本地 JSON 配置。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()

    def load(self) -> Dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                return {"minecraft_path": "", "saves_path": "", "associations": {}}
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RelayError(f"配置文件无法读取：{exc}") from exc
            if not isinstance(data, dict):
                raise RelayError("配置文件的根内容必须是 JSON 对象。")
            return {
                "minecraft_path": str(data.get("minecraft_path", "")),
                "saves_path": str(data.get("saves_path", "")),
                "associations": dict(data.get("associations", {})),
            }

    def save(self, data: Dict[str, Any]) -> None:
        encoded = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(self.path, encoded)

    def update_settings(self, minecraft_path: str, saves_path: str) -> Dict[str, Any]:
        minecraft = _existing_directory(minecraft_path, ".minecraft 路径")
        saves = _existing_directory(saves_path, "saves 路径")
        if not (minecraft / "versions").is_dir():
            raise RelayError("选择的 .minecraft 目录中没有 versions 文件夹。")
        with self._lock:
            data = self.load()
            data["minecraft_path"] = str(minecraft)
            data["saves_path"] = str(saves)
            self.save(data)
            return data

    def set_association(self, save_name: str, version_name: str) -> Dict[str, Any]:
        _validate_name(save_name, "存档名称")
        _validate_name(version_name, "版本名称")
        with self._lock:
            data = self.load()
            data["associations"][save_name] = version_name
            self.save(data)
            return data

    def remove_association(self, save_name: str) -> None:
        with self._lock:
            data = self.load()
            if save_name in data["associations"]:
                del data["associations"][save_name]
                self.save(data)


def _existing_directory(value: str, label: str) -> Path:
    if not value.strip():
        raise RelayError(f"请先选择{label}。")
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise RelayError(f"{label}不存在或不是文件夹：{path}")
    return path


def _validate_name(value: str, label: str) -> None:
    if not value or Path(value).name != value or value in {".", ".."}:
        raise RelayError(f"{label}必须是单个文件夹名称。")


def _root_from_config(config: Dict[str, Any], key: str, label: str) -> Path:
    return _existing_directory(str(config.get(key, "")), label)


def _safe_child(root: Path, name: str, label: str) -> Path:
    _validate_name(name, label)
    resolved_root = root.resolve()
    candidate = root / name
    if candidate.is_symlink():
        raise RelayError(f"不支持操作符号链接形式的{label}：{name}")
    if candidate.resolve(strict=False).parent != resolved_root:
        raise RelayError(f"{label}超出了允许的目录范围。")
    return candidate


def discover_versions(config: Dict[str, Any]) -> List[Dict[str, str]]:
    minecraft = _root_from_config(config, "minecraft_path", ".minecraft 路径")
    versions_root = minecraft / "versions"
    if not versions_root.is_dir():
        return []
    result = []
    for entry in sorted(versions_root.iterdir(), key=lambda item: item.name.casefold()):
        if entry.is_dir() and not entry.is_symlink() and not entry.name.startswith("."):
            result.append({"name": entry.name, "path": str(entry.resolve())})
    return result


def discover_saves(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    saves_root = _root_from_config(config, "saves_path", "saves 路径")
    associations = config.get("associations", {})
    result = []
    for entry in sorted(saves_root.iterdir(), key=lambda item: item.name.casefold()):
        if (
            entry.is_dir()
            and not entry.is_symlink()
            and not entry.name.startswith(".")
        ):
            result.append(
                {
                    "name": entry.name,
                    "path": str(entry.resolve()),
                    "version": associations.get(entry.name, ""),
                    "hasLevelDat": (entry / "level.dat").is_file(),
                }
            )
    return result


def _version_directory(config: Dict[str, Any], version_name: str) -> Path:
    minecraft = _root_from_config(config, "minecraft_path", ".minecraft 路径")
    versions_root = minecraft / "versions"
    version = _safe_child(versions_root, version_name, "版本名称")
    if not version.is_dir():
        raise RelayError(f"版本目录不存在：{version}")
    return version


def _source_save(config: Dict[str, Any], save_name: str) -> Path:
    saves_root = _root_from_config(config, "saves_path", "saves 路径")
    save = _safe_child(saves_root, save_name, "存档名称")
    if not save.is_dir():
        raise RelayError(f"存档目录不存在：{save}")
    return save


def _usercache_candidates(config: Dict[str, Any], version_name: str) -> Iterable[Path]:
    minecraft = _root_from_config(config, "minecraft_path", ".minecraft 路径")
    version = _version_directory(config, version_name)
    # 独立版本目录的缓存优先；没有时再使用共享游戏目录的缓存。
    yield version / "usercache.json"
    yield minecraft / "usercache.json"


def _load_usercache(config: Dict[str, Any], version_name: str) -> Tuple[Dict[str, str], str]:
    merged: Dict[str, str] = {}
    used_paths: List[str] = []
    for path in _usercache_candidates(config, version_name):
        if not path.is_file():
            continue
        try:
            content = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(content, list):
            continue
        used_paths.append(str(path.resolve()))
        for item in content:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            uuid_text = item.get("uuid")
            if not isinstance(name, str) or not isinstance(uuid_text, str):
                continue
            try:
                normalized = str(uuid.UUID(uuid_text))
            except ValueError:
                continue
            # 版本缓存优先，因此只填补尚未出现的 UUID。
            merged.setdefault(normalized, name)
    return merged, "；".join(used_paths)


def uuid_to_uid(uuid_text: str) -> Tuple[int, int, int, int]:
    try:
        player_uuid = uuid.UUID(uuid_text)
    except ValueError as exc:
        raise RelayError(f"无效的玩家 UUID：{uuid_text}") from exc
    return struct.unpack(">4i", player_uuid.bytes)


def format_uid(uid: Sequence[int]) -> str:
    return "  ".join(str(value) for value in uid)


def parse_uid(text: str) -> Tuple[int, int, int, int]:
    parts = text.split()
    if len(parts) != 4:
        raise RelayError("玩家 UID 必须由 4 个整数构成。")
    values: List[int] = []
    for part in parts:
        try:
            value = int(part, 10)
        except ValueError as exc:
            raise RelayError(f"玩家 UID 中的 {part!r} 不是整数。") from exc
        if not -(2**31) <= value <= 2**31 - 1:
            raise RelayError(f"UID 整数 {value} 超出 32 位有符号范围。")
        values.append(value)
    return values[0], values[1], values[2], values[3]


def list_players(config: Dict[str, Any], save_name: str, version_name: str) -> Dict[str, Any]:
    save = _source_save(config, save_name)
    _version_directory(config, version_name)
    player_dir = save / "players" / "data"
    if not player_dir.is_dir():
        player_dir = save / "playerdata"  # 兼容 26.1 以前的存档布局。
    if not player_dir.is_dir():
        return {
            "players": [],
            "cachePath": "",
            "message": "该存档中没有找到 players/data 或 playerdata 目录。",
        }

    cache, cache_path = _load_usercache(config, version_name)
    players: List[Dict[str, str]] = []
    for dat_file in sorted(player_dir.glob("*.dat"), key=lambda item: item.name.casefold()):
        try:
            normalized_uuid = str(uuid.UUID(dat_file.stem))
        except ValueError:
            continue
        name = cache.get(normalized_uuid)
        if not name:
            continue
        uid_text = format_uid(uuid_to_uid(normalized_uuid))
        players.append(
            {
                "name": name,
                "uuid": normalized_uuid,
                "uid": uid_text,
                "label": f"{name}：{uid_text}",
            }
        )

    if not cache_path:
        message = "没有找到可用的 usercache.json，因此未显示玩家。"
    elif not players:
        message = "DAT 文件中的玩家均未出现在当前版本的 usercache.json 中。"
    else:
        message = ""
    return {"players": players, "cachePath": cache_path, "message": message}


class _NBTScanner:
    _FIXED_PAYLOAD_SIZES = {1: 1, 2: 2, 3: 4, 4: 8, 5: 4, 6: 8}

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.position = 0
        self.matches: List[Tuple[int, int, int]] = []

    def _require(self, size: int) -> None:
        if size < 0 or self.position + size > len(self.data):
            raise NBTFormatError("level.dat 的 NBT 数据意外结束或长度字段无效。")

    def _read_u8(self) -> int:
        self._require(1)
        value = self.data[self.position]
        self.position += 1
        return value

    def _read_u16(self) -> int:
        self._require(2)
        value = struct.unpack_from(">H", self.data, self.position)[0]
        self.position += 2
        return value

    def _read_i32(self) -> int:
        self._require(4)
        value = struct.unpack_from(">i", self.data, self.position)[0]
        self.position += 4
        return value

    def _skip(self, size: int) -> None:
        self._require(size)
        self.position += size

    def _read_name(self) -> bytes:
        length = self._read_u16()
        self._require(length)
        value = self.data[self.position : self.position + length]
        self.position += length
        return value

    def _skip_payload(self, tag_type: int, path: Tuple[bytes, ...]) -> None:
        if tag_type in self._FIXED_PAYLOAD_SIZES:
            self._skip(self._FIXED_PAYLOAD_SIZES[tag_type])
            return
        if tag_type == 7:
            length = self._read_i32()
            if length < 0:
                raise NBTFormatError("NBT 字节数组长度为负数。")
            self._skip(length)
            return
        if tag_type == 8:
            self._skip(self._read_u16())
            return
        if tag_type == 9:
            element_type = self._read_u8()
            length = self._read_i32()
            if length < 0 or (element_type == 0 and length != 0):
                raise NBTFormatError("NBT 列表长度或元素类型无效。")
            for _ in range(length):
                self._skip_payload(element_type, path)
            return
        if tag_type == 10:
            while True:
                child_type = self._read_u8()
                if child_type == 0:
                    return
                child_name = self._read_name()
                child_path = path + (child_name,)
                start = self.position
                self._skip_payload(child_type, child_path)
                if child_path == TARGET_NBT_PATH:
                    self.matches.append((child_type, start, self.position))
        elif tag_type == 11:
            length = self._read_i32()
            if length < 0:
                raise NBTFormatError("NBT 整数数组长度为负数。")
            self._skip(length * 4)
        elif tag_type == 12:
            length = self._read_i32()
            if length < 0:
                raise NBTFormatError("NBT 长整数数组长度为负数。")
            self._skip(length * 8)
        else:
            raise NBTFormatError(f"遇到未知的 NBT 标签类型：{tag_type}。")

    def find_target(self) -> Tuple[int, int, int]:
        root_type = self._read_u8()
        if root_type != 10:
            raise NBTFormatError("NBT 根标签不是 TAG_Compound。")
        self._read_name()
        self._skip_payload(root_type, ())
        if self.position != len(self.data):
            raise NBTFormatError("NBT 根标签结束后仍存在无法识别的数据。")
        if len(self.matches) != 1:
            if not self.matches:
                raise RelayError("level.dat 中未找到 Data/singleplayer_uuid 字段。")
            raise RelayError("level.dat 中存在多个 singleplayer_uuid 字段。")
        return self.matches[0]


def _decompress_nbt(file_data: bytes) -> Tuple[bytes, str]:
    if file_data.startswith(b"\x1f\x8b"):
        try:
            return gzip.decompress(file_data), "gzip"
        except (OSError, EOFError) as exc:
            raise NBTFormatError("level.dat 的 GZIP 数据已损坏。") from exc
    try:
        return zlib.decompress(file_data), "zlib"
    except zlib.error:
        if file_data[:1] == b"\x0a":
            return file_data, "raw"
        raise NBTFormatError("level.dat 不是可识别的 GZIP、zlib 或原始 NBT。")


def _compress_nbt(data: bytes, compression: str) -> bytes:
    if compression == "gzip":
        return gzip.compress(data, mtime=0)
    if compression == "zlib":
        return zlib.compress(data)
    return data


def _atomic_write(path: Path, data: bytes) -> None:
    temporary_name: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink()
            except FileNotFoundError:
                pass


def update_level_dat(level_dat: Path, uid: Sequence[int]) -> bytes:
    original = level_dat.read_bytes()
    nbt_data, compression = _decompress_nbt(original)
    tag_type, start, end = _NBTScanner(nbt_data).find_target()
    if tag_type != 11:
        raise RelayError("Data/singleplayer_uuid 不是 TAG_Int_Array。")
    replacement = struct.pack(">i4i", 4, *uid)
    updated_nbt = nbt_data[:start] + replacement + nbt_data[end:]
    backup = level_dat.with_name("level.dat.owner-change.bak")
    if not backup.exists():
        shutil.copy2(level_dat, backup)
    try:
        _atomic_write(level_dat, _compress_nbt(updated_nbt, compression))
        verified_nbt, _ = _decompress_nbt(level_dat.read_bytes())
        verified_type, verified_start, verified_end = _NBTScanner(verified_nbt).find_target()
        if verified_type != 11 or verified_nbt[verified_start:verified_end] != replacement:
            raise RelayError("level.dat 写入后的校验失败。")
    except BaseException:
        _atomic_write(level_dat, original)
        raise
    return original


def _replace_directory(source: Path, destination: Path) -> Optional[str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    staging = destination.parent / f".{destination.name}.incoming-{token}"
    previous = destination.parent / f".{destination.name}.old-{token}"
    switched = False
    try:
        shutil.copytree(source, staging)
        if destination.exists():
            destination.rename(previous)
        try:
            staging.rename(destination)
            switched = True
        except BaseException:
            if previous.exists() and not destination.exists():
                previous.rename(destination)
            raise
        if previous.exists():
            try:
                shutil.rmtree(previous)
            except OSError as exc:
                return f"新存档已启用，但旧临时目录清理失败：{exc}"
        return None
    finally:
        if staging.exists() and not switched:
            shutil.rmtree(staging, ignore_errors=True)


def replace_owner(
    config: Dict[str, Any],
    save_name: str,
    version_name: str,
    uid_text: str,
    progress: ProgressCallback,
) -> Optional[str]:
    progress(5, "正在检查路径和玩家 UID")
    source = _source_save(config, save_name)
    version = _version_directory(config, version_name)
    level_dat = source / "level.dat"
    if not level_dat.is_file():
        raise RelayError(f"存档中没有 level.dat：{level_dat}")
    uid = parse_uid(uid_text)
    available = {item["uid"] for item in list_players(config, save_name, version_name)["players"]}
    if uid_text not in available:
        raise RelayError("所选 UID 不属于当前存档中可识别的玩家。")

    progress(25, "正在备份并修改 singleplayer_uuid")
    original = update_level_dat(level_dat, uid)
    destination = version / "saves" / save_name
    try:
        progress(55, "正在完整复制新存档")
        warning = _replace_directory(source, destination)
    except BaseException:
        progress(75, "复制失败，正在恢复来源存档的 level.dat")
        _atomic_write(level_dat, original)
        raise
    progress(95, "正在核对目标存档")
    if not (destination / "level.dat").is_file():
        raise RelayError("目标存档复制完成后缺少 level.dat。")
    progress(100, "服主 UID 已修改，目标版本存档已替换")
    return warning


def import_save(
    config: Dict[str, Any], source_text: str, overwrite: bool, progress: ProgressCallback
) -> Tuple[str, Optional[str]]:
    source = _existing_directory(source_text, "待添加存档路径")
    if not (source / "level.dat").is_file():
        raise RelayError("选择的文件夹中没有 level.dat，无法识别为 Minecraft 存档。")
    saves_root = _root_from_config(config, "saves_path", "saves 路径")
    destination = _safe_child(saves_root, source.name, "存档名称")
    if source == destination.resolve(strict=False):
        raise RelayError("该存档已经位于当前 saves 目录中。")
    if destination.exists() and not overwrite:
        raise RelayError("同名存档已经存在，需要确认替换后才能继续。")
    progress(15, "正在验证待添加存档")
    progress(35, "正在复制存档文件")
    warning = _replace_directory(source, destination)
    progress(100, "存档已添加到管理目录")
    return source.name, warning


def delete_save(
    config: Dict[str, Any], save_name: str, progress: ProgressCallback
) -> None:
    source = _source_save(config, save_name)
    token = uuid.uuid4().hex
    deleting = source.parent / f".{source.name}.deleting-{token}"
    progress(20, "正在锁定待删除存档")
    source.rename(deleting)
    try:
        progress(55, "正在删除存档文件")
        shutil.rmtree(deleting)
    except BaseException:
        if deleting.exists() and not source.exists():
            deleting.rename(source)
        raise
    progress(100, "存档已删除")


def import_conflict(config: Dict[str, Any], source_text: str) -> Dict[str, Any]:
    source = _existing_directory(source_text, "待添加存档路径")
    if not (source / "level.dat").is_file():
        raise RelayError("选择的文件夹中没有 level.dat。")
    saves_root = _root_from_config(config, "saves_path", "saves 路径")
    destination = _safe_child(saves_root, source.name, "存档名称")
    return {"name": source.name, "conflict": destination.exists()}
