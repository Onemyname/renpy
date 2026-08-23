"""Обвязка CLI (G1/C13): состав дерева команд и проводка флагов в модули.

Принцип под тестом: CLI — тонкий слой. Логику проверяют тесты своих модулей
(test_android, test_corpus, test_voice), а здесь проверяется ровно то, что
живёт только в cli.py и ломается молча: перечень доменов и заглушек (его
цитирует дока), порядок дорогих шагов и соответствие имён опций именам
аргументов модуля. Опечатка в `--vars` -> `variables` не даст ни ошибки, ни
предупреждения — просто корпус другого масштаба."""

from __future__ import annotations

import json
import re
import shutil

import click
import pytest
import yaml
from click.testing import CliRunner

from vn import cli

# Заглушки фаз: команда есть в дереве, но честно отвечает «фаза N» и кодом 3.
# Список ЗАМОРОЖЕН здесь, потому что его цитируют docs/handbook/25-custom-engine.md
# и docs/handbook/37-roadmap.md: реализовали команду — обновите и доку.
EXPECTED_STUBS = {
    "save migrate": 3,
}
# Выведены из нормы, а не реализованы (ADR-0017): `vn migrate` (миграций деклараций
# в дереве нет ни одной, а забытый документ теперь ловит гейт версий схем) и
# `vn shell` (у SDK нет linux-aarch64, поэтому «то же окружение, что на раннере» на
# машине владельца недостижимо). Список ниже — гард: заглушка, вернувшаяся под этими
# именами, обязана споткнуться об этот тест и потребовать пересмотра ADR.
RETIRED_COMMANDS = ("migrate", "shell", "validate")
# `vn test perf` тоже не создаётся (ADR-0019): три измеримых числа снимает прогон
# автопилота, а референсного слабого железа и Android-эмулятора у проекта нет.
RETIRED_TEST_COMMANDS = ("perf",)


def _leaves(command, prefix: str = ""):
    """Плоский список (полное имя, фаза заглушки | None) по всему дереву команд."""
    if isinstance(command, click.Group):
        out = []
        for name, sub in sorted(command.commands.items()):
            out += _leaves(sub, f"{prefix}{name} ")
        return out
    return [(prefix.strip(), getattr(command.callback, "vn_stub_phase", None))]


def test_stub_inventory_matches_frozen_list():
    stubs = {name: phase for name, phase in _leaves(cli.main) if phase}
    assert stubs == EXPECTED_STUBS


def test_retired_commands_stay_retired():
    """Команда, выведенная из нормы решением (ADR-0017), не должна вернуться
    заглушкой: обещание в help — это долг, который кто-то потом читает как факт."""
    names = {name for name, _ in _leaves(cli.main)}
    for retired in RETIRED_TEST_COMMANDS:
        assert f"test {retired}" not in names, (
            f"vn test {retired} снова в дереве — решение фиксирует ADR-0019")
    for retired in RETIRED_COMMANDS:
        assert retired not in names, (
            f"vn {retired} снова в дереве команд — если решение изменилось, "
            f"меняйте ADR-0017, а не только код")


@pytest.mark.parametrize("name", ["voice tts", "test corpus",
                                  "char new", "char validate", "char sheet",
                                  "test screens", "test paths", "test replay",
                                  "content flow",
                                  "release android setup",
                                  "release android status",
                                  "release android preflight",
                                  "release android build"])
def test_new_commands_are_real_not_phase_stubs(name):
    """Подключённые в этой фазе команды: у заглушки был бы exit 3 и ноль опций."""
    phases = dict(_leaves(cli.main))
    assert name in phases, f"{name} нет в дереве команд"
    assert phases[name] is None


