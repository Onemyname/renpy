"""Флейворы и build-info (ADR-0006): конфиг, вычисление исключений, схема,
бюджеты видео. Полный validate_release гоняется в CI/вручную (нужен SDK) —
здесь юнит-уровень."""

import io
import json
import shutil
import subprocess
import sys
import textwrap
import types

import pytest

from vn.release import (BUILD_INFO_REL, ReleaseError, budget_failures,
                        clear_build_info, compute_build_info,
                        early_content_checks, flavor_config,
                        nsfw_exclude_globs, patron_tag, write_build_info)

from conftest import REPO_ROOT

PROJECT = """\
schema: project@1
version: 0.2.0
save_schema: 1
min_tools: "0.1"
budgets:
  video_total_mb: 10
  video_file_mb: 1
flavors:
  public:
    packs: [ep_beach]
    nsfw: false
    early_content: false
    watermark: false
  patron:
    packs: [nsfw, ep_beach]
    nsfw: true
    early_content: true
    watermark: true
"""


def _mk_root(tmp_path):
    root = tmp_path / "repo"
    (root / "tools").mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "tools" / "schemas", root / "tools" / "schemas")
    (root / "project.yaml").write_text(PROJECT, encoding="utf-8")
    (root / "game").mkdir()
    return root


def test_flavor_config_and_unknown():
    import yaml
    project = yaml.safe_load(PROJECT)
    assert flavor_config(project, "public")["nsfw"] is False
    with pytest.raises(ReleaseError) as ei:
        flavor_config(project, "steam_deck")
    assert "public" in str(ei.value)     # перечисляет доступные


def test_build_info_excludes_nsfw_assets_for_public(tmp_path):
    root = _mk_root(tmp_path)
    for d in ("cg/nsfw/ch01", "mov/nsfw", "bg/city"):
        (root / "game" / "assets" / d).mkdir(parents=True)

    info = compute_build_info(root, "public")
    assert info["schema"] == "build_info@2"
    assert info["nsfw"] is False and info["watermark"] is False
    assert info["exclude"] == ["game/assets/cg/nsfw/**", "game/assets/mov/nsfw/**"]
    assert info["build_id"].startswith("0.2.0+")
    assert ".public." in info["build_id"]

    patron = compute_build_info(root, "patron", patron_token="tok_abc123")
    assert patron["exclude"] == []                     # полный контент
    assert patron["packs"] == ["ep_beach", "nsfw"]     # сортировано
    assert patron["early_content"] is True and patron["watermark"] is True
    # build_info@2: наружу уходит производная метка, а не сам токен — документ
    # целиком уезжает игроку внутри дистрибутива (game/build_id.json).
    assert "patron_token" not in patron
    assert patron["patron_tag"] == patron_tag("tok_abc123")
    assert "tok_abc123" not in json.dumps(patron)


def test_patron_tag_is_short_stable_and_not_the_token():
    """Регрессия на утечку секрета: до build_info@2 токен уезжал игроку как есть."""
    tag = patron_tag("tok_abc123")
    assert tag == patron_tag("tok_abc123")             # детерминирована
    assert len(tag) == 8 and all(c in "0123456789abcdef" for c in tag)
    assert "tok_abc123" not in tag
    assert patron_tag("tok_abc124") != tag             # различает получателей
    assert patron_tag(None) is None and patron_tag("") is None


def test_write_build_info_validates_schema_and_cleanup(tmp_path):
    root = _mk_root(tmp_path)
    info = compute_build_info(root, "public")
    path = write_build_info(root, info)
    assert path == root / BUILD_INFO_REL and path.is_file()
    clear_build_info(root)
    assert not path.exists()

    info["flavor"] = "Не-Слуг"                         # ломаем схему
    with pytest.raises(ReleaseError):
        write_build_info(root, info)


def test_nsfw_globs_only_from_real_dirs(tmp_path):
    root = _mk_root(tmp_path)
    assert nsfw_exclude_globs(root) == []              # нет assets вовсе
    (root / "game" / "assets" / "bg" / "city").mkdir(parents=True)
    assert nsfw_exclude_globs(root) == []              # nsfw-подпапок нет


def test_video_budget_failures(tmp_path):
    root = _mk_root(tmp_path)
    mov = root / "game" / "assets" / "mov" / "demo"
    mov.mkdir(parents=True)
    (mov / "big.webm").write_bytes(b"\0" * (2 * 1024 * 1024))   # 2 МБ > 1 МБ на файл
    failures = budget_failures(root)
    assert any("big.webm" in f and "на файл" in f for f in failures)
    # 2 МБ < video_total_mb: 10 — суммарный бюджет не нарушен
    assert not any("game/assets/mov:" in f for f in failures)


def test_release_gate_fails_on_draft_encoded_video(tmp_path):
    """Черновой энкод (CRF 42 / ≤720p) в проданной сборке — дефект, а не мелочь.
    От production он отличается ТОЛЬКО записью в mov_meta: контейнер и кодек те же,
    строгую видео-валидацию он проходит целиком — и потому уезжал в дистрибутив."""
    from vn.assets.video import draft_profile_outputs
    from vn.release import validate_release

    root = _mk_root(tmp_path)
    mov = root / "game" / "assets" / "mov" / "demo"
    mov.mkdir(parents=True)

    def _built(name, profile=None):
        (mov / f"{name}.webm").write_bytes(b"\0" * 32)
        if profile:
            (mov / f"{name}.webm.meta.json").write_text(
                json.dumps({"schema": "mov_meta@1", "profile": profile}),
                encoding="utf-8")

    _built("ambient", "full")
    _built("ambient@2", "draft")    # оверсэмпл-вариант — такой же отгружаемый товар
    _built("nometa")                # без метаданных: это несвежий выход, не профиль

    drafts = draft_profile_outputs(root)
    assert len(drafts) == 1 and "mov/demo/ambient@2.webm" in drafts[0]

    checks, ok = validate_release(root, "public")
    assert not ok
    assert any(s == "FAIL" and "профиль энкода видео" in m for s, m in checks)

    # Пересобранный production-профиль тот же файл пропускает
    _built("ambient@2", "full")
    assert draft_profile_outputs(root) == []
    checks2, _ok = validate_release(root, "public")
    assert any(s == "PASS" and "профиль энкода видео" in m for s, m in checks2)


