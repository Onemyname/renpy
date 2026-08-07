<#
.SYNOPSIS
    Bootstrap DAZ Studio для конвейера рендеров (Фаза 0, ADR-0006).

.DESCRIPTION
    Полностью автоматическая установка DAZ Studio невозможна: дистрибутив
    привязан к бесплатному аккаунту DAZ и ставится через DAZ Install Manager
    (DIM) с логином. Скрипт доводит машину до последнего ручного шага:

      1. Детектирует уже установленные DAZ Studio / DIM (реестр + стандартные пути).
      2. Готовит библиотеку контента на D: (D:\DAZ3D\Library) — модели/ассеты
         не должны жить на системном диске.
      3. Ищет скачанный установщик DIM в ~/Downloads и запускает его.
      4. Печатает точный чеклист оставшихся ручных шагов (аккаунт, DIM, Iray).

    Пиратские сборки/ассеты не используются: только официальный дистрибутив.

.PARAMETER LibraryRoot
    Куда класть библиотеку контента DAZ. По умолчанию D:\DAZ3D\Library.

.PARAMETER OpenDownloadPage
    Открыть страницу загрузки DAZ в браузере (по умолчанию НЕ открывается —
    скрипт только печатает URL).
#>
[CmdletBinding()]
param(
    [string]$LibraryRoot = "D:\DAZ3D\Library",
    [switch]$OpenDownloadPage
)

$ErrorActionPreference = "Stop"

function Ok($msg)   { Write-Host " [OK]   $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host " [....] $msg" -ForegroundColor Yellow }

Write-Host "=== DAZ Studio bootstrap ===" -ForegroundColor Cyan

# ── 1. Детекция установленного ────────────────────────────────────────────────
$studioExe = $null
$studioCandidates = @(
    "C:\Program Files\DAZ 3D\DAZStudio4 64-bit\DAZStudio.exe"
)
try {
    $reg = Get-ItemProperty "HKLM:\SOFTWARE\DAZ\Studio4" -ErrorAction SilentlyContinue
    if ($reg -and $reg.InstallPath) { $studioCandidates += (Join-Path $reg.InstallPath "DAZStudio.exe") }
} catch {}
foreach ($c in $studioCandidates) { if (Test-Path $c) { $studioExe = $c; break } }

$dim = $null
foreach ($c in @("C:\Program Files (x86)\DAZ 3D\DAZ3DIM1\DAZ3DIM.exe",
                 "C:\Program Files\DAZ 3D\DAZ3DIM1\DAZ3DIM.exe")) {
    if (Test-Path $c) { $dim = $c; break }
}

if ($studioExe) { Ok "DAZ Studio установлен: $studioExe" } else { Warn "DAZ Studio не найден" }
if ($dim)       { Ok "DAZ Install Manager установлен: $dim" } else { Warn "DAZ Install Manager (DIM) не найден" }

# ── 2. Библиотека контента на D: ─────────────────────────────────────────────
if (-not (Test-Path $LibraryRoot)) {
    New-Item -ItemType Directory -Force -Path $LibraryRoot | Out-Null
    Ok "создана библиотека контента: $LibraryRoot"
} else {
    Ok "библиотека контента: $LibraryRoot"
}

# ── 3. Установщик DIM в Downloads? ───────────────────────────────────────────
if (-not $dim) {
    $installer = Get-ChildItem "$env:USERPROFILE\Downloads" -Filter "*DAZ*Install*Manager*.exe" -ErrorAction SilentlyContinue |
                 Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $installer) {
        $installer = Get-ChildItem "$env:USERPROFILE\Downloads" -Filter "DAZ3DIM*.exe" -ErrorAction SilentlyContinue |
                     Sort-Object LastWriteTime -Descending | Select-Object -First 1
    }
    if ($installer) {
        Ok "найден установщик DIM: $($installer.FullName) — запускаю"
        Start-Process $installer.FullName
    } else {
        Warn "установщик DIM в ~/Downloads не найден"
        if ($OpenDownloadPage) { Start-Process "https://www.daz3d.com/get_studio" }
    }
}

# ── 4. Оставшиеся ручные шаги ────────────────────────────────────────────────
Write-Host ""
Write-Host "Ручные шаги (лицензия/аккаунт — автоматизация невозможна):" -ForegroundColor Cyan
$step = 1
if (-not $dim) {
    Write-Host " $step) Создайте бесплатный аккаунт и скачайте DAZ Install Manager: https://www.daz3d.com/get_studio"; $step++
    Write-Host " $step) Запустите этот скрипт снова — он подхватит установщик из Downloads"; $step++
}
if (-not $studioExe) {
    Write-Host " $step) В DIM залогиньтесь и установите: DAZ Studio 4.24+ (Blackwell/RTX 50xx"
    Write-Host "     поддерживается только свежим Iray), Genesis 8.1/9 Starter Essentials"; $step++
}
Write-Host " $step) В DIM: Settings -> Installation -> добавьте путь библиотеки: $LibraryRoot"; $step++
Write-Host " $step) В DAZ Studio: Edit -> Preferences -> Content -> Content Directory Manager ->"
Write-Host "     добавьте $LibraryRoot (DAZ Studio Formats + Poser Formats)"; $step++
Write-Host " $step) Render Settings -> Advanced: включите видеокарту (RTX 5080) + OptiX Prime,"
Write-Host "     снимите галку CPU fallback — контроль, что рендерит GPU (см. docs/pipeline/phase-0.md)"
Write-Host ""
Write-Host "Проверка после установки: vn pipeline doctor (строка 'DAZ Studio')" -ForegroundColor Green
