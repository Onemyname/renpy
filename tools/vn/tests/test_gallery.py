"""Галерея (gallery@1, ADR-0010): валидация деклараций, состав реестра и логика
разблокировки стора vn_gal.

Стор — блок `init python in vn_gal` в .rpy, но его тело это обычный Python: тесты
исполняют его с подставным persistent/renpy (_store_module) и проверяют РЕШЕНИЯ,
а не наличие строк. Полный путь «показ кадра -> persistent -> галерея» всё равно
проверяется e2e: vn test smoke пишет .vncache/smoke/gallery.json с фактическими
разблокировками.
"""

import ast
import shutil
import sys
import textwrap
import types

import pytest

from vn.content.compile import CompileError, _emit_gallery, compile_content
from vn.repo import load_yaml
from vn.schemas import SchemaRegistry

from conftest import REPO_ROOT


class _Rep:
    """Заглушка CompileResult: нужны только warnings."""

    def __init__(self):
        self.warnings = []


def _mk_assets(root, *rel_paths):
    # Пустышки пишутся ТОЛЬКО в tmp_path: перепутанный корень затирал бы собранную
    # зону разработчика однобайтовыми файлами, а сборка молча брала бы их из кэша.
    assert root != REPO_ROOT, "фикстура пишет в game/assets репозитория"
    for rel in rel_paths:
        p = root / "game" / "assets" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")


def _doc(items, categories=None):
    return [("content/gallery/t.gallery.yaml", {
        "schema": "gallery@1",
        "categories": categories or {"cg": {"title_key": "ui.gallery.cat.cg"}},
        "items": items,
    })]


# Декларация послойного шота сцены (shots@1): тот же документ, что в test_shots.
SHOTS_DOCS = [("ch01", "content/chapters/ch01_x/shots/s030.shots.yaml", {
    "schema": "shots@1",
    "scene": "s030",
    "shots": {"sunset": {
        "layers": {"env": {},
                   "mira": {"variants": ["school", "casual"], "var": "g.mira_outfit"}},
        "order": ["env", "mira"],
    }},
})]


def _shot_item(**over):
    item = {"category": "cg", "kind": "shot", "asset": "shots/ch01/s030/sunset",
            "title_key": "gal.shot.title", "unlock": {"seen_image": True}}
    item.update(over)
    return {"shot_sunset": item}


def test_registry_shape_and_thumb_resolution(tmp_path):
    root = tmp_path
    _mk_assets(root, "cg/ch01/a.webp", "cg/ch01/a.thumb.webp", "cg/ch01/b.webp")
    rep, errors = _Rep(), []
    text = _emit_gallery(root, _doc({
        "cg_a": {"category": "cg", "kind": "image", "asset": "cg/ch01/a",
                 "variants": ["cg/ch01/b"], "title_key": "gal.a.title",
                 "unlock": {"seen_image": True}},
    }), {"ch01_s010"}, {"ch01"}, {"g.route"}, {}, rep, errors, [("t", "d")])
    assert errors == []
    assert "define VN_GALLERY_CATEGORIES" in text
    # превью взято из конвейера, а не полноразмерный кадр
    assert "'thumb': 'assets/cg/ch01/a.thumb.webp'" in text
    assert "'image_name': 'cg ch01 a'" in text          # для renpy.seen_image
    assert "'variants': ['assets/cg/ch01/b.webp']" in text