PACK_MANIFEST = """\
schema: pack_manifest@1
id: {pid}
kind: dlc
version: 1.0.0
api_level: {{min: 1, below: 2}}
"""


def _mk_pack(root, pid, chapters=()):
    """Пак на диске: манифест + (опционально) каталоги глав. Генерат сцен — отдельно,
    именно его отсутствие и проверяет охранник."""
    pack = root / "packs" / pid
    (pack / "chapters").mkdir(parents=True)
    (pack / "manifest.yaml").write_text(PACK_MANIFEST.format(pid=pid), encoding="utf-8")
    for ch in chapters:
        (pack / "chapters" / f"{ch}_demo").mkdir()
    return pack


def _run_pack_build(root, pid, monkeypatch):
    from click.testing import CliRunner

    from vn.cli import pack_build

    monkeypatch.chdir(root)                            # _root() ищет корень от cwd
    return CliRunner().invoke(pack_build, [pid])


def test_pack_build_fails_when_declared_chapters_have_no_generated_scenes(tmp_path, monkeypatch):
    """Охранник был мёртв (счётчик общий с манифестом) — пак без генерата уезжал
    архивом из одного манифеста и печатал OK."""
    root = _mk_root(tmp_path)
    _mk_pack(root, "ep_winter", chapters=["ch91"])     # главы объявлены, vn build не звали

    res = _run_pack_build(root, "ep_winter", monkeypatch)
    assert res.exit_code == 1
    assert "ch91" in res.output and "vn build" in res.output
    # Неполный zip не должен оставаться на диске: он выглядит как готовый депот
    assert not (root / "build" / "packs" / "ep_winter.zip").exists()


def test_pack_build_ok_for_container_pack_without_chapters(tmp_path, monkeypatch):
    """packs/nsfw — пак-контейнер для ассетов: глав нет легитимно, «ноль сцен» не ошибка."""
    import zipfile

    root = _mk_root(tmp_path)
    _mk_pack(root, "nsfw")

    res = _run_pack_build(root, "nsfw", monkeypatch)
    assert res.exit_code == 0
    out = root / "build" / "packs" / "nsfw.zip"
    assert zipfile.ZipFile(out).namelist() == ["packs/nsfw/manifest.yaml"]
    # Про «1 файл в архиве» команда обязана сказать вслух, иначе это читается как поломка
    assert "не объявляет глав" in res.output


def test_pack_build_packs_generated_scenes_of_declared_chapters(tmp_path, monkeypatch):
    import zipfile

    root = _mk_root(tmp_path)
    _mk_pack(root, "ep_winter", chapters=["ch91"])
    scenes = root / "game" / "generated" / "scenes" / "ch91"
    scenes.mkdir(parents=True)
    (scenes / "ch91_s010.gen.rpy").write_text("label ch91_s010:\n    return\n", encoding="utf-8")

    res = _run_pack_build(root, "ep_winter", monkeypatch)
    assert res.exit_code == 0
    assert zipfile.ZipFile(root / "build" / "packs" / "ep_winter.zip").namelist() == [
        "packs/ep_winter/manifest.yaml",
        "game/generated/scenes/ch91/ch91_s010.gen.rpy",
    ]
    assert "warning:" not in res.output              # у пака с главами лишней строки нет


def test_release_gate_fails_on_lfs_pointer_fonts(tmp_path):
    """Битый LFS-чекаут не должен превращаться в падающий у игрока дистрибутив:
    гейт обязан валить сборку, даже если конфигурация CI разъехалась."""
    from vn.doctor import _lfs_pointer_fonts

    root = _mk_root(tmp_path)
    fonts = root / "game" / "fonts"
    fonts.mkdir(parents=True)
    (fonts / "Ok.ttf").write_bytes(b"\x00\x01\x00\x00" + b"\x00" * 60)
    (fonts / "Ptr.ttf").write_bytes(
        b"version https://git-lfs.github.com/spec/v1\noid sha256:x\nsize 1\n")

    bad, total = _lfs_pointer_fonts(root)
    assert total == 2 and bad == ["Ptr.ttf"]

    # Та же функция питает и vn doctor, и релизный гейт — один источник истины
    # (иначе одна из проверок разойдётся с другой и снова пропустит указатель).
    from vn import release as rel
    import inspect
    assert "_lfs_pointer_fonts" in inspect.getsource(rel.validate_release)


def test_gate_reports_all_sources_even_when_empty():
    """Молчание гейта при нуле деклараций читалось как «источника нет».
    Провайдеров теперь три (DAZ / VaM / Sims 4), и отчитываться обязаны все:
    иначе выпавшая ветка валидатора незаметна (AUDIT-020)."""
    import inspect

    import vn.release as rel

    src = inspect.getsource(rel.validate_release)
    for label in ("DAZ-декларации", "VaM-декларации", "Sims4-декларации"):
        assert label in src
    # Ни один источник не должен печатать PASS «только если что-то проверено»
    assert "elif vrep.checked" not in src
    assert "elif srep.checked" not in src


def test_built_asset_ids_ignores_derivatives(tmp_path):
    """Выпущенные id ассетов — только референсные варианты: миниатюры, постеры и
    @2 адресуются движком, а не сценарием (AUDIT-013)."""
    import vn.release as rel

    assets = tmp_path / "game" / "assets"
    for rel_path in ("cg/ch01/a.webp", "cg/ch01/a@2.webp", "cg/ch01/a.thumb.webp",
                     "bg/roof/day.webp", "mov/demo/x.webm", "mov/demo/x.poster.webp",
                     "spr/mira/a/base.webp", "spr/mira/a/base@2.webp"):
        p = assets / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    assert rel.built_asset_ids(tmp_path) == [
        "bg/roof/day", "cg/ch01/a", "mov/demo/x", "spr/mira/a/base",
    ]


