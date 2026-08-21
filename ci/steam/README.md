# Steam-поставка (ADR-0014)

> **🧊 ЗАМОРОЖЕНО (ADR-0020, 2026-08-21).** Решение «идти ли в Steam» не принято:
> App ID не заводится, депотов нет, workflow `steam-upload` отключён вместе с
> остальным CI. Тулинг (`vn release steam`, `steam_stage_content`, этот каталог)
> сознательно НЕ удаляется — он рабочий и покрыт тестами; ревью пропускает эту
> зону осознанно. Разморозка = решение о выходе в Steam → App ID в project.yaml.

Steam — одна из платформ распространения, не фундамент: тот же дистрибутив,
собранный `vn release build`, становится Steam-сборкой только за счёт
steam_api-библиотеки рядом с исполняемым файлом. Без неё (или при
`platform.steam.appid: null` в project.yaml) игра — обычный standalone.

> **Статус: не заработает, пока нет App ID.** Приложения в Steamworks ещё нет,
> `platform.steam.appid` (`project.yaml:15`) = `null`, номеров депотов нет,
> steam_api-библиотек Valve на build-машине нет. Поэтому `vn release steam` и
> workflow `steam-upload` сейчас останавливаются с сообщением «заполните App ID» —
> это ожидаемое поведение, а не поломка. Всё ниже — процедура для человека,
> у которого есть аккаунт Steamworks; проверить её без аккаунта нельзя, и там,
> где утверждение непроверяемо, это сказано прямо.

## Что где живёт

| Артефакт | Место | В git? |
|---|---|---|
| App ID, номера депотов | `project.yaml: platform.steam` | да (публичные) |
| VDF для steamcmd | генерируются: `vn release steam --flavor <f>` → `build/steam/` | нет (генерат) |
| steam_api редистрибутивы Valve | `$RENPY_SDK/lib/py3-<platform>/` (кладутся один раз на build-машину из Steamworks SDK: `redistributable_bin/`) | **нет — лицензия Valve** |
| Логин steamcmd | секрет репозитория `STEAM_USERNAME` | **никогда** |
| Сентри Steam Guard (`config.vdf`) | секрет репозитория `STEAM_CONFIG_VDF` (base64) | **никогда** |

## Процесс релиза

```bash
# 1. Обычная сборка (гейт vn release validate внутри):
vn release build --flavor public --package win --package linux --package mac

# 2. Генерация VDF + распаковка контента под депоты + префлайт:
vn release steam --flavor public [--branch beta]

# 3. Аплоад (credentials вне репозитория):
steamcmd +login <account> +run_app_build build/steam/app_build_public.vdf +quit
```

`--branch beta` выставляет `setlive beta`: выкладка уходит в бета-ветку,
release-ветку переключают руками в Steamworks после проверки (в т.ч. на
Steam Deck — обязательный прогон перед setlive default).

Те же три шага из CI — workflow `steam-upload` (`.github/workflows/steam-upload.yml`),
ручной запуск с выбором флейвора и ветки. Он не привязан к тегу намеренно:
выкладка игрокам — решение человека, а не следствие пуша.

## Донастройка человеком

### 1. Steamworks (один раз)

1. Создать приложение → взять **App ID** → `project.yaml: platform.steam.appid`
   (публичное значение, не секрет).
2. **SteamPipe → Depots**: создать по депоту на платформу и вписать номера в
   `project.yaml: platform.steam.depots` ключами `windows` / `linux` / `mac`
   (`tools/vn/src/vn/release.py:153` — других имён генератор VDF не знает).
   Платформа без номера депота просто не уедет (`vn release steam` скажет об этом
   предупреждением).
3. **Launch Options** на каждую ОС: исполняемые файлы даёт launcher distribute
   (`vn.exe` / `vn.sh` / `.app`).
4. Создать ветку **beta** (Builds → Betas): дефолт `--branch beta` кладёт выкладку
   в неё, а не игрокам.
5. Steamworks SDK → `redistributable_bin/` → положить `steam_api64.dll`,
   `libsteam_api.so`, `libsteam_api.dylib` в `$RENPY_SDK/lib/py3-{windows-x86_64,
   linux-x86_64,mac-universal}/` на build-машине. Без них `vn release steam`
   предупреждает, сборка остаётся standalone (`release.py:274` — `steam_libs_status`).
