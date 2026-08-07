<#
.SYNOPSIS
    Идемпотентный bootstrap ComfyUI для production-конвейера (Фаза 0, ADR-0006).

.DESCRIPTION
    Разворачивает ComfyUI в изолированном окружении:
      1. Проверяет git / Python >= 3.10 / свободное место.
      2. Клонирует ComfyUI (или использует существующий чекаут).
      3. Создаёт venv и ставит PyTorch с CUDA 12.8 (единственная ветка с
         поддержкой Blackwell / RTX 50xx; более старые wheel'ы не знают sm_120
         и молча падают на CPU).
      4. Ставит зависимости ComfyUI и ComfyUI-Manager.
      5. Создаёт структуру models/ (сами модели НЕ качает — это делает
         `vn pipeline models --pull` по манифесту tools/comfyui-models.yaml).
      6. Прописывает пользовательскую переменную VN_COMFYUI (для vn pipeline doctor).

    Скрипт безопасно перезапускаем: каждый шаг сначала проверяет, не сделан ли он.

.PARAMETER InstallRoot
    Куда ставить ComfyUI. По умолчанию D:\ComfyUI (диск D освобождён под тяжёлые
    ассеты/модели; см. docs/pipeline/phase-0.md).

.PARAMETER Update
    Подтянуть свежие ComfyUI и ComfyUI-Manager (git pull --ff-only), если уже установлены.

.PARAMETER NoEnvVar
    Не трогать пользовательскую переменную окружения VN_COMFYUI.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools/setup-comfyui.ps1
    powershell -ExecutionPolicy Bypass -File tools/setup-comfyui.ps1 -InstallRoot C:\ComfyUI -Update
#>
[CmdletBinding()]
param(
    [string]$InstallRoot = "D:\ComfyUI",
    [switch]$Update,
    [switch]$NoEnvVar
)

$ErrorActionPreference = "Stop"
$TorchIndex = "https://download.pytorch.org/whl/cu128"
$ComfyRepo = "https://github.com/comfyanonymous/ComfyUI.git"
$ManagerRepo = "https://github.com/Comfy-Org/ComfyUI-Manager.git"
$ModelDirs = @("checkpoints", "diffusion_models", "text_encoders", "vae", "loras", "upscale_models")

function Step($msg)  { Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok($msg)    { Write-Host "  + $msg" -ForegroundColor Green }
function Skip($msg)  { Write-Host "  = $msg (уже сделано)" -ForegroundColor DarkGray }
function Fail($msg)  { Write-Host "ОШИБКА: $msg" -ForegroundColor Red; exit 1 }

# ── 1. Предусловия ────────────────────────────────────────────────────────────
Step "Проверка предусловий"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Fail "git не найден в PATH" }
Ok "git: $((git --version) -join '')"

$py = $null
foreach ($cand in @("py -3.12", "py -3.11", "py -3.10", "python")) {
    $exe, $pyArgs = $cand.Split(" ")
    try {
        $v = & $exe @($pyArgs) -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and [version]$v -ge [version]"3.10") { $py = $cand; break }
    } catch {}
}
if (-not $py) { Fail "Python >= 3.10 не найден (python.org или winget install Python.Python.3.12)" }
Ok "Python: $py"

