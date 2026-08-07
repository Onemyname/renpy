# Build-метаданные флейвора (ADR-0006). Источник — game/build_id.json: его пишет
# vn release build на время distribute и удаляет после; в dev-чекауте файла нет,
# работают дефолты (flavor=dev, весь контент виден). Значения — константы процесса,
# НЕ default: в сейв не попадают, rollback их не трогает.
#
# Гейты для систем: vn_build.nsfw / vn_build.early_content / pack_registry.owned —
# контент-код спрашивает их, а не имя флейвора (новый флейвор = правка project.yaml,
# не кода игры).

init -985 python in vn_build:
    from store import renpy
    import json

    flavor = "dev"
    build_id = "dev"
    version = None
    packs = []
    nsfw = True             # dev видит весь контент; релизные значения — из файла
    early_content = True
    watermark = False
    patron_token = None

    _info = {}
    try:
        with renpy.open_file("build_id.json", encoding="utf-8") as _f:
            _info = json.load(_f)
    except Exception:
        pass    # файла нет (dev) или битый — работаем дефолтами, не падаем на старте

    if _info:
        flavor = _info.get("flavor", "dev")
        build_id = _info.get("build_id", "dev")
        version = _info.get("version")
        packs = list(_info.get("packs") or [])
        nsfw = bool(_info.get("nsfw", False))
        early_content = bool(_info.get("early_content", False))
        watermark = bool(_info.get("watermark", False))
        patron_token = _info.get("patron_token")

    def label():
        """Подпись вотермарки: build-id + хвост patron-токена (если задан)."""
        tail = (u" · " + str(patron_token)[-8:]) if patron_token else u""
        return build_id + tail
