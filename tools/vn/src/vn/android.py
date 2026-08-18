"""Android-поставка: предполётные проверки и запуск ШТАТНОЙ сборки Ren'Py (RAPT).

Что здесь есть и чего здесь нет. APK/AAB собирает не этот модуль, а RAPT — тулчейн
Ren'Py (Android SDK, gradle, keytool). Единственный поддерживаемый способ запустить
его из командной строки — команда ЛАУНЧЕРА `android_build`
(SDK: launcher/game/android.rpy: android_build_command + register_command;
doc/cli.html, раздел «Android Build»):

    <SDK>/renpy.sh <SDK>/launcher android_build <root> [--bundle] [--install]
                                                [--launch] [--destination DIR]

Подготовка (`vn release android setup <шаг>`) у Ren'Py тоже есть, только не в CLI:
RAPT приезжает апдейтером лаунчера (`add_dlc("rapt")`), Android SDK ставится
кнопкой Install SDK, ключи подписи — Generate Keys, конфиг приложения — Configure.
Мы не переписываем эти шаги, а вызываем ТЕ ЖЕ функции RAPT, что и лаунчер
(`rapt.install_sdk.install_sdk`, `rapt.keys.generate_keys`,
`rapt.configure.configure` — launcher/game/android.rpy, label android_installsdk /
android_keys / android_configure), просто без GUI: `setup_step` запускает движок с
командой `vn_android_toolchain` (game/framework/90_debug/040_android_toolchain.rpy).
Так шаг автоматизируется и остаётся штатным: на апдейте SDK меняется реализация
RAPT, а не наша обвязка. Интерактивность шагов сохранена намеренно — установщик
Android SDK требует принять Terms and Conditions, а генератор ключей — подтвердить,
что владелец сделает бэкап; за человека такое не отвечают.

Секретов в репозитории нет и быть не может: android.keystore / bundle.keystore
создаёт лаунчер, они остаются у владельца. Что они не уедут в git — проверяет
`keystore_leaks`; что они не уедут игрокам — исключение в game/options.rpy
(`build.classify("**.keystore", None)`: движок исключает такие файлы только в корне
проекта, а положенный не туда ключ попал бы под общее `("**", "all")`).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .assets.render_config import RenderConfig, load_render_config

# ── Потолки каналов поставки (doc/android.html: Building Android Applications) ──
# Universal APK и Play-бандл — до 2 ГБ. Бандл при этом делится на 4 fast-follow
# пакета по 500 МБ, и один файл целиком живёт в одном пакете: файл крупнее 500 МБ
# в бандл не влезает вообще, сколько бы места ни оставалось.
PACKAGE_LIMIT_MB = 2048
BUNDLE_PACK_LIMIT_MB = 500
# Доля потолка, после которой канал считается «на грани»: до релиза ещё доедут
# главы, и узнать про потолок лучше сейчас, а не на последней сборке.
PACKAGE_WARN_SHARE = 0.8
# Накладные расходы пакета помимо game/: движок, CPython, нативные библиотеки под
# три ABI (armv7a/arm64/x86_64), ресурсы Android. Точная величина известна только
# собранному пакету, поэтому это ОЦЕНКА СВЕРХУ для порога, а не измерение.
PACKAGE_OVERHEAD_MB = 150

# Мобильный пакет не содержит @N-вариантов (game/options.rpy: classify оверсэмпла
# в desktop-списки), поэтому движок грузит безсуффиксный референс — масштаб 1.
# Модель памяти считается ровно для того, что реально уедет на устройство.
MOBILE_SCALE = 1

# JDK: doc/android.html, Step 1 — «You'll need version 21 of the JDK». RAPT
# проверяет то же самое сам (rapt.plat.jdk_requirement) и отказывается собирать,
# но узнать об этом до часа gradle-сборки дешевле.
JDK_REQUIRED = 21

# Ключи подписи (vn release android setup keys). Лежат в КОРНЕ проекта:
# launcher/game/android.rpy: rapt.keys.keys_exist(project.current.path), и
# NO_KEY_TEXT «copy android.keystore and bundle.keystore to the base directory».
KEYSTORES = {
    "android.keystore": "universal APK",
    "bundle.keystore": "Play-бандла (.aab)",
}

# Конфиг приложения (vn release android setup config): имя пакета, версия,
# ориентация, permissions. Обе раскладки имени штатные — 00build.rpy классифицирует
# и android.json, и .android.json в список "android".
ANDROID_CONFIG_NAMES = ("android.json", ".android.json")

# Оформление мобильного приложения (doc/android.html: Icon / Presplash). Без этих
# файлов Ren'Py подставит свои — узнаваемо чужие в сторе и в списке приложений.
ANDROID_ART = {
    "android-icon_foreground.png": "передний слой adaptive-иконки (432x432, с альфой)",
    "android-icon_background.png": "фон adaptive-иконки (432x432, без альфы)",
    "android-presplash.jpg": "экран загрузки (первый запуск распаковывает файлы — "
                             "виден дольше всего)",
}

# Каталоги внутри game/, которых в поставке нет по определению: сейвы разработчика
# движок не пакует (00build.rpy: ("game/saves/", None)), а весить они могут
# десятки мегабайт — в оценке размера пакета это был бы чистый шум.
LOCAL_ONLY_DIRS = ("saves",)

MB = 1024 * 1024


class AndroidError(RuntimeError):
    pass


# ── Тулчейн ───────────────────────────────────────────────────────────────────

def _javac() -> Path | None:
    """JAVA_HOME важнее PATH: именно его лаунчер советует, когда в системе
    несколько JDK (launcher/game/androidstrings.rpy, сообщение о версии Java)."""
    home = os.environ.get("JAVA_HOME")
    if home:
        cand = Path(home) / "bin" / ("javac.exe" if os.name == "nt" else "javac")
        if cand.is_file():
            return cand
    found = shutil.which("javac")
    return Path(found) if found else None


def jdk_major() -> int | None:
    """Мажорная версия javac (None — javac не найден). Разбор терпит оба формата:
    современный `javac 21.0.5` и старый `javac 1.8.0_292`, где мажор — вторая
    цифра; Java 8 к тому же печатала версию в stderr."""
    exe = _javac()
    if exe is None:
        return None
    try:
        proc = subprocess.run([str(exe), "-version"], capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"javac\s+(\d+)(?:\.(\d+))?", (proc.stdout or "") + (proc.stderr or ""))
    if not m:
        return None
    major, minor = int(m.group(1)), m.group(2)
    return int(minor) if major == 1 and minor else major


def rapt_hash_matches(sdk: Path) -> bool:
    """Совпадает ли установленный RAPT с этим SDK. Лаунчер импортирует RAPT только
    при совпадении хешей (launcher/game/mobilebuild.rpy: check_hash_txt —
    launcher/game/rapt_hash.txt против rapt/hash.txt), иначе ведёт себя так, будто
    RAPT нет вовсе. Нет hash-файла у лаунчера — dev-раскладка SDK, проверки нет."""
    expected = sdk / "launcher" / "game" / "rapt_hash.txt"
    if not expected.is_file():
        return True
    actual = sdk / "rapt" / "hash.txt"
    if not actual.is_file():
        return False
    return (expected.read_text(encoding="utf-8", errors="replace").strip()
            == actual.read_text(encoding="utf-8", errors="replace").strip())


def find_adb(sdk: Path) -> Path | None:
    """adb как признак установленного Android SDK (лаунчер судит по нему же:
    `if not os.path.exists(rapt.plat.adb)` -> ANDROID_NO_SDK).

    Путь знает RAPT (rapt/plat.py), поэтому ищем по ДОКУМЕНТИРОВАННОЙ раскладке, а
    не по угаданному имени каталога: rapt/sdk.txt — одна строка с путём к уже
    установленному Android SDK (doc/android.html, Step 2), иначе platform-tools
    внутри rapt/, куда кладёт Install SDK."""
    rapt = sdk / "rapt"
    bases = []
    sdk_txt = rapt / "sdk.txt"
    if sdk_txt.is_file():
        lines = [ln.strip() for ln in
                 sdk_txt.read_text(encoding="utf-8", errors="replace").splitlines()
                 if ln.strip()]
        if lines:
            bases.append(Path(lines[0]).expanduser())
    bases.append(rapt)
    for base in bases:
        for pattern in ("platform-tools/adb*", "*/platform-tools/adb*"):
            for cand in sorted(base.glob(pattern)):
                if cand.is_file():
                    return cand
    return None


RAPT_URL = "https://www.renpy.org/dl/{version}/renpy-{version}-rapt.zip"

# Команда движка, проводящая подготовительные шаги RAPT: они работают ТОЛЬКО
# внутри процесса Ren'Py (game/framework/90_debug/040_android_toolchain.rpy —
# dev-зона, в дистрибутив не попадает). Порядок шагов = порядок прохождения:
# без Android SDK нет keytool для ключей.
TOOLCHAIN_COMMAND = "vn_android_toolchain"
SETUP_STEPS = ("sdk", "keys", "config")


def install_rapt(sdk: Path, version: str) -> list[str]:
    """Скачать и распаковать RAPT в <SDK>/rapt. Возвращает список сообщений.

    RAPT в архив SDK не входит: renpy.org отдаёт его отдельным zip той же
    версии. Лаунчер качает его своим апдейтером по кнопке; здесь — то же самое
    из CLI, чтобы шаг «поставить тулчейн» не требовал GUI."""
    import io
    import urllib.request
    import zipfile

    dest = sdk / "rapt"
    if dest.is_dir():
        return [f"RAPT уже установлен: {dest}"]
    url = RAPT_URL.format(version=version)
    with urllib.request.urlopen(url) as resp:          # noqa: S310 — фиксированный host renpy.org
        data = resp.read()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        # В архиве один верхний каталог rapt/ — распаковываем в SDK как есть.
        zf.extractall(sdk)
    if not dest.is_dir():
        raise AndroidError(f"{url}: в архиве нет каталога rapt/")
    return [f"RAPT установлен из {url}"]


def setup_step(root: Path, sdk: Path, step: str) -> int:
    """Провести подготовительный шаг RAPT внутри движка, ИНТЕРАКТИВНО.

    Интерактивность принципиальна: шаг `sdk` просит принять Android SDK Terms and
    Conditions, шаг `keys` — подтвердить, что владелец сохранит копию ключа. Это
    решения человека, поэтому stdin/stdout не перехватываются — команда отдаёт
    управление RAPT и возвращает его код выхода."""
    import os

    if step not in SETUP_STEPS:
        raise AndroidError(f"неизвестный шаг {step!r} — есть {', '.join(SETUP_STEPS)}")
    rapt = sdk / "rapt"
    if not rapt.is_dir():
        raise AndroidError(f"нет {rapt} — сначала vn release android setup sdk --download-rapt")
    exe = sdk / ("renpy.exe" if os.name == "nt" else "renpy.sh")
    if not exe.is_file():
        raise AndroidError(f"нет {exe} — проверьте RENPY_SDK")
    # cwd = rapt/: RAPT строит пути к buildlib, android-sdk и project от текущего
    # каталога (rapt/android.py делает то же самое своим chdir).
    return subprocess.call([str(exe), str(root), TOOLCHAIN_COMMAND, str(rapt), step],
                           cwd=rapt)


def rapt_status(sdk: Path | None, root: Path | None = None) -> list[str]:
    """Чего не хватает для сборки Android-пакета; пустой список = можно собирать.

    Каждая строка говорит И что отсутствует, И какой командой это ставится: гейт,
    который только запрещает, заставляет искать шаг по документации. `root`
    (корень проекта) не обязателен: без него проверяется только SDK-часть."""
    if sdk is None:
        return ["RENPY_SDK не задан — Android-тулчейн живёт внутри SDK (vn doctor подскажет)"]

    gaps: list[str] = []
    rapt = sdk / "rapt"
    launcher = sdk / ("renpy.exe" if sys.platform == "win32" else "renpy.sh")
    if not rapt.is_dir():
        # Дальше проверять нечего: без rapt/ нет ни Android SDK, ни keytool-обвязки.
        return [f"нет {rapt} — RAPT (тулчейн Android) не установлен: "
                f"vn release android setup sdk --download-rapt (или лаунчер "
                f"{launcher}, раздел Android)"]
    if not rapt_hash_matches(sdk):
        gaps.append(f"RAPT в {rapt} собран для другой версии SDK "
                    f"(launcher/game/rapt_hash.txt != rapt/hash.txt) — лаунчер его не "
                    f"импортирует; переустановите RAPT под этот SDK")
    if find_adb(sdk) is None:
        gaps.append(f"не найден adb — Android SDK не установлен: "
                    f"vn release android setup sdk (нужен интернет; шаг попросит "
                    f"принять Android SDK Terms and Conditions), либо положите "
                    f"{rapt / 'sdk.txt'} с путём к уже установленному Android SDK "
                    f"(doc/android.html, Step 2)")
    jdk = jdk_major()
    if jdk is None:
        gaps.append(f"javac не найден ни в JAVA_HOME, ни в PATH — нужен JDK "
                    f"{JDK_REQUIRED} (adoptium.net); JRE не подходит, keytool и javac "
                    f"есть только в JDK")
    elif jdk < JDK_REQUIRED:
        gaps.append(f"javac версии {jdk}, а сборка требует JDK {JDK_REQUIRED}+ "
                    f"(doc/android.html, Step 1) — поставьте новее или укажите его "
                    f"через JAVA_HOME")

    if root is not None:
        for name, channel in KEYSTORES.items():
            if not (root / name).is_file():
                gaps.append(f"нет {name} — ключ подписи {channel}: "
                            f"vn release android setup keys. Ключ остаётся у "
                            f"владельца: ни в git, ни в дистрибутив он не уезжает, а "
                            f"его потеря = невозможность обновить опубликованное "
                            f"приложение")
        if not any((root / name).is_file() for name in ANDROID_CONFIG_NAMES):
            gaps.append("проект не сконфигурирован под Android (нет "
                        f"{' / '.join(ANDROID_CONFIG_NAMES)}): "
                        "vn release android setup config — имя пакета, ориентация, "
                        "магазин, permissions")
    return gaps


# ── Секреты ───────────────────────────────────────────────────────────────────

def _git(root: Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None


def keystore_leaks(root: Path) -> tuple[list[str], list[str]]:
    """Ключи подписи, лежащие так, что уедут за пределы машины владельца:
    (блокеры, предупреждения).

    Проверяется git — единственный канал, который здесь не спасти правкой
    конфига: попавший в коммит ключ считается скомпрометированным навсегда
    (история переписывается только силой и у всех клонов). Второй канал —
    дистрибутив — закрыт исключением в game/options.rpy."""
    errors: list[str] = []
    warnings: list[str] = []
    found = sorted(root.rglob("*.keystore"))
    if not found:
        return errors, warnings
    if _git(root, "rev-parse", "--git-dir") is None:
        return errors, ["git недоступен — не проверить, не уедут ли *.keystore в репозиторий"]
    for path in found:
        rel = path.relative_to(root).as_posix()
        tracked = _git(root, "ls-files", "--", rel)
        if tracked is not None and tracked.stdout.strip():
            errors.append(f"{rel} под версионным контролем: ключ подписи в git = "
                          f"скомпрометированный ключ. Уберите из индекса и истории, "
                          f"перегенерируйте ключи в лаунчере")
            continue
        ignored = _git(root, "check-ignore", "-q", "--", rel)
        if ignored is None or ignored.returncode == 128:
            warnings.append(f"{rel}: не проверить git-игнор (репозиторий недоступен)")
        elif ignored.returncode != 0:
            errors.append(f"{rel} не игнорируется git — уедет в репозиторий на первом "
                          f"`git add -A`. Добавьте *.keystore в .gitignore")
    return errors, warnings


# ── Предпосылки мобильной поставки ────────────────────────────────────────────

def oversample_suffixes(cfg: RenderConfig) -> set[str]:
    """Суффиксы отгружаемых оверсэмпл-вариантов ('@2', '@4', …) — считаются из
    render-профиля, а не берутся списком: набор масштабов решает project.yaml
    (ADR-0012), и жёсткий '@2' здесь разъехался бы с ним молча."""
    out: set[str] = set()
    for name in cfg.classes:
        cls = cfg.cls(name)
        for scale in cls.scales:
            suffix = cls.suffix_for(scale)
            if suffix:
                out.add(suffix)
    return out


def _measure_game(root: Path, suffixes: set[str]) -> tuple[int, int, list[tuple[str, int]]]:
    """Обход game/: (всего байт, из них в оверсэмпл-вариантах, крупные файлы).

    Оценка сознательно пессимистична: считается весь game/, хотя dev-инструменты и
    QA-генерат из пакета исключены (game/options.rpy). Эти исключения делают
    реальный пакет только меньше, а завышенный порог не даёт узнать о потолке
    канала из отказа стора."""
    total = 0
    oversample = 0
    big: list[tuple[str, int]] = []
    game = root / "game"
    for path in game.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        if path.relative_to(game).parts[0] in LOCAL_ONLY_DIRS:
            continue
        size = path.stat().st_size
        total += size
        stem = path.name.rsplit(".", 1)[0]
        if any(stem.endswith(sfx) for sfx in suffixes):
            oversample += size
            continue                      # в мобильный пакет такой файл не едет
        if size > BUNDLE_PACK_LIMIT_MB * MB:
            big.append((path.relative_to(root).as_posix(), size))
    big.sort(key=lambda item: -item[1])
    return total, oversample, big


@dataclass
class AndroidPreflight:
    """Готовность САМОГО ПРОЕКТА к мобильной поставке (тулчейн — rapt_status)."""

    game_mb: float = 0.0
    oversample_mb: float = 0.0
    mobile_mb: float = 0.0          # что уедет в пакет: game/ - @N + накладные
    mobile_cache_mb: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def preflight(root: Path, bundle: bool = False) -> AndroidPreflight:
    """Предпосылки мобильной поставки: размер против потолка канала, пофайловый
    лимит бандла, мобильный бюджет памяти образов, ключи подписи, оформление.

    Всё это дешевле проверить за секунды, чем узнать после часа gradle-сборки или,
    хуже, из отказа стора."""
    from .assets.memory import analyze

    cfg = load_render_config(root)
    total, oversample, big = _measure_game(root, oversample_suffixes(cfg))
    rep = AndroidPreflight(
        game_mb=total / MB,
        oversample_mb=oversample / MB,
        mobile_mb=(total - oversample) / MB + PACKAGE_OVERHEAD_MB,
        mobile_cache_mb=cfg.mobile_image_cache_mb,
    )
    channel = "Play-бандл (.aab)" if bundle else "universal APK"

    if rep.mobile_mb > PACKAGE_LIMIT_MB:
        rep.errors.append(
            f"{channel}: {rep.mobile_mb:.0f} МБ (game/ без @N-вариантов + ~"
            f"{PACKAGE_OVERHEAD_MB} МБ движка) против потолка {PACKAGE_LIMIT_MB} МБ — "
            f"пакет не соберётся. Выходы: докачиваемый контент (doc/android.html: "
            f"Downloader for Large Games on Mobile) или отказ от этого канала")
    elif rep.mobile_mb > PACKAGE_LIMIT_MB * PACKAGE_WARN_SHARE:
        rep.warnings.append(
            f"{channel}: {rep.mobile_mb:.0f} МБ — уже "
            f"{rep.mobile_mb / PACKAGE_LIMIT_MB:.0%} потолка {PACKAGE_LIMIT_MB} МБ")
    if bundle:
        for rel, size in big:
            rep.errors.append(
                f"{rel}: {size / MB:.0f} МБ > {BUNDLE_PACK_LIMIT_MB} МБ — в Play-бандле "
                f"один файл живёт в одном fast-follow пакете и целиком в него не влезет; "
                f"порежьте файл или собирайте universal APK")

    key_errors, key_warnings = keystore_leaks(root)
    rep.errors += key_errors
    rep.warnings += key_warnings

    # Память: тот же расчёт worst-case, что у десктопа, но с мобильным лимитом
    # кэша и на масштабе, который реально грузится на устройстве.
    if cfg.mobile_image_cache_mb >= cfg.image_cache_mb:
        rep.warnings.append(
            f"render.mobile.image_cache_mb ({cfg.mobile_image_cache_mb}) не меньше "
            f"десктопного ({cfg.image_cache_mb}) — почти наверняка опечатка: у "
            f"мобильного процесса памяти меньше, а не больше")
    mem = analyze(root, cfg.for_mobile(), scale=MOBILE_SCALE)
    rep.warnings += [f"память (mobile): {w}" for w in mem.warnings]
    rep.errors += [f"память (mobile): {e}" for e in mem.errors]

    for name, what in ANDROID_ART.items():
        if not (root / name).is_file():
            rep.warnings.append(f"нет {name} — {what}: Ren'Py подставит свои дефолты")
    return rep


# ── Сборка ────────────────────────────────────────────────────────────────────

@dataclass
class ApkBuild:
    command: list[str]
    artifacts: list[Path]
    facts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def package_facts(artifact: Path) -> tuple[list[str], list[str], list[str]]:
    """Фактический вес собранного пакета против потолков канала:
    (строки факта, предупреждения, блокеры).

    Зачем отдельно от `preflight`. Предполётная проверка считает ОЦЕНКУ СВЕРХУ по
    `game/` плюс фиксированные накладные — до сборки другого способа нет. Но потолок
    канала — жёсткое ограничение стора, и сверять с ним оценку, когда рядом лежит
    настоящий пакет, значит не проверять ничего. Здесь мерится файл.

    У Play-бандла проверяется ещё и крупнейшая запись: файл живёт в одном
    fast-follow пакете целиком (`BUNDLE_PACK_LIMIT_MB`), а внутри `.aab` это уже
    не наши ассеты, а нативные библиотеки — по `game/` их не видно вовсе."""
    size_mb = artifact.stat().st_size / MB
    bundle = artifact.suffix.lower() == ".aab"
    channel = "Play-бандл (.aab)" if bundle else "universal APK"
    facts = [f"{artifact.name}: {size_mb:.1f} МБ — {size_mb / PACKAGE_LIMIT_MB:.0%} "
             f"потолка {channel} ({PACKAGE_LIMIT_MB} МБ)"]
    warnings: list[str] = []
    errors: list[str] = []

    if size_mb > PACKAGE_LIMIT_MB:
        errors.append(f"{artifact.name}: {size_mb:.0f} МБ > {PACKAGE_LIMIT_MB} МБ — стор "
                      f"такой пакет не примет (doc/android.html: Building Android "
                      f"Applications)")
    elif size_mb > PACKAGE_LIMIT_MB * PACKAGE_WARN_SHARE:
        warnings.append(f"{artifact.name}: {size_mb:.0f} МБ — уже "
                        f"{size_mb / PACKAGE_LIMIT_MB:.0%} потолка {PACKAGE_LIMIT_MB} МБ")

    if bundle:
        import zipfile

        try:
            with zipfile.ZipFile(artifact) as zf:
                worst = max(zf.infolist(), key=lambda i: i.file_size, default=None)
        except (OSError, zipfile.BadZipFile) as e:
            warnings.append(f"{artifact.name}: не прочитать как zip ({e}) — пофайловый "
                            f"лимит бандла не проверен")
            return facts, warnings, errors
        if worst is not None:
            worst_mb = worst.file_size / MB
            facts.append(f"крупнейший файл внутри: {worst.filename} — {worst_mb:.1f} МБ "
                         f"из {BUNDLE_PACK_LIMIT_MB} МБ на fast-follow пакет")
            if worst_mb > BUNDLE_PACK_LIMIT_MB:
                errors.append(f"{worst.filename}: {worst_mb:.0f} МБ > "
                              f"{BUNDLE_PACK_LIMIT_MB} МБ — файл не влезет ни в один "
                              f"fast-follow пакет; порежьте его или собирайте APK")
    return facts, warnings, errors


def build_apk(root: Path, sdk: Path | None, *, bundle: bool = False,
              install: bool = False, launch: bool = False,
              dest: Path | None = None, timeout_s: int = 3600) -> ApkBuild:
    """Собрать APK/AAB штатной командой лаунчера. Диагностика — до запуска: час
    gradle-сборки, который упадёт на отсутствующем ключе, никому не нужен.

    Вывод НЕ перехватывается: сборка идёт минутами и десятками минут, и живой лог
    gradle/RAPT — единственный способ понять, что она не зависла."""
    if sdk is None:
        raise AndroidError("Ren'Py SDK не найден (RENPY_SDK) — vn doctor подскажет")
    gaps = rapt_status(sdk, root)
    if gaps:
        raise AndroidError("Android-тулчейн не готов (подготовка — vn release android "
                           "setup):\n  - " + "\n  - ".join(gaps))
    rep = preflight(root, bundle=bundle)
    if not rep.ok:
        raise AndroidError("проект не готов к мобильной поставке:\n  - "
                           + "\n  - ".join(rep.errors))

    dest = dest or root / "build" / "android"
    # Чистка: старый .apk рядом с новым выдаёт себя за результат этой сборки.
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    exe = sdk / ("renpy.exe" if sys.platform == "win32" else "renpy.sh")
    cmd = [str(exe), str(sdk / "launcher"), "android_build", str(root),
           "--destination", str(dest)]
    if bundle:
        cmd.append("--bundle")
    if install:
        cmd.append("--install")
    if launch:
        cmd.append("--launch")     # подразумевает --install (лаунчер сам добавит)
    try:
        proc = subprocess.run(cmd, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        raise AndroidError(
            f"android_build не завершился за {timeout_s} с. Первая сборка тянет gradle "
            f"и зависимости — поднимите --timeout; повторные обычно кратно быстрее")
    if proc.returncode != 0:
        raise AndroidError(
            f"android_build упал (код {proc.returncode}); лог выше. Если он молчит о "
            f"причине — тот же путь в лаунчере (Android -> Build) показывает шаги RAPT "
            f"подробнее, а Android -> Clean снимает мусор прошлой сборки")
    artifacts = sorted(p for p in dest.iterdir()
                       if p.suffix.lower() in (".apk", ".aab"))
    if not artifacts:
        raise AndroidError(
            f"android_build отчитался успехом, но в {dest} нет ни .apk, ни .aab — "
            f"проверьте лог: пакет мог остаться в rapt/bin (без --destination)")
    # Пакет собран — значит потолки канала сверяются с ФАКТОМ, а не с оценкой
    # `preflight`. Блокеры не отменяют артефакт: файл на диске нужен, чтобы понять,
    # чем именно он раздут, — поэтому они возвращаются, а не бросаются.
    rv = ApkBuild(command=cmd, artifacts=artifacts)
    for art in artifacts:
        facts, warnings, errors = package_facts(art)
        rv.facts += facts
        rv.warnings += warnings
        rv.errors += errors
    return rv
