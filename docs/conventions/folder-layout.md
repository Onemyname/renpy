# Нормативная структура каталогов

Источник нормы — раздел 1.2 ARCHITECTURE.md (G2). `vn content lint --layout` сверяет
фактическую структуру с этим документом. Ключевые инварианты:

- `content/` — строго ВНЕ `game/` (движок грузит всё под `game/`; черновики не должны попадать в билд);
- `game/generated/` — единственная зона генерата; в .gitignore;
- `game/assets/`, `game/tl/` — производные, не в git (`vn bootstrap`);
- художник никогда не пишет в `game/`: путь ассета — `assets_src/` → пайплайн → `game/assets/`;
- разрешения, форматы и отгружаемые масштабы задаются данными — `project.yaml: render` (ADR-0012);
- DLC-контент — `packs/<pack_id>/`, принадлежность паку по расположению;
- `game/images/` не существует (автоопределение образов отключено — явные image из Asset Registry).

```
vn/
├── project.yaml            # version, save_schema, min_tools (schema: project@1)
├── .vnstorage.yaml         # логические хранилища сырцов (schema: storage@1)
├── CODEOWNERS  .gitattributes  .gitignore  .gitlab-ci.yml
├── game/
│   ├── framework/          # рукописный код: 00_core/ (вкл. engine_compat/), 10_systems/, 20_ui/, 90_debug/
│   ├── generated/          # ЕДИНСТВЕННАЯ зона генерата (в .gitignore)
│   ├── assets/             # game-ready ассеты (не в git)
│   ├── tl/                 # генерируется из PO (не в git)
│   ├── options.rpy  gui.rpy
├── content/                # источник истины: chapters/, characters/, locations/, audio/,
│   │                       #   variables/, migrations/, registry/, renames.yaml, anchors.yaml, flags.yaml
├── packs/                  # DLC: <pack_id>/manifest.yaml + chapters/ characters/ loc/
│                           #   (nsfw — контент 18+, база его не требует; ADR-0006)
├── assets_src/             # мастера: art/ (characters/, backgrounds/, cg/), psd/, daz/, vam/,
│                           #   sims4/, live2d/, spine_export/, audio_stems/, video_src/.
│                           #   Растр/аудио/видео — в Git LFS (.gitattributes, ADR-0012);
│                           #   не-растровые гиганты (PSD, Tray-бандлы) — через vn assets push.
│                           #   assets_src/png/ — исторический алиас art/, поддерживается
├── loc/                    # loc.yaml, po/<lang>/, ledger/chNN.json
├── tools/
│   ├── vn/                 # единственный CLI (src/vn/…)
│   ├── schemas/            # реестр JSON Schema: <name>@<int>.schema.json
│   └── vn.lock             # пиннованный тулчейн
├── build/                  # локальные артефакты (в .gitignore)
├── docs/                   # ARCHITECTURE.md, adr/, conventions/, runbooks/, onboarding/, pipeline/
└── ci/                     # скрипты проверок CI
```
