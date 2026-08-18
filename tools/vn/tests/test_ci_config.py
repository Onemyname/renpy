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

# Конфиги ДРУГИХ систем CI, которых в этом репозитории быть не должно. Второй
# пайплайн, который никто не запускает, — не портативность, а ловушка: он отстаёт
# по составу шагов, при этом выглядит рабочим и попадает в документацию как
# главный. Именно так и вышло с `.gitlab-ci.yml` (выведен из эксплуатации
# 2026-08-18): три джобы против восьми, без LFS, ffmpeg, локализационных проверок,
# smoke, сейв-корпуса и релиза, — а `ci/README.md` называл его конфигом пайплайна.
# Портативность даёт CLI: перенос пайплайна — это те же команды `vn` в конфиге
# новой системы, а не второй файл про запас.
FOREIGN_CI = (".gitlab-ci.yml", ".circleci", "azure-pipelines.yml", "Jenkinsfile",
              "bitbucket-pipelines.yml", ".drone.yml")

# Куда положена каждая команда, у которой внешний тулчейн или прогон масштаба:
# дешёвая диагностика — в MR-пайплайн, дорогое измерение — в nightly (G15).
# Список ЗАМОРОЖЕН здесь: команда, реализованная без покрытия в CI, не ломает ни
# один прогон — она просто никогда не запускается, и это выясняется у игрока.
COMMAND_PLACEMENT = {
    "vn release android preflight": "ci.yml",
    "vn release android status": "ci.yml",
    "vn release android build": "ci.yml",
    "vn voice tts": "ci.yml",
    "vn test corpus": "nightly.yml",
}

# Потолок масштаба ночного корпуса. 7.6 ARCHITECTURE.md приводит замеры (macOS
# arm64, профиль full, 8 реплик на сцену): 100 сцен — 1,2 с, 2000 — 11,1 с,
# 7000 — 21,2 МБ генерата и 277 МБ RSS. До 2000 сцен прогон остаётся секундами
# на любом раннере; выше — это уже не «ночная проверка», а исследование, и его
# место в ручном запуске с --keep, а не в расписании.
CORPUS_SCENES_CEILING = 2000


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


def _github_commands(workflow):
    """Все строки shell одного workflow, по всем его джобам."""
    return [cmd for job, cmds in _github_jobs().items()
            if job.startswith(f"{workflow}:") for cmd in cmds]


def _github_steps(needle, workflow=None):
    """[(имя workflow, шаг)] — шаги, в run которых встречается подстрока.

    Шаг целиком, а не строки shell: у него есть ещё working-directory и
    continue-on-error, и они тоже меняют смысл прогона.
    """
    names = [workflow] if workflow else [wf.name for wf in GH_WORKFLOWS]
    return [(name, step)
            for name in names
            for job in (_workflow(name).get("jobs") or {}).values()
            for step in (job.get("steps") or [])
            if any(needle in cmd for cmd in _lines(step.get("run")))]


def test_workflows_are_discovered():
    """Тест бессмысленен, если glob промахнулся мимо конфигов, — фиксируем находку."""
    assert {wf.name for wf in GH_WORKFLOWS} == {"ci.yml", "nightly.yml", "canary.yml",
                                                "release.yml", "steam-upload.yml"}


def test_lock_installed_before_editable():
    """G17: откат тулчейна = revert tools/vn.lock. Работает только если лок реально ставится,
    и ставится ДО editable — иначе pip уже отрезолвил >=-диапазоны из pyproject и пины
    декоративны. Порядок проверен вручную: после лока editable не поднимает ни один пакет."""
    sites = 0
    for job, cmds in _github_jobs().items():
        for i, cmd in enumerate(cmds):
            if "pip install" not in cmd or "-e " not in cmd or "tools/vn" not in cmd:
                continue
            sites += 1
            before = cmds[:i]
            assert any("pip install" in c and "tools/vn.lock" in c for c in before), (
                f"{job}: editable-установка без предшествующего "
                f"pip install -r tools/vn.lock — G17 не обеспечен"
            )
    # 8 джоб GitHub: ci x2, nightly x3, canary, release, steam-upload.
    assert sites == 8, f"изменилось число мест установки тулчейна: {sites} != 8"


def test_ffmpeg_installed_before_vn_build():
    """ADR-0006: в assets_src/video_src лежат сырцы, и видео-ветка конвейера без ffmpeg
    бросает VideoError. Любой пайплайн, который зовёт vn build, обязан поставить ffmpeg
    раньше."""
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


def test_commands_run_in_the_pipeline_they_belong_to():
    """Раскладка G15 по командам: реализованная команда без прогона в CI не ломает
    ничего — она просто никогда не запускается, и её поломку находит уже человек.
    Обратная ошибка так же молчалива: измерительный прогон, переехавший в ci,
    съедает бюджет MR-пайплайна не заметно для автора правки."""
    for command, expected in COMMAND_PLACEMENT.items():
        found = {wf for wf in ("ci.yml", "nightly.yml")
                 if any(command in cmd for cmd in _github_commands(wf))}
        assert expected in found, (
            f"«{command}» не запускается в {expected} — команда есть, прогона нет")
        if expected != "ci.yml":
            assert "ci.yml" not in found, (
                f"«{command}» переехала в MR-пайплайн — это дорого на каждый пуш (G15)")


