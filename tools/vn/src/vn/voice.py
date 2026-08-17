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
             мастер-сирота без строки манифеста;
  drafts   — реплики со status: draft (в релизном гейте — WARN);
  holes    — реплики главы, НЕ покрытые манифестом языка, который для этой
             главы начали озвучивать (в релизном гейте — FAIL, §4.9).
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .repo import load_yaml

LINE_ID_RE = re.compile(r"^(ch\d{2})_s\d{3}_\d{4}$")
LANG_RE = re.compile(r"^[a-z]{2,3}(_[A-Z]{2})?$")
MANIFEST_SUFFIX = ".voice.yaml"
# Форматы мастеров дублей: без потерь либо исходники студии; транскод в opus —
# забота конвейера (voice_opus), сюда .opus допущен для уже готовых дублей.
MASTER_EXTS = (".wav", ".flac", ".ogg", ".opus")


class VoiceError(RuntimeError):
    pass


@dataclass
class VoiceReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    drafts: list[str] = field(default_factory=list)      # "<lang>: <line_id>"
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
            bad = [lid for lid in (doc.get("lines") or {})
                   if (LINE_ID_RE.match(lid) or [None])
                   and not lid.startswith(ch_id + "_")]
            for lid in sorted(bad):
                errors.append(f"{rel}: {lid}: реплика чужой главы в манифесте {ch_id}")
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
            if spec["status"] == "draft":
                rep.drafts.append(f"{lang}: {lid}")
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
        for f in sorted(vsrc.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in MASTER_EXTS:
                continue
            parts = f.relative_to(vsrc).parts
            if len(parts) != 3:
                rep.errors.append(
                    f"assets_src/voice/{'/'.join(parts)}: путь вне конвенции "
                    f"voice/<lang>/<chNN>/<line_id>.<ext>")
                continue
            lang, _ch, _name = parts
            if f.stem not in declared.get(lang, set()):
                rep.errors.append(
                    f"assets_src/voice/{'/'.join(parts)}: мастер без строки в "
                    f"voice-манифесте — объявите реплику или удалите файл")
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


def import_takes(root: Path, src_dir: Path, lang: str,
                 status: str = "final") -> ImportReport:
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
        per_chapter.setdefault(ch_id, []).append(f)
    if rep.errors:
        return rep    # ничего не раскладываем: половинчатый импорт хуже отказа

    for ch_id, takes in sorted(per_chapter.items()):
        for f in takes:
            dest = root / "assets_src" / "voice" / lang / ch_id / (f.stem + f.suffix.lower())
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, dest)
            rep.imported.append(dest.relative_to(root).as_posix())

        mf = chapter_dir_by_id[ch_id] / "voice" / f"{lang}{MANIFEST_SUFFIX}"
        doc = load_yaml(mf) if mf.is_file() else {
            "schema": "voice@1", "chapter": ch_id, "lang": lang, "lines": {}}
        doc.setdefault("lines", {})
        for f in takes:
            doc["lines"][f.stem] = dict(doc["lines"].get(f.stem) or {}, status=status)
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


def _write_manifest(path: Path, doc: dict) -> None:
    """Детерминированная запись: сортировка строк по id — диффы читаемы,
    merge-конфликты локальны."""
    lines = doc.get("lines") or {}
    out = [f"schema: {doc['schema']}",
           f"chapter: {doc['chapter']}",
           f"lang: {doc['lang']}",
           "lines:" if lines else "lines: {}"]
    for lid in sorted(lines):
        spec = lines[lid]
        fields_ = [f"status: {spec['status']}"]
        if spec.get("actor"):
            fields_.append(f"actor: {spec['actor']}")
        out.append(f"  {lid}: {{{', '.join(fields_)}}}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
