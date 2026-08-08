"""vn pipeline — окружение production-конвейера рендеров (ADR-0006, Фаза 0).

Конвейер: DAZ Studio (рендер) -> ComfyUI/Wan (AI-обработка/видео) -> ffmpeg
(VP9/WebM) -> game/assets. Этот модуль проверяет и готовит ВНЕШНЮЮ часть
конвейера: инструменты, GPU, модели. Внутренняя часть (сырцы -> артефакты) —
assets/video.py и assets/provenance.py.

Пути инструментов не хардкодятся: ffmpeg/ffprobe ищутся в PATH (переопределение —
VN_FFMPEG/VN_FFPROBE), ComfyUI — VN_COMFYUI либо стандартные корни. Манифест
моделей — tools/comfyui-models.yaml (schema comfyui_models@1): статусы, загрузка
свободных моделей с докачкой, честная остановка на auth: manual."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import click

from . import __version__
from .repo import load_yaml
from .schemas import SchemaRegistry

MODELS_MANIFEST_REL = "tools/comfyui-models.yaml"
MODELS_LOCK_NAME = ".vn-models.json"      # лежит в <ComfyUI>/models/, НЕ в git
COMFYUI_DEFAULT_ROOTS = ("D:/ComfyUI", "C:/ComfyUI", "~/ComfyUI")


class PipelineError(RuntimeError):
    pass


# ── Обнаружение инструментов ──────────────────────────────────────────────────

def find_tool(name: str, env_var: str) -> Path | None:
    """PATH + env-переопределение: doctor обязан показывать, ЧЕМ именно кодируем."""
    env = os.environ.get(env_var)
    if env:
        p = Path(env)
        if p.is_file():
            return p
        return None    # явное переопределение битое — не маскируем PATH-фоллбеком
    which = shutil.which(name)
    return Path(which) if which else None


def find_ffmpeg() -> Path | None:
    return find_tool("ffmpeg", "VN_FFMPEG")


def find_ffprobe() -> Path | None:
    return find_tool("ffprobe", "VN_FFPROBE")


def comfyui_root(explicit: str | None = None) -> Path | None:
    candidates = [explicit] if explicit else []
    env = os.environ.get("VN_COMFYUI")
    if env:
        candidates.append(env)
    candidates += list(COMFYUI_DEFAULT_ROOTS)
    for cand in candidates:
        if not cand:
            continue
        p = Path(os.path.expanduser(cand))
        if (p / "main.py").is_file():
            return p
    return None


def comfyui_python(comfy: Path) -> Path | None:
    venv = comfy / "venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    return venv if venv.is_file() else None


def _dim_settings() -> dict:
    """Пути из конфигов DAZ Install Manager: DIM может ставить и приложение,
    и контент куда угодно — хардкод Program Files слеп. Пути установки живут
    в per-account настройках (UserAccounts/*.ini), не в AppSettings.ini."""
    im_dir = Path(os.environ.get("APPDATA", "")) / "DAZ 3D" / "InstallManager"
    result: dict[str, str] = {}
    if not im_dir.is_dir():
        return result
    inis = sorted((im_dir / "UserAccounts").glob("*.ini")) + [
        im_dir / "Settings" / "AppSettings.ini"]
    for ini in inis:
        if not ini.is_file():
            continue
        for line in ini.read_text(encoding="utf-8", errors="replace").splitlines():
            key, _, value = line.partition("=")
            if value and key.strip() not in result:
                result[key.strip()] = value.strip()
    return result


def daz_studio_path() -> Path | None:
    candidates: list[Path] = []
    dim = _dim_settings()
    for key in ("Software64Path", "Software32Path"):
        base = dim.get(key)
        if base:
            candidates += sorted(Path(base).glob("DAZ 3D/DAZStudio*/DAZStudio.exe"),
                                 reverse=True)   # свежая версия первой
    if sys.platform == "win32":
        try:
            import winreg

            for studio in ("Studio6", "Studio5", "Studio4"):
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                        rf"SOFTWARE\DAZ\{studio}") as k:
                        install, _ = winreg.QueryValueEx(k, "InstallPath")
                        candidates.append(Path(install) / "DAZStudio.exe")
                except OSError:
                    continue
        except ImportError:
            pass
    candidates += [Path(rf"C:\Program Files\DAZ 3D\DAZStudio{v} 64-bit\DAZStudio.exe")
                   for v in ("6", "5", "4")]
    for c in candidates:
        if c.is_file():
            return c
    return None