$drive = (Resolve-Path -Path (Split-Path -Qualifier $InstallRoot)).Path
$free = (Get-PSDrive -Name $drive.TrimEnd(':\')).Free / 1GB
if ($free -lt 30) { Fail ("на диске {0} свободно {1:N0} ГБ — нужно >= 30 ГБ (venv+torch ~12 ГБ, модели десятки ГБ)" -f $drive, $free) }
Ok ("диск {0} свободно {1:N0} ГБ" -f $drive, $free)

# ── 2. ComfyUI ────────────────────────────────────────────────────────────────
Step "ComfyUI -> $InstallRoot"
if (Test-Path (Join-Path $InstallRoot "main.py")) {
    if ($Update) {
        git -C $InstallRoot pull --ff-only
        Ok "ComfyUI обновлён"
    } else { Skip "чекаут ComfyUI" }
} else {
    New-Item -ItemType Directory -Force -Path (Split-Path $InstallRoot -Parent) | Out-Null
    git clone --depth 1 $ComfyRepo $InstallRoot
    Ok "ComfyUI склонирован"
}

# ── 3. venv + PyTorch cu128 (Blackwell) ──────────────────────────────────────
Step "Изолированное окружение Python"
$venvPy = Join-Path $InstallRoot "venv\Scripts\python.exe"
if (Test-Path $venvPy) {
    Skip "venv"
} else {
    $exe, $pyArgs = $py.Split(" ")
    & $exe @($pyArgs) -m venv (Join-Path $InstallRoot "venv")
    if ($LASTEXITCODE -ne 0) { Fail "создание venv не удалось" }
    Ok "venv создан"
}

& $venvPy -m pip install --quiet --upgrade pip
if ($LASTEXITCODE -ne 0) { Fail "pip upgrade не удался" }

Step "PyTorch (CUDA 12.8, RTX 50xx/Blackwell)"
& $venvPy -c "import torch; assert torch.cuda.is_available(); print(torch.__version__)" 2>$null
if ($LASTEXITCODE -eq 0) {
    Skip "torch с CUDA"
} else {
    # Версии сознательно не пиннуем: индекс cu128 отдаёт последние совместимые
    # сборки; пин появится, если апстрим что-то сломает (тогда — фиксация здесь).
    & $venvPy -m pip install torch torchvision --index-url $TorchIndex
    if ($LASTEXITCODE -ne 0) { Fail "установка torch (cu128) не удалась" }
    Ok "torch установлен"
}

Step "Зависимости ComfyUI"
& $venvPy -m pip install --quiet -r (Join-Path $InstallRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { Fail "pip install -r requirements.txt не удался" }
Ok "requirements.txt установлены"

# ── 4. ComfyUI-Manager ────────────────────────────────────────────────────────
Step "ComfyUI-Manager"
$managerDir = Join-Path $InstallRoot "custom_nodes\ComfyUI-Manager"
if (Test-Path $managerDir) {
    if ($Update) { git -C $managerDir pull --ff-only; Ok "Manager обновлён" }
    else { Skip "ComfyUI-Manager" }
} else {
    git clone --depth 1 $ManagerRepo $managerDir
    Ok "ComfyUI-Manager установлен"
}

# ── 5. Структура models/ ─────────────────────────────────────────────────────
Step "Каталоги моделей"
foreach ($d in $ModelDirs) {
    $p = Join-Path $InstallRoot "models\$d"
    if (-not (Test-Path $p)) { New-Item -ItemType Directory -Force -Path $p | Out-Null; Ok "models/$d" }
}

# ── 6. VN_COMFYUI для vn pipeline doctor ─────────────────────────────────────
if (-not $NoEnvVar) {
    $cur = [Environment]::GetEnvironmentVariable("VN_COMFYUI", "User")
    if ($cur -ne $InstallRoot) {
        [Environment]::SetEnvironmentVariable("VN_COMFYUI", $InstallRoot, "User")
        $env:VN_COMFYUI = $InstallRoot
        Ok "VN_COMFYUI=$InstallRoot (user env; новые терминалы подхватят сами)"
    } else { Skip "VN_COMFYUI" }
}

# ── 7. Проверка GPU ──────────────────────────────────────────────────────────
Step "Проверка CUDA"
& $venvPy -c "import torch; print('torch', torch.__version__, '| cuda:', torch.cuda.is_available(), '|', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-')"
if ($LASTEXITCODE -ne 0) { Fail "torch не импортируется — окружение неконсистентно" }

Write-Host ""
Write-Host "Готово. Дальше:" -ForegroundColor Green
Write-Host "  1) vn pipeline models --pull     # модели по манифесту tools/comfyui-models.yaml"
Write-Host "  2) vn pipeline doctor            # сводная проверка окружения"
Write-Host "  3) запуск: $venvPy $InstallRoot\main.py"
