"""Хранилище сырцов (G21/G14): логические id -> бэкенды.

Бэкенд file — локальная папка / внешний диск / NAS / синхронизируемая папка:
для соло и малой команды S3 не нужен, а переход на него потом — смена одной
строки в .vnstorage.yaml (манифесты в git не меняются). Локи ОБЯЗАТЕЛЬНЫ (G14):
push без валидного лока автора отказывает — PSD не мержится, потерянная работа
дороже дисциплины.

Конфиг: .vnstorage.yaml (+ локальный override .vnstorage.local.yaml, в .gitignore):
  storages:
    default: {type: file, path: "~/vn-assets-store"}
    # cloud: {type: s3, endpoint: "https://...", bucket: "vn-assets"}   # фаза S3
"""

from __future__ import annotations

import getpass
import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import blake3

from ..repo import load_yaml, write_text_lf

MANIFEST_SUFFIX = ".manifest.json"


class StorageError(RuntimeError):
    pass


@dataclass
class SyncReport:
    pushed: list[str] = field(default_factory=list)
    pulled: list[str] = field(default_factory=list)
    fresh: list[str] = field(default_factory=list)
    locked: list[str] = field(default_factory=list)
    rows: list[str] = field(default_factory=list)     # status
    errors: list[str] = field(default_factory=list)


def _owner(root: Path) -> str:
    try:
        out = subprocess.run(["git", "config", "user.name"], cwd=root,
                             capture_output=True, text=True, check=True)
        if out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return getpass.getuser()


def load_storages(root: Path) -> dict[str, dict]:
    cfg = load_yaml(root / ".vnstorage.yaml").get("storages") or {}
    local = root / ".vnstorage.local.yaml"
    if local.is_file():
        cfg.update(load_yaml(local).get("storages") or {})
    return cfg