def daz_content_library() -> Path | None:
    """Контентная библиотека по конфигу DIM (CurInstallPath)."""
    cur = _dim_settings().get("CurInstallPath")
    if cur and Path(cur).is_dir():
        return Path(cur)
    return None


VAM_STEAM_APPID = "2149830"


def _steam_libraries() -> list[Path]:
    """Корни библиотек Steam: дефолт + записи libraryfolders.vdf (несколько дисков)."""
    libs: list[Path] = []
    steam_root = None
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
                steam_root = Path(winreg.QueryValueEx(k, "SteamPath")[0])
        except OSError:
            pass
    for cand in (steam_root, Path(r"C:\Program Files (x86)\Steam")):
        if cand and cand.is_dir():
            libs.append(cand)
            vdf = cand / "steamapps" / "libraryfolders.vdf"
            if vdf.is_file():
                import re as _re
                for m in _re.finditer(r'"path"\s*"([^"]+)"',
                                      vdf.read_text(encoding="utf-8", errors="replace")):
                    libs.append(Path(m.group(1).replace("\\\\", "\\")))
    # dedup, порядок сохраняем
    seen, out = set(), []
    for p in libs:
        if str(p) not in seen:
            seen.add(str(p))
            out.append(p)
    return out


def vam_path() -> Path | None:
    """VaM.exe: VN_VAM -> стандартные корни -> Steam-библиотеки (appid 2149830)."""
    candidates: list[Path] = []
    env = os.environ.get("VN_VAM")
    if env:
        p = Path(env)
        candidates += [p, p / "VaM.exe"]
    candidates += [Path(r"D:\VaM\VaM.exe"), Path(r"C:\VaM\VaM.exe")]
    for lib in _steam_libraries():
        candidates.append(lib / "steamapps" / "common" / "Virt-A-Mate" / "VaM.exe")
    for c in candidates:
        if c.is_file():
            return c
        if c.is_dir() and (c / "VaM.exe").is_file():
            return c / "VaM.exe"
    return None


def _run_out(cmd: list[str], timeout: int = 30) -> str | None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            return None
        return proc.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None