6. Auto-Cloud — см. раздел «Steam Cloud» ниже.
7. Ачивки — см. раздел «Ачивки».

### 2. Аккаунт для аплоада и `config.vdf` (2FA)

steamcmd не умеет вводить код Steam Guard за человека, поэтому вход проходят
**один раз вручную** и переносят в CI полученный сентри-файл `config.vdf`.

```bash
# Отдельный аккаунт-билдер (не личный), приглашённый в партнёрскую группу с
# правами публикации. Тот же steamcmd, что качает workflow:
curl -sL https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz | tar -xz
./steamcmd.sh +login <builder_account>      # пароль + код Steam Guard руками
# ... "Waiting for user info...OK", затем:
quit

# Проверка, что сентри лежит и код больше не спрашивают:
./steamcmd.sh +login <builder_account> +quit

# Упаковать в секрет (base64: config.vdf бинарный, через поле секрета иначе не доедет)
base64 -w0 ~/Steam/config/config.vdf        # macOS: base64 -i ~/Steam/config/config.vdf
```

Секреты репозитория (Settings → Secrets and variables → Actions):

| Секрет | Значение |
|---|---|
| `STEAM_USERNAME` | логин аккаунта-билдера |
| `STEAM_CONFIG_VDF` | вывод `base64` из команды выше |

Без любого из двух секретов workflow **осознанно ничего не публикует**: собирает
дистрибутив, генерирует VDF, печатает `::notice::` и завершается зелёным.
Так шаги сборки можно проверить до того, как появится аккаунт.

Чего ожидать в эксплуатации: если steamcmd в CI просит код Steam Guard или падает
`Account Logon Denied`, значит сентри устарел или снят на стороне Valve —
процедуру выше проходят заново и обновляют секрет. Срок жизни токена Valve не
документирует, проверить его без аккаунта нельзя.

## Steam Cloud

Синхронизация сейвов — **Auto-Cloud** в настройках Steamworks; кода в игре нет
(ADR-0014), Steam забирает файлы по маскам сам.

### Где лежат сейвы на самом деле

`config.save_directory = "vn-1755000000"` (`game/options.rpy:7`) плюс
платформенный корень (`$RENPY_SDK/renpy.py:190-202`, вызывается из
`renpy/main.py:429-430`):

| ОС | Каталог сейвов |
|---|---|
| Windows | `%APPDATA%\RenPy\vn-1755000000` (то есть `AppData\Roaming`, **не** Local) |
| macOS | `~/Library/RenPy/vn-1755000000` |
| Linux, Steam Deck | `~/.renpy/vn-1755000000` |

Что в этом каталоге:

| Файл | Кто пишет | Синхронизировать? |
|---|---|---|
| `<slot>-LT1.save` | движок; суффикс — `renpy/__init__.py:144` | **да** — это и есть сейвы |
| `persistent` | движок (`renpy/savelocation.py:411`) | **да** — галерея, прочитанный текст, настройки |
| `persistent.new` | движок, только если краш случился между двумя rename | не нужно (движок сам предпочтёт его при загрузке, если он остался) |
| `<файл>.<unixtime>.tmp` | движок, промежуточная запись | **нет** — мусор гонки |
| `crash/crash-*.txt` | наш обработчик (`game/framework/00_core/070_crash.rpy:27-34`) | **нет** — диагностика конкретной машины, в облаке бесполезна и жжёт квоту |

Логи в savedir не попадают вовсе: `log.txt`/`errors.txt` пишутся в каталог
установки (`config.logdir = basedir`, `renpy/bootstrap.py:396` →
`renpy.py:218-230`), с фолбэком в системный temp. Токены подписи сейвов лежат
**рядом, но вне** нашего каталога — `<корень>/tokens/security_keys.txt`
(`renpy/savetoken.py:301-306`), и синхронизировать их нельзя (см. риски).

### Готовая конфигурация Auto-Cloud

Построчно, как заполняется в Steamworks (Application → Cloud → Auto-Cloud →
Add Root Path). Recursive держим **выключенным** — иначе под маску попадёт
подкаталог `crash/`.

