"""Инварианты конфигов CI: пиннованный тулчейн (G17), наличие ffmpeg до сборки,
триггеры без дублей и раскладка «дорогое — в nightly, MR-пайплайн быстрый» (G15).

Все они — про класс поломок «зелено локально, красно (или ложно-зелено) в CI»: их
нельзя поймать ни одним прогоном vn, потому что ломается не код, а конфиг раннера.
Дешевле держать их тестом по YAML, чем ловить ночью по красному письму.
"""

import re

import yaml

from conftest import REPO_ROOT

# И `vn build`, и `vn release build` (релизный путь зовёт ту же сборку ассетов)
VN_BUILD = re.compile(r"\bvn\s+(?:release\s+)?build\b")

GH_WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
GITLAB_CI = REPO_ROOT / ".gitlab-ci.yml"


def _workflow(name):
    """Разобранный workflow по имени файла."""
    return yaml.safe_load((REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))


def _lines(value):
    """Строки shell из run/script: и скаляр, и список, и многострочный блок."""
    if value is None:
        return []
    if isinstance(value, str):
        return [s.strip() for s in value.splitlines() if s.strip()]
    out = []
    for item in value:
        out.extend(_lines(item))
    return out


def _github_jobs():
    """{'ci.yml:build-test': [строки shell по порядку шагов]} — порядок и есть предмет проверки."""
    jobs = {}
    for wf in GH_WORKFLOWS:
        doc = _workflow(wf.name)
        for job_id, job in (doc.get("jobs") or {}).items():
            cmds = []
            for step in job.get("steps") or []:
                cmds.extend(_lines(step.get("run")))
            jobs[f"{wf.name}:{job_id}"] = cmds
    return jobs


def _gitlab_jobs():
    """То же для GitLab: extends-шаблон разворачивается, before_script идёт перед script."""
    doc = yaml.safe_load(GITLAB_CI.read_text(encoding="utf-8"))
    jobs = {}
    for job_id, job in doc.items():
        if job_id.startswith(".") or not isinstance(job, dict) or "script" not in job:
            continue
        base = doc.get(job.get("extends"), {}) if job.get("extends") else {}
        cmds = _lines(job.get("before_script") or base.get("before_script"))
        cmds += _lines(job.get("script"))
        jobs[f".gitlab-ci.yml:{job_id}"] = cmds
    return jobs


def _all_jobs():
    jobs = _github_jobs()
    jobs.update(_gitlab_jobs())
    return jobs


def test_workflows_are_discovered():
    """Тест бессмысленен, если glob промахнулся мимо конфигов, — фиксируем находку."""
    assert {wf.name for wf in GH_WORKFLOWS} == {"ci.yml", "nightly.yml", "canary.yml",
                                                "release.yml", "steam-upload.yml"}
    assert GITLAB_CI.is_file()


def test_lock_installed_before_editable():
    """G17: откат тулчейна = revert tools/vn.lock. Работает только если лок реально ставится,
    и ставится ДО editable — иначе pip уже отрезолвил >=-диапазоны из pyproject и пины
    декоративны. Порядок проверен вручную: после лока editable не поднимает ни один пакет."""
    sites = 0
    for job, cmds in _all_jobs().items():
        for i, cmd in enumerate(cmds):
            if "pip install" not in cmd or "-e " not in cmd or "tools/vn" not in cmd:
                continue
            sites += 1
            before = cmds[:i]
            assert any("pip install" in c and "tools/vn.lock" in c for c in before), (
                f"{job}: editable-установка без предшествующего "
                f"pip install -r tools/vn.lock — G17 не обеспечен"
            )
    # 7 джоб GitHub (ci x2, nightly x2, canary, release, steam-upload) + 3 GitLab:
    # там строк установки две, но before_script шаблона .with-sdk разворачивается
    # и в build, и в test.
    assert sites == 10, f"изменилось число мест установки тулчейна: {sites} != 10"


def test_ffmpeg_installed_before_vn_build():
    """ADR-0006: в assets_src/video_src лежат сырцы, и видео-ветка конвейера без ffmpeg
    бросает VideoError. Любой пайплайн, который зовёт vn build, обязан поставить ffmpeg
    раньше. GitLab исключён намеренно: конфиг исторический и вне паритета (нет ни LFS,
    ни релиза) — долг разбирается в docs/handbook/04-development-workflow.md §4."""
    checked = 0
    for job, cmds in _github_jobs().items():
        build_at = next((i for i, c in enumerate(cmds) if VN_BUILD.search(c)), None)
        if build_at is None:
            continue
        checked += 1
        assert any("ffmpeg" in c for c in cmds[:build_at]), (
            f"{job}: vn build без установки ffmpeg — видео-ветка конвейера упадёт VideoError"
        )
    assert checked, "ни одна джоба не зовёт vn build — проверка выродилась"