def test_shot_item_addresses_image_name_not_file(tmp_path):
    """kind: shot адресует ШОТ: файла у него нет, в реестр едут имя образа
    (тег сцены + атрибут) и переключаемые варианты слоёв из shots@1."""
    root = tmp_path
    _mk_assets(root, "shots/ch01/s030/sunset.thumb.webp",
               "shots/ch01/s030/sunset/env.webp")
    rep, errors = _Rep(), []
    text = _emit_gallery(root, _doc(_shot_item()), {"ch01_s030"}, {"ch01"}, set(), {},
                         rep, errors, [("t", "d")], shots_docs=SHOTS_DOCS)
    assert errors == []
    assert "'asset': 'shot_ch01_s030 sunset'" in text
    assert "'image_name': 'shot_ch01_s030 sunset'" in text
    # Первый вид — как в игре (auto по переменной гардероба), дальше явные варианты
    assert ("'shot_layers': [{'layer': 'mira', 'options': "
            "['mira_auto', 'mira_school', 'mira_casual']}]") in text
    # Превью — композит конвейера рядом с папкой слоёв
    assert "'thumb': 'assets/shots/ch01/s030/sunset.thumb.webp'" in text
    assert not rep.warnings


def test_shot_item_requires_declared_shot(tmp_path):
    root = tmp_path
    _mk_assets(root, "cg/ch01/a.webp")
    rep, errors = _Rep(), []
    _emit_gallery(root, _doc(_shot_item(asset="shots/ch01/s030/ghost")), set(), set(),
                  set(), {}, rep, errors, [("t", "d")], shots_docs=SHOTS_DOCS)
    assert any("shots/ch01/s030/ghost" in e and "нет в декларациях shots@1" in e
               for e in errors)


def test_shot_kind_and_reference_must_agree(tmp_path):
    """Плоский ассет под kind: shot и шот под kind: image — обе ошибки сборки."""
    root = tmp_path
    _mk_assets(root, "cg/ch01/a.webp", "cg/ch01/a.thumb.webp")
    rep, errors = _Rep(), []
    items = _shot_item(asset="cg/ch01/a")
    items["img_shot"] = {"category": "cg", "kind": "image",
                         "asset": "shots/ch01/s030/sunset",
                         "title_key": "t", "unlock": {"seen_image": True}}
    _emit_gallery(root, _doc(items), set(), set(), set(), {}, rep, errors,
                  [("t", "d")], shots_docs=SHOTS_DOCS)
    text = "\n".join(errors)
    assert "kind: shot, но ассет cg/ch01/a — не шот" in text
    assert "послойный шот, а kind: image" in text


def test_shot_item_rejects_flat_variants(tmp_path):
    """Варианты слоёв объявлены в shots@1 — второй список в галерее был бы
    вторым источником правды."""
    root = tmp_path
    _mk_assets(root, "shots/ch01/s030/sunset.thumb.webp", "cg/ch01/b.webp")
    rep, errors = _Rep(), []
    _emit_gallery(root, _doc(_shot_item(variants=["cg/ch01/b"])), set(), set(), set(),
                  {}, rep, errors, [("t", "d")], shots_docs=SHOTS_DOCS)
    assert any("variants у kind: shot не бывает" in e for e in errors)


def test_shot_without_composite_thumb_warns(tmp_path):
    """Нет композитного превью — не ошибка, но сетка потянет весь шот."""
    root = tmp_path
    _mk_assets(root, "shots/ch01/s030/sunset/env.webp")
    rep, errors = _Rep(), []
    text = _emit_gallery(root, _doc(_shot_item()), set(), set(), set(), {}, rep,
                         errors, [("t", "d")], shots_docs=SHOTS_DOCS)
    assert errors == []
    assert any("shot_thumb" in w for w in rep.warnings)
    # Заглушки в реестре нет: сетка возьмёт живой кадр (asset), а не битый путь
    assert "'thumb': None" in text


def test_renamed_shot_keeps_unlock_history(tmp_path):
    """Переименование шота не должно стирать открытый кадр: исторические имена
    образа считаются наравне, как у плоских ассетов (ADR-0012)."""
    root = tmp_path
    _mk_assets(root, "shots/ch01/s030/sunset.thumb.webp")
    rep, errors = _Rep(), []
    renames = {"assets": {"shots/ch01/s030/dusk": "shots/ch01/s030/sunset",
                          # переименование СЛОЯ галереи не касается — оно не шот
                          "shots/ch01/s030/sunset/mira__old": "shots/ch01/s030/sunset/mira__school"}}
    text = _emit_gallery(root, _doc(_shot_item()), set(), set(), set(), {}, rep,
                         errors, [("t", "d")], renames=renames, shots_docs=SHOTS_DOCS)
    assert errors == []
    assert "'image_name_history': ['shot_ch01_s030 dusk']" in text


