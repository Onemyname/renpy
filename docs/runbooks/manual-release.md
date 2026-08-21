# Runbook: релиз вручную (без CI)

CI отключён ([ADR-0020](../adr/0020-ci-disabled-manual-releases.md)) — релиз
собирается и публикуется с локальной машины. Процедура проверена на v1.0.0
(2026-08-20, Windows 11). Каждая команда ниже существует и прогонялась.

## 0. Тулчейн (один раз на машину)

| Что | Откуда | Куда |
|---|---|---|
| Python 3.12 | `winget install Python.Python.3.12 --scope user` | `%LOCALAPPDATA%\Programs\Python\Python312` |
| ffmpeg | `winget install Gyan.FFmpeg --scope user` | winget Packages, добавить `bin` в PATH |
| Ren'Py SDK **8.5.3** (пин `project.yaml: renpy_sdk`) | renpy.org/dl/8.5.3 | `~/.renpy-sdk/renpy-8.5.3-sdk` — ВНЕ репозитория |
| venv проекта | `python -m venv .venv` → `pip install -r tools/vn.lock` → `pip install -e "tools/vn[dev]"` | `.venv/` (в .gitignore) |
| git-hook | `sh ci/hooks/install.sh` | `.git/hooks/pre-push` |

Окружение сессии (Git Bash):

```bash
export PATH="$PWD/.venv/Scripts:$PATH"
export RENPY_SDK="$HOME/.renpy-sdk/renpy-8.5.3-sdk"
export SDL_AUDIODRIVER=dummy PYTHONIOENCODING=utf-8
vn doctor        # все пункты ✓, включая SDK и шрифты
```

## 1. Подготовка версии

Чистое дерево (`git status` пуст), затем **строго в этом порядке**:

1. Бамп `project.yaml: version` (semver: фиксы = patch, новая глава = minor).
2. При мажорном бампе проверить `packs/*/manifest.yaml: requires.core` —
   диапазон вида `<N` отсекает паки от нового мажора (на 1.0.0 ловилось G9).
3. `vn release changelog` — раздел CHANGELOG + `ci/release-manifest.json` +
   автоштамп `content/registry/id_registry.json` (G7). Порядок обязателен:
   прогон ДО бампа съедает дифф.
4. Свернуть заметки из «## Не выпущено» в раздел новой версии (руками).
5. Новая глава готова к продаже? — `status: release` в её `chapter.yaml`
   (включает G7 и строгие граф-проверки именно для неё).

## 2. Полный гейт (замена ночной матрицы, ADR-0020)

```bash
vn build
vn loc keys --check
"$RENPY_SDK/renpy.exe" . lint
vn test smoke --picks 0,0        # на Windows работает без xvfb
vn save check
(cd tools/vn && python -m pytest tests -q)
vn release validate --flavor public
vn release validate --flavor patron
```

**Красный гейт** — не обходить, а чинить причину; сообщения самодостаточны
(FAIL называет команду-лекарство). Типовые: «генерат несвеж» → `vn build`
(реестр/статусы — вход компилятора); «тег уже существует» у changelog →
версию забыли бампнуть. `--force` у changelog — только для перезаписи уже
выпущенной версии, он съедает дифф.

## 3. Коммит и тег

Подпись — переменными окружения, `git config` не трогать:

```bash
export GIT_AUTHOR_NAME="Onemyname" GIT_AUTHOR_EMAIL="98846207+onemyname@users.noreply.github.com" GIT_COMMITTER_NAME="Onemyname" GIT_COMMITTER_EMAIL="98846207+onemyname@users.noreply.github.com"
git add -A && git commit -m "release: <версия>"
git tag -a v<версия> -m "VN <версия>"
git push origin main && git push origin v<версия>
```

## 4. Сборка дистрибутивов

```bash
vn release build --flavor public --package win --package linux --package mac --timeout 1800
vn release build --flavor patron --package win --package linux --package mac --timeout 1800
```

Каждый вызов сам прогоняет `vn build` + полный гейт (FAIL останавливает),
восстанавливает `.rpyc` прошлого релиза из `ci/rpyc-cache/<флейвор>/` (G6)
и пишет свежий снимок туда же. Выход: `build/dist/<версия>-<флейвор>/`.

**Сразу после сборки** закоммитить обновлённые линии — это носитель
save-совместимости, потеря = сломанные сейвы игроков:

```bash
git add ci/rpyc-cache && git commit -m "release: rpyc-линии <версия>" && git push origin main
```

`.dmg` локально не собрать (нужен `hdiutil`/macOS) — пользователям macOS
идёт `mac.zip`. `--patron-token` добавлять при наличии секрета (ADR-0011).

## 5. Публикация (GitHub REST API, `gh` не установлен)

Токен — из git credential manager (scopes `repo`):

```bash
TOK=$(printf 'protocol=https\nhost=github.com\n\n' | git credential fill | sed -n 's/^password=//p')
```

1. `POST /repos/Onemyname/renpy/releases` — `tag_name: v<версия>`,
   `name: "VN v<версия>"`, body из раздела CHANGELOG.
2. `POST uploads.github.com/.../releases/<id>/assets?name=<файл>` — по одному
   на ассет, `Content-Type: application/zip|application/x-bzip2`.
   Patron-файлы переименовывать: `vn-<версия>-patron-<платформа>.*`.
3. Сверить sha256 хотя бы одного скачанного ассета с локальным файлом.

> ⚠️ **ПРЕДОХРАНИТЕЛЬ (ADR-0020): patron = NSFW.** Класть patron-ассеты в
> GitHub Release допустимо ТОЛЬКО пока репозиторий приватный. Перед любой
> сменой видимости на public — СНАЧАЛА удалить patron-ассеты из всех релизов,
> ПОТОМ менять видимость. Проверка: `GET /repos/.../releases` не содержит
> файлов с `patron` в имени.

## 6. Чеклист перед тегом

- [ ] `git status` чист; `vn doctor` без ✗
- [ ] версия бампнута ДО `vn release changelog`; заметки свёрнуты из «Не выпущено»
- [ ] полный гейт раздела 2 зелёный целиком (не выборочно)
- [ ] `ci/rpyc-cache/` содержит линии ПРОШЛОГО релиза (иначе сборка честно
      скажет «первый релиз» — и сейвы прошлой версии не перенесут имена)
- [ ] после сборки: свежие линии закоммичены и запушены
- [ ] patron не уходит в публичный доступ (см. предохранитель выше)
