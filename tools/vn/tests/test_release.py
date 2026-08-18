"""Флейворы и build-info (ADR-0006): конфиг, вычисление исключений, схема,
бюджеты видео. Полный validate_release гоняется в CI/вручную (нужен SDK) —
здесь юнит-уровень."""

import io
import json
import shutil
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

def test_steam_preflight_is_useful_without_appid(repo_root):
    """Главный сценарий: приложения у Valve ещё нет. Пустой App ID обязан быть
    пунктом TODO, а не провалом — иначе команда бесполезна ровно тогда, когда
    она нужнее всего, и владелец не узнает, что остальное готово."""
    from vn.release import steam_preflight

    checks = steam_preflight(repo_root, "public")
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