def test_missing_asset_is_error(tmp_path):
    # Строгая проверка включается только при собранной зоне ассетов
    (tmp_path / "game" / "assets").mkdir(parents=True)
    rep, errors = _Rep(), []
    _emit_gallery(tmp_path, _doc({
        "cg_a": {"category": "cg", "kind": "image", "asset": "cg/ch01/ghost",
                 "title_key": "t", "unlock": {"always": True}},
    }), set(), set(), set(), {}, rep, errors, [("t", "d")])
    assert any("нет в game/assets" in e for e in errors)


def test_unknown_category_and_bad_kind(tmp_path):
    root = tmp_path
    _mk_assets(root, "mov/demo/x.webm", "cg/ch01/a.webp")
    rep, errors = _Rep(), []
    _emit_gallery(root, _doc({
        "bad_cat": {"category": "nope", "kind": "image", "asset": "cg/ch01/a",
                    "title_key": "t", "unlock": {"always": True}},
        "bad_kind": {"category": "cg", "kind": "image", "asset": "mov/demo/x",
                     "title_key": "t", "unlock": {"always": True}},
    }), set(), set(), set(), {}, rep, errors, [("t", "d")])
    text = "\n".join(errors)
    assert "категория 'nope' не объявлена" in text
    assert "kind: image, но ассет mov/demo/x — видео" in text


def test_unlock_anchor_must_exist(tmp_path):
    root = tmp_path
    _mk_assets(root, "cg/ch01/a.webp")
    rep, errors = _Rep(), []
    _emit_gallery(root, _doc({
        "s": {"category": "cg", "kind": "image", "asset": "cg/ch01/a",
              "title_key": "t", "unlock": {"scene": "ch09_s999"}},
        "c": {"category": "cg", "kind": "image", "asset": "cg/ch01/a",
              "title_key": "t", "unlock": {"chapter_done": "ch77"}},
        "v": {"category": "cg", "kind": "image", "asset": "cg/ch01/a",
              "title_key": "t", "unlock": {"var": "g.ghost"}},
    }), {"ch01_s010"}, {"ch01"}, {"g.route"}, {}, rep, errors, [("t", "d")])
    text = "\n".join(errors)
    assert "unlock.scene ch09_s999" in text
    assert "unlock.chapter_done ch77" in text
    assert "unlock.var g.ghost" in text


def test_seen_image_is_rejected_for_movies(tmp_path):
    """Показ образа движок пишет в _seen_images, проигрывание Movie — нет."""
    root = tmp_path
    _mk_assets(root, "mov/demo/x.webm", "cg/ch01/p.webp")
    rep, errors = _Rep(), []
    _emit_gallery(root, _doc({
        "m": {"category": "cg", "kind": "movie", "asset": "mov/demo/x",
              "thumb": "cg/ch01/p", "title_key": "t",
              "unlock": {"seen_image": True}},
    }), set(), set(), set(), {}, rep, errors, [("t", "d")])
    assert any("seen_image не работает для kind: movie" in e for e in errors)


def test_warnings_for_missing_thumb_and_orphan_cg(tmp_path):
    root = tmp_path
    # CG без thumb-варианта + осиротевший CG + видео без постер-кадра
    _mk_assets(root, "cg/ch01/a.webp", "cg/ch01/orphan.webp", "mov/demo/x.webm")
    rep, errors = _Rep(), []
    _emit_gallery(root, _doc({
        "cg_a": {"category": "cg", "kind": "image", "asset": "cg/ch01/a",
                 "title_key": "t", "unlock": {"always": True}},
        "mov_x": {"category": "cg", "kind": "movie", "asset": "mov/demo/x",
                  "title_key": "t", "unlock": {"always": True}},
    }), set(), set(), set(), {}, rep, errors, [("t", "d")])
    assert errors == []
    text = "\n".join(rep.warnings)
    assert "нет превью" in text                     # картинка без thumb
    assert "нет постер-кадра" in text                # видео без постера
    assert "cg/ch01/orphan" in text and "не объявлен в галерее" in text