class FileBackend:
    """Папка-хранилище: объекты по ключам + lock-файлы. Атомарные записи."""

    def __init__(self, base: str):
        self.base = Path(os.path.expanduser(base))

    def _obj(self, key: str) -> Path:
        return self.base / "objects" / key

    def _lock(self, lock_key: str) -> Path:
        return self.base / "locks" / (lock_key + ".lock")

    def put(self, key: str, data: bytes) -> None:
        path = self._obj(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def get(self, key: str) -> bytes:
        path = self._obj(key)
        if not path.is_file():
            raise StorageError(f"объекта {key!r} нет в хранилище {self.base}")
        return path.read_bytes()

    def lock_holder(self, lock_key: str) -> str | None:
        path = self._lock(lock_key)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))["by"]
        except Exception:
            return "<битый lock-файл>"

    def acquire_lock(self, lock_key: str, owner: str) -> str | None:
        """None = лок наш; иначе — имя держателя."""
        holder = self.lock_holder(lock_key)
        if holder is not None and holder != owner:
            return holder
        path = self._lock(lock_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text_lf(path, json.dumps(
            {"by": owner, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
            ensure_ascii=False))
        return None

    def release_lock(self, lock_key: str, owner: str, force: bool = False) -> str | None:
        holder = self.lock_holder(lock_key)
        if holder is None:
            return None
        if holder != owner and not force:
            return holder
        self._lock(lock_key).unlink()
        return None


def backend_for(root: Path, name: str):
    storages = load_storages(root)
    if name not in storages:
        raise StorageError(f"хранилище {name!r} не описано в .vnstorage.yaml "
                           f"(есть: {sorted(storages)})")
    cfg = storages[name]
    if cfg.get("type") == "file":
        return FileBackend(cfg["path"])
    if cfg.get("type") == "s3":
        raise StorageError(
            f"хранилище {name!r}: s3-бэкенд подключается при переходе команды на облако "
            f"(G21: манифесты не изменятся) — пока используйте type: file"
        )
    raise StorageError(f"хранилище {name!r}: неизвестный type {cfg.get('type')!r}")


# ── Операции над сырцами ──────────────────────────────────────────────────────

def _src_root(root: Path) -> Path:
    return root / "assets_src"


def _iter_manifests(root: Path, scope: str | None):
    base = _src_root(root)
    for mf in sorted(base.rglob(f"*{MANIFEST_SUFFIX}")):
        rel = mf.relative_to(base).as_posix()[: -len(MANIFEST_SUFFIX)]
        if scope and not rel.startswith(scope.rstrip("/")):
            continue
        yield rel, mf


def _b3(data: bytes) -> str:
    return blake3.blake3(data).hexdigest()


def push(root: Path, paths: list[Path], storage: str = "default") -> SyncReport:
    """Залить сырцы: ТРЕБУЕТ лока автора (G14). Версия монотонно растёт, объекты
    иммутабельны (key = <путь>/v<N>) — история не переписывается."""
    rep = SyncReport()
    owner = _owner(root)
    base = _src_root(root)
    for p in paths:
        p = p.resolve()
        try:
            rel = p.relative_to(base.resolve()).as_posix()
        except ValueError:
            rep.errors.append(f"{p}: сырцы живут только в assets_src/ (G2)")
            continue
        if rel.endswith(MANIFEST_SUFFIX):
            continue
        if not p.is_file():
            rep.errors.append(f"{rel}: файла нет")
            continue
        mf_path = base / (rel + MANIFEST_SUFFIX)
        prev = json.loads(mf_path.read_text(encoding="utf-8")) if mf_path.is_file() else None
        storage_name = prev["storage"] if prev else storage
        backend = backend_for(root, storage_name)

        holder = backend.lock_holder(rel)
        if holder is None:
            rep.errors.append(
                f"{rel}: push без лока запрещён (G14) — возьмите: vn assets lock {rel}"
            )
            continue
        if holder != owner:
            rep.errors.append(f"{rel}: залочен «{holder}» — push отклонён (G14)")
            continue

        data = p.read_bytes()
        digest = _b3(data)
        if prev and prev["hash"]["hex"] == digest:
            rep.fresh.append(rel)
            continue
        version = (prev["version"] + 1) if prev else 1
        key = f"{rel}/v{version}"
        backend.put(key, data)
        manifest = {
            "schema": "asset_src@1",
            "path": rel,
            "version": version,
            "size": len(data),
            "hash": {"algo": "blake3", "hex": digest},
            "storage": storage_name,
            "key": key,
            "uploaded_by": owner,
            "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        write_text_lf(mf_path, json.dumps(manifest, ensure_ascii=False, indent=1,
                                      sort_keys=True) + "\n")
        rep.pushed.append(f"{rel} v{version}")
    return rep


def pull(root: Path, scope: str | None = None, edit: bool = False) -> SyncReport:
    """Восстановить бинари по манифестам; --edit заодно берёт лок (правильный путь
    совпадает с ленивым, G14)."""
    rep = SyncReport()
    owner = _owner(root)
    base = _src_root(root)
    for rel, mf_path in _iter_manifests(root, scope):
        manifest = json.loads(mf_path.read_text(encoding="utf-8"))
        backend = backend_for(root, manifest["storage"])
        target = base / rel
        local_ok = target.is_file() and _b3(target.read_bytes()) == manifest["hash"]["hex"]
        if not local_ok:
            data = backend.get(manifest["key"])
            if _b3(data) != manifest["hash"]["hex"]:
                rep.errors.append(f"{rel}: хэш объекта в хранилище не совпал с манифестом!")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, target)
            rep.pulled.append(f"{rel} v{manifest['version']}")
        else:
            rep.fresh.append(rel)
        if edit:
            holder = backend.acquire_lock(rel, owner)
            if holder is not None:
                rep.errors.append(f"{rel}: лок держит «{holder}»")
            else:
                rep.locked.append(rel)
    return rep


def lock(root: Path, rel: str, release: bool = False, force: bool = False,
         storage: str = "default") -> SyncReport:
    rep = SyncReport()
    owner = _owner(root)
    base = _src_root(root)
    mf_path = base / (rel + MANIFEST_SUFFIX)
    if mf_path.is_file():
        storage = json.loads(mf_path.read_text(encoding="utf-8"))["storage"]
    backend = backend_for(root, storage)
    if release:
        holder = backend.release_lock(rel, owner, force=force)
        if holder is not None:
            rep.errors.append(f"{rel}: лок держит «{holder}» (снять: --force, эскалация на лида)")
        else:
            rep.rows.append(f"{rel}: лок снят")
    else:
        holder = backend.acquire_lock(rel, owner)
        if holder is not None:
            rep.errors.append(f"{rel}: уже залочен «{holder}»")
        else:
            rep.locked.append(rel)
    return rep


def status(root: Path) -> SyncReport:
    rep = SyncReport()
    base = _src_root(root)
    for rel, mf_path in _iter_manifests(root, None):
        manifest = json.loads(mf_path.read_text(encoding="utf-8"))
        try:
            backend = backend_for(root, manifest["storage"])
            holder = backend.lock_holder(rel)
        except StorageError as e:
            rep.errors.append(str(e))
            continue
        target = base / rel
        if not target.is_file():
            state = "нет локально (vn assets pull)"
        elif _b3(target.read_bytes()) != manifest["hash"]["hex"]:
            state = "ИЗМЕНЁН локально (не запушен)"
        else:
            state = "ok"
        lock_info = f", лок: {holder}" if holder else ""
        rep.rows.append(f"{rel}: v{manifest['version']}, {state}{lock_info}")
    return rep
