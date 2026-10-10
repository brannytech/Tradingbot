# Authorization is integrated in the local app. The old helper is no longer used.
$ErrorActionPreference = 'Stop'
Write-Host 'Open http://127.0.0.1:8765 and sign in with your owner password.'
Write-Host 'Select Connect Bybit, then Start live account authorization.'
Write-Host 'The app uses www.bybitglobal.com/oauth and api2.bybitglobal.com.'
Write-Host 'If the app is stopped, run Start-TradingBot.ps1 first.'
Write-Host 'Review and approve Bybit authorization yourself. Automated trading stays locked.'
