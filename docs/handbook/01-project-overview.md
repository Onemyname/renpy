# 01. Обзор проекта

> **Статус подсистемы:** PARTIALLY IMPLEMENTED — фундамент, компилятор, ассет-конвейер, локализация и релизный гейт работают; главное «но» — в репозитории одна черновая глава, а `README.md:43` до сих пор объявляет «фазу 0», хотя код закрывает почти всю фазу 1 и половину фазы 2.
> **Отвечает на вопрос:** «Что это за проект, что в нём уже работает, и на что нельзя рассчитывать?»

Это монорепозиторий коммерческой визуальной новеллы на Ren'Py 8.5.3 с собственным тулингом `vn`
(Python-пакет `tools/vn/`) и производственным конвейером DAZ → ComfyUI → ffmpeg → Ren'Py.
Нормативный фундамент — [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) (4182 строки, версия 1.0 от 2026-08-07):
**это целевой контракт, а не описание построенного**. Что построено на самом деле — таблица ниже.

## Быстрый ответ

```bash
pip install -e tools/vn      # единственный CLI проекта
vn doctor                    # окружение; сейчас печатает 8 строк — 8 PASS / 0 FAIL
vn build                     # lint → ассеты → компиляция → генерат → импорт переводов
vn play                      # запуск игры (нужен RENPY_SDK)
```

| Что | Значение | Где проверить |
|---|---|---|
| Версия игры | `0.1.5` | [`project.yaml:2`](../../project.yaml) |
| Версия тулинга `vn` | `0.1.0` (число независимое) | [`tools/vn/src/vn/__init__.py:3`](../../tools/vn/src/vn/__init__.py) |
| Пин Ren'Py SDK | `8.5.3` | `project.yaml:5`, проверяется `vn doctor` |
| Схема сейвов | `save_schema: 2` | `project.yaml:3` |
| Коммитов / ветка / remote | 51 / `main` / `github.com/Onemyname/renpy` | `git rev-list --count HEAD` |

Подробный старт с нуля — [03-getting-started.md](03-getting-started.md); устройство зон и слоёв —
[02-architecture.md](02-architecture.md).

---

## 1. Что это за игра

| Параметр | Значение | Источник |
|---|---|---|
| Жанр | Коммерческая визуальная новелла на Ren'Py | `README.md:1` |
| Арт-направление | DAZ-реализм: DAZ Studio (Iray) → ComfyUI (Wan 2.2 I2V) → ffmpeg → WebP/WebM | [ADR-0006](../adr/0006-daz-comfyui-video-pipeline.md) |
| Контент | 18+/NSFW как отдельная зона и отдельный пак | `packs/nsfw/`, `project.yaml:19-20`, [ADR-0008](../adr/0008-ai-model-licensing-for-commercial-adult-content.md) |
| Горизонт планирования | 5–10 лет | `docs/ARCHITECTURE.md:8` |
| Целевой масштаб | 20+ глав, 300+ сцен, 150+ персонажей | `docs/ARCHITECTURE.md:8` |

Главная ставка проекта: **тулинг — это второй продукт размером с игру**
(`ARCHITECTURE.md:4070`). Поэтому здесь есть свой компилятор контента, свой ассет-конвейер,
свой релизный гейт и 373 теста на всё это — при одной черновой главе игры.

## 2. Монетизация: флейворы `public` и `patron`

Модель заложена в `project.yaml:12-22` и материализуется командой `vn release build --flavor <id>`
([`tools/vn/src/vn/release.py:479-506`](../../tools/vn/src/vn/release.py) — `compute_build_info`,
документ `build_info@2`).

| Флейвор | `packs` | `nsfw` | `early_content` | `watermark` | Смысл |
|---|---|---|---|---|---|
| `public` | `[ep_beach]` | `false` | `false` | `false` | Публичный билд: позже и без NSFW |
| `patron` | `[ep_beach, nsfw]` | `true` | `true` | `true` | Ранний доступ подписчикам, вотермарка с build-id |

**Честно о том, что из этого реально гейтит контент — сегодня:**

