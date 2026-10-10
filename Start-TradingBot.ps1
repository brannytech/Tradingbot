$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$botPython = 'C:\ProgramData\anaconda3\python.exe'
if (-not (Test-Path -LiteralPath $botPython)) {
    $botPython = (Get-Command python -ErrorAction Stop).Source
}
& $botPython -m tradingbot serve
