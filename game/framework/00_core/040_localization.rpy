# Локализация (раздел 5, ADR-0005): Language Registry + текстовые lookup'и.
#
# vn_lang — ЕДИНСТВЕННЫЙ источник знания о языках в рантайме: какие есть
# (renpy.known_languages + манифесты tl/*/language.json), какой текущий, как
# переключить, кого уведомить. Списка языков в коде/конфиге нет: язык, чей
# пакет доехал до game/tl/ (в т.ч. внутри .rpa DLC-пака или каталогом
# пользовательского перевода), появляется в настройках сам.
#
# vn_loc — lookup UI/мета-строк и пунктов меню по стабильным id (G8/C1):
# НЕ translate strings — коллизии одинаковых текстов («Да»/«Нет») между
# сценами неизбежны. Горячая смена языка: renpy.change_language перезапускает
# интеракцию и экраны переоцениваются — обе функции читают текущий язык на
# каждом вызове, кеша переводов нет.

init -995 python in vn_lang:
    from store import renpy, vn_log
    import json as _json

    # Подписчики смены языка. Единая точка — движковый config.language_callbacks
    # (per-language; refresh() регистрирует _notify на КАЖДЫЙ обнаруженный язык):
    # срабатывает при ЛЮБОМ пути смены (экран настроек, автопилот, код) — пути
    # «мимо реестра» не существует. ВАЖНО: config.change_language_callbacks в
    # Ren'Py 8.5 — мёртвый список («Removed.» в config.py), движок его не зовёт.
    _subscribers = []

    # Кеш пакетов: [{code, name, font, synthetic}]. Наполняется refresh()
    # на init 999 (когда загружены все tl, включая .rpa паков) и далее
    # не мутирует — в rollback-лог не попадает.
    _languages = []

    def _source():
        src = getattr(renpy.store, "VN_SOURCE_LANG", None) or {}
        return {"code": src.get("code", "source"), "name": src.get("name", "Source"),
                "font": None, "synthetic": False}

    def _manifest(code):
        fn = "tl/%s/language.json" % code
        if not renpy.loadable(fn):
            return {}
        try:
            with renpy.open_file(fn) as f:
                return _json.load(f)
        except Exception as e:
            vn_log("vn_lang: битый манифест %s: %s" % (fn, e))
            return {}

    def _hook(renpy_lang):
        """Регистрация _notify на язык в движке (идемпотентно)."""
        cbs = renpy.config.language_callbacks[renpy_lang]
        if _notify not in cbs:
            cbs.append(_notify)

    def refresh():
        """Пересканировать языки. known_languages — источник существования
        (перевод без манифеста работает и виден под своим кодом),
        манифест language.json — источник метаданных (native-название, шрифт)."""
        found = []
        _hook(None)    # исходный язык (в движке — None)
        for code in sorted(renpy.known_languages()):
            _hook(code)
            mf = _manifest(code)
            found.append({
                "code": code,
                "name": mf.get("name") or code,
                "font": mf.get("font"),
                "synthetic": bool(mf.get("synthetic")),
            })
        found.sort(key=lambda l: l["name"].casefold())
        _languages[:] = [_source()] + found
        # Висячий выбор: язык из преференсов удалили/переименовали — без сброса
        # игра молча играет на исходном, а в списке настроек ничего не выбрано.
        pref = renpy.game.preferences.language
        if pref is not None and pref not in {l["code"] for l in found}:
            vn_log("vn_lang: сохранённый язык %r исчез — сброс на исходный" % pref)
            renpy.game.preferences.language = None
        return list(_languages)

    def available(include_synthetic=None):
        """Языки для UI: исходный первым, дальше по алфавиту native-названий.
        synthetic (pseudo) по умолчанию виден только разработчику."""
        if include_synthetic is None:
            include_synthetic = renpy.store.config.developer
        return [l for l in _languages if include_synthetic or not l["synthetic"]]

    def current():
        """Код текущего языка (код исходного, если перевод не выбран)."""
        return renpy.game.preferences.language or _source()["code"]

    def display_name(code=None):
        code = code or current()
        for l in _languages:
            if l["code"] == code:
                return l["name"]
        return code

    def renpy_code(code):
        """Код реестра -> язык движка (исходный язык в Ren'Py — None)."""
        return None if code == _source()["code"] else code

    def set(code):
        """Программная смена языка: применяется сразу (ретрансляция + перезапуск
        интеракции), выбор движок сам сохраняет в persistent-преференсы."""
        renpy.change_language(renpy_code(code))

    def action(code):
        """Screen action смены языка (кнопки настроек): штатный Language() движка —
        кнопка получает selected-состояние и persistence бесплатно."""
        return renpy.store.Language(renpy_code(code))

    def subscribe(fn):
        """Подписка на смену языка: fn(code). Экранам НЕ нужна (переоцениваются
        сами) — для систем с языкозависимым состоянием (озвучка, атласы шрифтов).
        Уведомление приходит и при старте/полном рестарте игры (движок прогоняет
        translate-хуки принудительно) — подписчики обязаны быть идемпотентны."""
        _subscribers.append(fn)

    def unsubscribe(fn):
        if fn in _subscribers:
            _subscribers.remove(fn)

    def _notify():
        code = current()
        vn_log("language -> %s" % code)
        for fn in list(_subscribers):
            try:
                fn(code)
            except Exception as e:
                vn_log("vn_lang: подписчик %r упал: %s" % (fn, e))


init 999 python:
    # Скан ПОСЛЕ загрузки всего скрипта: к этому моменту зарегистрированы все
    # translate-блоки (включая приехавшие в .rpa паков) и читаемы все манифесты.
    vn_lang.refresh()


init -995 python in vn_loc:
    from store import renpy

    def _lang():
        return renpy.game.preferences.language

    def choice_text(menu_id, idx, caption):
        """Перевод пункта (menu_id, idx) по VN_MENUS_TL (наполняется tl/<lang>/common.rpy).
        Исходный язык / нет перевода -> авторский caption."""
        tl = getattr(renpy.store, "VN_MENUS_TL", {}).get(_lang())
        if tl and menu_id in tl and idx < len(tl[menu_id]):
            return tl[menu_id][idx]
        return caption

    def t(key):
        """UI/мета-строка по ключу (content/ui/strings.yaml): исходник или перевод."""
        source = getattr(renpy.store, "VN_STRINGS", {}).get(key, key)
        tl = getattr(renpy.store, "VN_STRINGS_TL", {}).get(_lang())
        if tl and key in tl:
            return tl[key]
        return source
