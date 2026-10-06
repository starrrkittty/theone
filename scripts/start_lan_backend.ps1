param(
    [Parameter(Mandatory = $true)]
    [string]$HostIp,
    [Parameter(Mandatory = $true)]
    [string]$DevToken,
    [int]$Port = 8803
)

$ErrorActionPreference = "Stop"
$parsedAddress = $null
if (-not [System.Net.IPAddress]::TryParse($HostIp, [ref]$parsedAddress) -or
    $parsedAddress.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
    throw "HostIp must be this computer's Wi-Fi IPv4 address."
}
if ($Port -lt 1 -or $Port -gt 65535) {
    throw "Port must be between 1 and 65535."
}

$project = Split-Path -Parent $PSScriptRoot
$python = Join-Path $project ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    & python -m venv (Join-Path $project ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Could not create Python virtual environment." }
}

& $python -c "import fastapi, uvicorn, pydantic_settings, scipy"
if ($LASTEXITCODE -ne 0) {
    & $python -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) { throw "Could not initialize pip in .venv." }
    & $python -m pip install -r (Join-Path $project "backend\requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Could not install backend dependencies." }
}

$env:FITNESS_APP_DEV_TOKEN = $DevToken
Push-Location (Join-Path $project "backend")
try {
    & $python -m uvicorn main:app --host $HostIp --port $Port
    if ($LASTEXITCODE -ne 0) { throw "Backend failed to start." }
} finally {
    Pop-Location
}