| Поле флейвора | Статус | Факт |
|---|---|---|
| `nsfw` | **IMPLEMENTED** | Исключение считается по *реальным* директориям: для каждой категории с подпапкой `nsfw/` эмитится глоб `game/assets/<категория>/nsfw/**` (`release.py:441-452`). Ни у одной категории (`bg cg mov spr ui`) такой подпапки пока нет, поэтому список исключений в `build-info.json` пуст (`"exclude": []`) |
| `watermark` | **IMPLEMENTED** | Оверлей с build-id — `game/framework/20_ui/screens/build_overlay.rpy`; текст вотермарки — `build_id + " · " + patron_tag` (`060_build_info.rpy:44-45`) |
| `patron_tag` (не поле флейвора, а поле `build-info`) | **IMPLEMENTED** | Вход остался прежним — флаг `vn release build --patron-token` (`cli.py:1510`), но наружу уезжает только `blake2s(токен, digest_size=4, person=b"vnpatron")`, 8 hex (`release.patron_tag`, `release.py:455-476`). Схема бампнута `build_info@1` → `build_info@2` ([ADR-0011](../adr/0011-patron-tag-instead-of-token.md)); `build_info@1` оставлена в реестре с пометкой «устарела», чтобы читались артефакты сборок до 0.1.5 |
| `packs` (как список разрешённых) | **IMPLEMENTED как рантайм-гейт установленности** | `VN_PACKS` перечисляет все паки независимо от флейвора (скрипты уезжают всегда, G9), но `pack_registry.installed()` сверяет их со списком поставки `vn_build.packs` (`030_flow.rpy:77-91`) — в `public`-сборке пак `nsfw` невидим |
| `early_content` | **IMPLEMENTED как релизный гейт** | Проверка «зрелость контента» в `vn release validate` (`early_content_checks`, `release.py:403-438`); самоактивирующаяся — до первой главы `status: release` это WARN, с её появлением `draft` становится FAIL. В `game/` флаг по-прежнему не читает никто |

**Требование к процессу, появившееся вместе с ADR-0011:** токен, выдаваемый получателю, обязан быть
случайным (`secrets.token_hex(16)` и подобное). Метка в дистрибутиве короткая (8 hex), поэтому
короткий низкоэнтропийный токен подбирается по ней перебором. Соответствие «метка → получатель»
нигде не хранится — владелец пересчитывает `patron_tag` из своего токена по рецепту в докстринге
`release.patron_tag`.

Платформы — **закрыто** [ADR-0014](../adr/0014-platform-services.md): Steam, Steam Deck и Big Picture
работают (штатный стек движка, ownership-провайдер паков, controller-first UI, авто-масштаб),
`vn release steam` рендерит VDF и раскладывает депоты всех трёх платформ — Linux-пакет приходит
`tar.bz2`, и раскладка это знает ([40-steamworks.md](40-steamworks.md) §4.3). Осталось **не**
закрытым: приложения в Steamworks нет (`platform.steam.appid: null`, ключа `depots` в
`project.yaml` нет — команда честно падает на первом шаге), аплоад — ручной `steamcmd`,
каналов dev/beta/release нет, Android нет, на живом железе не проверено ничего. Подробности — [39-platforms.md](39-platforms.md),
[40-steamworks.md](40-steamworks.md), [41-steam-deck.md](41-steam-deck.md), [43-steam-qa.md](43-steam-qa.md),
[29-build-and-release.md](29-build-and-release.md) и [30-packs-and-dlc.md](30-packs-and-dlc.md).

Правовая рамка коммерческого 18+ контента — **не закрыта**: [ADR-0008](../adr/0008-ai-model-licensing-for-commercial-adult-content.md)
единственный ADR со статусом «предложено», развилка A/B/C ждёт решения владельца,
авто-гейт «модель с `commercial_use != allowed` не участвует в релизном контенте» не реализован.
См. [33-security-and-legal.md](33-security-and-legal.md).

## 3. Что в репозитории есть на 2026-08-08

