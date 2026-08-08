# Онбординг: художник / motion-дизайнер

> Фаза 0: ассет-конвейер (раздел 2 ARCHITECTURE.md) появится в фазе 1. Этот документ — контракт заранее.

## Правила, действующие с первого дня

- Вы никогда не кладёте файлы в `game/` — путь ассета: `assets_src/` → пайплайн → `game/assets/`.
- Сырцы (PSD, Spine, Live2D, стемы) живут в S3; в git — только `*.manifest.json`
  (`vn assets push` / `vn assets pull`, с фазы 1).
- Локи обязательны (G14): `vn assets pull --edit <файл>` берёт лок автоматически;
  push без лока откажет. PSD не мержится — потерянный лок = потерянный день чьей-то работы.
- Именование слоёв в PSD и файлов — по docs/conventions/naming.md; нарушение ловит CI, а не арт-директор.

## Рендеры и видео (DAZ/AI-конвейер, ADR-0006)

- Окружение (DAZ Studio, ComfyUI, ffmpeg, модели) — по docs/pipeline/phase-0.md;
  самопроверка: `vn pipeline doctor`.
- Каждый DAZ-рендер объявлен: `assets_src/daz/**/<имя>.render.yaml` (сцена,
  камера, свет, разрешение, пресеты персонажей). `vn assets daz validate`
  проверит и запишет провенанс.
- AI-обработка (ComfyUI): выходной PNG не переименовывать до
  `vn assets provenance record <файл> --source <исходник>` — параметры генерации
  (seed, модель, LoRA, промпты) извлекаются из метаданных файла автоматически.
- CG-стиллы кладутся в `assets_src/png/cg/**`, видео-лупы — в
  `assets_src/video_src/<группа>/` (опции энкода — `<имя>.video.yaml`);
  сборка/проверка: `vn assets video build` / `vn assets video validate`.
- **Virt-a-Mate** — опциональный третий источник (когда нужна физика тел):
  сцену объявляют в `assets_src/vam/**/<имя>.render.yaml` (schema `vam_render@1`),
  захват — в те же `png/cg/**` / `video_src/**`; `vn assets vam validate`.
  Установка — `tools/install-vam.ps1`. Основной путь анимации остаётся DAZ→Wan.
- **The Sims 4** — опциональный четвёртый источник, задел (ADR-0007;
  продакшен-трек — DAZ). Технически — как VaM: `assets_src/sims4/**/<имя>.render.yaml`
  (schema `sims4_render@1`), захват в `png/cg/**` / `video_src/**`,
  `vn assets sims4 validate`; установка — `tools/install-sims4.ps1`.
  В декларации **обязательна `game_version`**: патчи EA меняют картинку.
- **Контент 18+ — только в подпапке `nsfw/` своей категории** (`png/cg/nsfw/…`,
  `video_src/nsfw/…`): по этой конвенции public-сборки вырезают его автоматически.
  Ошиблись папкой = 18+ уехал в публичный билд.
- **Лицензии — до первого рендера.** Купили ассет (DAZ-продукт, волосы, окружение,
  анатомию, шрифт, музыку) → сразу запись в `content/licenses.yaml`
  (`license_registry@1`): SKU, тип лицензии, инвойс, `game_use`, `nsfw_allowed`.
  В декларации рендера перечислите использованные ассеты полем `license: [...]`.
  Проверка — `vn assets licenses` (входит в релизный гейт): ассет с
  `game_use: false` или `nsfw_allowed: false` в nsfw-зоне блокирует сборку.
  Часть продуктов Published Artists **запрещает adult-использование** — это
  читается при покупке и фиксируется в реестре, восстановить задним числом дорого.
