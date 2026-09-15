<#
.SYNOPSIS
  版本化备份 + 更新日志
.DESCRIPTION
  用法:
    .\备份.ps1 -Ver "v1.1" -Note "OCR 断网秒数支持、时间对话框紧凑化"
  输出:
    · 备份\v1.1_20260914_143025\
    · 更新日志.md 追加一条（最新在上）
#>
param(
    [Parameter(Mandatory=$true)]
    [string]$Ver,
    [Parameter(Mandatory=$true)]
    [string]$Note
)

# 切 UTF-8 输出
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$root = $PSScriptRoot
if (-not $root) { $root = (Get-Location).Path }
Set-Location $root

# 版本号校验
if (-not $Ver.StartsWith("v")) {
    Write-Host "错误: 版本号需以 v 开头（如 v1.1）" -ForegroundColor Red
    exit 1
}

# 时间戳
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$bak = "备份\${Ver}_${ts}"
$utf8 = New-Object System.Text.UTF8Encoding($false)

# ---- 1. 备份 ----
New-Item -ItemType Directory -Force -Path $bak | Out-Null
if (Test-Path "main.pyw") {
    Copy-Item -Force "main.pyw" "$bak\main.pyw"
}
if (Test-Path "src") {
    robocopy "src" "$bak\src" /E /XD "__pycache__" /NFL /NDL /NJH /NJS | Out-Null
}
if (Test-Path "config") {
    New-Item -ItemType Directory -Force -Path "$bak\config" | Out-Null
    Get-ChildItem "config\*.toml" -ErrorAction SilentlyContinue | ForEach-Object {
        Copy-Item -Force $_.FullName "$bak\config\$($_.Name)"
    }
}
if (Test-Path "内置文本.md") {
    Copy-Item -Force "内置文本.md" "$bak\内置文本.md"
}
if (Test-Path "requirements.txt") {
    Copy-Item -Force "requirements.txt" "$bak\requirements.txt"
}
Write-Host "OK 备份目录: $bak" -ForegroundColor Green

# ---- 2. 追加更新日志（最新在上） ----
$now = Get-Date -Format "yyyy-MM-dd HH:mm"
$entry = "## $Ver · $now`r`n- $Note`r`n`r`n"

$logFile = Join-Path $root "更新日志.md"
$header = "# 更新日志`r`n`r`n"

if (Test-Path $logFile) {
    $old = [System.IO.File]::ReadAllText($logFile, $utf8)
    $idx = $old.IndexOf("# 更新日志")
    if ($idx -ge 0) {
        # 保留标题，后面插入新条目
        $afterHeader = $old.Substring($idx + "# 更新日志".Length)
        $afterHeader = $afterHeader.TrimStart("`r", "`n")
        $newContent = $header + $entry + $afterHeader
    } else {
        $newContent = $header + $entry + $old
    }
} else {
    $newContent = $header + $entry
}
[System.IO.File]::WriteAllText($logFile, $newContent, $utf8)
Write-Host "OK 更新日志已追加: $Ver · $now" -ForegroundColor Green
Write-Host "   说明: $Note" -ForegroundColor Cyan
Write-Host ""
Write-Host "接下来可以开始改代码了。" -ForegroundColor Yellow