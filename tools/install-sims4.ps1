<#
.SYNOPSIS
    Bootstrap The Sims 4 как опционального четвёртого источника конвейера
    (ADR-0007) — источник за лицензионным гейтом EA.

.DESCRIPTION
    ВАЖНО (ADR-0007): визуал Sims 4 строится на ассетах EA. Пока лицензия с EA
    не урегулирована (project.yaml: sources.sims4.license: cleared), релизный
    гейт БЛОКИРУЕТ Sims4-контент в сборках; локальная подготовка (сцены, CC,
    захваты, провенанс) не ограничивается — основа готовится заранее.

    Установщик у игры есть (в отличие от VaM) — легальные пути:
      1. EA App — базовая игра free-to-play;
      2. Steam — appId 1222670 (тоже f2p; DLC покупаются отдельно).
    Скрипт:
      - детектит уже установленную игру (VN_SIMS4, реестр Maxis, EA App/Origin,
        Steam-библиотеки);
      - прописывает VN_SIMS4 для vn pipeline doctor;
      - печатает чеклист оставшихся ручных шагов (аккаунт EA, Mods/Tray, script mods).
    Пиратские сборки/крэки DLC не используются.
#>
[CmdletBinding()]
param(
    [switch]$NoEnvVar
)

$ErrorActionPreference = "Stop"
$SteamAppId = "1222670"
$ExeRel = "Game\Bin\TS4_x64.exe"

function Ok($m)   { Write-Host " [OK]   $m" -ForegroundColor Green }
function Warn($m) { Write-Host " [....] $m" -ForegroundColor Yellow }

Write-Host "=== The Sims 4 bootstrap (источник за лицензионным гейтом, ADR-0007) ===" -ForegroundColor Cyan

# ── 1. Детект установленного ──────────────────────────────────────────────────
function Find-Sims4 {
    $cands = @()
    if ($env:VN_SIMS4) {
        if ($env:VN_SIMS4 -like "*.exe") { $cands += $env:VN_SIMS4 }
        $cands += (Join-Path $env:VN_SIMS4 $ExeRel)
    }
    # Реестр Maxis — его пишут и EA App, и Origin
    foreach ($key in @("HKLM:\SOFTWARE\Maxis\The Sims 4",
                       "HKLM:\SOFTWARE\WOW6432Node\Maxis\The Sims 4")) {
        try {
            $dir = (Get-ItemProperty $key -ErrorAction Stop)."Install Dir"
            if ($dir) { $cands += (Join-Path $dir $ExeRel) }
        } catch {}
    }
    $cands += "C:\Program Files\EA Games\The Sims 4\$ExeRel"
    $cands += "C:\Program Files (x86)\Origin Games\The Sims 4\$ExeRel"
    # Steam-библиотеки: дефолт + libraryfolders.vdf
    $steamRoots = @()
    try {
        $sp = (Get-ItemProperty "HKCU:\Software\Valve\Steam" -ErrorAction Stop).SteamPath
        if ($sp) { $steamRoots += ($sp -replace '/','\') }
    } catch {}
    $steamRoots += "C:\Program Files (x86)\Steam"
    foreach ($sr in $steamRoots | Select-Object -Unique) {
        $cands += "$sr\steamapps\common\The Sims 4\$ExeRel"
        $vdf = "$sr\steamapps\libraryfolders.vdf"
        if (Test-Path $vdf) {
            foreach ($m in [regex]::Matches((Get-Content $vdf -Raw), '"path"\s*"([^"]+)"')) {
                $lib = $m.Groups[1].Value -replace '\\\\','\'
                $cands += "$lib\steamapps\common\The Sims 4\$ExeRel"
            }
        }
    }
    foreach ($c in $cands) { if ($c -and (Test-Path $c)) { return $c } }
    return $null
}

$sims = Find-Sims4
if ($sims) {
    Ok "The Sims 4 найден: $sims"
    if (-not $NoEnvVar) {
        # корень установки = две папки вверх от Game\Bin\TS4_x64.exe
        $dir = Split-Path (Split-Path (Split-Path $sims -Parent) -Parent) -Parent
        if ([Environment]::GetEnvironmentVariable("VN_SIMS4","User") -ne $dir) {
            [Environment]::SetEnvironmentVariable("VN_SIMS4", $dir, "User")
            Ok "VN_SIMS4=$dir (user env; новые терминалы подхватят)"
        }
    }
    $userData = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Electronic Arts\The Sims 4"
    if (Test-Path $userData) { Ok "пользовательские данные: $userData (Mods, Tray, Screenshots)" }
    else { Warn "папки Documents\Electronic Arts\The Sims 4 ещё нет — появится после первого запуска игры" }
    Write-Host ""
    Write-Host "Готово. Проверка: vn pipeline doctor (строка The Sims 4)." -ForegroundColor Green
    Write-Host "Дальше — контент: Tray-бандл (лот+семья) zip'ом -> assets_src/sims4/<...>.render.yaml"
    Write-Host "(sims4_render@1, game_version обязателен) -> захват в assets_src/png/cg или"
    Write-Host "video_src -> vn assets sims4 validate."
    Write-Host ""
    Write-Host "НАПОМИНАНИЕ (ADR-0007): до урегулирования лицензии с EA Sims4-контент" -ForegroundColor Yellow
    Write-Host "не пройдёт vn release validate — гейт снимается только project.yaml:" -ForegroundColor Yellow
    Write-Host "sources.sims4.license: cleared (после письменной договорённости)." -ForegroundColor Yellow
    return
}

Warn "The Sims 4 не найден ни по VN_SIMS4, ни в реестре Maxis, ни в EA/Origin/Steam-путях"

# ── 2. Оставшиеся ручные шаги ────────────────────────────────────────────────
Write-Host ""
Write-Host "Ручные шаги (аккаунт EA — автоматизация невозможна):" -ForegroundColor Cyan
Write-Host " Вариант A (EA App):"
Write-Host "   1) установите EA App, войдите в аккаунт EA"
Write-Host "   2) The Sims 4 — база free-to-play; нужные DLC покупаются (без крэков)"
Write-Host " Вариант B (Steam):"
Write-Host "   1) Steam -> установите 'The Sims 4' (appId $SteamAppId, f2p; привязка к аккаунту EA)"
Write-Host " После установки:"
Write-Host "   3) запустите игру один раз (создаст Documents\Electronic Arts\The Sims 4)"
Write-Host "   4) моды/CC — в ...\The Sims 4\Mods; в игре включите Options -> Other ->"
Write-Host "      Enable Custom Content and Mods (+ Script Mods Allowed) и перезапустите"
Write-Host "   5) запустите этот скрипт снова — он найдёт игру и пропишет VN_SIMS4"
Write-Host ""
Write-Host "После установки: vn pipeline doctor (строка The Sims 4 должна стать PASS)" -ForegroundColor Green
Write-Host "ЛИЦЕНЗИЯ (ADR-0007): релиз с Sims4-контентом заблокирован до урегулирования с EA." -ForegroundColor Yellow
