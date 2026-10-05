param(
    [string]$Pairing = "",
    [switch]$DemoCamera,
    [switch]$NoBrowser,
    [switch]$NoCamera
)
$ErrorActionPreference = "Stop"
if (-not $Pairing) { $Pairing = Join-Path $PSScriptRoot "companion_pairing.json" }
Push-Location $PSScriptRoot
try {
    $runArgs = @("run", "python", "run_customer_screen.py", "--pairing", $Pairing)
    if ($DemoCamera) { $runArgs += "--demo-camera" }
    if ($NoBrowser) { $runArgs += "--no-browser" }
    if ($NoCamera) { $runArgs += "--no-camera" }
    & uv @runArgs
    $runExit = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $runExit
