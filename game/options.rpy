# Тонкий options.rpy (раздел 1.2): почти всё вынесено в framework/00_core.
# config.version НЕ задаётся здесь — его эмитит generated/version.gen.rpy из project.yaml.

# Имя игры — бренд-константа (заголовок окна ОС): сознательно НЕ переводится.
# Захочется переводить — через translate strings, define вычисляется один раз.
define config.name = "VN"
define config.save_directory = "vn-1755000000"
define config.has_autosave = True
define config.autosave_slots = 10
define config.window_icon = None

# ── Сборка дистрибутивов (vn package -> launcher distribute) ─────────────────
init python:
    build.name = "vn"
    # В дистрибутив уходит ТОЛЬКО game/ и лаунчер-обвязка: источники, инструменты,
    # сырцы и прошлые артефакты — не для игроков (и не для дата-майнеров).
    for _zone in ("tools/**", "content/**", "assets_src/**", "loc/**", "docs/**",
                  "ci/**", "packs/**", "build/**", ".vncache/**", ".git/**",
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
