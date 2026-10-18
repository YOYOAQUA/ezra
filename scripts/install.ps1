# Ezra installer (Windows): creates %USERPROFILE%\Ezra, the ezra.cmd shortcut, config.json and an empty key file.
$ErrorActionPreference = "Stop"
$Skill = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Dir = if ($env:EZRA_HOME) { $env:EZRA_HOME } else { Join-Path $env:USERPROFILE "Ezra" }

$py = $null
foreach ($c in @("py -3", "python", "python3")) {
  try { $v = & cmd /c "$c --version" 2>$null; if ($LASTEXITCODE -eq 0 -and $v -match "Python 3") { $py = $c; break } } catch {}
}
if (-not $py) {
  Write-Host "✗ Python 3 is missing. Run: winget install Python.Python.3.12   then close and reopen Claude, and run this again."
  exit 1
}

New-Item -ItemType Directory -Force -Path $Dir | Out-Null
Set-Content -Path (Join-Path $Dir "ezra.cmd") -Encoding ASCII -Value "@echo off`r`nchcp 65001 >nul`r`nset PYTHONUTF8=1`r`nset EZRA_HOME=$Dir`r`n$py `"$Skill\scripts\ezra.py`" %*"

$cfg = Join-Path $Dir "config.json"
if (-not (Test-Path $cfg)) { Copy-Item (Join-Path $Skill "templates\config.example.json") $cfg }
$envFile = Join-Path $Dir ".env"
if (-not (Test-Path $envFile)) {
  Set-Content -Path $envFile -Encoding UTF8 -Value "# Paste your Zernio API key right after the = sign, save, close.`r`nZERNIO_API_KEY="
}
Write-Host "✓ Ezra is ready in $Dir"
Write-Host "  next: $Dir\ezra.cmd key   then   $Dir\ezra.cmd check"
