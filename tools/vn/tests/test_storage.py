"""Файловый бэкенд хранилища сырцов (G21) и обязательные локи (G14)."""

import json

import pytest

from vn.assets.storage import StorageError, backend_for, lock, pull, push, status


def _mk_root(tmp_path):
    root = tmp_path / "repo"
    (root / "assets_src" / "psd" / "characters" / "mira").mkdir(parents=True)
    store = tmp_path / "store"
    (root / ".vnstorage.yaml").write_text(
        f'schema: storage@1\nstorages:\n  default: {{type: file, path: "{store.as_posix()}"}}\n',
        encoding="utf-8",
    )
    src = root / "assets_src" / "psd" / "characters" / "mira" / "mira_a.psd"
    src.write_bytes(b"PSD-v1-bytes")
    return root, src


def test_push_requires_lock(tmp_path):
    root, src = _mk_root(tmp_path)
    rep = push(root, [src])
    assert any("push без лока запрещён (G14)" in e for e in rep.errors)
    assert not rep.pushed


def test_lock_push_pull_roundtrip(tmp_path):
    root, src = _mk_root(tmp_path)
    rel = "psd/characters/mira/mira_a.psd"

    assert lock(root, rel).errors == []
    rep = push(root, [src])
    assert rep.errors == [] and rep.pushed == [f"{rel} v1"]
    manifest = json.loads((src.parent / (src.name + ".manifest.json")).read_text(encoding="utf-8"))
    assert manifest["version"] == 1 and manifest["storage"] == "default"

    # Повторный push без изменений — актуален; с изменениями — v2, объекты иммутабельны
    assert push(root, [src]).fresh == [rel]
    src.write_bytes(b"PSD-v2-bytes")
    rep = push(root, [src])
    assert rep.pushed == [f"{rel} v2"]
    backend = backend_for(root, "default")
    assert backend.get(f"{rel}/v1") == b"PSD-v1-bytes"   # история не переписана
    assert backend.get(f"{rel}/v2") == b"PSD-v2-bytes"

    # Свежий чекаут: бинаря нет — pull восстанавливает по манифесту
    src.unlink()
    rep = pull(root)
    assert rep.pulled == [f"{rel} v2"] and src.read_bytes() == b"PSD-v2-bytes"
    assert pull(root).fresh == [rel]                     # идемпотентно


def test_foreign_lock_blocks_push_and_force_release(tmp_path):
    root, src = _mk_root(tmp_path)
    rel = "psd/characters/mira/mira_a.psd"
    backend = backend_for(root, "default")
    backend.acquire_lock(rel, "artist-kate")

    rep = push(root, [src])
    assert any("залочен «artist-kate»" in e for e in rep.errors)
    rep = lock(root, rel)
    assert any("уже залочен" in e for e in rep.errors)
    rep = lock(root, rel, release=True)
    assert any("лок держит" in e for e in rep.errors)    # чужой лок без --force не снять
    assert lock(root, rel, release=True, force=True).errors == []


def test_status_reports_states(tmp_path):
    root, src = _mk_root(tmp_path)
    rel = "psd/characters/mira/mira_a.psd"
    lock(root, rel)
    push(root, [src])
    assert any("v1, ok, лок:" in r for r in status(root).rows)

    src.write_bytes(b"local-edit")
    assert any("ИЗМЕНЁН локально" in r for r in status(root).rows)
    src.unlink()
    assert any("нет локально" in r for r in status(root).rows)


def test_s3_backend_is_honest_stub(tmp_path):
    root, _src = _mk_root(tmp_path)
    (root / ".vnstorage.yaml").write_text(
        'schema: storage@1\nstorages:\n'
        '  default: {type: s3, endpoint: "https://s3.example.com", bucket: "vn"}\n',
        encoding="utf-8",
    )
    with pytest.raises(StorageError, match="s3-бэкенд подключается"):
        backend_for(root, "default")