def test_top_level_domains_match_architecture_c13(repo_root):
    """C13 — «финальный перечень доменов». Расхождение с кодом обнаруживается
    только чтением обоих текстов, поэтому сверяет тест: домен, появившийся в CLI
    без записи в C13, и наоборот — ошибка доки, а не мелочь."""
    text = (repo_root / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    block = re.search(r"\*\*C13\..*?(?=\n\*\*C1[45]\.)", text, re.S)
    assert block, "в ARCHITECTURE.md не найден раздел C13"
    # Домен — ПЕРВОЕ слово после `vn `: «vn release android status» — это release.
    # Короткие домены дока перечисляет через `|` («vn bootstrap|doctor|dev|…»).
    documented = {name for group in re.findall(r"vn ([a-z|]+)", block.group(0))
                  for name in group.split("|")}
    assert documented == set(cli.main.commands)


def _declarations_only_root(tmp_path, repo_root):
    """Копия боевых деклараций БЕЗ авторских `*.scene.rpy`.

    `vn content flow` зовёт build-bridge (движок) только когда в зонах глав есть
    сцены-исходники. Убрав их, тест идёт целиком настоящим путём — chapter_zones,
    build_model, validate_flow, flow_json на РЕАЛЬНЫХ декларациях проекта, — но не
    поднимает движок (его тут нет) и не засоряет кэш анализа боевого репозитория
    поддельным разбором. Декларации не подделываем: топологию графа задают они,
    и подделка проверяла бы подделку.
    """
    root = tmp_path / "repo"
    root.mkdir()
    shutil.copy(repo_root / "project.yaml", root / "project.yaml")
    shutil.copytree(repo_root / "tools" / "schemas", root / "tools" / "schemas")
    for rel in ("content", "packs"):
        shutil.copytree(repo_root / rel, root / rel,
                        ignore=shutil.ignore_patterns("*.scene.rpy"))
    assert not list(root.rglob("*.scene.rpy")), "исходники сцен остались — тест позовёт движок"
    return root


def test_content_flow_json_writes_the_artifact_it_prints(tmp_path, monkeypatch, repo_root):
    """`--json` — документ для диффа и ревью между сборками, `--out` — его файл.
    У этой пары две тихие поломки, и обе оставляют команду зелёной.

    Первая: `--out` пишет НЕ то, что печатает `--json` (обрезанное, пересериализованное,
    сводку вместо артефакта) — тогда ревью смотрит один документ, а рантайм получает
    другой, и расхождение обнаруживается уже по поведению фичи. Вторая: запись голым
    `Path.write_text` — на Windows артефакт уезжает в CRLF, и следующий дифф сборок
    оказывается полным, то есть бесполезным (repo.write_text_lf, .gitattributes).

    Сводка без `--json` тоже под проверкой: она обязана называть числа посчитанной
    модели, а не нули — иначе прогон в CI печатает бодрый отчёт ни о чём.
    """
    from vn.content.flow import build_model, flow_json

    root = _declarations_only_root(tmp_path, repo_root)
    monkeypatch.chdir(root)
    dest = tmp_path / "flow.json"

    res = CliRunner().invoke(cli.content_flow, ["--json", "--out", str(dest)])
    assert res.exit_code == 0, res.output
    assert str(dest) in res.output                      # где искать записанное
    raw = dest.read_bytes()
    assert b"\r" not in raw, "артефакт записан с CRLF — следующий дифф сборок будет полным"

    # Байт-в-байт тот же документ, что уезжает в генерат: никакой второй сборки
    # модели «для файла» и никакой обрезки. analyses={} — ровно тот вход, что
    # собирает сама команда: исходников сцен в дереве нет, значит мост не зовётся.
    model = build_model(root, analyses={})
    assert raw.decode("utf-8") == flow_json(model)
    doc = json.loads(raw.decode("utf-8"))
    assert doc["schema"] == "flow@1"
    assert doc["scenes"], "модель собрана по пустому дереву — проверять нечего"
    # …и раз мост не звался, модель обязана честно назвать себя неполной: на
    # флаге complete стоит право строить подсказки walkthrough, а без разбора
    # AST авторство выборов неизвестно.
    assert doc["complete"] is False

    printed = CliRunner().invoke(cli.content_flow, ["--json"])
    assert printed.exit_code == 0, printed.output
    assert printed.output == raw.decode("utf-8"), "stdout и --out расходятся"

    # `--out` без `--json`: в файл уезжает артефакт, а не сводка. Раньше эта
    # пара молча не писала ничего и возвращала 0 — то есть CI-шаг «выгрузи граф»
    # был зелёным с пустыми руками.
    only_out = tmp_path / "flow-implied.json"
    res2 = CliRunner().invoke(cli.content_flow, ["--out", str(only_out)])
    assert res2.exit_code == 0, res2.output
    assert only_out.read_bytes() == raw

    summary = CliRunner().invoke(cli.content_flow, [])
    assert summary.exit_code == 0, summary.output
    assert f"сцен: {len(model.scenes)}" in summary.output
    assert f"рёбер: {len(model.edges)}" in summary.output
    # Сводка — обозримый текст для человека: числа плюс не больше WARN_SAMPLES
    # примеров конфликтов. Артефакт (тысяча строк) в этот режим попасть не должен:
    # именно он гоняется в CI, и вывалить туда весь граф — значит утопить в нём
    # предупреждения сборки.
    lines = summary.output.splitlines()
    assert len(lines) <= cli.WARN_SAMPLES + 4, (              # 2 строки чисел + «ещё N» + запас
        f"в сводку вывалилось {len(lines)} строк — похоже на артефакт целиком")


def _strip_default_of_a_read_var(root) -> str:
    """Убрать `default` у переменной, чтение которой ОБЪЯВЛЕНО сценой; вернуть её ref.

    Главу не хардкодим: топологии qa_flow живут вместе с ADR-0021 и меняются, а
    дефект, который сторожит тест, общий для любой сцены.
    """
    from vn.repo import chapter_zones, load_yaml, write_text_lf

    var_docs = {}          # store -> (путь, документ vars@1)
    reads = []
    for _pack_id, zone in chapter_zones(root):
        for f in sorted(zone.glob("*/vars.yaml")):
            doc = load_yaml(f)
            var_docs[doc.get("store")] = (f, doc)
        for f in sorted(zone.glob("*/scenes/*.scene.yaml")):
            reads.extend((load_yaml(f).get("vars") or {}).get("reads") or [])

    for ref in reads:
        store, _, name = ref.partition(".")
        path, doc = var_docs.get(store, (None, None))
        spec = ((doc or {}).get("vars") or {}).get(name) or {}
        # dict/list прекондиции реплея не требуют значения (ADR-0021 §2: только
        # пустота/непустота), поэтому такая переменная ошибки не даст.
        if spec.get("type") in ("dict", "list") or "default" not in spec:
            continue
        del spec["default"]
        write_text_lf(path, yaml.safe_dump(doc, allow_unicode=True, sort_keys=False))
        return ref
    raise AssertionError("ни одна сцена не объявляет чтение скалярной переменной "
                         "с default — фикстура теста устарела")


def test_content_flow_exits_nonzero_when_replay_state_is_unbuildable(tmp_path, monkeypatch,
                                                                     repo_root):
    """Шаг `vn content flow` в ci.yml имеет смысл ровно настолько, насколько команда
    умеет краснеть: ошибка модели графа обязана уйти в код выхода, а не только в
    вывод. Гейт, который печатает «ошибка» и возвращает 0, — ложно-зелёный шаг, и
    это хуже отсутствующего.

    Ошибка взята настоящая и худшая из возможных (ADR-0021 §5): сцена читает
    переменную, которой ни один путь до неё не даёт значения и у которой нет
    `default`. Собрать состояние входа для реплея такой сцены нельзя — без гейта
    это `NameError` в песочнице реплея у игрока.
    """
    root = _declarations_only_root(tmp_path, repo_root)
    monkeypatch.chdir(root)
    # Опорная точка: на нетронутых декларациях гейт зелёный, значит красное ниже —
    # следствие внесённого дефекта, а не общего состояния дерева.
    assert CliRunner().invoke(cli.content_flow, []).exit_code == 0

    ref = _strip_default_of_a_read_var(root)
    res = CliRunner().invoke(cli.content_flow, [])
    assert res.exit_code == 1, res.output
    assert ref in res.output and "default" in res.output, (
        f"команда не назвала переменную {ref} — по выводу непонятно, что править")


def _fake_sdk(tmp_path):
    """SDK без RAPT: renpy.py достаточно, чтобы doctor.sdk_path его признал."""
    sdk = tmp_path / "renpy-sdk"
    sdk.mkdir()
    (sdk / "renpy.py").write_text("", encoding="utf-8")
    (sdk / "renpy.sh").write_text("", encoding="utf-8")
    return sdk


def test_android_status_names_the_fix_and_fails(tmp_path, monkeypatch, repo_root):
    """Без RAPT команда обязана упасть кодом 1 и назвать КОМАНДУ, которая это
    лечит: гейт, который только запрещает, отправляет читать документацию."""
    monkeypatch.setenv("RENPY_SDK", str(_fake_sdk(tmp_path)))
    monkeypatch.chdir(repo_root)

    res = CliRunner().invoke(cli.release_android_status, [])
    assert res.exit_code == 1
    assert "RAPT" in res.output and "setup sdk --download-rapt" in res.output


def test_android_setup_rejects_unknown_step(tmp_path, monkeypatch, repo_root):
    """Шаги подготовки — закрытый список: опечатка в шаге обязана отбиваться
    разбором аргументов, а не запуском движка с мусором."""
    monkeypatch.setenv("RENPY_SDK", str(_fake_sdk(tmp_path)))
    monkeypatch.chdir(repo_root)

    res = CliRunner().invoke(cli.release_android_setup, ["everything"])
    assert res.exit_code == 2
    assert "everything" in res.output


def test_android_build_checks_toolchain_before_full_build(tmp_path, monkeypatch, repo_root):
    """Порядок шагов: assets build + compile идут МИНУТЫ, а проверка тулчейна —
    миллисекунды. Раньше падало после сборки, теперь — до неё."""
    monkeypatch.setenv("RENPY_SDK", str(_fake_sdk(tmp_path)))
    monkeypatch.chdir(repo_root)
    built = []

    @click.command("build")
    @click.option("--check", is_flag=True)
    @click.option("--profile", default="full")
    def fake_build(check, profile):
        built.append(profile)

    monkeypatch.setattr(cli, "build", fake_build)
    res = CliRunner().invoke(cli.release_android_build, [])
    assert res.exit_code == 1
    assert built == [], "полная сборка запущена до проверки тулчейна"


def _fake_measure_report(dest, spec):
    """Пустой, но валидный отчёт: format_table обходит все зоны и стадии."""
    from vn import corpus

    return corpus.MeasureReport(
        spec=spec, layout=corpus.CorpusLayout(), dest=dest,
        zones={zone: corpus.ZoneSize() for zone in corpus.ZONES})


def test_corpus_flags_map_to_spec(tmp_path, monkeypatch, repo_root):
    """Каждый флаг масштаба должен доехать до своего поля CorpusSpec: перепутанные
    --vars/--lines дадут зелёный прогон и неверные измерения."""
    from vn import corpus

    captured = {}

    def fake_run(dest, spec, template_root, profile="full", keep=False):
        captured.update(dest=dest, spec=spec, template_root=template_root,
                        profile=profile, keep=keep)
        return _fake_measure_report(dest, spec)

    monkeypatch.setattr(corpus, "run", fake_run)
    monkeypatch.chdir(repo_root)
    dest = tmp_path / "corpus"

    res = CliRunner().invoke(cli.test_corpus, [
        "--scenes", "7", "--images", "9", "--videos", "2", "--lines", "3",
        "--vars", "5", "--profile", "draft", "--dest", str(dest), "--keep"])
    assert res.exit_code == 0, res.output
    assert captured["spec"] == corpus.CorpusSpec(scenes=7, images=9, videos=2,
                                                lines=3, variables=5)
    assert captured["dest"] == dest and captured["keep"] is True
    assert captured["profile"] == "draft"
    assert captured["template_root"] == repo_root      # шаблон корпуса — сам репозиторий
    assert str(dest) in res.output                     # где искать оставленный корпус


def test_corpus_scale_error_is_message_not_traceback(tmp_path, monkeypatch, repo_root):
    """Невозможный масштаб — ошибка пользователя: сообщение и код 1, без каталога."""
    monkeypatch.chdir(repo_root)
    dest = tmp_path / "corpus"

    res = CliRunner().invoke(cli.test_corpus, ["--scenes", "1", "--dest", str(dest)])
    assert res.exit_code == 1
    assert "минимум" in res.output
    assert not dest.exists()


def test_voice_tts_flags_map_to_synth_drafts(monkeypatch, repo_root):
    """--regenerate-drafts инвертирует only_missing, а неуказанный --rate обязан
    стать штатным темпом голоса, а не None (иначе бэкенд получил бы None)."""
    from vn import voice

    captured = {}

    def fake_synth(root, chapter_id, **kwargs):
        captured.update(root=root, chapter_id=chapter_id, **kwargs)
        rep = voice.TtsReport(backend="say", voice="Milena")
        rep.generated.append("ch01_s010_0001")
        rep.updated_manifests.append("content/chapters/ch01/voice/ru.voice.yaml")
        return rep

    monkeypatch.setattr(voice, "synth_drafts", fake_synth)
    monkeypatch.chdir(repo_root)

    res = CliRunner().invoke(cli.voice_tts, ["ch01", "--char", "mira",
                                            "--regenerate-drafts"])
    assert res.exit_code == 0, res.output
    assert captured["chapter_id"] == "ch01" and captured["char"] == "mira"
    assert captured["only_missing"] is False
    assert captured["rate"] == voice.TTS_DEFAULT_RATE
    assert captured["allow_download"] is False
    # Дубли лежат мастерами: без транскода игрок их не услышит — это должно быть
    # сказано в выводе, а не только в доке.
    assert "vn assets build" in res.output


def test_help_is_utf8_even_when_console_asks_cp1251(repo_root):
    """click печатает --help на этапе РАЗБОРА аргументов, до вызова callback
    группы, поэтому перекодировка stdout обязана случиться на импорте модуля.
    Пока она жила только в callback, `vn --help` на cp1251-консоли выходил
    кракозябрами — то есть первое, что видит новый человек в проекте.

    Проверка поведением, а не поиском строки в исходнике: греп остался бы зелёным
    и при выпотрошенной перекодировке."""
    import os
    import subprocess
    import sys

    env = dict(os.environ, PYTHONIOENCODING="cp1251")
    res = subprocess.run([sys.executable, "-m", "vn.cli", "--help"],
                         capture_output=True, env=env,
                         cwd=str(repo_root / "tools" / "vn"))
    assert res.returncode == 0, res.stderr[:400]
    text = res.stdout.decode("utf-8")      # упадёт, если поток ушёл в cp1251
    assert "Единственный CLI проекта" in text