def test_movie_thumb_falls_back_to_poster(tmp_path):
    """Постер-кадр конвейер делает сам (ADR-0012): ручной thumb у видео больше
    не обязателен, и предупреждения быть не должно."""
    root = tmp_path
    _mk_assets(root, "mov/demo/x.webm", "mov/demo/x.poster.webp")
    rep, errors = _Rep(), []
    rows = _emit_gallery(root, _doc({
        "mov_x": {"category": "cg", "kind": "movie", "asset": "mov/demo/x",
                  "title_key": "t", "unlock": {"always": True}},
    }), set(), set(), set(), {}, rep, errors, [("t", "d")])
    assert errors == []
    assert not any("постер" in w for w in rep.warnings)
    assert "assets/mov/demo/x.poster.webp" in rows


def test_duplicate_ids_across_files_are_error(tmp_path):
    root = tmp_path
    _mk_assets(root, "cg/ch01/a.webp")
    docs = _doc({"dup": {"category": "cg", "kind": "image", "asset": "cg/ch01/a",
                         "title_key": "t", "unlock": {"always": True}}})
    docs.append(("content/gallery/other.gallery.yaml", {
        "schema": "gallery@1", "categories": {},
        "items": {"dup": {"category": "cg", "kind": "image", "asset": "cg/ch01/a",
                          "title_key": "t", "unlock": {"always": True}}}}))
    rep, errors = _Rep(), []
    _emit_gallery(root, docs, set(), set(), set(), {}, rep, errors, [("t", "d")])
    assert any("объявлен дважды" in e for e in errors)


def test_repo_gallery_declarations_are_schema_valid(repo_root):
    """Боевые декларации проекта валидны и все их строки объявлены. Файлов может
    быть несколько (реестр собирается из всех content/gallery/*.gallery.yaml),
    поэтому проверяются все — иначе новый файл проехал бы мимо теста."""
    reg = SchemaRegistry(repo_root / "tools" / "schemas")
    strings = load_yaml(repo_root / "content" / "ui" / "strings.yaml")["strings"]
    files = sorted((repo_root / "content" / "gallery").glob("*.gallery.yaml"))
    assert files, "боевой декларации галереи нет"
    for f in files:
        rel = f"content/gallery/{f.name}"
        doc = load_yaml(f)
        assert reg.validate(doc, rel) == []
        for cid, cspec in (doc.get("categories") or {}).items():
            assert cspec["title_key"] in strings, f"{rel}: категория {cid}: нет строки"
        for gid, spec in (doc.get("items") or {}).items():
            assert spec["title_key"] in strings, f"{rel}: {gid}: нет title_key"
            if spec.get("desc_key"):
                assert spec["desc_key"] in strings, f"{rel}: {gid}: нет desc_key"


def test_repo_compiles_gallery_registry(repo_root, tmp_path):
    """Сквозная компиляция реального проекта эмитит реестр галереи."""
    import os

    sdk = os.environ.get("RENPY_SDK")
    if not (sdk and (REPO_ROOT / "game").is_dir()):
        pytest.skip("нужен RENPY_SDK для компиляции сцен")
    gen = tmp_path / "generated"
    compile_content(repo_root, out_dir=gen)
    text = (gen / "registry" / "gallery.gen.rpy").read_text(encoding="utf-8")
    assert "define VN_GALLERY = {" in text
    assert "cg_ch01_rooftop" in text
    # locked-элемент тоже в реестре: закрытость — состояние, а не отсутствие записи
    assert "cg_ch01_route_mira" in text
    # Послойный шот демо-главы доехал живым образом, а не путём к файлу
    assert "'asset': 'shot_ch01_s030 sunset'" in text
    assert "'mira_auto', 'mira_school', 'mira_casual'" in text