def test_android_preflight_runs_after_build():
    """На пустом game/ предполётная проверка мобильного канала зелена всегда: и
    размер против потолка, и модель памяти считаются ПО СОБРАННОМУ дереву. Шаг,
    уехавший выше сборки, не краснеет — он становится ложно-зелёным, а это хуже
    отсутствующего шага."""
    checked = 0
    for job, cmds in _github_jobs().items():
        at = next((i for i, c in enumerate(cmds)
                   if "vn release android preflight" in c), None)
        if at is None:
            continue
        checked += 1
        assert any(VN_BUILD.search(c) for c in cmds[:at]), (
            f"{job}: vn release android preflight до сборки — потолок канала и бюджет "
            f"памяти будут посчитаны по пустому game/")
    assert checked, "ни одна джоба не зовёт android preflight — проверка выродилась"


def test_missing_external_toolchains_are_asserted_not_silenced():
    """RAPT и piper на раннере отсутствуют, и проверяется ровно одно: команда честно
    называет отсутствующий тулчейн НЕнулевым кодом. Такой шаг ломается ровно двумя
    способами, и оба тихие: `|| true`/continue-on-error глушат провал (шаг всегда
    зелёный и ничего не проверяет), а `vn voice tts` без `--backend` берёт первый
    доступный на машине бэкенд — стоит образу раннера обзавестись piper, и шаг
    начнёт молча писать синтезированные мастера в assets_src (LFS-зона)."""
    for command in ("vn release android status", "vn release android build",
                    "vn voice tts"):
        steps = _github_steps(command, "ci.yml")
        assert len(steps) == 1, f"«{command}»: ожидался ровно один шаг, нашлось {len(steps)}"
        _, step = steps[0]
        assert not step.get("continue-on-error"), (
            f"«{command}»: continue-on-error — провал тулчейна перестал быть провалом")
        for cmd in _lines(step.get("run")):
            if command in cmd:
                assert "|| true" not in cmd, (
                    f"«{command}»: провал заглушен `|| true` — шаг ничего не проверяет")
                if command == "vn voice tts":
                    assert "--backend" in cmd, (
                        "vn voice tts без --backend возьмёт любой бэкенд раннера и "
                        "запишет мастера в assets_src — бэкенд обязан быть пиннован")


def _pytest_invocations():
    """[(пайплайн, команда, cwd шага)] — каждый прогон pytest во всех пайплайнах.

    Форм две, потому что таковы механизмы GitHub: каталог шага задаётся полем
    working-directory, а внутри многострочного блока — только подоболочкой (иначе
    cd увёл бы и остальные команды блока)."""
    return [(workflow, cmd, step.get("working-directory"))
            for workflow, step in _github_steps("pytest")
            for cmd in _lines(step.get("run")) if "pytest" in cmd]


def test_pytest_runs_from_tools_vn_in_every_pipeline():
    """Прогон набора обязан совпадать с локальным во всех пайплайнах: pytest
    запускается ИЗ tools/vn.

    Исторически это было жёстче: набор импортировал сам себя как пакет
    (tests.test_compile), и запуск из корня падал ModuleNotFoundError — по одному
    красному тесту, невоспроизводимому локально. Импорты починены
    (test_verify_regressions.test_suite_never_imports_itself_as_package), но
    инвариант остаётся: одинаковый cwd = одинаковые rootdir, sys.path и кэш
    pytest, то есть красное в CI воспроизводится одной командой разработчика.
    Разъехавшийся cwd — это снова «зелено локально, красно в CI», ради чего и
    существует этот файл.
    """
    runs = _pytest_invocations()
    assert runs, "ни один пайплайн не гоняет pytest — проверка выродилась"
    for pipeline, cmd, workdir in runs:
        assert "cd tools/vn" in cmd or workdir == "tools/vn", (
            f"{pipeline}: pytest запускается не из tools/vn ({cmd!r}) — прогон "
            f"перестаёт совпадать с локальным")


def test_nightly_corpus_scale_is_explicit_and_bounded():
    """Масштаб корпуса — это и есть содержание прогона, поэтому он задаётся явно, а
    не дефолтами команды (дефолты меняются вместе с CLI, ночная проверка — нет).
    Потолок держит ночь конечной: без него безобидная правка числа превращает
    измерение в исследование на десятки минут."""
    runs = [cmd for cmd in _github_commands("nightly.yml") if "vn test corpus" in cmd]
    assert len(runs) == 1, f"ожидался ровно один ночной прогон корпуса, нашлось {len(runs)}"
    scenes = re.search(r"--scenes\s+(\d+)", runs[0])
    assert scenes, "масштаб не задан явно — прогон поедет на дефолтах vn test corpus"
    assert int(scenes.group(1)) <= CORPUS_SCENES_CEILING, (
        f"--scenes {scenes.group(1)} > потолка {CORPUS_SCENES_CEILING}: ночной прогон "
        f"перестаёт быть проверкой и становится исследованием (7.6)")


def test_no_second_ci_platform_config():
    """Один пайплайн — одна система CI.

    Мёртвое зеркало опаснее его отсутствия: оно отстаёт по составу шагов, при этом
    выглядит рабочим и попадает в документацию как главный конфиг — и ночью по
    красному письму человек чинит не тот пайплайн. Появится нужда в другой системе
    CI — переносится ЦЕЛИКОМ, вместе с этим тестом.
    """
    found = [name for name in FOREIGN_CI if (REPO_ROOT / name).exists()]
    assert not found, (
        f"второй конфиг CI: {', '.join(found)} — либо он полный и заменяет GitHub "
        f"Actions, либо его нет; наполовину живой пайплайн ночью починят вместо "
        f"настоящего")
