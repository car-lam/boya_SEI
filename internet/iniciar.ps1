# Levanta la central y la publica en https://sei.silosense.dev
#   powershell -ExecutionPolicy Bypass -File iniciar.ps1            servidor + tunel
#   powershell -ExecutionPolicy Bypass -File iniciar.ps1 -Simular   ademas, datos simulados
param([switch]$Simular)

$aqui = $PSScriptRoot
$env:SEI_CLAVE = [Environment]::GetEnvironmentVariable("SEI_CLAVE", "User")
if (-not $env:SEI_CLAVE) { Write-Host "Falta la variable SEI_CLAVE"; exit 1 }
$token = Get-Content "$env:USERPROFILE\.sei\tunel_token" -Raw
$cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe"

$corriendo = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'app\.py' }
if ($corriendo) { Write-Host "La central ya estaba corriendo" }
else { Start-Process python -ArgumentList "app.py" -WorkingDirectory $aqui -WindowStyle Minimized }

if (Get-Process cloudflared -ErrorAction SilentlyContinue) { Write-Host "El tunel ya estaba corriendo" }
else { Start-Process $cloudflared -ArgumentList "tunnel --no-autoupdate run --token $token" -WindowStyle Minimized }

if ($Simular) { Start-Process python -ArgumentList "simulador.py --rapido 5" -WorkingDirectory $aqui -WindowStyle Minimized }

Start-Sleep -Seconds 8
try {
    $r = Invoke-WebRequest "https://sei.silosense.dev/api/resumen" -UseBasicParsing -TimeoutSec 15
    Write-Host "Listo: https://sei.silosense.dev (HTTP $($r.StatusCode))"
} catch { Write-Host "El tunel aun no responde; espera unos segundos y abre https://sei.silosense.dev" }