def test_unbuilt_assets_zone_warns_not_errors(tmp_path):
    """vn content compile без предшествующей сборки — легитимное состояние:
    ссылки не проверяются, но об этом честно предупреждают (зона G4 производная)."""
    rep, errors = _Rep(), []
    _emit_gallery(tmp_path, _doc({
        "cg_a": {"category": "cg", "kind": "image", "asset": "cg/ch01/ghost",
                 "title_key": "t", "unlock": {"always": True}},
    }), set(), set(), set(), {}, rep, errors, [("t", "d")])
    assert errors == []
    assert any("game/assets не собран" in w for w in rep.warnings)


def test_renamed_asset_keeps_unlock_history(tmp_path):
    """Переименование CG после релиза не должно стирать игроку открытый кадр:
    галерея открывает картинки по ИМЕНИ образа (persistent._seen_images), поэтому
    исторические имена обязаны попадать в реестр (ADR-0012)."""
    root = tmp_path
    _mk_assets(root, "cg/ch01/kiss_final.webp", "cg/ch01/kiss_final.thumb.webp")
    rep, errors = _Rep(), []
    renames = {"assets": {"cg/ch01/kiss": "cg/ch01/kiss_v2",
                          "cg/ch01/kiss_v2": "cg/ch01/kiss_final"}}
    text = _emit_gallery(root, _doc({
        "cg_kiss": {"category": "cg", "kind": "image", "asset": "cg/ch01/kiss_final",
                    "title_key": "t", "unlock": {"seen_image": True}},
    }), set(), set(), set(), {}, rep, errors, [("t", "d")], renames=renames)
    assert errors == []
    # Цепочка переименований разворачивается до конечного id
    assert "'image_name_history': ['cg ch01 kiss', 'cg ch01 kiss_v2']" in text


def test_asset_history_is_empty_without_renames(tmp_path):
    root = tmp_path
    _mk_assets(root, "cg/ch01/a.webp", "cg/ch01/a.thumb.webp")
    rep, errors = _Rep(), []
    text = _emit_gallery(root, _doc({
        "cg_a": {"category": "cg", "kind": "image", "asset": "cg/ch01/a",
                 "title_key": "t", "unlock": {"seen_image": True}},
    }), set(), set(), set(), {}, rep, errors, [("t", "d")])
    assert "'image_name_history': []" in text


# ── Рантайм-стор vn_gal: решения разблокировки и виды кадра ──────────────────

STORE_REL = "game/framework/00_core/090_gallery.rpy"


def _store_module(repo_root, registry, seen_images=None, unlocked=None):
    """Стор vn_gal, исполненный без движка: тело `init python in vn_gal` — обычный
    Python, а его внешний мир это persistent, renpy.seen_image и реестр паков.
    Подставляем ровно их и получаем настоящие функции, а не их пересказ."""
    tail = (repo_root / STORE_REL).read_text(encoding="utf-8") \
        .partition("python in vn_gal:")[2]
    assert tail, f"{STORE_REL}: блок `python in vn_gal:` не найден"
    body = []
    for line in tail.splitlines():
        if line.strip() and not line.startswith("    "):
            break                     # блок кончился (default persistent.… и т. п.)
        body.append(line)

    persistent = types.SimpleNamespace(
        vn_gallery_unlocked=dict(unlocked or {}),
        _seen_images=dict(seen_images or {}))
    renpy_store = types.SimpleNamespace(
        VN_GALLERY=registry,
        VN_GALLERY_CATEGORIES={"cg": {"title_key": "k", "order": 10, "nsfw": False}},
        vn=types.SimpleNamespace(
            pack_registry=types.SimpleNamespace(owned=lambda pack: True)))
    # store — рантайм-модуль движка, из которого стор берёт себе окружение.
    fake_store = types.ModuleType("store")
    fake_store.persistent = persistent
    fake_store.renpy = types.SimpleNamespace(
        store=renpy_store,
        # Движковый seen_image — СТРОГОЕ сравнение кортежа имени
        # (SDK renpy/exports/persistentexports.py): повторяем дословно.
        seen_image=lambda name: tuple(name.split()) in persistent._seen_images)
    fake_store.vn_log = lambda msg: None
    ns = {}
    sys.modules["store"] = fake_store
    try:
        exec(compile(textwrap.dedent("\n".join(body)), STORE_REL, "exec"), ns)
    finally:
        del sys.modules["store"]
    return types.SimpleNamespace(**ns)