def gpu_info() -> str | None:
    out = _run_out(["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                    "--format=csv,noheader"])
    return out.splitlines()[0].strip() if out else None


def ffmpeg_has_vp9(ffmpeg: Path) -> bool:
    out = _run_out([str(ffmpeg), "-hide_banner", "-encoders"])
    return bool(out) and "libvpx-vp9" in out


# ── Манифест моделей ──────────────────────────────────────────────────────────

@dataclass
class ModelStatus:
    entry: dict
    state: str        # ok | missing | undersized | no_root
    actual_mb: float | None = None


def load_models_manifest(root: Path) -> list[dict]:
    path = root / MODELS_MANIFEST_REL
    if not path.is_file():
        raise PipelineError(f"{MODELS_MANIFEST_REL} не найден")
    doc = load_yaml(path)
    errors = SchemaRegistry(root / "tools" / "schemas").validate(doc, MODELS_MANIFEST_REL)
    if errors:
        raise PipelineError("манифест моделей не проходит схему:\n  " + "\n  ".join(errors))
    return doc["models"]


def _models_root(comfy: Path | None) -> Path | None:
    return (comfy / "models") if comfy else None


def _load_lock(models_root: Path) -> dict:
    lock = models_root / MODELS_LOCK_NAME
    if lock.is_file():
        try:
            return json.loads(lock.read_text(encoding="utf-8"))
        except ValueError:
            return {}
    return {}


def _save_lock(models_root: Path, data: dict) -> None:
    (models_root / MODELS_LOCK_NAME).write_text(
        json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")


def model_status(entry: dict, models_root: Path | None, lock: dict) -> ModelStatus:
    if models_root is None:
        return ModelStatus(entry, "no_root")
    dest = models_root / entry["dest"]
    if not dest.is_file():
        return ModelStatus(entry, "missing")
    actual_mb = dest.stat().st_size / (1024 * 1024)
    locked = lock.get(entry["id"])
    if locked and abs(actual_mb - locked["size_mb"]) > 1:
        return ModelStatus(entry, "undersized", actual_mb)   # обрезанная докачка/подмена
    if entry.get("size_mb") and actual_mb < entry["size_mb"] * 0.5:
        return ModelStatus(entry, "undersized", actual_mb)
    return ModelStatus(entry, "ok", actual_mb)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _civitai_key() -> str | None:
    """Ключ Civitai из окружения процесса."""
    return os.environ.get("CIVITAI_API_KEY") or None


def _civitai_key_in_registry() -> bool:
    """Есть ли ключ в User-окружении Windows (реестр), даже если процесс его не
    унаследовал — типичный случай после свежего setx в уже открытом терминале."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            value, _ = winreg.QueryValueEx(k, "CIVITAI_API_KEY")
            return bool(value)
    except OSError:
        return False


def _download(url: str, dest: Path, headers: list[str] | None = None) -> None:
    """curl с докачкой (-C -), фоллбек на urllib. Пишем в .part: обрезанный файл
    никогда не выглядит готовой моделью. headers — например Authorization
    для Civitai (ключ пользователя, значение в логи не попадает)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    curl = shutil.which("curl")
    if curl:
        cmd = [curl, "-L", "--fail", "--retry", "3", "--retry-delay", "5",
               "-C", "-", "-o", str(part)]
        for h in headers or []:
            cmd += ["-H", h]
        proc = subprocess.run(cmd + [url])
        if proc.returncode != 0:
            raise PipelineError(f"curl вернул код {proc.returncode}: {url}")
    else:
        import urllib.request
        try:
            req = urllib.request.Request(url)
            for h in headers or []:
                name, _, value = h.partition(":")
                req.add_header(name.strip(), value.strip())
            with urllib.request.urlopen(req) as r, part.open("wb") as f:
                shutil.copyfileobj(r, f, length=1 << 20)
        except OSError as e:
            raise PipelineError(f"загрузка не удалась ({e}): {url}") from e
    os.replace(part, dest)


def pull_models(root: Path, comfy: Path | None, only: set[str] | None = None,
                include_optional: bool = False) -> int:
    """Возвращает exit-код: 0 = всё необходимое на месте (manual-шаги — не ошибка)."""
    if comfy is None:
        click.secho("ComfyUI не найден — сначала tools/setup-comfyui.ps1 "
                    "(или установите VN_COMFYUI)", fg="red")
        return 1
    models_root = _models_root(comfy)
    entries = load_models_manifest(root)
    lock = _load_lock(models_root)
    failures, manual, needs_key = 0, [], []
    for entry in entries:
        if only is not None and entry["id"] not in only:
            continue
        if only is None and not include_optional and not entry["required"]:
            continue
        st = model_status(entry, models_root, lock)
        if st.state == "ok":
            click.echo(f"  на месте: {entry['id']} ({st.actual_mb:.0f} МБ)")
            continue
        if entry["auth"] == "manual":
            manual.append(entry)
            continue
        headers = None
        if entry["auth"] == "civitai_key":
            key = _civitai_key()
            if not key:
                click.secho(f"  нужен ключ: {entry['id']} — Civitai отдаёт файл только "
                            f"с API-ключом вашего аккаунта", fg="yellow")
                if _civitai_key_in_registry():
                    # Частая грабля Windows: setx записал ключ в реестр, но текущий
                    # процесс (и родительская оболочка) унаследовали старое окружение.
                    click.secho("    ключ ЕСТЬ в User-окружении, но не виден этому "
                                "процессу — откройте НОВЫЙ терминал и повторите "
                                "vn pipeline models --pull", fg="yellow")
                else:
                    click.echo("    1) civitai.com -> Account Settings -> API Keys -> Add API key")
                    click.echo("    2) setx CIVITAI_API_KEY <ключ>")
                    click.echo("    3) в НОВОМ терминале: vn pipeline models --pull")
                needs_key.append(entry)
                continue
            headers = [f"Authorization: Bearer {key}"]
        size = f" (~{entry['size_mb']:.0f} МБ)" if entry.get("size_mb") else ""
        click.secho(f"  скачиваю: {entry['id']}{size} -> models/{entry['dest']}", fg="cyan")
        try:
            _download(entry["source"], models_root / entry["dest"], headers=headers)
        except PipelineError as e:
            click.secho(f"  ошибка: {entry['id']}: {e}", fg="red")
            failures += 1
            continue
        dest = models_root / entry["dest"]
        digest = _sha256(dest)
        if entry.get("sha256") and digest != entry["sha256"]:
            click.secho(f"  ошибка: {entry['id']}: sha256 не совпал с манифестом — "
                        f"файл удалён", fg="red")
            dest.unlink()
            failures += 1
            continue
        lock[entry["id"]] = {
            "sha256": digest,
            "size_mb": dest.stat().st_size / (1024 * 1024),
            "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": entry["source"],
        }
        _save_lock(models_root, lock)
        click.secho(f"  готово: {entry['id']} (sha256 {digest[:16]}…)", fg="green")
    for entry in manual:
        click.secho(f"  ручной шаг: {entry['id']} — требуется аккаунт/лицензия", fg="yellow")
        click.echo(f"    1) откройте: {entry['source']}")
        click.echo(f"    2) скачайте модель ({entry['role']})")
        click.echo(f"    3) положите файл как: {models_root / entry['dest']}")
    if failures:
        click.secho(f"models: {failures} загрузок не удалось", fg="red")
        return 1
    remaining = len(manual) + len(needs_key)
    click.secho("models: OK" + (f" ({remaining} ручных шагов осталось)" if remaining else ""),
                fg="green")
    return 0


def models_table(root: Path, comfy: Path | None) -> tuple[list[ModelStatus], dict]:
    entries = load_models_manifest(root)
    models_root = _models_root(comfy)
    lock = _load_lock(models_root) if models_root else {}
    return [model_status(e, models_root, lock) for e in entries], lock


# ── vn pipeline doctor ────────────────────────────────────────────────────────

def _check(checks: list, state: str, title: str, hint: str = "") -> None:
    checks.append((state, title, hint))


def run_pipeline_doctor(root: Path, comfy_opt: str | None = None) -> int:
    """PASS/WARN/FAIL-сводка окружения конвейера. FAIL => exit 1."""
    checks: list[tuple[str, str, str]] = []

    py_ok = sys.version_info >= (3, 10)
    _check(checks, "PASS" if py_ok else "FAIL", f"Python {sys.version.split()[0]}",
           "" if py_ok else "нужен Python >= 3.10")
    _check(checks, "PASS", f"vn {__version__}")

    ffmpeg = find_ffmpeg()
    if ffmpeg:
        ver = _run_out([str(ffmpeg), "-version"]) or ""
        ver = ver.splitlines()[0].split(" version ")[-1].split()[0] if ver else "?"
        _check(checks, "PASS", f"ffmpeg {ver} ({ffmpeg})")
        _check(checks, "PASS" if ffmpeg_has_vp9(ffmpeg) else "FAIL", "VP9-энкодер (libvpx-vp9)",
               "сборка ffmpeg без libvpx — поставьте полную (winget install Gyan.FFmpeg)")
    else:
        _check(checks, "FAIL", "ffmpeg не найден",
               "winget install Gyan.FFmpeg (или переопределите VN_FFMPEG)")
    _check(checks, "PASS" if find_ffprobe() else "FAIL",
           "ffprobe" + ("" if find_ffprobe() else " не найден"),
           "" if find_ffprobe() else "идёт в комплекте ffmpeg; проверьте PATH/VN_FFPROBE")

    gpu = gpu_info()
    _check(checks, "PASS" if gpu else "WARN", f"GPU: {gpu or 'nvidia-smi не отвечает'}",
           "" if gpu else "без NVIDIA GPU локальная генерация невозможна (аренда GPU — phase-0.md)")

    comfy = comfyui_root(comfy_opt)
    if comfy:
        _check(checks, "PASS", f"ComfyUI: {comfy}")
        venv_py = comfyui_python(comfy)
        if venv_py:
            out = _run_out([str(venv_py), "-c",
                            "import torch; print(torch.__version__, torch.cuda.is_available())"],
                           timeout=120)
            if out:
                torch_ver, cuda_ok = out.split()
                _check(checks, "PASS" if cuda_ok == "True" else "WARN",
                       f"PyTorch {torch_ver}, CUDA {'доступна' if cuda_ok == 'True' else 'НЕдоступна'}",
                       "" if cuda_ok == "True" else
                       "нужен torch с индексом cu128 (Blackwell) — tools/setup-comfyui.ps1")
            else:
                _check(checks, "WARN", "PyTorch в venv ComfyUI не импортируется",
                       "перезапустите tools/setup-comfyui.ps1")
        else:
            _check(checks, "WARN", "venv ComfyUI отсутствует", "tools/setup-comfyui.ps1")
        manager = comfy / "custom_nodes" / "ComfyUI-Manager"
        _check(checks, "PASS" if manager.is_dir() else "WARN",
               "ComfyUI-Manager" + ("" if manager.is_dir() else " отсутствует"),
               "" if manager.is_dir() else "tools/setup-comfyui.ps1 доставит")
    else:
        _check(checks, "WARN", "ComfyUI не найден",
               "tools/setup-comfyui.ps1 (ставит в D:/ComfyUI и пропишет VN_COMFYUI)")

    try:
        statuses, _lock = models_table(root, comfy)
    except PipelineError as e:
        _check(checks, "FAIL", "манифест моделей", str(e))
        statuses = []
    req = [s for s in statuses if s.entry["required"]]
    if comfy is None:
        if req:
            _check(checks, "WARN", f"модели: не проверялись (нет ComfyUI), требуется {len(req)}")
    elif req:
        missing = [s for s in req if s.state != "ok"]
        if not missing:
            _check(checks, "PASS", f"модели: все обязательные на месте ({len(req)})")
        else:
            names = ", ".join(s.entry["id"] for s in missing[:4])
            more = f" и ещё {len(missing) - 4}" if len(missing) > 4 else ""
            _check(checks, "WARN", f"модели: {len(req) - len(missing)}/{len(req)} обязательных "
                                   f"(нет: {names}{more})", "vn pipeline models --pull")
    opt_manual = [s for s in statuses if not s.entry["required"] and s.state != "ok"]
    if opt_manual:
        _check(checks, "WARN", f"опциональные модели: {len(opt_manual)} не установлено",
               "vn pipeline models (список и инструкции)")

    daz = daz_studio_path()
    _check(checks, "PASS" if daz else "WARN",
           f"DAZ Studio: {daz or 'не найден'}",
           "" if daz else "tools/install-daz.ps1 + docs/pipeline/phase-0.md (ручные шаги)")
    if daz:
        lib = daz_content_library()
        _check(checks, "PASS" if lib else "WARN",
               f"библиотека DAZ: {lib or 'не найдена в конфиге DIM'}",
               "" if lib else "DIM -> Settings -> Installation: путь контента")

    # VaM — опциональный третий источник (ADR-0006): отсутствие не проблема.
    vam = vam_path()
    _check(checks, "PASS" if vam else "WARN",
           f"Virt-a-Mate: {vam or 'не установлен (опционально)'}",
           "" if vam else "опционально: tools/install-vam.ps1 (третий источник рендеров)")

    seen_drives = set()
    for label, p in (("репозиторий", root), ("модели", comfy)):
        if p is None:
            continue
        anchor = Path(p).resolve().anchor or str(p)
        if anchor in seen_drives:
            continue
        seen_drives.add(anchor)
        free_gb = shutil.disk_usage(p).free / (1024 ** 3)
        _check(checks, "PASS" if free_gb >= 30 else "WARN",
               f"диск {anchor} ({label}): свободно {free_gb:.0f} ГБ",
               "" if free_gb >= 30 else "меньше 30 ГБ — модели/рендеры быстро упрутся")

    from .doctor import sdk_path, sdk_version
    sdk = sdk_path()
    _check(checks, "PASS" if sdk else "WARN",
           f"Ren'Py SDK: {sdk_version(sdk) if sdk else 'не найден (RENPY_SDK)'}",
           "" if sdk else "нужен для vn build/play — vn doctor подскажет")

    colors = {"PASS": "green", "WARN": "yellow", "FAIL": "red"}
    hard_fail = False
    for state, title, hint in checks:
        click.secho(f" {state:<4}  {title}", fg=colors[state])
        if hint and state != "PASS":
            click.echo(f"       -> {hint}")
        if state == "FAIL":
            hard_fail = True
    return 1 if hard_fail else 0
