# Тонкий options.rpy (раздел 1.2): почти всё вынесено в framework/00_core.
# config.version НЕ задаётся здесь — его эмитит generated/version.gen.rpy из project.yaml.

define config.name = _("VN")
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