def _registry_from(tmp_path, items, shots_docs=None):
    """Реестр так, как его собирает компилятор: тесты стора не выдумывают форму
    записи, иначе они разъехались бы с эмиттером и ничего не проверяли."""
    _mk_assets(tmp_path, "cg/ch01/a.webp", "cg/ch01/a.thumb.webp", "cg/ch01/b.webp",
               "shots/ch01/s030/sunset.thumb.webp")
    rep, errors = _Rep(), []
    text = _emit_gallery(tmp_path, _doc(items), set(), set(), set(), {}, rep, errors,
                         [("t", "d")], shots_docs=shots_docs)
    assert errors == []
    return ast.literal_eval(text.split("define VN_GALLERY = ", 1)[1])


def test_store_unlocks_shot_by_tag_and_attribute(repo_root, tmp_path):
    """Липкие атрибуты слоёв доезжают в _seen_images вместе с именем шота, и их
    порядок произволен — поэтому шот засчитывается по тегу+атрибуту, а не целым
    кортежем. Проверяем оба конца: свой шот открыт, чужой — нет."""
    registry = _registry_from(tmp_path, _shot_item(), SHOTS_DOCS)
    seen = {("shot_ch01_s030", "sunset", "mira_casual"): True}
    gal = _store_module(repo_root, registry, seen_images=seen)
    assert gal.is_unlocked("shot_sunset") is True

    other = {("shot_ch01_s030", "dawn", "mira_casual"): True}
    gal2 = _store_module(repo_root, registry, seen_images=other)
    assert gal2.is_unlocked("shot_sunset") is False


def test_gallery_screen_keeps_ui_state_out_of_saves(repo_root):
    """Вкладка и зум — состояние ЭКРАНА. Любой изменённый store-`default` движок
    кладёт в ever_been_changed, то есть в КАЖДЫЙ сейв и в rollback-лог (SDK
    rollback.py: freeze/roots): вкладка галереи ехала в сейв игрока, возвращалась
    из него при загрузке, а откат за вход в меню её сбрасывал. Префикс «_» от
    этого не спасает — фильтра по нему в roots нет."""
    screen = (repo_root / "game" / "framework" / "20_ui" / "screens"
              / "gallery.rpy").read_text(encoding="utf-8")
    store_defaults = [ln for ln in screen.splitlines() if ln.startswith("default ")]
    assert store_defaults == [], \
        f"состояние экрана объявлено store-default (уедет в сейв): {store_defaults}"
    assert "default category = None" in screen and "default zoom = False" in screen