def test_built_asset_ids_include_composite_shot_id(tmp_path):
    """У послойного шота своего файла нет (кадр собирает движок из слоёв, ADR-0013),
    а галерея разблокирует его по атрибуту ШОТА, не по имени файла слоя. Поэтому
    составной id шота — такой же выпущенный id, и перечислять его обязан тот же
    обход, что и файловые: иначе штамп реестра не заметит шот, и переименование
    молча отберёт у игроков открытый кадр (G7)."""
    import vn.release as rel

    shots = tmp_path / "game" / "assets" / "shots" / "ch01" / "s030"
    for rel_path in ("sunset/env.webp", "sunset/env@2.webp", "sunset/mira__school.webp",
                     "sunset/mira__casual.webp", "sunset.thumb.webp"):
        p = shots / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    assert rel.built_asset_ids(tmp_path) == [
        "shots/ch01/s030/sunset",                  # сам шот — по каталогу слоёв
        "shots/ch01/s030/sunset/env",
        "shots/ch01/s030/sunset/mira__casual",
        "shots/ch01/s030/sunset/mira__school",
    ]


def test_stamp_freezes_composite_shot_id(tmp_path):
    """Релиз штампует id шота наравне с файловыми ассетами, и штамп схемно валиден:
    id_registry@1 допускает префикс shots/ (ADR-0013, п. 7)."""
    import vn.release as rel
    from vn.schemas import SchemaRegistry

    root = _mk_root(tmp_path)
    _mk_chapter(root, "ch01", "release")
    layers = root / "game" / "assets" / "shots" / "ch01" / "s030" / "sunset"
    layers.mkdir(parents=True)
    (layers / "env.webp").write_bytes(b"x")

    assert rel.stamp_id_registry(root) > 0
    reg = json.loads((root / rel.ID_REGISTRY_REL).read_text(encoding="utf-8"))
    assert "shots/ch01/s030/sunset" in reg["assets"]         # шот
    assert "shots/ch01/s030/sunset/env" in reg["assets"]     # и его слой
    assert SchemaRegistry(root / "tools" / "schemas").validate(
        reg, rel.ID_REGISTRY_REL) == []
    assert rel.stamp_id_registry(root) == 0                  # append-only, идемпотентно


def test_options_rpy_ships_assets_loose_without_rpa(repo_root):
    """Ассеты едут россыпью намеренно: Steam дельта-патчит отдельные файлы, а
    монолитный .rpa перекачивался бы игроком целиком при правке одного спрайта;
    защиты архив всё равно не добавляет — распаковывается извне (G9).
    Появление .rpa — осознанное решение с ADR (мобильная поставка фазы 3,
    ARCHITECTURE.md §2.4), а не случайная правка options.rpy — её и ловим."""
    import re

    text = (repo_root / "game" / "options.rpy").read_text(encoding="utf-8")
    assert "build.archive" not in text, (
        "в game/options.rpy появился build.archive — desktop-поставка должна "
        "остаться россыпью (Steam delta-патчи); если это осознанно — нужен ADR")
    # Второй путь к .rpa — классификация ассетов в имя архива вместо None
    for pattern, target in re.findall(r"build\.classify\(\s*([^,]+),\s*([^)]+)\)", text):
        if "game/assets" in pattern:
            assert target.strip() == "None", (
                f"game/assets классифицирован в {target.strip()!r} — это упаковка "
                "в архив, см. докстринг теста")


CHAPTER_YAML = """\
schema: chapter@1
id: {cid}
title_key: ui.ch.{cid}
status: {status}
entry_scene: s010
scene_order: [s010]
"""


def _mk_chapter(root, cid, status, name="demo"):
    ch = root / "content" / "chapters" / f"{cid}_{name}"
    (ch / "scenes").mkdir(parents=True)
    (ch / "chapter.yaml").write_text(CHAPTER_YAML.format(cid=cid, status=status),
                                     encoding="utf-8")
    (ch / "scenes" / "s010_intro.scene.yaml").write_text("schema: scene@1\n",
                                                         encoding="utf-8")
    return ch


def test_early_content_gate_blocks_draft_chapters_in_public_build(tmp_path):
    """early_content писался в build_info и никем не читался. Смысл ему даёт гейт:
    незрелая глава всё равно уезжает в дистрибутив (скрипты грузятся всегда, G9),
    и решение «публиковать ли её» обязано приниматься ДО сборки."""
    import yaml

    root = _mk_root(tmp_path)
    project = yaml.safe_load(PROJECT)
    _mk_chapter(root, "ch01", "release")
    _mk_chapter(root, "ch02", "playtest")

    # playtest проходит те же строгие проверки, что release: не блокер, но и молчать
    # о неподписанном контенте гейт не должен.
    checks = early_content_checks(root, flavor_config(project, "public"))
    assert [state for state, _ in checks] == ["WARN"]
    assert "ch02" in checks[0][1] and "ch01" not in checks[0][1]

    # draft ослабляет граф-проверки конвейера до warnings — у игрока это «сцена
    # недоступна» посреди публичной сборки, поэтому FAIL.
    _mk_chapter(root, "ch03", "draft")
    states = {state for state, _ in early_content_checks(root, flavor_config(project, "public"))}
    assert states == {"FAIL", "WARN"}

    # Ранний доступ объявлен — незрелые главы для флейвора штатны.
    assert early_content_checks(root, flavor_config(project, "patron")) == [
        ("PASS", "early_content=true: незрелые главы для этого флейвора штатны")]


def test_early_content_gate_passes_on_fully_released_content(tmp_path):
    import yaml

    root = _mk_root(tmp_path)
    cfg = flavor_config(yaml.safe_load(PROJECT), "public")
    assert early_content_checks(root, cfg) == [
        ("PASS", "зрелость контента: все главы сборки status=release")]   # глав нет вовсе
    _mk_chapter(root, "ch01", "release")
    assert [state for state, _ in early_content_checks(root, cfg)] == ["PASS"]


