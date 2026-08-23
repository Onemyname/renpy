"""vn voice — покрытие озвучкой (§4.9, C5).

Источник истины о том, ЧТО озвучено, — voice-манифесты
content/chapters/chNN_slug/voice/<lang>.voice.yaml (voice@1, шард глава × язык:
merge-конфликтов между главами и языками нет). Сами файлы дублей — мастера
assets_src/voice/<lang>/<chNN>/<line_id>.<ext>; в game/assets/voice/ их
транскодирует ассет-конвейер (pipeline.py: voice_opus).

Универс реплик — ledger локализации (loc/ledger/chNN.json, vn loc keys):
это те же стабильные say-id, на которых держится перевод, поэтому озвучка
не отвязывается от реплики ни правкой текста, ни правкой перевода.

Роли отчёта:
  errors   — структурные поломки: id вне ledger, манифест без мастера,
             мастер-сирота без строки манифеста, два мастера одного дубля;
  drafts   — реплики со status: draft (в релизном гейте — WARN);
  holes    — реплики главы, НЕ покрытые манифестом языка, который для этой
             главы начали озвучивать (в релизном гейте — FAIL, §4.9).
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .repo import load_yaml, write_text_lf

LINE_ID_RE = re.compile(r"^(ch\d{2})_s\d{3}_\d{4}$")
LANG_RE = re.compile(r"^[a-z]{2,3}(_[A-Z]{2})?$")
MANIFEST_SUFFIX = ".voice.yaml"
# Форматы мастеров дублей: без потерь либо исходники студии; транскод в opus —
# забота конвейера (voice_opus), сюда .opus допущен для уже готовых дублей.
MASTER_EXTS = (".wav", ".flac", ".ogg", ".opus")
# Статусы дубля (enum схемы voice@1): draft — черновик/TTS (WARN релизного гейта),
# final — записанный дубль, который автоматика не перезаписывает никогда.
STATUS_DRAFT = "draft"
STATUS_FINAL = "final"


class VoiceError(RuntimeError):
    pass


@dataclass
class VoiceReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    drafts: list[str] = field(default_factory=list)      # "<lang>: <line_id>"
    # Драфты, ЯВНО принятые как релизное качество (accepted: true, ADR-0020):
    # гейт по ним молчит, но список виден — принятие не превращается в невидимость.
    accepted: list[str] = field(default_factory=list)    # "<lang>: <line_id>"
    holes: list[str] = field(default_factory=list)       # "<lang>: <line_id>"
    # (chapter, lang) -> (покрыто, всего реплик главы)
    coverage: dict[tuple[str, str], tuple[int, int]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def _chapter_dirs(root: Path) -> list[Path]:
    zones = [root / "content" / "chapters"]
    if (root / "packs").is_dir():
        zones += sorted((root / "packs").glob("*/chapters"))
    out: list[Path] = []
    for zone in zones:
        if zone.is_dir():
            out += sorted(p for p in zone.iterdir() if p.is_dir())
    return out


def load_manifests(root: Path, errors: list[str]) -> list[tuple[str, str, str, dict]]:
    """[(chapter_id, lang, rel, doc)] по всем главам ядра и паков.
    Схема, совпадение chapter/lang с путём и принадлежность line_id главе —
    проверяются здесь: это инварианты файла, а не прогона."""
    from .schemas import SchemaRegistry

    registry = SchemaRegistry(root / "tools" / "schemas")
    out: list[tuple[str, str, str, dict]] = []
    for ch_dir in _chapter_dirs(root):
        ch_id = ch_dir.name[:4]
        vdir = ch_dir / "voice"
        if not vdir.is_dir():
            continue
        for f in sorted(vdir.glob("*" + MANIFEST_SUFFIX)):
            rel = f.relative_to(root).as_posix()
            lang = f.name[: -len(MANIFEST_SUFFIX)]
            doc = load_yaml(f)
            errs = registry.validate(doc, rel)
            if errs:
                errors.extend(errs)
                continue
            if not LANG_RE.match(lang):
                errors.append(f"{rel}: имя файла {lang!r} — не код языка "
                              f"(ожидается <lang>{MANIFEST_SUFFIX})")
                continue
            if doc["lang"] != lang:
                errors.append(f"{rel}: lang ({doc['lang']}) != имени файла ({lang})")
                continue
            if doc["chapter"] != ch_id:
                errors.append(f"{rel}: chapter ({doc['chapter']}) != главе каталога ({ch_id})")
                continue
            # Две РАЗНЫЕ ошибки, и раньше вторая проверка была всегда истинной
            # (`LINE_ID_RE.match(lid) or [None]` — непустой список в любом случае),
            # то есть конвенция id здесь не проверялась вовсе.
            malformed = [lid for lid in (doc.get("lines") or {})
                         if not LINE_ID_RE.match(lid)]
            for lid in sorted(malformed):
                errors.append(f"{rel}: {lid}: id реплики вне конвенции "
                              f"chNN_sNNN_NNNN (naming.md)")
            bad = [lid for lid in (doc.get("lines") or {})
                   if LINE_ID_RE.match(lid) and not lid.startswith(ch_id + "_")]
            for lid in sorted(bad):
                errors.append(f"{rel}: {lid}: реплика чужой главы в манифесте {ch_id}")
            bad += malformed
            if bad:
                continue
            out.append((ch_id, lang, rel, doc))
    return out


def _ledger_says(root: Path, chapter_id: str) -> dict[str, dict] | None:
    """say-id главы из ledger (None = ledger не собран: нужен vn loc keys)."""
    f = root / "loc" / "ledger" / f"{chapter_id}.json"
    if not f.is_file():
        return None
    try:
        return dict(json.loads(f.read_text(encoding="utf-8")).get("says") or {})
    except Exception:
        return None


def master_path(root: Path, lang: str, line_id: str) -> Path | None:
    """Мастер дубля в assets_src/voice/<lang>/<chNN>/<line_id>.<ext> (или None)."""
    base = root / "assets_src" / "voice" / lang / line_id[:4]
    for ext in MASTER_EXTS:
        cand = base / (line_id + ext)
        if cand.is_file():
            return cand
    return None


def _drop_stale_masters(root: Path, lang: str, line_id: str, keep_ext: str) -> None:
    """Убрать мастера того же дубля в ОСТАЛЬНЫХ форматах: master_path берёт первое
    расширение из MASTER_EXTS, поэтому оставленный .wav заглушал бы новый .opus, а
    ассет-конвейер (voice_opus, Job на каждый файл assets_src/voice) спотыкался бы
    об это гораздо позже — ошибкой про два источника на один выход."""
    base = root / "assets_src" / "voice" / lang / line_id[:4]
    for ext in MASTER_EXTS:
        if ext != keep_ext:
            (base / (line_id + ext)).unlink(missing_ok=True)


def validate(root: Path) -> VoiceReport:
    rep = VoiceReport()
    manifests = load_manifests(root, rep.errors)

    declared: dict[str, set[str]] = {}    # lang -> объявленные line_id
    for ch_id, lang, rel, doc in manifests:
        says = _ledger_says(root, ch_id)
        if says is None:
            rep.warnings.append(
                f"{rel}: ledger loc/ledger/{ch_id}.json не собран — покрытие не "
                f"посчитать (прогоните vn loc keys)")
            says = {}
        lines = dict(doc.get("lines") or {})
        declared.setdefault(lang, set()).update(lines)
        covered = 0
        for lid, spec in sorted(lines.items()):
            if says and lid not in says:
                rep.errors.append(
                    f"{rel}: {lid}: такой реплики нет в ledger главы — опечатка "
                    f"или реплика удалена/пере-id-шена (файл дубля осиротеет)")
                continue
            covered += 1
            if spec["status"] == STATUS_DRAFT:
                if spec.get("accepted"):
                    rep.accepted.append(f"{lang}: {lid}")
                else:
                    rep.drafts.append(f"{lang}: {lid}")
            elif spec.get("accepted"):
                rep.errors.append(
                    f"{rel}: {lid}: accepted у final-дубля бессмыслен — флаг "
                    f"существует для принятых драфтов (ADR-0020), уберите его")
            if master_path(root, lang, lid) is None:
                rep.errors.append(
                    f"{rel}: {lid}: объявлен, но мастера нет в "
                    f"assets_src/voice/{lang}/{ch_id}/ ({'|'.join(MASTER_EXTS)}) — "
                    f"vn voice import")
        if says:
            rep.coverage[(ch_id, lang)] = (covered, len(says))
            for lid in sorted(set(says) - set(lines)):
                rep.holes.append(f"{lang}: {lid}")

    # Мастера-сироты: файл есть, а строки манифеста нет. Компилятор эмитит
    # voice-оператор ТОЛЬКО для реплик из манифестов, поэтому файл-сирота
    # доедет до дистрибутива, но не прозвучит никогда — мёртвые мегабайты.
    # Источник истины один (манифест), расхождение в обе стороны — ошибка.
    vsrc = root / "assets_src" / "voice"
    if vsrc.is_dir():
        # (lang, chNN, line_id) -> имена файлов: дубль в двух форматах сиротой не
        # считается (stem-то объявлен), поэтому его ловит отдельная проверка ниже.
        by_line: dict[tuple[str, str, str], list[str]] = {}
        for f in sorted(vsrc.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in MASTER_EXTS:
                continue
            parts = f.relative_to(vsrc).parts
            if len(parts) != 3:
                rep.errors.append(
                    f"assets_src/voice/{'/'.join(parts)}: путь вне конвенции "
                    f"voice/<lang>/<chNN>/<line_id>.<ext>")
                continue
            lang, ch, name = parts
            if f.stem not in declared.get(lang, set()):
                rep.errors.append(
                    f"assets_src/voice/{'/'.join(parts)}: мастер без строки в "
                    f"voice-манифесте — объявите реплику или удалите файл")
                continue      # необъявленному дублю совет «оставьте нужный» не про то
            by_line.setdefault((lang, ch, f.stem), []).append(name)
        # У line_id ровно один мастер. Иначе озвучка берёт первый по MASTER_EXTS —
        # то есть возможно черновик вместо записанного финала, — а ассет-конвейер
        # (voice_opus) красит релизный гейт гораздо позже и невнятным «два
        # источника претендуют на один выход».
        for (lang, ch, lid), names in sorted(by_line.items()):
            if len(names) > 1:
                rep.errors.append(
                    f"assets_src/voice/{lang}/{ch}/: у {lid} несколько мастеров "
                    f"({', '.join(sorted(names))}) — оставьте нужный дубль, "
                    f"остальные удалите: озвучка возьмёт первый по "
                    f"{'|'.join(MASTER_EXTS)}, и это может быть не он")
    return rep


def manifest_rows(root: Path, chapter_id: str, lang: str,
                  char: str | None = None) -> list[dict]:
    """Лист для актёра/студии: реплики главы с контекстом соседних строк.
    Колонка status показывает, что уже покрыто манифестом этого языка."""
    says = _ledger_says(root, chapter_id)
    if says is None:
        raise VoiceError(
            f"loc/ledger/{chapter_id}.json не собран — сначала vn loc keys")
    lines: dict[str, dict] = {}
    for ch_id, mlang, _rel, doc in load_manifests(root, errors=[]):
        if ch_id == chapter_id and mlang == lang:
            lines.update(doc.get("lines") or {})
    ordered = sorted(says.items())
    rows = []
    for i, (lid, spec) in enumerate(ordered):
        if char is not None and spec.get("who") != char:
            continue
        rows.append({
            "line_id": lid,
            "who": spec.get("who") or "",
            "text": spec.get("text") or "",
            "prev": ordered[i - 1][1].get("text", "") if i else "",
            "next": ordered[i + 1][1].get("text", "") if i + 1 < len(ordered) else "",
            "status": (lines.get(lid) or {}).get("status", ""),
        })
    return rows


def write_manifest_csv(rows: list[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["line_id", "who", "text", "prev", "next", "status"])
        w.writeheader()
        w.writerows(rows)


@dataclass
class ImportReport:
    imported: list[str] = field(default_factory=list)
    updated_manifests: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _rel_to(path: Path, base: Path) -> str:
    """Путь для сообщения — от каталога импорта, а не одно имя файла: пачку дублей
    студия отдаёт подкаталогами, и одинаковые имена в них — штатный случай."""
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.name


def import_takes(root: Path, src_dir: Path, lang: str,
                 status: str = STATUS_FINAL) -> ImportReport:
    """Разложить дубли по мастер-зоне и обновить манифесты.

    Вход: каталог с файлами <line_id>.<ext>. Каждый файл валидируется против
    ledger своей главы, копируется в assets_src/voice/<lang>/<chNN>/ и получает
    строку в content/chapters/<глава>/voice/<lang>.voice.yaml. Транскод в opus —
    следующий vn assets build (voice_opus)."""
    rep = ImportReport()
    if not LANG_RE.match(lang):
        rep.errors.append(f"--lang {lang!r}: не код языка")
        return rep
    files = [f for f in sorted(src_dir.rglob("*"))
             if f.is_file() and f.suffix.lower() in MASTER_EXTS]
    if not files:
        rep.errors.append(f"{src_dir}: нет файлов дублей ({'|'.join(MASTER_EXTS)})")
        return rep

    chapter_dir_by_id = {d.name[:4]: d for d in _chapter_dirs(root)}
    per_chapter: dict[str, list[Path]] = {}
    seen: dict[str, Path] = {}      # line_id -> первый файл пачки с этим id
    for f in files:
        m = LINE_ID_RE.match(f.stem)
        if not m:
            rep.errors.append(f"{f.name}: имя файла — не line_id (ch NN _s NNN _ NNNN)")
            continue
        ch_id = m.group(1)
        if ch_id not in chapter_dir_by_id:
            rep.errors.append(f"{f.name}: главы {ch_id} нет в content/chapters/")
            continue
        says = _ledger_says(root, ch_id)
        if says is not None and f.stem not in says:
            rep.errors.append(
                f"{f.name}: реплики нет в ledger {ch_id} — опечатка в имени дубля?")
            continue
        # Две версии одного дубля в пачке: в разных форматах обе легли бы мастерами
        # одного line_id, а в одном — вторая молча затёрла бы первую. Какая из них
        # нужна, знает только студия, поэтому это отказ, а не догадка. Пути — от
        # каталога импорта: пачка приходит подкаталогами (takes/day1, takes/day2),
        # и по одним именам файлов конфликт не разобрать.
        if f.stem in seen:
            rep.errors.append(
                f"{_rel_to(f, src_dir)}: тот же line_id уже пришёл как "
                f"{_rel_to(seen[f.stem], src_dir)} — в пачке две версии дубля, "
                f"оставьте одну")
            continue
        seen[f.stem] = f
        # Черновиком поверх записанного финала — только осознанно: раскладка
        # вытесняет мастер прежнего формата, то есть дубль актёра исчез бы с диска
        # (шапка модуля обещает обратное: final автоматика не перезаписывает).
        if status == STATUS_DRAFT:
            mf = chapter_dir_by_id[ch_id] / "voice" / f"{lang}{MANIFEST_SUFFIX}"
            prev = (load_yaml(mf).get("lines") or {}).get(f.stem) if mf.is_file() else None
            if prev and prev.get("status") == STATUS_FINAL:
                rep.errors.append(
                    f"{_rel_to(f, src_dir)}: у реплики уже есть записанный дубль "
                    f"(status: final) — черновик поверх него не кладём. Нужна "
                    f"замена? Импортируйте как финал (без --draft) либо сначала "
                    f"уберите строку из {mf.relative_to(root).as_posix()}")
                continue
        per_chapter.setdefault(ch_id, []).append(f)
    if rep.errors:
        return rep    # ничего не раскладываем: половинчатый импорт хуже отказа

    for ch_id, takes in sorted(per_chapter.items()):
        for f in takes:
            ext = f.suffix.lower()
            dest = root / "assets_src" / "voice" / lang / ch_id / (f.stem + ext)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, dest)
            # Финал .opus поверх чернового .wav — обычный случай, и прежний мастер
            # обязан уйти: иначе у line_id их два (см. _drop_stale_masters).
            _drop_stale_masters(root, lang, f.stem, ext)
            rep.imported.append(dest.relative_to(root).as_posix())

        mf = chapter_dir_by_id[ch_id] / "voice" / f"{lang}{MANIFEST_SUFFIX}"
        doc = load_yaml(mf) if mf.is_file() else {
            "schema": "voice@1", "chapter": ch_id, "lang": lang, "lines": {}}
        doc.setdefault("lines", {})
        for f in takes:
            spec = dict(doc["lines"].get(f.stem) or {}, status=status)
            # Новый дубль обнуляет принятие старого (ADR-0020): accepted относился
            # к конкретному черновику, а не к реплике навсегда.
            spec.pop("accepted", None)
            doc["lines"][f.stem] = spec
        _write_manifest(mf, doc)
        rep.updated_manifests.append(mf.relative_to(root).as_posix())
    return rep


def encode_opus(src: Path, tmp_dir: Path) -> bytes:
    """Мастер дубля -> Opus 96k, громкость нормализована к −19 LUFS (§4.9/C18).
    Однопроходный loudnorm: реплики короткие, двухпроходная точность не окупается.
    Зовётся ассет-конвейером (pipeline.py: voice_opus) — кэш и манифест там."""
    from .pipeline import find_ffmpeg

    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise VoiceError("ffmpeg не найден (vn pipeline doctor)")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out = tmp_dir / (src.stem + ".opus")
    cmd = [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
           "-vn", "-af", "loudnorm=I=-19:TP=-1.5:LRA=11",
           "-c:a", "libopus", "-b:a", "96k", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise VoiceError(f"{src.name}: ffmpeg: {proc.stderr.strip()[:500]}")
    data = out.read_bytes()
    out.unlink()
    return data


def _manifest_header_comments(path: Path) -> list[str]:
    """Шапка-комментарий манифеста (всё до строки lines:). Её пишет человек —
    «почему в этой главе одни драфты», «кто актёр» — и перезапись манифеста
    автоматикой (import/tts) не имеет права стирать объяснение."""
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("lines:"):
            break
        if line.lstrip().startswith("#"):
            out.append(line)
    return out


def _write_manifest(path: Path, doc: dict) -> None:
    """Детерминированная запись: сортировка строк по id — диффы читаемы,
    merge-конфликты локальны."""
    lines = doc.get("lines") or {}
    out = [f"schema: {doc['schema']}",
           f"chapter: {doc['chapter']}",
           f"lang: {doc['lang']}",
           *_manifest_header_comments(path),
           "lines:" if lines else "lines: {}"]
    for lid in sorted(lines):
        spec = lines[lid]
        fields_ = [f"status: {spec['status']}"]
        if spec.get("accepted"):
            fields_.append("accepted: true")
        if spec.get("actor"):
            fields_.append(f"actor: {spec['actor']}")
        out.append(f"  {lid}: {{{', '.join(fields_)}}}")
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_lf(path, "\n".join(out) + "\n")


# ── TTS-черновики (§4.9, C5) ──────────────────────────────────────────────────
# Зачем: голосовой контур (voice-операторы, деградация языков, дакинг музыки)
# проверяется только там, где звук физически есть, а ждать актёров нельзя —
# записываются они месяцами. До записи главу озвучивает синтез: дубли идут в
# манифест со status: draft, релизный гейт честно ворчит за них WARN, а vn voice
# import с боевыми дублями заменяет их на final.
#
# Мастер черновика кладём сразу в .opus (encode_opus: 96k, −19 LUFS, как боевые
# дубли): assets_src — LFS-зона, и WAV-черновики раздували бы историю в десять
# раз ради звука, который всё равно выбросят.
TTS_MASTER_EXT = ".opus"
TTS_STAGE_REL = Path(".vncache") / "voice-tts"   # C19: локальный кэш — .vncache

# Темп речи — множитель к нормальному темпу голоса. Границы не косметика: за ними
# синтез теряет разборчивость и черновик перестаёт быть пригодным для вычитки.
TTS_DEFAULT_RATE = 1.0
TTS_RATE_MIN = 0.5
TTS_RATE_MAX = 2.0

# Разметка Ren'Py внутри реплики: теги {w=0.5}/{i} и интерполяции [player_name].
# Синтезатор произнёс бы их буквально («фигурная скобка дабл-ю»), поэтому из
# текста дубля они снимаются. Экранирование {{ и [[ остаётся без пары — отдельным
# проходом убираем и одиночные скобки.
_MARKUP_RE = re.compile(r"\{[^{}]*\}|\[[^\[\]]*\]")
_BRACES = str.maketrans({"{": "", "}": "", "[": "", "]": ""})


def tts_text(raw: str) -> str:
    """Реплика -> то, что реально произносится (без разметки и лишних пробелов)."""
    return " ".join(_MARKUP_RE.sub(" ", raw).translate(_BRACES).split())


# ── Бэкенды синтеза ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _TtsBackendSpec:
    """Бэкенд синтеза как данные: чем зовём, как ищем голос, как строим команду.

    Абстракция явная (образец — find_tool в pipeline.py): бинарь не хардкодится
    (PATH + env-переопределение), «чем именно синтезировали» уезжает в отчёт, а
    --backend снимает угадывание. Порядок в TTS_BACKENDS = приоритет автовыбора.

    resolve_voice(tool, lang, voice, root, allow_download) -> идентификатор голоса
    для команды (у piper — путь к .onnx, у say — имя системного голоса).
    argv(tool, voice, rate) -> функция out_wav -> команда: всё, что стоит спросить
    у бэкенда один раз (например версию флагов piper), спрашивается при сборке
    функции, а не на каждой реплике.
    """
    tool_name: str
    env_var: str
    install_hint: str
    resolve_voice: Callable[[Path, str, str | None, Path, bool], str]
    argv: Callable[[Path, str, float], Callable[[Path], list[str]]]


# piper — основной бэкенд: кроссплатформенный, голоса моделями, звучит как
# черновик для вычитки, а не как системный диктор.
PIPER_VOICES_ENV = "VN_PIPER_VOICES"
PIPER_VOICES_CACHE_REL = Path(".vncache") / "piper-voices"
PIPER_VOICES_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
# Имя голоса piper само кодирует язык, регион, диктора и качество, а раскладка
# репозитория голосов из имени выводится — поэтому URL считается, а не хранится
# списком, который пришлось бы синхронизировать руками.
PIPER_VOICE_RE = re.compile(r"^([a-z]{2,3})_([A-Z]{2})-([a-z0-9_]+)-(x_low|low|medium|high)$")
PIPER_MODEL_EXT = ".onnx"
PIPER_MODEL_CONFIG_EXT = ".onnx.json"    # лежит рядом с моделью; без него piper не стартует
# Дефолтные голоса по языку. Таблица короткая намеренно: язык без записи — явная
# ошибка с просьбой указать --voice, а не молчаливый чужой акцент в черновике.
PIPER_DEFAULT_VOICES = {"ru": "ru_RU-irina-medium", "en": "en_US-lessac-medium"}

# say — дев-фолбэк: есть на каждой macOS без установки, но только там.
SAY_PREFERRED_VOICES = {"ru": "Milena", "en": "Samantha"}
# Темп say задаётся словами в минуту; опорное значение — примерный темп системных
# голосов по умолчанию (API его не сообщает), rate — множитель к нему.
SAY_BASE_WPM = 180
# 16-битный PCM 22.05 кГц: формат черновика ровно до encode_opus, дальше не живёт.
SAY_WAV_FORMAT = "LEI16@22050"
_SAY_VOICE_RE = re.compile(r"^(.+?)\s{2,}([a-z]{2,3}(?:_[A-Z]{2})?)\s")


def _piper_voice_dirs(root: Path) -> list[Path]:
    """Где ищем модели: явный каталог -> кэш репозитория -> общий каталог piper."""
    dirs: list[Path] = []
    env = os.environ.get(PIPER_VOICES_ENV)
    if env:
        dirs.append(Path(env).expanduser())
    dirs.append(root / PIPER_VOICES_CACHE_REL)
    dirs.append(Path.home() / ".local" / "share" / "piper-voices")
    return dirs


def _piper_voice_url(name: str, ext: str) -> str:
    lang, region, speaker, quality = PIPER_VOICE_RE.match(name).groups()
    return f"{PIPER_VOICES_URL}/{lang}/{lang}_{region}/{speaker}/{quality}/{name}{ext}"


def _piper_download_voice(name: str, dest_dir: Path) -> Path:
    """Модель + её конфиг в кэш репозитория. Докачка, .part-семантика и фоллбек
    curl -> urllib уже реализованы в pipeline._download — своя обвязка была бы копией."""
    from .pipeline import PipelineError, _download

    dest_dir.mkdir(parents=True, exist_ok=True)
    for ext in (PIPER_MODEL_EXT, PIPER_MODEL_CONFIG_EXT):
        dest = dest_dir / (name + ext)
        if dest.is_file():
            continue
        try:
            _download(_piper_voice_url(name, ext), dest)
        except PipelineError as e:
            raise VoiceError(f"piper: голос {name}{ext} не скачался: {e}") from e
    return dest_dir / (name + PIPER_MODEL_EXT)


def _piper_voice(tool: Path, lang: str, voice: str | None, root: Path,
                 allow_download: bool) -> str:
    """Голос piper -> путь к .onnx. Сеть трогаем ТОЛЬКО с allow_download: тихая
    загрузка сотен мегабайт из vn voice tts — не то, чего ждёт вызывающий."""
    name = voice or PIPER_DEFAULT_VOICES.get(lang.split("_")[0])
    if not name:
        raise VoiceError(
            f"piper: дефолтного голоса для языка {lang} нет — укажите --voice "
            f"(имя вида ru_RU-irina-medium или путь к {PIPER_MODEL_EXT})")
    direct = Path(name).expanduser()
    if direct.suffix == PIPER_MODEL_EXT:
        if direct.is_file():
            return str(direct)
        raise VoiceError(f"--voice {name}: файла модели нет")
    if not PIPER_VOICE_RE.match(name):
        raise VoiceError(
            f"--voice {name!r}: это не голос piper (<lang>_<REGION>-<диктор>-<качество>) "
            f"и не путь к {PIPER_MODEL_EXT}")
    dirs = _piper_voice_dirs(root)
    for d in dirs:
        cand = d / (name + PIPER_MODEL_EXT)
        if cand.is_file():
            return str(cand)
    if not allow_download:
        raise VoiceError(
            f"piper: модели голоса {name} нет ни в одном каталоге "
            f"({', '.join(str(d) for d in dirs)})\n"
            f"  скачать вручную: {_piper_voice_url(name, PIPER_MODEL_EXT)} "
            f"(и рядом {PIPER_MODEL_CONFIG_EXT})\n"
            f"  либо разрешить загрузку флагом --allow-download\n"
            f"  либо указать свой каталог моделей в {PIPER_VOICES_ENV}")
    return str(_piper_download_voice(name, root / PIPER_VOICES_CACHE_REL))


def _piper_help(tool: Path) -> str:
    """piper --help: у части сборок usage уходит в stderr и код возврата не 0,
    поэтому смотрим оба потока и считаем провалом только пустой вывод."""
    try:
        proc = subprocess.run([str(tool), "--help"], capture_output=True, text=True,
                              timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise VoiceError(f"{tool}: piper --help не отвечает ({e})") from e
    out = (proc.stdout or "") + (proc.stderr or "")
    if not out.strip():
        raise VoiceError(f"{tool}: piper --help ничего не вывел — битый бинарь?")
    return out


def _piper_argv(tool: Path, voice: str, rate: float) -> Callable[[Path], list[str]]:
    """Команда piper. Флаги спрашиваем у самого бинаря один раз: у piper1-gpl
    (pip install piper-tts) они через дефис (--output-file), у старого piper
    (rhasspy, C++) — через подчёркивание (--output_file). Гадать нельзя, а --help
    честно показывает, какой из двух перед нами."""
    dashed = "--output-file" in _piper_help(tool)
    out_flag = "--output-file" if dashed else "--output_file"
    len_flag = "--length-scale" if dashed else "--length_scale"
    # length_scale — множитель ДЛИТЕЛЬНОСТИ: чем быстрее речь, тем он меньше.
    scale = f"{1.0 / rate:.3f}"
    return lambda out_wav: [str(tool), "--model", voice, out_flag, str(out_wav),
                            len_flag, scale]


def _say_voices(tool: Path) -> dict[str, str]:
    """Установленные голоса say: имя -> локаль (`say -v '?'`)."""
    proc = subprocess.run([str(tool), "-v", "?"], capture_output=True, text=True)
    if proc.returncode != 0:
        raise VoiceError(f"{tool} -v '?': код {proc.returncode}")
    out: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        m = _SAY_VOICE_RE.match(line)
        if m:
            out[m.group(1).strip()] = m.group(2)
    return out


def _say_voice(tool: Path, lang: str, voice: str | None, root: Path,
               allow_download: bool) -> str:
    """Голос say: явный -> предпочтительный для языка -> первый с этой локалью.
    Автовыбор по локали нужен потому, что состав системных голосов у каждого свой:
    таблица предпочтений — только подсказка, а не требование."""
    installed = _say_voices(tool)
    if voice:
        if voice not in installed:
            raise VoiceError(f"--voice {voice!r}: say такого голоса не знает "
                             f"(список: say -v '?')")
        return voice
    pref = SAY_PREFERRED_VOICES.get(lang.split("_")[0])
    if pref and pref in installed:
        return pref
    for name, locale in installed.items():
        if locale.split("_")[0] == lang.split("_")[0]:
            return name
    raise VoiceError(
        f"say: ни одного голоса для языка {lang} — доустановите его (Системные "
        f"настройки -> Универсальный доступ -> Устная речь) или укажите --voice")


def _say_argv(tool: Path, voice: str, rate: float) -> Callable[[Path], list[str]]:
    return lambda out_wav: [
        str(tool), "-v", voice, "-r", str(round(SAY_BASE_WPM * rate)),
        f"--data-format={SAY_WAV_FORMAT}", "-o", str(out_wav)]


TTS_BACKENDS: dict[str, _TtsBackendSpec] = {
    "piper": _TtsBackendSpec(
        tool_name="piper", env_var="VN_PIPER",
        install_hint="pipx install piper-tts (кроссплатформенный, модель голоса — "
                     "--voice/--allow-download); путь к бинарю — VN_PIPER",
        resolve_voice=_piper_voice, argv=_piper_argv),
    "say": _TtsBackendSpec(
        tool_name="say", env_var="VN_SAY",
        install_hint="дев-фолбэк, только macOS: /usr/bin/say входит в систему",
        resolve_voice=_say_voice, argv=_say_argv),
}


@dataclass(frozen=True)
class Tts:
    """Готовый синтезатор: выбранный бэкенд, разрешённый голос и сборщик команды."""
    backend: str
    voice: str
    rate: float
    argv: Callable[[Path], list[str]]


def resolve_tts(root: Path, lang: str, backend: str | None = None,
                voice: str | None = None, rate: float = TTS_DEFAULT_RATE,
                allow_download: bool = False) -> Tts:
    """Выбрать бэкенд (явно либо первый доступный) и разрешить голос для языка."""
    if not TTS_RATE_MIN <= rate <= TTS_RATE_MAX:
        raise VoiceError(f"--rate {rate}: вне диапазона {TTS_RATE_MIN}..{TTS_RATE_MAX}")
    if backend is not None and backend not in TTS_BACKENDS:
        raise VoiceError(f"--backend {backend!r}: неизвестен "
                         f"(есть: {', '.join(TTS_BACKENDS)})")
    from .pipeline import find_tool

    for bid in ([backend] if backend else list(TTS_BACKENDS)):
        spec = TTS_BACKENDS[bid]
        tool = find_tool(spec.tool_name, spec.env_var)
        if tool is None:
            continue
        resolved = spec.resolve_voice(tool, lang, voice, root, allow_download)
        return Tts(backend=bid, voice=resolved, rate=rate,
                   argv=spec.argv(tool, resolved, rate))
    if backend:
        spec = TTS_BACKENDS[backend]
        raise VoiceError(f"TTS-бэкенд {backend!r} недоступен: {spec.tool_name} нет "
                         f"в PATH, {spec.env_var} не задан\n  {spec.install_hint}")
    raise VoiceError("TTS-бэкенда нет — черновики озвучки собирать нечем:\n" + "\n".join(
        f"  {bid}: {s.install_hint}" for bid, s in TTS_BACKENDS.items()))


def _synth_wav(tts: Tts, text: str, out_wav: Path) -> None:
    """Один WAV бэкендом. Текст идёт на stdin (его читают и piper, и say): реплики
    в argv упирались бы в лимит длины команды и в экранирование кавычек."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    # encoding обязателен: text=True без него кодирует stdin локалью ОС (на
    # Windows — cp1251), а piper читает utf-8 — кириллица роняла синтез.
    proc = subprocess.run(tts.argv(out_wav), input=text, capture_output=True,
                          text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise VoiceError(f"{tts.backend}: код {proc.returncode}: "
                         f"{(proc.stderr or proc.stdout).strip()[:500]}")
    if not out_wav.is_file() or out_wav.stat().st_size == 0:
        raise VoiceError(f"{tts.backend}: WAV пуст ({out_wav.name}) — проверьте "
                         f"голос {tts.voice!r}")


# ── Поток генерации ───────────────────────────────────────────────────────────

@dataclass
class TtsReport:
    backend: str = ""
    voice: str = ""
    generated: list[str] = field(default_factory=list)     # line_id
    skipped: list[str] = field(default_factory=list)       # "<line_id>: причина"
    updated_manifests: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _draft_translations(root: Path, lang: str, src_lang: str) -> dict[str, str]:
    """line_id -> перевод на язык дубляжа (для исходного языка не нужен).
    Дубляж обязан говорить своим текстом, а ledger хранит только исходный;
    загрузчик PO уже есть в loc-домене, свой парсер был бы его копией."""
    if lang == src_lang:
        return {}
    from .loc.po import load_translations

    return {ctx: msgstr for ctx, (msgstr, _fuzzy) in load_translations(root, lang).items()}


def synth_drafts(root: Path, chapter_id: str, lang: str | None = None,
                 char: str | None = None, backend: str | None = None,
                 voice: str | None = None, rate: float = TTS_DEFAULT_RATE,
                 only_missing: bool = True, allow_download: bool = False) -> TtsReport:
    """Черновые дубли для непокрытых реплик главы (§4.9): билд играбелен и озвучен
    до записи актёров.

    Идемпотентность: по умолчанию берутся только реплики без покрытия — плюс те,
    чей мастер пропал (манифест обещает дубль, а файла нет: такую главу
    vn voice validate и так считает сломанной). Реплики status: final не трогаются
    НИКОГДА, даже с only_missing=False: перезаписать записанного актёра синтезом
    недопустимо. Повтор без работы завершается успешно и без бэкенда вообще.
    """
    from .loc.po import source_language

    rep = TtsReport()
    src_lang = source_language(root).code
    lang = lang or src_lang
    if not LANG_RE.match(lang):
        raise VoiceError(f"--lang {lang!r}: не код языка")
    rows = manifest_rows(root, chapter_id, lang, char=char)
    translated = _draft_translations(root, lang, src_lang)

    targets: list[tuple[str, str]] = []
    for row in rows:
        lid, status = row["line_id"], row["status"]
        if status == STATUS_FINAL:
            rep.skipped.append(f"{lid}: записанный дубль (final)")
            continue
        if status == STATUS_DRAFT and only_missing and master_path(root, lang, lid):
            rep.skipped.append(f"{lid}: черновик уже есть "
                               f"(перегенерация — --regenerate-drafts)")
            continue
        text = tts_text(row["text"] if lang == src_lang else translated.get(lid, ""))
        if not text:
            rep.warnings.append(
                f"{lid}: озвучивать нечего — "
                + (f"нет перевода на {lang} (vn loc extract, затем перевод и "
                   f"vn loc import)" if lang != src_lang
                   else "после снятия разметки текст пуст"))
            continue
        targets.append((lid, text))
    if not targets:
        return rep

    tts = resolve_tts(root, lang, backend=backend, voice=voice, rate=rate,
                      allow_download=allow_download)
    rep.backend, rep.voice = tts.backend, tts.voice
    stage = root / TTS_STAGE_REL / f"{chapter_id}-{lang}"
    takes, enc = stage / "takes", stage / "enc"
    shutil.rmtree(stage, ignore_errors=True)   # мусор прошлого прогона не доедет до импорта
    takes.mkdir(parents=True)
    try:
        for lid, text in targets:
            wav = takes / (lid + ".wav")
            _synth_wav(tts, text, wav)
            (takes / (lid + TTS_MASTER_EXT)).write_bytes(encode_opus(wav, enc))
            wav.unlink()
            rep.generated.append(lid)
        # Раскладку мастеров (включая вытеснение прежнего мастера в другом
        # формате), сверку с ledger, атомарность и запись манифестов делает импорт
        # дублей — своего пути в assets_src у синтеза нет.
        imported = import_takes(root, takes, lang, status=STATUS_DRAFT)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    if imported.errors:
        rep.errors += imported.errors
        rep.generated.clear()      # импорт атомарен: не приписываем себе чего нет
        return rep
    rep.updated_manifests = imported.updated_manifests
    return rep
