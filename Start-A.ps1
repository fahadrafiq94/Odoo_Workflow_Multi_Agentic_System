param(
    [string]$CompanionHost = "",
    [string]$OdooDisplayUrl = "",
    [string]$Product = "Lemonade",
    [switch]$Demo,
    [switch]$NoBrowser,
    [switch]$NoCamera
)
$ErrorActionPreference = "Stop"
if ($CompanionHost -and -not $Demo -and -not $OdooDisplayUrl) {
    throw "Supply -OdooDisplayUrl with the Odoo address reachable from Computer B, or use -Demo."
}
Push-Location $PSScriptRoot
try {
    $runArgs = @("run", "python", "run_agent_view.py", "--smile-product", $Product)
    if ($CompanionHost) { $runArgs += @("--companion-host", $CompanionHost) }
    if ($NoCamera) { $runArgs += "--no-camera" }
    if ($Demo) { $runArgs += "--demo" } else { $runArgs += "--live" }
    if ($OdooDisplayUrl) { $runArgs += @("--odoo-display-url", $OdooDisplayUrl) }
    if ($NoBrowser) { $runArgs += "--no-browser" }
    & uv @runArgs
    $runExit = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $runExit