def test_early_content_gate_is_warning_until_first_release_chapter(tmp_path):
    """Пока ни одна глава не доведена до release, требование «в публичном флейворе
    только зрелые главы» невыполнимо — гейт запретил бы собрать даже демо. Такой
    гейт учит игнорировать гейты, поэтому до первой зрелой главы это WARN; норма
    включается сама, без флага, как только release-глава появляется."""
    import yaml

    root = _mk_root(tmp_path)
    cfg = flavor_config(yaml.safe_load(PROJECT), "public")
    _mk_chapter(root, "ch01", "draft")

    checks = early_content_checks(root, cfg)
    assert [state for state, _ in checks] == ["WARN"]
    assert "ch01" in checks[0][1] and "станет строгим" in checks[0][1]

    # Появилась зрелая глава -> та же draft-глава становится блокером публикации.
    _mk_chapter(root, "ch02", "release")
    assert ("FAIL", ) == tuple(state for state, _ in early_content_checks(root, cfg))


def test_gate_reads_early_content_declaration(repo_root):
    """Регрессия на мёртвую декларацию: поле обязано читаться гейтом, а не только
    писаться в build_info."""
    import inspect

    import vn.release as rel

    assert "early_content_checks" in inspect.getsource(rel.validate_release)


# ── Рантайм-гейт паков (G9): исполняем блоки init python из framework ─────────
# Ren'Py в pytest недоступен, а гейт — рантайм-логика: грепом по исходнику его не
# проверить. Блок исполняется как есть на заглушке store, поэтому тест ловит
# фактическое поведение installed()/owned(), а не пересказ.

FLOW_RPY_REL = "game/framework/00_core/030_flow.rpy"
BUILD_INFO_RPY_REL = "game/framework/00_core/060_build_info.rpy"
VN_PACKS = {"ep_beach": {"kind": "dlc"}, "nsfw": {"kind": "dlc"}}