def test_video_sources_present():
    """Инвариант выше держится на факте: сырцы есть, значит видео-ветка не пропускается."""
    srcs = list((REPO_ROOT / "assets_src" / "video_src").rglob("*.mp4"))
    assert srcs, "видео-сырцы исчезли — пересмотрите требование ffmpeg в CI"


def test_ci_runs_on_every_branch_not_only_main():
    """Ветка без прогона CI — это проверки уже после слияния, а не до него.

    Ровно так и вышло с fix/critical-gaps-and-handbook: пуш ветки не поднял ни одного
    прогона, потому что триггер был branches: [main].
    """
    doc = _workflow("ci.yml")
    # YAML 1.1: голое `on:` парсится как True — ключ ищем в обоих написаниях.
    triggers = doc.get("on", doc.get(True))
    branches = triggers["push"]["branches"]
    assert branches == ["**"], f"ci должен ловить любую ветку, а не {branches}"


def test_ci_push_trigger_does_not_catch_tags():
    """На теге v* работает release.yml; ci на том же теге — второй прогон того же самого.

    branches: ['**'] матчит ветки и не матчит теги. Ключ tags не должен появиться.
    """
    doc = _workflow("ci.yml")
    push = (doc.get("on", doc.get(True)))["push"]
    assert "tags" not in push, "ci не должен триггериться на тегах — это работа release.yml"


def test_ci_has_no_pull_request_trigger_while_push_is_unfiltered():
    """push по всем веткам + pull_request = два прогона на каждый PR из этого же репозитория.

    Если pull_request когда-нибудь вернут (ради форков), он обязан прийти с гардом
    head.repo.full_name != github.repository — тогда этот тест нужно осознанно обновить.
    """
    doc = _workflow("ci.yml")
    triggers = doc.get("on", doc.get(True))
    if "pull_request" in triggers:
        guards = [str(job.get("if", "")) for job in (doc.get("jobs") or {}).values()]
        assert all("head.repo.full_name" in g for g in guards), (
            "pull_request вернули без форк-гарда — каждый PR будет прогоняться дважды"
        )


def test_nightly_runs_controller_first_variants():
    """Без прогона с RENPY_VARIANT вёрстку Deck/ТВ не проверяет никто: остальные прогоны
    идут в десктопном профиле, а варианты steam_deck/steam_big_picture движок вставляет
    только при живой Steam-инициализации. Значит «интерфейс сплющился при масштабе 1.4»
    или «оверлей срезан кромкой» доехало бы до игрока.

    Прогоны обязаны стоять в nightly и НЕ в ci: каждый — это отдельный запуск движка,
    а MR-пайплайн держим под 10 минут (G15). Гейта у них нет по замыслу — предмет
    проверки визуальный, поэтому обязателен артефакт со скриншотами.
    """
    job = _workflow("nightly.yml")["jobs"]["controller-first"]
    variants = [str(e["variant"]) for e in job["strategy"]["matrix"]["include"]]
    assert any(v.startswith("steam_deck") for v in variants), (
        f"нет прогона в профиле Steam Deck: {variants}")
    assert any(v == "steam_big_picture" for v in variants), (
        f"нет прогона в профиле Big Picture: {variants}")

    runs = [s for s in job["steps"] if any("vn test smoke" in c for c in _lines(s.get("run")))]
    assert len(runs) == 1, "профиль задаётся матрицей — прогон в джобе ровно один"
    env = runs[0].get("env") or {}
    assert env.get("RENPY_VARIANT") == "${{ matrix.variant }}", (
        "прогон не берёт профиль из матрицы — оба прогона матрицы будут одинаковыми")
    assert env.get("VN_AUTOPILOT_SCREENS"), (
        "без VN_AUTOPILOT_SCREENS прохождение не открывает меню и галерею — "
        "именно их вёрстку и проверяем")
    assert any("upload-artifact" in str(s.get("uses", "")) for s in job["steps"]), (
        "скриншоты без артефакта посмотреть нельзя — джоба выродится в пустой прогон")

    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "RENPY_VARIANT" not in ci, (
        "вариантные прогоны переехали в ci — это минуты движка на каждый пуш (G15)")