| Сущность | Сколько | Где |
|---|---|---|
| Главы ядра | 1 — `ch01_awakening`, `status: draft`, 3 сцены (`s010_intro`, `s020_school_gate`, `s030_rooftop`) | `content/chapters/` |
| Персонажи | 1 — `mira` | `content/characters/mira/character.yaml` |
| Локации | 2 — `rooftop`, `school_gate` | `content/locations/` |
| Паки | 2 — `ep_beach` (глава `ch90_beach`, 1 сцена) и `nsfw` (манифест есть, глав нет) | `packs/` |
| Языковые пакеты | 3 — `en`, `de`, `pseudo`; покрытие 136/136 (100 %), fuzzy 0 | `loc/po/` |
| JSON Schema | 39 (включая `assets_manifest@1` и `build_info@2`) | `tools/schemas/` |
| Выходы Content Compiler | 21 `*.gen.rpy` + `manifest.json` | `game/generated/` |
| Тесты | 373 собирается (в 27 файлах; часть тестов параметризована) | `tools/vn/tests/` |
| Фикстуры сейв-корпуса | 2 — `schema1-demo.save` (схема 1, `ch01_s010`) и `schema2-demo.save` (схема 2, `ch01_s020`) | `ci/fixtures/saves/` |
| ADR | 14 решений + шаблон; 13 приняты, ADR-0008 предложен, ни один не заменён | `docs/adr/` |
| Релизы | 0.1.0 … 0.1.4 | `docs/CHANGELOG.md` |

Проверенные прогоны на машине владельца (Windows 11, RTX 5080, Python 3.12.10):
`vn doctor` → 8 PASS / 0 FAIL; `vn build` → `build: OK` за ~0.3 с на прогретом кэше;
`pytest tools/vn/tests -q` → 400 passed; `vn release validate --flavor public` → 20 строк (18 PASS + 2 WARN: зрелость контента и черновые дубли озвучки), exit 0;
`vn release validate --flavor patron` → 21 строка (20 PASS + 1 WARN), exit 0 (в том числе `сейв-корпус: 2 фикстур`); `vn save corpus` → OK, обе фикстуры загружены и мигрированы;
`vn pipeline doctor` → PASS (ffmpeg 8.1.2 VP9, ComfyUI `D:\ComfyUI`, PyTorch 2.11.0+cu128,
6 обязательных моделей, DAZ Studio 6), WARN на неустановленные Virt-a-Mate и The Sims 4.

## 4. Роли и кто что пишет

Онбординг-документы существуют для четырёх ролей — это единственные ролевые документы в репозитории:

| Роль | Документ | Зона ответственности | Раздел хендбука |
|---|---|---|---|
| Сценарист | [`docs/onboarding/writer.md`](../onboarding/writer.md) | `content/chapters/**` — пара `*.scene.{yaml,rpy}` | [12-scenes.md](12-scenes.md), [13-dialogue.md](13-dialogue.md) |
| Художник / motion | [`docs/onboarding/artist.md`](../onboarding/artist.md) | `assets_src/**`, декларации рендеров | [17-daz-studio.md](17-daz-studio.md), [20-image-generation.md](20-image-generation.md), [21-video-generation.md](21-video-generation.md) |
| Локализатор | [`docs/onboarding/localizer.md`](../onboarding/localizer.md) | `loc/po/<lang>/` | [14-localization.md](14-localization.md) |
| Tools-инженер | [`docs/onboarding/tools-engineer.md`](../onboarding/tools-engineer.md) | `tools/vn/`, `tools/schemas/`, `game/framework/` | [25-custom-engine.md](25-custom-engine.md) |

**Грабли этих документов** (учитывайте, читая их): `localizer.md` помечен «конвейер появится в фазе 2» —
конвейер работает; `writer.md` говорит «`vn scene new` — с фазы 1» — команда реализована
(`cli.py:467`); `artist.md` обещает сырцы в S3 — реально `.vnstorage.yaml` объявляет
`type: file, path: "~/vn-assets-store"`, каталог не создан, а PNG временно легализованы в git
[ADR-0004](../adr/0004-local-png-sources-in-git.md); карта модулей в `tools-engineer.md`
покрывает 11 из ~28 модулей тулинга.

