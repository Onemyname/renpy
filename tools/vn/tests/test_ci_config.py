"""Инварианты конфигов CI: пиннованный тулчейн (G17) и наличие ffmpeg до сборки.

Оба инварианта — про класс поломок «зелено локально, красно в CI»: их нельзя поймать
ни одним прогоном vn, потому что ломается не код, а окружение раннера. Дешевле держать
их тестом по YAML, чем ловить ночью по красному письму.
"""

import re

import yaml

from conftest import REPO_ROOT

# И `vn build`, и `vn release build` (релизный путь зовёт ту же сборку ассетов)
VN_BUILD = re.compile(r"\bvn\s+(?:release\s+)?build\b")

GH_WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
GITLAB_CI = REPO_ROOT / ".gitlab-ci.yml"


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
        doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
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
                                                "release.yml"}
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
    # 5 джоб GitHub (ci x2, nightly, canary, release) + 3 GitLab: там строк установки две,
    # но before_script шаблона .with-sdk разворачивается и в build, и в test.
    assert sites == 8, f"изменилось число мест установки тулчейна: {sites} != 8"


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