def _exec_init_block(monkeypatch, path, store_name, **store_attrs):
    """Тело блока `init … python in <store_name>` из .rpy-файла на заглушке store."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines)
                 if ln.startswith("init") and ln.rstrip().endswith(f"python in {store_name}:"))
    body = []
    for ln in lines[start + 1:]:
        if ln.strip() and not ln.startswith("    "):
            break                                  # блок кончился (dedent до нуля)
        body.append(ln)
    store = types.ModuleType("store")
    for name, value in store_attrs.items():
        setattr(store, name, value)
    monkeypatch.setitem(sys.modules, "store", store)
    ns: dict = {}
    exec(compile(textwrap.dedent("\n".join(body)), str(path), "exec"), ns)
    module = types.ModuleType(store_name)
    for name, value in ns.items():
        if not name.startswith("__"):
            setattr(module, name, value)
    return module


def _vn_build_store(monkeypatch, info):
    """Стор vn_build: info=None — dev-чекаут (build_id.json нет), dict — релиз."""
    def open_file(name, encoding=None):
        if info is None:
            raise IOError(f"нет {name}")
        return io.StringIO(json.dumps(info))

    return _exec_init_block(monkeypatch, REPO_ROOT / BUILD_INFO_RPY_REL, "vn_build",
                            renpy=types.SimpleNamespace(open_file=open_file))


def _pack_registry(monkeypatch, vn_build):
    store_ns = types.SimpleNamespace(VN_PACKS=VN_PACKS)
    if vn_build is not None:
        store_ns.vn_build = vn_build
    return _exec_init_block(
        monkeypatch, REPO_ROOT / FLOW_RPY_REL, "vn",
        renpy=types.SimpleNamespace(store=store_ns),
        vn_log=lambda msg: None, vn_registry=types.SimpleNamespace()).pack_registry


def test_pack_gate_honours_flavor_pack_list(tmp_path, monkeypatch):
    """Пак вне флейвора не установлен. VN_PACKS перечисляет ВСЕ паки дерева, и без
    сверки со списком сборки public-билд считал бы nsfw-пак установленным — а без
    Steam-провайдера (DRM-free: владение = установленность) ещё и купленным."""
    info = compute_build_info(_mk_root(tmp_path), "public")
    build = _vn_build_store(monkeypatch, info)
    assert build.is_release is True and build.packs == ["ep_beach"]

    reg = _pack_registry(monkeypatch, build)
    assert reg.installed("ep_beach") and reg.owned("ep_beach")
    assert not reg.installed("nsfw") and not reg.owned("nsfw")   # пак patron-флейвора
    assert reg.installed("core") and reg.owned("core")           # ядро вне гейта
    assert not reg.installed("ep_winter")                        # нет и в генерате


def test_pack_gate_open_in_dev_checkout(tmp_path, monkeypatch):
    """В dev-чекауте build_id.json нет: разработчику доступно всё установленное,
    иначе dev-прогон и smoke гейтились бы вслепую."""
    dev = _vn_build_store(monkeypatch, None)
    assert dev.is_release is False and dev.flavor == "dev"
    reg = _pack_registry(monkeypatch, dev)
    assert all(reg.installed(pid) and reg.owned(pid) for pid in VN_PACKS)

    # Стор vn_build создаётся позже стора vn (init -985 против -999): гейт,
    # спрошенный до него, тоже не должен отбирать контент.
    assert _pack_registry(monkeypatch, None).installed("nsfw")

    # А вот пустой список паков — легитимный релизный флейвор, а не dev: признак
    # dev это отсутствие build_id.json (is_release), а не пустота packs.
    info = dict(compute_build_info(_mk_root(tmp_path), "public"), packs=[])
    assert not _pack_registry(monkeypatch, _vn_build_store(monkeypatch, info)).installed("nsfw")

# ── Готовность к Steam-поставке до получения App ID ──────────────────────────

def test_steam_preflight_is_useful_without_appid(tmp_path, repo_root):
    """Сценарий «приложения у Valve ещё нет»: пустой App ID обязан быть пунктом
    TODO, а не провалом — иначе команда бесполезна ровно тогда, когда она нужнее
    всего. На синтетическом корне: в репозитории App ID заполнен плейсхолдером
    (симуляция Steam, 2026-08-21), и «пустого» состояния у repo_root больше нет."""
    import shutil

    import yaml

    from vn.release import steam_preflight

    root = tmp_path / "repo"
    root.mkdir()
    shutil.copy(repo_root / "project.yaml", root / "project.yaml")
    shutil.copytree(repo_root / "content" / "achievements",
                    root / "content" / "achievements")
    shutil.copytree(repo_root / "game", root / "game",
                    ignore=shutil.ignore_patterns("assets", "generated", "tl",
                                                  "saves", "cache"))
    proj = yaml.safe_load((root / "project.yaml").read_text(encoding="utf-8"))
    proj["platform"] = {"steam": {"appid": None}}
    (root / "project.yaml").write_text(yaml.safe_dump(proj, allow_unicode=True,
                                                      sort_keys=False), encoding="utf-8")
    checks = steam_preflight(root, "public")
    states = [st for st, _ in checks]
    assert "FAIL" not in states, [m for st, m in checks if st == "FAIL"]
    assert any(st == "TODO" and "App ID" in m for st, m in checks)
    # Список ачивок для партнёрки печатается по декларациям: API Name = id
    ach_line = next(m for st, m in checks if "ачивки для партнёрки" in m)
    for aid in ("met_mira", "reached_rooftop"):
        assert aid in ach_line


def test_steam_preflight_reports_ready_state(tmp_path, repo_root):
    """С заполненными App ID и депотами пункты TODO по ним исчезают."""
    import shutil

    import yaml

    from vn.release import steam_preflight

    root = tmp_path / "repo"
    root.mkdir()
    shutil.copy(repo_root / "project.yaml", root / "project.yaml")
    shutil.copytree(repo_root / "game", root / "game",
                    ignore=shutil.ignore_patterns("assets", "generated", "tl", "saves", "cache"))
    proj = yaml.safe_load((root / "project.yaml").read_text(encoding="utf-8"))
    proj["platform"] = {"steam": {"appid": 480, "depots": {"windows": 481, "linux": 482}}}
    (root / "project.yaml").write_text(yaml.safe_dump(proj, allow_unicode=True, sort_keys=False),
                                      encoding="utf-8")
    checks = steam_preflight(root, "public")
    assert any(st == "PASS" and "App ID: 480" in m for st, m in checks)
    assert any(st == "PASS" and "депоты" in m for st, m in checks)
    assert not any(st == "TODO" and "App ID" in m for st, m in checks)


def test_steam_preflight_catches_duplicate_depots(tmp_path, repo_root):
    """Один депот на две платформы — реальная ошибка конфигурации: SteamPipe
    залил бы содержимое одной платформы поверх другой."""
    import shutil

    import yaml

    from vn.release import steam_preflight

    root = tmp_path / "repo"
    root.mkdir()
    shutil.copy(repo_root / "project.yaml", root / "project.yaml")
    proj = yaml.safe_load((root / "project.yaml").read_text(encoding="utf-8"))
    proj["platform"] = {"steam": {"appid": 480, "depots": {"windows": 481, "linux": 481}}}
    (root / "project.yaml").write_text(yaml.safe_dump(proj, allow_unicode=True, sort_keys=False),
                                      encoding="utf-8")
    checks = steam_preflight(root, "public")
    assert any(st == "FAIL" and "повторяются" in m for st, m in checks)


def test_steam_preflight_requires_explicit_save_directory(tmp_path, repo_root):
    """Auto-Cloud привязывается к каталогу сейвов: неявный save_directory
    означает, что маски в Steamworks задать не к чему."""
    import shutil

    from vn.release import steam_preflight

    root = tmp_path / "repo"
    (root / "game").mkdir(parents=True)
    shutil.copy(repo_root / "project.yaml", root / "project.yaml")
    (root / "game" / "options.rpy").write_text("define config.name = _('VN')\n", encoding="utf-8")
    checks = steam_preflight(root, "public")
    assert any(st == "FAIL" and "save_directory" in m for st, m in checks)

# ── Линии кэша .rpyc: флейворы не делят носитель statement-имён (G6) ──────────

def _rpyc_cache(root, *rel_versions):
    for rel in rel_versions:
        (root / "ci" / "rpyc-cache" / rel).mkdir(parents=True, exist_ok=True)


def test_rpyc_lane_is_per_flavor(tmp_path):
    """Público и patron не делят кэш: наборы .rpyc у них разные, и перенос имён из
    чужой линии — тот самый случай, от которого страхует G6."""
    from vn.release import rpyc_cache_lane

    root = _mk_root(tmp_path)
    _rpyc_cache(root, "public/0.1.4", "patron/0.1.4", "patron/0.1.5")
    lane, caches, legacy = rpyc_cache_lane(root, "-public")
    assert lane.name == "public" and [c.name for c in caches] == ["0.1.4"] and not legacy
    lane, caches, _ = rpyc_cache_lane(root, "-patron")
    assert [c.name for c in caches] == ["0.1.4", "0.1.5"], "версии линии сортируются semver"


def test_rpyc_lane_without_flavor_is_separate(tmp_path):
    """Прямой `vn package` пишет в линию dev и НЕ видит релизных: ручной прогон не
    должен ни затирать релизную линию, ни брать из неё имена."""
    from vn.release import rpyc_cache_lane

    root = _mk_root(tmp_path)
    _rpyc_cache(root, "public/0.1.4")
    lane, caches, legacy = rpyc_cache_lane(root, "")
    assert lane.name == "dev" and caches == [] and not legacy


def test_rpyc_lane_falls_back_to_legacy_layout(tmp_path):
    """Раскладка до разделения по линиям (версии в корне кэша) читается как
    запасной вариант с пометкой: молча потерять кэш опаснее — без переноса имён
    ломаются сейвы прошлого релиза."""
    from vn.release import rpyc_cache_lane

    root = _mk_root(tmp_path)
    _rpyc_cache(root, "0.1.0", "0.1.4")
    lane, caches, legacy = rpyc_cache_lane(root, "-public")
    assert legacy and [c.name for c in caches] == ["0.1.0", "0.1.4"]
    assert lane.name == "public", "запись всё равно идёт в линию"


def test_snapshot_content_sees_pack_chapters(tmp_path):
    """Главы паков — такой же выпущенный контент: их сцены едут в сейвы игрока и
    подпадают под G7. Пока снимок обходил только content/chapters, changelog и
    штамп реестра о паках не знали вовсе."""
    from vn.release import snapshot_content

    root = _mk_root(tmp_path)
    for base, ch, scene in ((root / "content" / "chapters", "ch01_core", "s010_intro"),
                            (root / "packs" / "ep_beach" / "chapters", "ch90_beach",
                             "s010_shore")):
        (base / ch / "scenes").mkdir(parents=True)
        (base / ch / "chapter.yaml").write_text("status: release\n", encoding="utf-8")
        (base / ch / "scenes" / f"{scene}.scene.yaml").write_text("id: s010\n",
                                                                 encoding="utf-8")
    snap = snapshot_content(root)
    assert set(snap) == {"ch01", "ch90"}
    assert snap["ch01"]["pack"] == "core" and snap["ch90"]["pack"] == "ep_beach"
    assert snap["ch90"]["scenes"] == ["ch90_s010"]

# ── Changelog: раздел версии одноразовый ─────────────────────────────────────

def _chapter(root, base_rel, ch, scene="s010_intro"):
    base = root / base_rel / ch
    (base / "scenes").mkdir(parents=True)
    (base / "chapter.yaml").write_text("status: draft\n", encoding="utf-8")
    (base / "scenes" / f"{scene}.scene.yaml").write_text("id: s010\n", encoding="utf-8")


def test_changelog_refuses_version_already_in_file(tmp_path):
    """Прогон на уже выпущенной версии не просто дублирует заголовок — он СЪЕДАЕТ
    дифф: манифест становится базой следующего сравнения, и сцены, добавленные
    после релиза, в блок следующей версии уже не попадут."""
    from vn.release import ReleaseError, update_changelog

    root = _mk_root(tmp_path)
    _chapter(root, "content/chapters", "ch01_core")
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "CHANGELOG.md").write_text(
        "# Changelog\n\n## 0.2.0\n\nТехнический выпуск.\n", encoding="utf-8")
    with pytest.raises(ReleaseError, match="уже есть раздел"):
        update_changelog(root)
    assert not (root / "ci" / "release-manifest.json").exists(), \
        "манифест не должен обновиться на отказе — иначе дифф уже съеден"


def test_changelog_refuses_released_tag(tmp_path, monkeypatch):
    """Тег есть даже когда CHANGELOG кто-то поправил руками: вторая половина
    проверки нужна ровно для этого случая."""
    from vn import release as rel

    root = _mk_root(tmp_path)
    _chapter(root, "content/chapters", "ch01_core")
    monkeypatch.setattr(rel, "git_tag_exists", lambda r, tag: tag == "v0.2.0")
    with pytest.raises(rel.ReleaseError, match="уже выпущена"):
        rel.update_changelog(root)


def test_changelog_force_overrides_the_guard(tmp_path, monkeypatch):
    """--force оставлен для перезаписи после ручной правки: запрет обязан быть
    снимаемым, иначе починка кривого CHANGELOG упрётся в собственный гейт."""
    from vn import release as rel

    root = _mk_root(tmp_path)
    _chapter(root, "content/chapters", "ch01_core")
    monkeypatch.setattr(rel, "git_tag_exists", lambda r, tag: True)
    rep = rel.update_changelog(root, force=True)
    assert rep.added_chapters == ["ch01"]


def test_changelog_writes_on_a_bumped_version(tmp_path, monkeypatch):
    """Штатный порядок: версия побампана, тега нет, раздела нет — команда пишет
    и раздел, и манифест, и дифф считается от прошлого манифеста."""
    from vn import release as rel

    root = _mk_root(tmp_path)
    _chapter(root, "content/chapters", "ch01_core")
    monkeypatch.setattr(rel, "git_tag_exists", lambda r, tag: False)
    rep = rel.update_changelog(root)
    text = (root / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## 0.2.0" in text and "ch01" in text and rep.added_scenes == ["ch01_s010"]
    manifest = json.loads((root / "ci" / "release-manifest.json").read_text(encoding="utf-8"))
    assert manifest["chapters"]["ch01"]["pack"] == "core"
    # Повторный прогон на той же версии обязан упереться в гейт, а не съесть дифф.
    with pytest.raises(rel.ReleaseError):
        rel.update_changelog(root)


def test_unshipped_pack_vars_are_excluded_from_every_flavor(tmp_path):
    """Пак вне всех флейворов никому не уезжает, поэтому его объявления
    переменных не должны попадать ни в один дистрибутив.

    Почему это вообще проблема. Генерат один на все флейворы (иначе рвётся линия
    .rpyc, G6), значит `default ch70.path = 'none'` исполняется и в релизной
    сборке, а Ren'Py кладёт в сейв любую изменённую переменную стора — то есть
    тестовые значения ехали бы каждому игроку (RTL-046). Лечение — не второй
    генерат, а глоб исключения: в dev-чекауте файл есть и тестовые главы
    играбельны, в сборке его нет.

    Проверяются два инварианта, и оба тихие: глоб зависит от НАЛИЧИЯ файла (иначе
    build_info обещал бы исключить то, чего нет), и глоб уходит в ОБА флейвора —
    в отличие от NSFW, где исключение зависит от флейвора и легко скопировать
    условие не туда.
    """
    from vn.release import unshipped_exclude_globs

    root = _mk_root(tmp_path)
    assert unshipped_exclude_globs(root) == [], "файла нет — обещать нечего"

    gen = root / "game" / "generated" / "state"
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "defaults_unshipped.gen.rpy").write_text(
        "init -980 python in ch70:\n    pass\n", encoding="utf-8")
    globs = unshipped_exclude_globs(root)
    assert globs == ["game/generated/state/defaults_unshipped.gen*"]
    # Глоб обязан ловить и .rpyc: поведение сборки определяет он, а не .rpy.
    assert globs[0].endswith("*") and not globs[0].endswith(".rpy")

    for flavor in ("public", "patron"):
        info = compute_build_info(root, flavor)
        assert globs[0] in info["exclude"], (
            f"флейвор {flavor}: генерат пака вне флейворов не исключён — "
            f"его переменные уедут в сейв игрока")


def test_released_rpyc_lane_is_not_overwritten(tmp_path):
    """Линия `.rpyc` выпущенной версии неприкосновенна.

    Это самая тихая из известных мне поломок сейвов. В линии лежат
    statement-имена сборки, которая стоит у игроков; следующий релиз кладёт их в
    `game/` перед компиляцией — на этом держится загрузка старых сейвов (G6).
    Перезапись сегодняшними именами не ломает НИЧЕГО сегодня: сборка зелёная,
    дистрибутив валиден, гейт проходит. Рвётся загрузка сейвов в СЛЕДУЮЩЕМ
    релизе, у игроков, и связать это с той сборкой уже почти невозможно.

    Пойман этот случай, кстати, живым способом: проверочный прогон
    `vn release build --flavor public` перезаписал линию выпущенной 1.0.0 в этом
    же репозитории (56 изменённых файлов, восстановлено из git).

    Ровно два состояния должны различаться, и оба проверяются:
    ДО тега пересборка той же версии законна (её делают десятки раз),
    ПОСЛЕ тега — запрещена.
    """
    from vn.release import rpyc_lane_frozen

    root = _mk_root(tmp_path)
    lane = root / "ci" / "rpyc-cache" / "public"
    (lane / "1.0.0").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "init"],
                   cwd=root, check=True)

    # Каталог есть, тега нет — пересборка законна.
    assert rpyc_lane_frozen(root, lane, "1.0.0") is None
    # Версия, которой в кэше нет вовсе, — тоже законна (первый релиз).
    assert rpyc_lane_frozen(root, lane, "1.1.0") is None

    subprocess.run(["git", "tag", "v1.0.0"], cwd=root, check=True)
    reason = rpyc_lane_frozen(root, lane, "1.0.0")
    assert reason and "1.0.0" in reason and "G6" in reason
    # Тег на ДРУГУЮ версию линию 1.0.0 не замораживает и наоборот.
    assert rpyc_lane_frozen(root, lane, "1.1.0") is None


def _mk_zone_chapter(base, dirname, ch_id, scenes, status="release", store=None):
    """Глава с декларациями сцен и (необязательно) своих переменных."""
    d = base / dirname
    (d / "scenes").mkdir(parents=True)
    (d / "chapter.yaml").write_text(
        f"schema: chapter@1\nid: {ch_id}\ntitle_key: meta.chapters.{ch_id}.title\n"
        f"status: {status}\nentry_scene: {scenes[0]}\n"
        f"scene_order: [{', '.join(scenes)}]\n", encoding="utf-8")
    for sid in scenes:
        (d / "scenes" / f"{sid}_probe.scene.yaml").write_text(
            f"schema: scene@1\nid: {sid}\nexits: {{}}\n", encoding="utf-8")
    if store:
        (d / "vars.yaml").write_text(
            f"schema: vars@1\nstore: {store}\nvars:\n  flag:\n    type: bool\n"
            f"    default: false\n    doc: t\n    since: 1\n", encoding="utf-8")
    return d


def test_unshipped_pack_ids_are_never_stamped_as_released(tmp_path):
    """G7 защищает то, что уехало ИГРОКУ. Пак вне всех флейворов не уезжает никому
    ни в одной сборке — его id в append-only реестре быть не должно.

    Иначе первый же `vn release` навсегда вписывает тестовые топологии графа
    (packs/qa_flow: status обязан быть release, иначе гейт зрелости красит сборку
    независимо от флейвора — ADR-0021 §6), и удаление QA-пака — штатная операция —
    даёт красный `vn content lint` «выпущенная сцена исчезла», снимаемый только
    ручной правкой append-only файла.

    Вторая половина инварианта не менее важна: пак, который В флейворе
    (ep_beach), обязан штамповаться — вместе со своими переменными, которые
    раньше выпадали из сети, хотя сцены того же пака в неё попадали."""
    from vn.release import _released_ids

    root = _mk_root(tmp_path)
    _mk_zone_chapter(root / "content" / "chapters", "ch01_core", "ch01", ["s010"],
                store="ch01")
    _mk_zone_chapter(root / "packs" / "ep_beach" / "chapters", "ch90_beach", "ch90",
                ["s010"], store="ch90")
    _mk_zone_chapter(root / "packs" / "qa_flow" / "chapters", "ch70_diamond", "ch70",
                ["s010", "s020"], store="ch70")

    ids = _released_ids(root)
    assert ids["chapters"] == ["ch01", "ch90"], (
        "глава пака вне флейворов попала под G7 — её id станет неизменяемым")
    assert ids["scenes"] == ["ch01_s010", "ch90_s010"]
    assert "ch70.flag" not in ids["vars"]
    # Пак В флейворе — штампуется целиком, включая переменные (раньше терялись).
    assert "ch90.flag" in ids["vars"], (
        "переменные поставляемого пака остались без сети G7, хотя его сцены — нет")
    assert "ch01.flag" in ids["vars"]


def test_unmeasured_runtime_budget_is_a_failure_not_silence(tmp_path):
    """«Метрики нет» и «метрика в рамках» — разные ответы.

    Раньше оба давали пустой список: проверка стояла за `if metric is not None`.
    На Windows perf.json не создавался вовсе (в рантайме падал `import resource`,
    а весь блок дампа был закрыт except), поэтому объявленный бюджет
    baseline_rss_mb не проверялся НИКОГДА и прогон оставался зелёным. Бюджет,
    который никто не проверяет, — это просто число в project.yaml."""
    from vn.release import runtime_budget_failures

    root = _mk_root(tmp_path)
    proj = (root / "project.yaml").read_text(encoding="utf-8")
    (root / "project.yaml").write_text(
        proj.replace("budgets:\n", "budgets:\n  baseline_rss_mb: 1200\n"
                                   "  cold_start_s: 30\n", 1), encoding="utf-8")

    missing = runtime_budget_failures(root, cold_start_s=None, baseline_rss_mb=None)
    assert any("RSS" in f and "не измерен" in f for f in missing), missing
    assert any("cold start" in f and "не измерен" in f for f in missing), missing

    ok = runtime_budget_failures(root, cold_start_s=3.0, baseline_rss_mb=540.0)
    assert ok == [], ok
    over = runtime_budget_failures(root, cold_start_s=3.0, baseline_rss_mb=1500.0)
    assert any("1500" in f or "> бюджета" in f for f in over), over


def test_content_snapshot_excludes_packs_outside_every_flavor(repo_root):
    """Обход гарда FWA-019: qa_flow уезжал в changelog и в release-manifest.

    Заголовок FWA-019 обещал закрыть ДВУХ потребителей («id_registry и changelog»),
    но фильтр лёг только в _released_ids. Общий снимок фильтра не имел, поэтому
    `vn release changelog` — штатный ПЕРВЫЙ шаг релиза — писал в docs/CHANGELOG.md
    «Новые главы: ch70 (pack qa_flow) …» и «Новые сцены (22): …», то есть тестовые
    топологии графа, которые не уезжают ни одному игроку ни в одном флейворе.

    Второй удар отложенный: ci/release-manifest.json впитывал их навсегда, и
    удаление QA-пака — штатная операция, ради которой FWA-019 и заводили — давало
    в следующем разделе «Удалены сцены (см. renames.yaml)» и жёлтое предупреждение
    про renames, хотя никаких переименований не было.

    Фильтр стоит ТАМ, ГДЕ РОЖДАЕТСЯ СНИМОК, а не у каждого потребителя: иначе
    класс промаха «забыли одного потребителя» воспроизводится снова."""
    from vn.release import snapshot_content
    from vn.repo import unshipped_chapters

    snap = snapshot_content(repo_root)
    unshipped = unshipped_chapters(repo_root)
    assert unshipped, ("в дереве нет пака вне флейворов — тест выродился, "
                       "проверять фильтр не на чем")
    leaked = sorted(set(snap) & set(unshipped))
    assert not leaked, (
        f"главы пака вне всех флейворов попали в снимок релиза: {leaked} — они "
        f"уедут в changelog и навсегда впитаются в release-manifest")
    # И гейт не должен выродиться: поставляемый контент в снимке остаться обязан.
    assert snap, "снимок пуст — фильтр съел всё"


# Зоны из .gitignore, которые ЛЕГАЛЬНО не исключены из дистрибутива. Каждая с
# причиной: список заморожен, чтобы новая зона не проехала молча.
_DISTRIBUTION_EXEMPT_ZONES = {
    # Движок поставляет свой lib/ и renpy/ уже скомпилированными — .pyc и
    # __pycache__ внутри них это нормальная часть пакета, а не наш мусор.
    "__pycache__/",
    # Обязаны ехать игроку: это и есть игра (генерат, ассеты, переводы).
    "game/generated/", "game/assets/", "game/tl/",
    # Локальные зоны движка рядом с каталогом игры: их исключает сам движок
    # (renpy/common/00build.rpy: ("game/saves/", None)) либо они не создаются в
    # поставке вовсе.
    "game/cache/", "game/saves/",
    # Метаданные флейвора: vn release build кладёт их на время distribute
    # НАМЕРЕННО — рантайм читает build_id.json, чтобы знать nsfw и состав паков.
    "game/build_id.json",
    # Мусор файловых менеджеров исключает сам движок:
    # renpy/common/00build.rpy: late_base_patterns содержит ("**/Thumbs.db", None)
    # и ("**/desktop.ini", None), а дотфайлы — общим (".*", None).
    "Thumbs.db",
}


def test_every_local_zone_excluded_from_git_is_excluded_from_the_distribution(repo_root):
    """Локальная зона, которой нет в git, не имеет права уезжать игроку.

    Два контура — .gitignore и game/options.rpy — независимы, и починка одного
    ничего не говорит про другой. Сам .gitignore это знает: у ключей подписи
    Android прямо написано, что «оба контура на месте» и что их сверяет preflight.
    А для reports/ был сделан только git-контур (FWA-030), и distribute исправно
    клал зону в КАЖДЫЙ пакет: в собранном vn-1.0.1-win.zip лежали reports/audit.md
    (138 КБ внутреннего отчёта аудита) и reports/decisions_needed.md.

    Это ровно то, от чего защищается список зон в options.rpy: «источники,
    инструменты, сырцы и прошлые артефакты — не для игроков (и не для
    дата-майнеров)». Для 18+ проекта внутренние отчёты в поставке — подарок
    дата-майнеру.

    Дотфайлы и дот-каталоги проверять не нужно: их исключает сам движок
    (renpy/common/00build.rpy: late_base_patterns содержит (".*", None))."""
    options = (repo_root / "game" / "options.rpy").read_text(encoding="utf-8")
    ignored = (repo_root / ".gitignore").read_text(encoding="utf-8")

    zones = []
    for raw in ignored.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "!", "*")) or line.startswith("."):
            continue
        if not line.endswith("/") and "." not in line.rsplit("/", 1)[-1]:
            continue
        zones.append(line)
    assert zones, "разбор .gitignore выродился — зон не нашлось"

    missing = []
    for zone in zones:
        if zone in _DISTRIBUTION_EXEMPT_ZONES:
            continue
        name = zone.rstrip("/")
        # Исключение может быть точным ("log.txt"), зоной ("reports/**") или
        # покрывающим префиксом ("tools/**" покрывает tools/vn/saves/).
        covered = f'"{name}/**"' in options or f'"{name}"' in options
        if not covered:
            head = name.split("/")[0]
            covered = f'"{head}/**"' in options
        if not covered:
            missing.append(zone)

    assert not missing, (
        "зоны есть в .gitignore, но НЕ исключены из дистрибутива — уедут игроку: "
        + ", ".join(missing)
        + ". Добавьте их в список build.classify(..., None) в game/options.rpy "
          "либо в _DISTRIBUTION_EXEMPT_ZONES с причиной, почему они должны ехать")