| # | Root | Path | Pattern |
|---|---|---|---|
| 1 | `WinAppDataRoaming` | `RenPy/vn-1755000000` | `*.save` |
| 2 | `WinAppDataRoaming` | `RenPy/vn-1755000000` | `persistent` |
| 3 | `MacHome` | `Library/RenPy/vn-1755000000` | `*.save` |
| 4 | `MacHome` | `Library/RenPy/vn-1755000000` | `persistent` |
| 5 | `LinuxHome` | `.renpy/vn-1755000000` | `*.save` |
| 6 | `LinuxHome` | `.renpy/vn-1755000000` | `persistent` |

Маска `*.save` покрывает и автосейвы, и быстрые сейвы: имя файла — это
`<слот>` + `-LT1.save`. `persistent` задан точным именем намеренно: `persistent*`
захватил бы и `.tmp`-мусор.

Имена root'ов — из выпадающего списка Steamworks; если интерфейс покажет другие,
прав интерфейс: аккаунта у нас нет, сверить не с чем. Строки 1-2 нужны и для
Steam Deck, если игрок запускает Windows-депот через Proton (сейвы уезжают внутрь
префикса, трансляцию пути делает Steam) — это тоже проверяемо только на живом
приложении; нативный linux-депот на Deck кладёт сейвы по строкам 5-6.

Чего Auto-Cloud не увидит по построению (обе ветки — `renpy.py:173-182`):
каталог `Ren'Py Data` рядом с игрой (портативный режим) и переменную
`RENPY_PATH_TO_SAVES` в Launch Options — они переносят сейвы в другое место.

### Имя `save_directory` менять нельзя

`vn-1755000000` выглядит как временное, но это штатное имя от лаунчера Ren'Py:
`<simple_name>-<unixtime создания проекта>` (`$RENPY_SDK/launcher/game/gui7/parameters.py:113`;
1755000000 = 2025-08-12). Это литерал в `options.rpy`, а не вычисляемое значение,
поэтому оно стабильно между сборками и версиями.

Переименование = смена каталога сейвов: у игроков «пропадают» все сейвы и весь
`persistent` (галерея, прочитанный текст, настройки, разблокировки), а Auto-Cloud
начинает синхронизировать пустой каталог, продолжая держать старый в облаке.
**Рекомендация: не переименовывать никогда**, даже если появится «красивое» имя.
Если однажды это всё же понадобится — задача не в options.rpy, а в миграции:
копирование содержимого старого каталога в новый при первом запуске.

### Риски

- **Два устройства.** Cloud — только синхронизация файлов; конфликт («игрок играл
  на Deck и на ПК без выхода из игры») разруливает клиент Steam, показывая выбор
  версии. Наша сторона от этого не защищает и не должна: система сейвов
  самодостаточна.
- **Разные версии игры на двух устройствах.** Сейв со старой схемой грузится через
  `save_schema` + миграции (G5, ночью это проверяют `vn save check` / `vn save corpus`).
  Обратный случай Cloud создаёт сам: игрок обновился на ПК, а на Deck билд старый —
  тогда приехавший сейв «из будущего» не мигрируется вниз, игра говорит об этом
  игроку и уходит в полный перезапуск (`game/framework/00_core/020_state.rpy:82-93`,
  строка `ui.flow.save_from_newer`). Поведение спроектированное: терять прогресс
  игрока молчаливой загрузкой несовместимого сейва нельзя.
- **Подпись сейвов (важное).** Ключ подписи генерируется **на устройстве** и живёт
  вне синхронизируемого каталога (`renpy/savetoken.py:290-306`). Поэтому сейв,
  приехавший из облака с другого устройства, движок встретит вопросом
  «This save was created on a different device…» (`renpy/common/00gui.rpy:459-460`,
  логика — `savetoken.py:141-185`): игрок один раз подтверждает доверие, ключ
  дописывается в `tokens/security_keys.txt`. Обойти это подстановкой общего ключа
  нельзя — `config.save_token_keys` принимает только verifying-ключи и явно
  отвергает signing-ключ (`savetoken.py:316-337`). Вывод: поведение штатное,
  фиксируем как ожидаемое, в баги не записываем.

## Ачивки

API Name каждой ачивки в Steamworks обязан ПОБУКВЕННО совпадать с id из
`content/achievements/*.yaml`: рантайм регистрирует те же id
(`framework/00_core/035_platform.rpy`), маппингов нет намеренно.