Онбординга QA, дизайнера и продюсера нет. Владение зонами — `CODEOWNERS`, но **все хэндлы там
плейсхолдеры** (`@tech-lead`, `@engine-dev-1/2`, `@lead-writer`, `@art-director`, `@loc-lead`),
и не покрыты `/content/{gallery,achievements,ui}`, `/content/licenses.yaml`, `/packs/`,
`/assets_src/`, `/game/fonts/`, `/.github/workflows/`, `/docs/` кроме `conventions/` и `adr/`.

## 5. Что работает, что частично, чего нет

Сводка верхнего уровня. Детали по каждой строке — в профильных файлах хендбука.

| Подсистема | Статус | Главное «но» |
|---|---|---|
| CLI `vn` — 20 доменов, exit-коды 0/1/2/3 | **IMPLEMENTED** | Module-docstring `cli.py:4-5` до сих пор врёт про «фазу 0» |
| Content Compiler `content/**` → 19 `*.gen.rpy` | **IMPLEMENTED** | Свежесть считается сравнением байт выходов; `manifest["inputs"]` пишется, но никогда не читается |
| `vn content lint` (33 диагностики, строгость по статусу главы) | **IMPLEMENTED** | Нет `--strict/--arch/--schemas` из ARCHITECTURE.md — только `--layout/--no-layout` |
| Реестр схем `tools/schemas/` (39 схем, `@N`) | **IMPLEMENTED** | Дыра G16 закрыта: `assets_manifest@1` заведена, и `.vncache/assets-manifest.json` валидируется ею при записи (`assets/pipeline.py:441-450`) |
| Ассет-конвейер (PNG→WebP, превью, кэш, GC, сироты, звук) | **IMPLEMENTED** | Ветка `copy_audio` читает нормативную зону `assets_src/audio_stems/{bgm,amb,sfx}/` (`assets/pipeline.py:159-170`), `.ogg` уезжает в `game/assets/audio/<kind>/`; тест `test_audio_stems_branch_copies_ogg`. Но контента нет: ни одного `.ogg` в репозитории, `content/audio/{bgm,sfx}.yaml` — `tracks: {}` |
| Видео-конвейер VP9/WebM + сайдкар `mov_meta@1` | **IMPLEMENTED** | Нет alpha-видео, 2-pass, профилей `hd`/`mobile`, loudnorm |
| Генерируемые UI-панели (ADR-0009), 8 панелей | **IMPLEMENTED / UNDOCUMENTED** | В `ARCHITECTURE.md` — ноль упоминаний. Нарушений `2*Borders` больше нет: под мелкие кнопки заведены `chip`/`chip_active` (radius 8, Borders 11, минимум 22×22), на них переведены стили `vn_gal_tab` и `vn_gal_ctl_button`; регресс стерегут тесты в `test_ui_panels.py` |
| Локализация: PO round-trip, псевдолокаль, ledger | **IMPLEMENTED** | Ledger стал журналом (`ledger@2`, 2026-08-19): удалённая реплика уходит в `retired`, её номер больше не выдаётся — перевод не переезжает на чужую реплику |
| Состояние: named stores, снапшот, миграции | **IMPLEMENTED** | Миграции исполняются только в игре (`after_load`); `vn save migrate` — заглушка фазы 3 |
| Галерея (ADR-0010, два источника разблокировки) | **IMPLEMENTED** | `ARCHITECTURE.md` C9/C24 описывают заменённый дизайн `Gallery` + `_seen_images` |
| Достижения | **IMPLEMENTED** | Бэкенд, экран `achievements`, пункты **главного меню и рельсы**, прогресс отдельной ачивки (`goal: {total, step}` → `stat_max`/`stat_modulo` в Steam), тост о выдаче и кнопка синхронизации в настройках (`achievement.Sync()`). Ни ADR, ни раздела в нормативе — одно упоминание в `ARCHITECTURE.md:2720`; канон — [15](15-gallery.md) |
| Релизный гейт `vn release validate --flavor` | **IMPLEMENTED** | 21 проверка; своих правил почти нет — агрегирует чужие. Исключение — «зрелость контента» (`early_content` vs `status` глав), у неё нет другого владельца; она самоактивирующаяся — на этом дереве даёт WARN (ни одной `release`-главы), оба флейвора зелёные, строгость включится с первой `release`-главой |
| Флейворы `public`/`patron` | **IMPLEMENTED** | Все четыре рычага гейтят: `nsfw` (исключение ассетов + рантайм), `watermark`/`patron_tag`, `packs` (рантайм-гейт установленности: `VN_PACKS ∩ vn_build.packs`), `early_content` (проверка зрелости контента в релизном гейте). Build-time-исключения скриптов паков нет и не будет — гейт логический (G9) |
| Паки/DLC | **PARTIALLY IMPLEMENTED** | `pack build` кладёт в zip только манифест и сцены. **Установленность** пака теперь честная: `installed()` сверяет `VN_PACKS` со списком поставки `vn_build.packs`, поэтому в `public`-сборке пак `nsfw` невидим. Провайдер **владения** подключён (ADR-0014, `035_platform.rpy:75`), но работает только при живом Steam и только для пака с `steam_dlc_appid`. Охранник «главы объявлены, а генерата нет» ожил и падает ДО создания zip (`cli.py:1624-1627`), но проверяет «хоть одна сцена на весь пак», а не по каждой главе |
| Платформы: Steam / Steam Deck / Big Picture | **PARTIALLY IMPLEMENTED** (фасад — IMPLEMENTED) | [ADR-0014](../adr/0014-platform-services.md): единственная точка касания — `00_core/035_platform.rpy` (под гард-тестом), ачивки и DLC-владение через штатный стек движка, controller-first UI и авто-масштаб. Открыто: `vn release steam` готовит VDF и раскладку депотов (включая Linux-`tar.bz2`, [40](40-steamworks.md) §4.3), но в репозитории нет ни `appid`, ни `depots` — до конца команда не доходит; аплоад — ручной `steamcmd`, аплоад автоматизирован ручным workflow `steam-upload`, но без секретов и App ID это no-op; на живом железе не проверено ничего ([43](43-steam-qa.md)), controller-вёрстку теперь ночью снимает CI в двух геймпадных профилях ([42](42-big-picture.md) §5.10). Android — **IMPLEMENTED как канал** с 2026-08-18: `vn release android setup\|status\|preflight\|build`, подготовка тулчейна из CLI через те же функции RAPT, что у лаунчера; APK собран и вскрыт (подписан, без `@N`, без dev-зоны, без ключей, только байткод). Открыто: запуск на живом устройстве, Play-бандл, оформление пакета ([39-platforms.md](39-platforms.md) §2.1) |
| QA-автопилот `vn test smoke` | **IMPLEMENTED** | `test replay`/`paths` — фаза 2, `test screens` — фаза 3, `test perf` не существует |
| Сейв-корпус `vn save check` / `save corpus` | **IMPLEMENTED** | 2 фикстуры, и одна из них на **старой** схеме: `schema1-demo.save` (`vn_save_schema=1`) поднимается до 2, в `log.txt` появляется `[vn] migration 0002` — миграция реально исполняется в игре. Линия имён `ci/fixtures/rpyc-line/` пересобрана: 52 `.rpyc` |
| Хранилище сырцов (`type: file`) | **IMPLEMENTED / НИ РАЗУ НЕ ЗАПУСКАЛОСЬ** | `~/vn-assets-store` не существует; `type: s3` — честный `StorageError` |
| Валидаторы DAZ/VaM/Sims4 + `vn pipeline doctor/models` | **IMPLEMENTED / UNDOCUMENTED** | В `ARCHITECTURE.md` ноль упоминаний DAZ/Comfy/VaM/Sims; деклараций рендера в репозитории ноль |
| Автоматизация рендера DAZ и вызов ComfyUI | **NOT IMPLEMENTED** | Ни `.dsa`, ни headless-запуска, ни API-клиента, ни одного workflow-JSON |
| CI: GitHub Actions (`ci`/`nightly`/`canary`/`release`/`steam-upload`) | **IMPLEMENTED** | Единственный пайплайн: GitLab-зеркало выведено из эксплуатации 2026-08-18, `ci/README.md` и `CODEOWNERS` приведены к нему, отсутствие второго конфига стережёт тест. `ffmpeg` ставится во всех workflow, которые зовут `vn build`; описание — [04](04-development-workflow.md) §4 |
| `vn bootstrap` | **PARTIALLY IMPLEMENTED** | Локальная пересборка; доставки трёх зон из CI-артефактов (G4/C22) нет, как и CI-джобы «clone → ≤ 5 мин» |
| `tools/vn.lock` (пиннованный тулчейн, G17) | **PARTIALLY IMPLEMENTED** | Лок читается: во всех в 8 джобах установки тулчейна (7 строк в конфигах: GitLab-шаблон `.with-sdk` разворачивается в `build` и `test`) перед editable-установкой идёт `pip install --quiet -r tools/vn.lock`; свойство стережёт `test_ci_config.py` (7 тестов). Остаток: в самом локе закреплены 18 пакетов, транзитивные зависимости (например `pygments`) не пиннованы |

