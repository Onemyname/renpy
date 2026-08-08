<#
.SYNOPSIS
    Bootstrap Virt-a-Mate (VaM) как опционального третьего источника конвейера
    (Фаза 0, ADR-0006).

.DESCRIPTION
    VaM не имеет установщика-мастера: это распаковка архива в папку + файл-ключ
    рядом (Patreon) ЛИБО установка через Steam. Легальные пути:
      1. Free — бесплатная сборка с демо-контентом (аккаунт VaM Hub);
      2. Steam — Creator edition + vamX (appId 2149830);
      3. Patreon — full-сборка + key-файл по уровню подписки.
    Скрипт:
      - детектит уже установленный VaM (VN_VAM, D:\VaM, Steam-библиотеки);
      - готовит D:\VaM;
      - если в ~/Downloads лежит распакуемый архив VaM (.zip) — распаковывает;
      - прописывает VN_VAM для vn pipeline doctor;
      - печатает чеклист оставшихся ручных шагов.
    Пиратские сборки/крэки/ключи не используются.

.PARAMETER InstallRoot
    Куда распаковывать VaM при ручной (Patreon/Free) установке. По умолчанию D:\VaM.
#>
[CmdletBinding()]
param(
    [string]$InstallRoot = "D:\VaM",
    [switch]$NoEnvVar
)

$ErrorActionPreference = "Stop"
$SteamAppId = "2149830"

function Ok($m)   { Write-Host " [OK]   $m" -ForegroundColor Green }
function Warn($m) { Write-Host " [....] $m" -ForegroundColor Yellow }

Write-Host "=== Virt-a-Mate bootstrap (опциональный источник, ADR-0006) ===" -ForegroundColor Cyan

# ── 1. Детект установленного ──────────────────────────────────────────────────
function Find-Vam {
    $cands = @()
    if ($env:VN_VAM) { $cands += (Join-Path $env:VN_VAM "VaM.exe") }
    $cands += @("$InstallRoot\VaM.exe", "C:\VaM\VaM.exe")
    # Steam-библиотеки: дефолт + libraryfolders.vdf
    $steamRoots = @()
    try {
        $sp = (Get-ItemProperty "HKCU:\Software\Valve\Steam" -ErrorAction Stop).SteamPath
        if ($sp) { $steamRoots += ($sp -replace '/','\') }
    } catch {}
    $steamRoots += "C:\Program Files (x86)\Steam"
    foreach ($sr in $steamRoots | Select-Object -Unique) {
        $cands += "$sr\steamapps\common\Virt-A-Mate\VaM.exe"
        $vdf = "$sr\steamapps\libraryfolders.vdf"
        if (Test-Path $vdf) {
            foreach ($m in [regex]::Matches((Get-Content $vdf -Raw), '"path"\s*"([^"]+)"')) {
                $lib = $m.Groups[1].Value -replace '\\\\','\'
                $cands += "$lib\steamapps\common\Virt-A-Mate\VaM.exe"
            }
        }
    }
    foreach ($c in $cands) { if ($c -and (Test-Path $c)) { return $c } }
    return $null
}

$vam = Find-Vam
if ($vam) {
    Ok "VaM найден: $vam"
    if (-not $NoEnvVar) {
        $dir = Split-Path $vam -Parent
        if ([Environment]::GetEnvironmentVariable("VN_VAM","User") -ne $dir) {
            [Environment]::SetEnvironmentVariable("VN_VAM", $dir, "User")
            Ok "VN_VAM=$dir (user env; новые терминалы подхватят)"
        }
    }
    Write-Host ""
    Write-Host "Готово. Проверка: vn pipeline doctor (строка Virt-a-Mate)." -ForegroundColor Green
    Write-Host "Дальше — контент: сцена -> assets_src/vam/<...>.render.yaml (vam_render@1) ->"
    Write-Host "захват в assets_src/png/cg или video_src -> vn assets vam validate."
    return
}

Warn "VaM не найден ни по VN_VAM, ни в $InstallRoot, ни в Steam-библиотеках"

# ── 2. Подготовка папки + распаковка из Downloads (Patreon/Free zip) ──────────
if (-not (Test-Path $InstallRoot)) {
    New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
    Ok "создана папка установки: $InstallRoot"
}

$zip = Get-ChildItem "$env:USERPROFILE\Downloads" -Filter "VaM*.zip" -ErrorAction SilentlyContinue |
       Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($zip) {
    Ok "найден архив: $($zip.FullName) — распаковываю в $InstallRoot"
    Expand-Archive -Path $zip.FullName -DestinationPath $InstallRoot -Force
    $vam = Find-Vam
    if ($vam) { Ok "распаковано: $vam" }
} else {
    Warn "архив VaM*.zip в ~/Downloads не найден"
}

# ── 3. Оставшиеся ручные шаги ────────────────────────────────────────────────
Write-Host ""
Write-Host "Ручные шаги (аккаунт/лицензия — автоматизация невозможна):" -ForegroundColor Cyan
Write-Host " Вариант A (Steam, проще всего):"
Write-Host "   1) Steam -> купите/установите 'Virt-A-Mate' (appId $SteamAppId, Creator + vamX)"
Write-Host "   2) запустите этот скрипт снова — он найдёт VaM в Steam-библиотеке"
Write-Host " Вариант B (Free/Patreon, ручная распаковка):"
Write-Host "   1) аккаунт на hub.virtamate.com; скачайте сборку VaM (Free — с демо-контентом)"
Write-Host "   2) положите архив VaM*.zip в ~/Downloads и запустите скрипт снова (распакует в $InstallRoot)"
Write-Host "      или распакуйте вручную в $InstallRoot"
Write-Host "   3) Patreon-подписчикам: положите файл-ключ (key) в корень $InstallRoot рядом с VaM.exe"
Write-Host ""
Write-Host "После установки: vn pipeline doctor (строка Virt-a-Mate должна стать PASS)" -ForegroundColor Green
Write-Host "Примечание: VR не нужен — VaM работает в desktop-режиме." -ForegroundColor DarkGray