def test_store_unlocks_shot_with_several_attributes(repo_root, tmp_path):
    """Имя шота из двух и более атрибутов: свои атрибуты обязаны найтись ВСЕ, а
    липкие от предыдущего кадра и произвольный их порядок не мешают. Сверка по
    склеенной строке («sunset rain» одним атрибутом) не совпала бы никогда — такой
    элемент навсегда остался бы «Закрыто» у игрока, который кадр видел. Генерат
    сегодня такое имя не даёт (ссылка шота без пробелов), поэтому имя ставится в
    реестр прямо: тест страхует стор от расширения схемы."""
    registry = _registry_from(tmp_path, _shot_item(), SHOTS_DOCS)
    registry["shot_sunset"]["image_name"] = "shot_ch01_s030 sunset rain"
    gal = _store_module(repo_root, registry, seen_images={
        ("shot_ch01_s030", "rain", "mira_casual", "sunset"): True})
    assert gal.is_unlocked("shot_sunset") is True

    # Один из своих атрибутов не показан — элемент закрыт.
    gal2 = _store_module(repo_root, registry,
                         seen_images={("shot_ch01_s030", "sunset"): True})
    assert gal2.is_unlocked("shot_sunset") is False


def test_store_shot_unlock_accepts_historical_name(repo_root, tmp_path):
    registry = _registry_from(tmp_path, _shot_item(), SHOTS_DOCS)
    registry["shot_sunset"]["image_name_history"] = ["shot_ch01_s030 dusk"]
    gal = _store_module(repo_root, registry,
                        seen_images={("shot_ch01_s030", "dusk"): True})
    assert gal.is_unlocked("shot_sunset") is True


def test_store_flat_image_still_needs_exact_name(repo_root, tmp_path):
    """Регрессия: у плоского ассета имя образа сравнивается целиком — иначе
    «cg ch01 a» открывался бы показом любого другого cg ch01."""
    registry = _registry_from(tmp_path, {
        "cg_a": {"category": "cg", "kind": "image", "asset": "cg/ch01/a",
                 "title_key": "t", "unlock": {"seen_image": True}}})
    gal = _store_module(repo_root, registry,
                        seen_images={("cg", "ch01", "b"): True})
    assert gal.is_unlocked("cg_a") is False
    gal2 = _store_module(repo_root, registry,
                         seen_images={("cg", "ch01", "a"): True})
    assert gal2.is_unlocked("cg_a") is True


def test_store_looks_walk_layer_variants(repo_root, tmp_path):
    """Виды кадра шота: одометр по слоям, первый вид — как в игре (auto)."""
    registry = _registry_from(tmp_path, _shot_item(), SHOTS_DOCS)
    gal = _store_module(repo_root, registry)
    assert gal.looks(registry["shot_sunset"]) == [
        "shot_ch01_s030 sunset mira_auto",
        "shot_ch01_s030 sunset mira_school",
        "shot_ch01_s030 sunset mira_casual",
    ]
    # Два вариативных слоя: разряды младше — выше по z-порядку
    two = dict(registry["shot_sunset"], shot_layers=[
        {"layer": "env", "options": ["env_day", "env_night"]},
        {"layer": "mira", "options": ["mira_school", "mira_casual"]}])
    assert gal.looks(two) == [
        "shot_ch01_s030 sunset env_day mira_school",
        "shot_ch01_s030 sunset env_day mira_casual",
        "shot_ch01_s030 sunset env_night mira_school",
        "shot_ch01_s030 sunset env_night mira_casual",
    ]


def test_store_looks_of_flat_item_are_asset_and_variants(repo_root, tmp_path):
    registry = _registry_from(tmp_path, {
        "cg_a": {"category": "cg", "kind": "image", "asset": "cg/ch01/a",
                 "variants": ["cg/ch01/b"], "title_key": "t",
                 "unlock": {"always": True}}})
    gal = _store_module(repo_root, registry)
    assert gal.looks(registry["cg_a"]) == ["assets/cg/ch01/a.webp",
                                           "assets/cg/ch01/b.webp"]