Полная построчная таблица статусов подсистем и норм — [02-architecture.md](02-architecture.md#7-что-в-architecturemd-есть-а-в-коде-нет)
и [37-roadmap.md](37-roadmap.md).

## 6. Фазы внедрения и где мы сейчас

`ARCHITECTURE.md` § 8 (`:4068-4122`) задаёт четыре фазы с измеримым DoD.

| Фаза | Что поставляет | Фактически |
|---|---|---|
| **0** — фундамент репозитория (недели 1–2) | Зоны каталогов, `CODEOWNERS`, `.gitattributes`/`.gitignore`, `project.yaml`, реестр схем, скелет CLI, lockfile, ADR-процесс | **ЗАКРЫТА.** DoD «пустой проект собирается `vn build` и запускается, CI зелёный» выполнен |
| **1** — вертикальный срез (месяцы 1–3) | Content Compiler, ассет-конвейер, layeredimage-эмиттер + golden-тесты, `vn bootstrap` + CI «clone → ≤ 5 мин», базовый CI, ролевой инсталлер | **ПОЧТИ ЗАКРЫТА.** Не сделано: golden-тесты через `renpy compile`+lint (в `tools/vn/tests/` ноль совпадений на «golden», ни один тест не запускает SDK), `vn bootstrap` в смысле G4, CI-джоба «clone → ≤ 5 мин», однокомандный ролевой инсталлер, `vn char new`/`char validate` (обе — заглушки *фазы 1*) |
| **2** — производство и первый релиз (месяцы 3–9) | Локализация, сейвы и миграции, релизный конвейер, QA-автопилот, видео/WebM, звуковой конвейер | **ЧАСТИЧНО.** Сделано: локализация целиком, `vn save check/corpus` (2 фикстуры, миграция реально проигрывается), `vn release changelog/validate/build`, `vn test smoke`, видео-конвейер, транспорт звука (`assets_src/audio_stems/` → `game/assets/audio/`) с эмиссией `loop_start`/`volume`, канал `ambient` + дакинг, озвучка целиком (`voice@1`, `vn voice manifest/import/validate`, транскод `voice_opus`, гейт в `vn release validate`). Не сделано: сам музыкальный/SFX-контент и loudnorm для него; `vn voice tts`, автоаплоад в Steam и каналы dev/beta/release (сама Steam-поставка реализована ADR-0014, см. [39](39-platforms.md)), депот пака как товара, `vn test replay/paths`, `vn migrate`, `vn shell`, перф-бюджеты сверх cold-start и размеров каталогов |
| **3** — рост после 1.0 | Live2D/Spine, DLC-инфраструктура, скриншот-тесты, телеметрия, моды/Workshop | **НЕ НАЧАТА** (кроме частичного каркаса паков). Единственная фаза без DoD в документе |

**Вывод для читателя:** формулировка «Статус: фаза 0» в `README.md:43` и «фаза 0 не содержит
компиляции сцен, локализации и DLC» в [ADR-0001](../adr/0001-adopt-architecture-baseline.md) —
устарели. Не наследуйте их. Проект живёт между концом фазы 1 и серединой фазы 2.

## 7. Три кита архитектуры — и что от них реально стоит

`ARCHITECTURE.md:13-17` объявляет три принципа. Ниже — что из них подтверждается кодом.

**1. Data-driven контент.** Добавление главы = добавление папки с YAML-декларациями и
`scene.rpy`. Меню, галерея, локализация, сейв-схема обновляются сами.
→ **IMPLEMENTED.** `vn chapter new <slug>` создаёт скелет, `emit_chapter_registry`
(`tools/vn/src/vn/content/scenes.py:276`) кладёт главу в `VN_CHAPTERS`, а `screens/chapter_select.gen.rpy`
рисует её в меню без единой строчки ручной регистрации. Ограничение: у персонажей и локаций
скаффолда нет — `vn char new` заглушка (`cli.py:958`), `character.yaml` и `location.yaml`
пишутся руками.

**2. Кодогенерация вместо runtime-магии.** Компилятор превращает декларации в статический `.rpy`,
чтобы save/rollback/prediction/lint Ren'Py работали штатно.
→ **IMPLEMENTED.** Реальная обвязка сцены из `game/generated/scenes/ch01/ch01_s020.gen.rpy`:

```renpy
label ch01_s020:
    $ vn.checkpoint("ch01_s020")
    $ renpy.scene("sprites")
    scene bg school_gate day with dissolve
    call ch01_s020__body from _call_ch01_s020__body
    $ vn.check_scene_stack()
    if _return == "roof":
        jump ch01_s030
    $ vn.unwind_call_stack()
    jump vn_scene_unavailable
```

Никакой рантайм-диспетчеризации: обычные `label`, обычный `jump`. Автор пишет только `__body`.

**3. Валидация до мержа.** Битые ссылки, отсутствующие ассеты, сломанный граф — ловит CI.
→ **PARTIALLY IMPLEMENTED.** Линтер (33 диагностики) и релизный гейт (21 проверка) реальны и
строги; GitHub Actions гоняет `lint`, `build-test`, ночной `smoke`, недельную canary на свежем
Ren'Py и релизный конвейер — все четыре с `ffmpeg` и с пиннованным `tools/vn.lock`. Сейв-корпус
с 2026-08-08 действительно проверяет миграции (фикстура на схеме 1 поднимается до 2). Но:
`content/registry/id_registry.json` пуст (все массивы), поэтому защита G7 «выпущенный id исчез»
сегодня инертна, а `vn_qa.choice()` — тот самый QA-якорь ветки из C1 — это `pass`-заглушка
(`game/framework/00_core/030_flow.rpy:98-101`), которую компилятор никогда не эмитит.

## Как изменить / Как расширить

| Задача | Куда идти |
|---|---|
| Поменять версию игры, бюджеты, флейворы | `project.yaml` — владельцы `@tech-lead @engine-dev-1` по `CODEOWNERS`; после правки `vn build` + `vn release validate --flavor public` |
| Изменить норму G/C | Только новым ADR по `docs/adr/template.md` со ссылкой на заменяемую норму (`ADR-0001:15-18`). Правка `ARCHITECTURE.md` без ADR не проходит ревью |
| Добавить главу / сцену | [09-chapters.md](09-chapters.md), [12-scenes.md](12-scenes.md) |
| Добавить язык | `vn loc add <code> --name <native>` — [14-localization.md](14-localization.md) |
| Завести новую роль в онбординге | `docs/onboarding/<role>.md` + строка в `CODEOWNERS` |
| Понять, где живёт конкретный файл | [02-architecture.md](02-architecture.md) |

## Чего НЕ делать

- **Не верьте `README.md:43` («фаза 0») и `cli.py:4-5`** — оба устарели на две фазы.
- **Не цитируйте `ARCHITECTURE.md` как описание работающего кода.** Это целевой контракт;
  [ADR-0002](../adr/0002-phase0-schema-subset.md) прямо признаёт, что его примеры внутренне
  противоречивы (раздел 1.5 против 3.4/3.5/4.3), и правка отложена. Канон — профильные разделы
  (3 — сцены/главы, 4 — персонажи, 6 — состояние) и схемы из `tools/schemas/`.
- **Не правьте `game/generated/`, `game/assets/`, `game/tl/`** — эти зоны не в git и их перезапишет
  ближайшая сборка.
- **Не считать `vn release steam` аплоадом и не считать её проходящей целиком** — она готовит VDF и раскладку депотов (это работает на всех трёх платформах, [40-steamworks.md](40-steamworks.md) §4.3), `steamcmd` запускает человек, а в этом чекауте команда останавливается на пустом `platform.steam.appid`.
- **Не считайте `public`-сборку «без NSFW» автоматически защищённой:** отсечение считается по
  фактическим подкаталогам `nsfw/` **внутри категории** — `game/assets/cg/nsfw/**`,
  `game/assets/mov/nsfw/**` и т. п. (`release.py:441-452`). Ни одного такого каталога сегодня нет
  (`game/assets` = `bg cg mov spr ui`), поэтому список исключений пуст; а `flavors.*.packs`
  не гейтит паки вовсе.
- **Не кладите patron-токен в `build-info.json` и не «возвращайте» поле `patron_token`** — этот
  документ целиком уезжает игроку внутри дистрибутива, и дефект воспроизведётся (ADR-0011).
  Наружу идёт только `patron_tag`. Артефакты сборок **до 0.1.5** (`build/dist/*/build-info.json`
  со `schema: build_info@1`) содержат токен в открытом виде — если там был боевой секрет, его
  нужно отозвать.
- **Не начинайте новый рендер до записи в `content/licenses.yaml`** — релизный гейт
  `vn release validate` проверит связь декларации с реестром лицензий и завалит билд.

## Проверка

```bash
vn doctor                              # ожидаем 8 PASS, 0 FAIL
vn build                               # ожидаем "build: OK"
vn build --check                       # CI-режим: генерат свеж? (упадёт после нового коммита — см. ниже)
python -m pytest tools/vn/tests -q     # ожидаем 400 passed
vn release validate --flavor public    # 20 строк: 18 PASS + 2 WARN (зрелость контента, драфты озвучки), exit 0
vn release validate --flavor patron    # 21 строка: 20 PASS + 1 WARN, exit 0 (в т.ч. «сейв-корпус: 2 фикстур»)
vn save corpus                         # обе фикстуры грузятся; schema1-demo мигрирует 1 -> 2
vn loc report                          # de/en/pseudo — 136/136, fuzzy 0
vn content graph                       # mermaid: ch01 (3 сцены); ch90 из пака НЕ попадёт
```

`config.version` содержит короткий git-sha (`tools/vn/src/vn/content/compile.py`), но на свежесть
генерата это больше не влияет: `--check` сравнивает `version.gen.rpy` с нормализованным sha
(`_stale_key`), потому что sha — метаданные сборки, а не контент. Раньше красным становился
любой коммит, и гейт свежести перестал отвечать на свой вопрос. Бамп semver в `project.yaml`
без пересборки ловится по-прежнему.

## Для AI-агента

| | |
|---|---|
| **Читать перед изменением** | `docs/handbook/02-architecture.md`, `project.yaml`, `docs/ARCHITECTURE.md` § 0 (строки 36–201), `CODEOWNERS` |
| **Не трогать** | `game/generated/`, `game/assets/`, `game/tl/`, `build/`, `.vncache/` — производные зоны; `docs/ARCHITECTURE.md` — правится только через ADR |
| **Зависимости** | Правка `project.yaml` меняет `version.gen.rpy`, бюджеты в `vn build` и релизном гейте, флейворы в `vn release build`; правка `CODEOWNERS` меняет требования к approve |
| **Валидация** | `vn build && python -m pytest tools/vn/tests -q && vn release validate --flavor public` |
| **Частые ошибки** | 1) выдать текст `ARCHITECTURE.md` за реализованное поведение; 2) сослаться на «фазу 0» из README; 3) предположить, что `flavors.*.packs` или `early_content` ничего не гейтят (`packs` — установленность в рантайме, `early_content` — зрелость контента в релизном гейте) либо, наоборот, что `public` сегодня не собирается (гейт зрелости даёт WARN, exit 0); 4) считать, что коммит сам по себе делает генерат несвежим — sha нормализуется при сравнении (`_stale_key`); 5) писать в `game/build_id.json` что-либо секретное — файл целиком уезжает игроку (ADR-0011), там допустима только производная `patron_tag`; 6) считать аудио-тракт мёртвым — ветка `copy_audio` работает, мёртв только контент (ноль `.ogg`) |
