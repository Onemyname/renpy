# Соглашения по именованию (нормативные)

Источник нормы — раздел 1.4 ARCHITECTURE.md. Проверяются `vn content lint`; нарушение = красный CI.
Id неизменяемы навсегда: переименование = новый id + запись в `content/renames.yaml` (G7).

| Сущность | Паттерн | Пример |
|---|---|---|
| Папка главы | `^ch(\d{2})_([a-z][a-z0-9_]{2,30})$` | `ch07_reunion` |
| id главы | `^ch\d{2}$` | `ch07` |
| Файл сцены | `^s(\d{3})_([a-z][a-z0-9_]{2,40})\.scene\.(yaml\|rpy)$` | `s030_rooftop.scene.yaml` |
| id сцены (полный) | `^ch\d{2}_s\d{3}$` | `ch07_s030` |
| Метка-обвязка (эмитит компилятор) | `^ch\d{2}_s\d{3}$` | `ch07_s030` |
| Авторская метка (`__body`/ветки) | `^ch\d{2}_s\d{3}__[a-z0-9_]+$` | `ch07_s030__b_lie` |
| say-id | `^ch\d{2}_s\d{3}_\d{4}$` | `ch07_s030_0042` |
| id меню (`vn_menu`) | `^ch\d{2}_s\d{3}_m\d{3}$` | `ch07_s030_m001` |
| id персонажа | `^[a-z][a-z0-9_]{1,23}$` | `mira` |
| Логический id ассета | `^(bg\|cg\|spr\|mov\|ui\|vfx\|bgm\|amb\|sfx)/[a-z0-9_/]+$` | `bg/school_gate/day`, `mov/demo/ambient` |
| Файл спрайт-слоя (референс) | `^assets/spr/<char>/<pose>/(base\|outfits/*\|faces/*\|overlays/*)\.webp$` | `assets/spr/mira/a/faces/smile.webp` |
| Оверсэмпл-вариант (ADR-0012) | `<имя>@<N>.<ext>` рядом с референсом; в ссылках НЕ употребляется | `assets/bg/rooftop/day@2.webp` |
| Мастер растра (ADR-0012) | `assets_src/art/{characters,backgrounds,cg}/…` — расширение по классу (`render.classes.<c>.formats`) | `assets_src/art/backgrounds/rooftop/day.jpg` |
| Видео-сырец (ADR-0006) | `video_src/<group>/…/<name>.(mp4\|mov\|mkv\|webm\|m4v\|avi)`, сегменты — слуги | `video_src/demo/ambient.mp4` |
| Декларация DAZ-рендера | `assets_src/daz/**/<name>.render.yaml` (schema daz_render@1) | `daz/ch01/kiss/kiss.render.yaml` |
| Декларация VaM/Sims4-захвата | `assets_src/{vam,sims4}/**/<name>.render.yaml` (schema `vam_render@1` / `sims4_render@1`) | `sims4/ch01/loft.render.yaml` |
| NSFW-контент (ADR-0006) | подпапка `nsfw/` внутри категории: `cg/nsfw/…`, `mov/nsfw/…` | `assets_src/video_src/nsfw/scene01.mp4` |
| Переменная состояния | `^(g\|ch\d{2}\|mech_[a-z0-9_]+\|dlc_[a-z0-9_]+)\.[a-z][a-z0-9_]*$` | `ch07.roof_visited` |
| Файл миграции | `^\d{4}_[a-z][a-z0-9_]+\.py$` | `0007_route_points_clamp.py` |

Принципы:

- **Слуг — только в имени файла/папки.** В id и label слуг не входит: слуг можно менять, id — никогда.
- Номера сцен — с шагом 10 (`s010`, `s020`, …); порядок задаёт `chapter.yaml`, номер — человекочитаемый якорь.
- Сохраняемые переменные никогда не начинаются с `_`. Это конвенция проекта «переменная не является
  состоянием прохождения», а не поведение движка: Ren'Py сохраняет и `_`-переменные стора.
- Каждый YAML начинается с `schema: <name>@<int>` (G16).
- **Ссылка на ассет — всегда референсное имя, без `@N`.** Крупный вариант подставляет
  движок сам по физическому размеру экрана; имя с `@N` этот механизм отключает (ADR-0012).
