"""Доставка генерата из артефакта CI — аварийный путь нормы G4.

Зачем. Компилятор контента — единственный способ получить `game/generated/`, и когда
он сломан, встаёт вся работа: сценарист не может запустить игру, чтобы прочитать свою
же сцену. Последний зелёный генерат при этом лежит артефактом CI (`ci.yml`:
`generated-<sha>`, 30 дней), и раньше его доставали руками — «скачайте артефакт и
распакуйте в game/generated/» из docs/runbooks/pipeline-broken-at-night.md. Ручной
путь остаётся рабочим; эта команда убирает из него шаги, на которых в три часа ночи
ошибаются: найти зелёный прогон нужного коммита, не перепутать sha, не оставить
вперемешку свои и чужие файлы.

Что здесь принципиально:
- **Скачивает `gh`, а не мы.** Токен, refresh и корпоративный SSO — забота gh CLI;
  свой HTTP-клиент к GitHub API означал бы хранение токена и второй путь авторизации.
- **Проверка перед установкой.** Распакованное обязано быть НАШИМ генератом: манифест
  проходит реестр схем, а хеши `outputs` пересчитываются по распакованным байтам теми
  же функциями, которыми их считал компилятор. Плюс защита от zip-slip: пути из чужого
  архива используются как пути записи в `game/`, то есть это ввод, которому нельзя
  доверять.
- **Замена, а не наложение.** Каталог генерата очищается: смешанный генерат (часть
  файлов локальные, часть из CI) дал бы манифест, который врёт про собственные байты.
- **Честная пометка.** В манифест пишется `source.kind = "artifact"`, и после этого
  `vn build --check` / `vn content compile --check` краснеют, даже если байты совпали:
  свежесть относительно локальных источников на чужом генерате не определена. Снять
  пометку может только успешная локальная компиляция.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import __version__
from .content import compile as cc
from .schemas import SchemaRegistry

# Имя артефакта и workflow заданы в .github/workflows/ci.yml (шаг upload-artifact:
# name: generated-${{ github.sha }}, retention-days: 30). Расходиться им нельзя —
# гард-тест сверяет эти константы с YAML.
ARTIFACT_NAME = "generated-{sha}"
WORKFLOW = "ci.yml"
RETENTION_DAYS = 30

SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
LIST_TIMEOUT = 60
DOWNLOAD_TIMEOUT = 600
# Сколько прогонов просматривать, разыскивая зелёный: на одном коммите их бывает
# несколько (повторные запуски, workflow_dispatch), и нужен новейший успешный.
RUN_SCAN_LIMIT = 20


class ArtifactError(RuntimeError):
    """Доставка не состоялась. Текст обязан говорить, что делать дальше."""


@dataclass
class ArtifactInfo:
    sha: str
    run_id: int
    created_at: str
    tool: str
    outputs: int
    rpyc: int


def gh_path() -> Path | None:
    """Путь к gh CLI или None. Отдельной функцией — её зовёт и `vn doctor`-стиль
    диагностика, и тесты подменяют PATH, а не эту функцию."""
    found = shutil.which("gh")
    return Path(found) if found else None


def _gh(root: Path, *args: str, timeout: int = LIST_TIMEOUT) -> str:
    """gh с предсказуемым выводом. Пейджер и notifier обязательно выключены: первый
    вешает неинтерактивный вызов, второй пишет в stderr и портит разбор."""
    exe = gh_path()
    if exe is None:
        raise ArtifactError(
            "не найден gh CLI — им скачивается артефакт (cli.github.com). "
            "Ручной путь остаётся: скачать generated-<sha> из вкладки Actions и "
            "распаковать в game/generated/")
    env = {**os.environ, "GH_PAGER": "cat", "NO_COLOR": "1",
           "GH_NO_UPDATE_NOTIFIER": "1"}
    try:
        proc = subprocess.run([str(exe), *args], cwd=root, env=env,
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ArtifactError(f"gh {' '.join(args)}: не ответил за {timeout} с")
    except OSError as e:
        raise ArtifactError(f"gh {' '.join(args)}: {e}")
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-800:]
        raise ArtifactError(f"gh {' '.join(args)} вернул {proc.returncode}:\n{tail}")
    return proc.stdout


def resolve_sha(root: Path, ref: str) -> str:
    """Полный sha по любой ссылке git (ветка, тег, короткий sha, HEAD~3).

    Артефакт назван полным sha, а человек в аварии называет коммит как удобно."""
    if SHA40_RE.match(ref):
        return ref
    try:
        proc = subprocess.run(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
                              cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        raise ArtifactError(f"git rev-parse {ref}: {e}")
    if proc.returncode != 0:
        raise ArtifactError(f"{ref!r} — не коммит этого репозитория "
                            f"({(proc.stderr or '').strip()[:200]})")
    return proc.stdout.strip()


def find_run(root: Path, sha: str) -> tuple[int, str]:
    """(run_id, created_at) новейшего ЗЕЛЁНОГО прогона ci.yml на этом коммите.

    Красный прогон отбрасывается намеренно: артефакт он публикует не всегда, а если
    публикует — это генерат, который не прошёл ни lint, ни тесты, то есть худший
    возможный источник в аварии."""
    out = _gh(root, "run", "list", "--workflow", WORKFLOW, "--commit", sha,
              "--limit", str(RUN_SCAN_LIMIT),
              "--json", "databaseId,conclusion,status,createdAt")
    try:
        runs = json.loads(out or "[]")
    except ValueError as e:
        raise ArtifactError(f"gh run list отдал не JSON: {e}")
    if not runs:
        raise ArtifactError(
            f"на коммите {sha[:12]} нет прогонов {WORKFLOW} — возможно, он не "
            f"выложен в origin или CI до него не дошёл")
    green = [r for r in runs if r.get("conclusion") == "success"]
    if not green:
        states = ", ".join(sorted({str(r.get("conclusion") or r.get("status"))
                                   for r in runs}))
        raise ArtifactError(
            f"на коммите {sha[:12]} нет зелёных прогонов {WORKFLOW} (состояния: "
            f"{states}) — генерат красной сборки брать нельзя, возьмите прошлый "
            f"зелёный коммит")
    newest = max(green, key=lambda r: str(r.get("createdAt") or ""))
    return int(newest["databaseId"]), str(newest.get("createdAt") or "")


def download(root: Path, sha: str, run_id: int, dest: Path) -> None:
    """Распаковать артефакт прогона в `dest` (gh скачивает и разворачивает сам)."""
    dest.mkdir(parents=True, exist_ok=True)
    _gh(root, "run", "download", str(run_id), "--name", ARTIFACT_NAME.format(sha=sha),
        "--dir", str(dest), timeout=DOWNLOAD_TIMEOUT)
    if not any(dest.iterdir()):
        raise ArtifactError(
            f"артефакт {ARTIFACT_NAME.format(sha=sha)} прогона {run_id} пуст — "
            f"вероятно, он истёк (артефакты живут {RETENTION_DAYS} дней)")


def _unsafe_rel(rel: str) -> bool:
    """Путь из чужого архива, которому нельзя доверять как пути записи."""
    pure = PurePosixPath(rel)
    return pure.is_absolute() or ".." in pure.parts or bool(Path(rel).drive)


def verify(root: Path, unpacked: Path) -> dict:
    """Проверить, что распакованное — наш генерат. Возвращает его манифест.

    Две проверки, и обе обязательны: манифест проходит реестр схем (значит документ
    наш и понятной версии), а хеши `outputs` совпадают с распакованными байтами
    (значит содержимое не побилось и не подменилось). Лишние файлы в артефакте
    законны — `.rpyc` там есть, а в `outputs` их нет."""
    manifest = cc.load_manifest(unpacked)
    if manifest is None:
        raise ArtifactError(
            f"в артефакте нет читаемого {cc.MANIFEST_NAME} — это не генерат "
            f"этого проекта")
    # allow_older: манифест собран прошлой версией тулинга, и требовать от него
    # сегодняшнюю схему бессмысленно — гейт версий существует для авторских
    # документов репозитория, не для исторических артефактов.
    errors = SchemaRegistry(root / "tools" / "schemas").validate(
        manifest, f"артефакт/{cc.MANIFEST_NAME}", allow_older=True)
    if errors:
        raise ArtifactError("манифест артефакта не проходит схему:\n  - "
                            + "\n  - ".join(errors[:5]))
    outputs = manifest.get("outputs") or {}
    if not outputs:
        raise ArtifactError("в манифесте артефакта пустой outputs — брать нечего")
    bad_paths = sorted(rel for rel in outputs if _unsafe_rel(rel))
    if bad_paths:
        raise ArtifactError("в манифесте артефакта пути вне генерата: "
                            + ", ".join(bad_paths[:5]))
    mismatched: list[str] = []
    for rel, digest in sorted(outputs.items()):
        path = unpacked / rel
        if not path.is_file():
            mismatched.append(f"{rel}: нет файла")
        elif cc._b3_file(path) != digest:
            mismatched.append(f"{rel}: хеш не совпал с манифестом")
    if mismatched:
        raise ArtifactError(
            f"артефакт не сходится со своим манифестом ({len(mismatched)} "
            f"расхождений):\n  - " + "\n  - ".join(mismatched[:5]))
    return manifest


def install(root: Path, unpacked: Path, sha: str, run_id: int,
            created_at: str) -> ArtifactInfo:
    """Заменить `game/generated/` распакованным и пометить манифест чужим."""
    gen = root / "game" / "generated"
    manifest = verify(root, unpacked)
    if gen.exists():
        shutil.rmtree(gen)
    gen.parent.mkdir(parents=True, exist_ok=True)
    # copytree, а не move: временный каталог обычно на другом томе, и move там
    # выродился бы в то же копирование, только без наших прав на dst.
    shutil.copytree(unpacked, gen)
    manifest["schema"] = cc.MANIFEST_SCHEMA
    manifest["source"] = {
        "kind": "artifact",
        "sha": sha,
        "run_id": run_id,
        "workflow": WORKFLOW,
        "downloaded_at": created_at or time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                    time.gmtime()),
        "installed_by": __version__,
    }
    (gen / cc.MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")
    outputs = manifest.get("outputs") or {}
    return ArtifactInfo(sha=sha, run_id=run_id, created_at=created_at,
                        tool=str(manifest.get("tool") or "?"),
                        outputs=len(outputs),
                        rpyc=sum(1 for p in gen.rglob("*.rpyc")))


def head_mismatch(root: Path, sha: str) -> str | None:
    """Предупреждение, если артефакт собран НЕ на текущем чекауте, или None.

    Это законный случай: в аварии берут последний зелёный прогон, а он почти всегда
    старше HEAD. Но генерат и рукописный `game/framework` связаны контрактом
    (`vn.API_LEVEL`), и на разъехавшихся версиях игра падает при запуске. Значит,
    сказать об этом надо ДО того, как человек решит, что сломался ещё и артефакт."""
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    head = proc.stdout.strip()
    if proc.returncode != 0 or not head or head == sha:
        return None
    return (f"артефакт собран на коммите {sha[:12]}, а чекаут на {head[:12]}: генерат "
            f"и рукописный game/framework связаны контрактом API_LEVEL, и на разных "
            f"коммитах игра может не запуститься. Совпадение версий надёжнее: "
            f"git checkout {sha[:12]} либо артефакт своего коммита")


def use_artifact(root: Path, ref: str) -> ArtifactInfo:
    """Аварийный путь целиком: ссылка git -> зелёный прогон -> генерат на диске."""
    sha = resolve_sha(root, ref)
    run_id, created_at = find_run(root, sha)
    with tempfile.TemporaryDirectory(prefix="vn-artifact-") as tmp:
        dest = Path(tmp) / "generated"
        download(root, sha, run_id, dest)
        return install(root, dest, sha, run_id, created_at)
