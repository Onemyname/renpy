# Тонкий options.rpy (раздел 1.2): почти всё вынесено в framework/00_core.
# config.version НЕ задаётся здесь — его эмитит generated/version.gen.rpy из project.yaml.

# Имя игры — бренд-константа (заголовок окна ОС): сознательно НЕ переводится.
# Захочется переводить — через translate strings, define вычисляется один раз.
define config.name = "VN"
define config.save_directory = "vn-1755000000"   # НЕ переименовывать: потеря сейвов (ci/steam/README.md)
define config.has_autosave = True
define config.autosave_slots = 10
define config.window_icon = None

# Controller-first окружения (Steam Deck / Big Picture): игрок без мыши не
# должен искать переключатель «Полный экран» — первый запуск сразу фуллскрин.
# На десктопе дефолт НЕ трогаем (None = движковый: оконный, выбор сохраняется).
init python:
    if vn_platform.controller_first():
        config.default_fullscreen = True

# ── Сборка дистрибутивов (vn package -> launcher distribute) ─────────────────
init python:
    build.name = "vn"
    # Подписные ключи Android (android.keystore / bundle.keystore, лаунчер:
    # Android -> Generate Keys). Движок исключает их ТОЛЬКО в корне проекта
    # (00build.rpy: early_base_patterns, `("*.keystore", None)`; `*` не переходит
    # через «/»), а положенный не туда файл — например, в game/ — попал бы под
    # общее `("**", "all")` и уехал игрокам в каждом пакете. Утечка ключа = чужие
    # сборки под нашей подписью, потеря = невозможность обновить опубликованное
    # приложение, поэтому запрет распространяется на все подкаталоги и не зависит
    # от того, собираем ли мы сегодня Android. Что ключи не уедут ещё и в git —
    # проверяет vn android preflight (tools/vn/src/vn/android.py).
    build.classify("**.keystore", None)
    # Осиротевший .rpyc движок НЕ удаляет, а ПЕРЕИМЕНОВЫВАЕТ в <имя>.rpyc.bak
    # (renpy/script.py: clean_script_files -> os.rename(name, name + ".bak")), и
    # делает это ровно на команде `compile`, которую третьим шагом исполняет
    # `vn package`. Шаблона *.bak нет ни в early_base_patterns, ни в
    # late_base_patterns движка (00build.rpy), а последний паттерн там всеядный —
    # ("**", "all"). То есть скомпилированный скрипт УДАЛЁННОГО контента уезжал
    # игроку в каждом пакете и в каждом следующем релизе, потому что удалять .bak
    # нечему: и линия .rpyc (G6), и бюджет rpyc_total_kb ходят по glob("*.rpyc").
    # Для 18+ проекта это выдача дата-майнеру вырезанного контента (unrpyc —
    # публичный инструмент) — ровно то, от чего защищается запрет зон ниже.
    # Запрет по тем же соображениям, что у keystore: он не зависит от того, есть
    # ли сироты сегодня.
    build.classify("**.bak", None)
    # В дистрибутив уходит ТОЛЬКО game/ и лаунчер-обвязка: источники, инструменты,
    # сырцы и прошлые артефакты — не для игроков (и не для дата-майнеров).
    # reports/** — рабочая зона аудитов: черновики отчётов и вывод линтера. В
    # .gitignore она есть с самого FWA-030, а здесь её не было, и distribute
    # исправно клал её в КАЖДЫЙ пакет: в vn-1.0.1-win.zip лежали reports/audit.md
    # (138 КБ внутреннего отчёта) и reports/decisions_needed.md. Это тот же класс,
    # что «два контура» у ключей подписи ниже — там оба на месте и проверяются, а
    # для reports/ был сделан только git-контур.
    for _zone in ("tools/**", "content/**", "assets_src/**", "loc/**", "docs/**",
                  "ci/**", "packs/**", "build/**", "reports/**", ".vncache/**",
                  ".git/**",
                  ".gitignore", ".gitattributes", ".gitlab-ci.yml", "CODEOWNERS",
                  "README.md", "project.yaml", ".vnstorage.yaml", "hdrs.tmp",
                  "log.txt", "traceback.txt", "errors.txt"):
        build.classify(_zone, None)
    # Release-профиль (раздел 7): dev-инструменты не поставляются игрокам.
    build.classify("game/framework/90_debug/**", None)
    build.classify("game/generated/qa/**", None)
    build.classify("game/generated/manifest.json", None)
    # Synthetic-языки (pseudo, ADR-0005) — QA-инструмент: из дистрибутива
    # исключаются по манифесту пакета, без хардкода кодов языков.
    import json as _json
    import os as _os
    _tl_dir = _os.path.join(config.gamedir, "tl")
    if _os.path.isdir(_tl_dir):
        for _code in _os.listdir(_tl_dir):
            _mf = _os.path.join(_tl_dir, _code, "language.json")
            try:
                with open(_mf, encoding="utf-8") as _f:
                    if _json.load(_f).get("synthetic"):
                        build.classify("game/tl/%s/**" % _code, None)
            except (OSError, ValueError):
                pass
    # Флейворы (ADR-0006): vn release build кладёт game/build_id.json со списком
    # исключений (NSFW-ассеты для public и т.п.) — применяем при distribute.
    # Глобы вычисляет тулинг (release.py), здесь только исполнение.
    _bi = _os.path.join(config.gamedir, "build_id.json")
    if _os.path.isfile(_bi):
        try:
            with open(_bi, encoding="utf-8") as _f:
                for _glob in (_json.load(_f).get("exclude") or []):
                    build.classify(_glob, None)
        except (OSError, ValueError):
            pass

    # ── Мобильная поставка: без оверсэмпл-вариантов ──────────────────────────
    # У universal APK и Play-бандла жёсткий потолок 2 ГБ (doc/android.html), а
    # @N-варианты (ADR-0012) удваивают вес ассетов. На телефоне они и не грузятся:
    # крупный вариант движок берёт только когда физический экран крупнее
    # виртуального (renpy/display/im.py: get_oversampled_image, draw_per_virt > 1)
    # и молча откатывается на безсуффиксный файл, если варианта нет. Цена — чуть
    # мягче картинка на high-DPI планшете; альтернатива — не влезть в канал вовсе.
    #
    # Паттерн по СУФФИКСУ, а не по каталогу: `<имя>@N.<ext>` — соглашение движка,
    # действующее для любого образа и видео, где бы он ни лежал (не только в
    # game/assets). Цель — не архив, а платформенные file lists: файл уезжает в
    # desktop-списки, а пакеты android/ios/web их не включают вовсе
    # (00build.rpy: package("android", "directory", "android all")).
    #
    # Место в файле значимо: правило ПЕРВОГО совпадения (distribute.rpy:
    # scan_and_classify), поэтому паттерн стоит ПОСЛЕ флейворных исключений —
    # иначе он перехватил бы NSFW-ассеты с суффиксом @N и вернул их в
    # desktop-поставку SFW-флейвора.
    #
    # Тот же набор суффиксов считает предполётная проверка размера
    # (vn android preflight, tools/vn/src/vn/android.py) — рассинхрон виден по
    # её отчёту: она показывает, сколько мегабайт мобильный пакет не берёт.
    build.classify("**@[2-9].*", "windows linux mac")