def test_gallery_hot_path_does_not_scan_all_seen_images(repo_root):
    """Горячий путь галереи не имеет права быть линейным по |_seen_images|.

    _seen_shot обходил весь словарь показанных кадров, а ранний выход там есть
    только при ПОПАДАНИИ — то есть для закрытого шота (а закрытым он остаётся
    почти всю игру) цена равна размеру словаря. Множитель двойной: is_unlocked
    зовётся из vn_gal.check на каждом якоре сцены и из экрана по ~2 раза на
    элемент при каждой сборке, а SL2 пересобирает экран на каждой интеракции —
    на каждом движении мыши по сетке. Размер _seen_images растёт не по числу
    файлов, а по числу комбинаций атрибутов: у layeredimage это резолвнутый
    набор всех слоёв, то есть десятки тысяч ключей на целевом масштабе.

    Замер класса (алгоритм, 800 вызовов = одна сборка экрана на 400 элементах):
    12000 ключей — 387 мс линейным сканом против 0.23 мс по индексу."""
    src = (repo_root / "game" / "framework" / "00_core"
           / "090_gallery.rpy").read_text(encoding="utf-8")

    shot = src.split("def _seen_shot(", 1)[1].split("\n    def ", 1)[0]
    assert "_seen_index()" in shot, "_seen_shot не пользуется индексом по тегу"
    # Только КОД: докстринг про _seen_images объясняет механику и остаётся.
    shot_code = shot.split('"""', 2)[-1]
    assert "_seen_images" not in shot_code, \
        "_seen_shot снова читает весь словарь показанных кадров"

    index = src.split("def _seen_index(", 1)[1].split("\n    def ", 1)[0]
    assert "len(seen)" in index, "индекс не инвалидируется по размеру _seen_images"

    unlocked = src.split("def is_unlocked(", 1)[1].split("\n    def ", 1)[0]
    # Кэш живёт атрибутом объекта, созданного на init, а не именем стора: имя,
    # переприсвоенное в рантайме, становится корнем сейва навсегда — см.
    # test_saves::test_no_store_name_is_reassigned_at_runtime.
    assert "_cache.unlocked" in unlocked, "повторный опрос движка не кэшируется"


def test_gallery_screen_walks_the_registry_once_per_build(repo_root):
    """Экран пересчитывал производные заново на каждой сборке: categories()
    (внутри items() на категорию), progress() по всем, progress(cid) в цикле по
    вкладкам, items(_cur) и is_unlocked в каждой ячейке. Это ~(2·Nкатегорий + 2)
    обходов реестра и ~2N вызовов is_unlocked на КАЖДЫЙ кадр сетки."""
    src = (repo_root / "game" / "framework" / "20_ui" / "screens"
           / "gallery.rpy").read_text(encoding="utf-8")
    body = src.split("screen gallery():", 1)[1].split("\nscreen ", 1)[0]

    assert body.count("vn_gal.overview()") == 1, "общий проход зовётся не один раз"
    for banned in ("vn_gal.progress(", "vn_gal.items(", "vn_gal.categories("):
        assert banned not in body, f"{banned} снова обходит реестр внутри экрана"

    cell = src.split("screen vn_gal_cell(", 1)[1].split("\nscreen ", 1)[0]
    assert "is_open" in cell, "ячейка снова спрашивает состояние сама"


def test_pack_ownership_is_memoized(repo_root):
    """owned() зовётся из visible() каждого элемента галереи и каждой ачивки, то
    есть на каждом якоре сцены и на каждой сборке экрана. Под Steam это
    steam.dlc_installed() — FFI-вызов; без кэша выходили тысячи вызовов на кадр.

    Кэш безопасен: владение DLC без перезапуска Steam не меняется, а провайдер и
    так подключается один раз на init 999."""
    src = (repo_root / "game" / "framework" / "00_core"
           / "030_flow.rpy").read_text(encoding="utf-8")
    owned = src.split("def owned(self, pack_id):", 1)[1].split("\n    def ", 1)[0]
    assert "_owned_cache" in owned, "владение паком спрашивается у платформы каждый раз"
    setter = src.split("def set_ownership_provider(", 1)[1].split("\n        def ", 1)[0]
    assert "_owned_cache" in setter, "смена провайдера не сбрасывает кэш"
