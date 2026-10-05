param(
    [Parameter(Mandatory=$true)][string]$CompanionHost,
    [string]$OdooDisplayUrl = "",
    [string]$Product = "Lemonade",
    [switch]$Demo,
    [switch]$NoBrowser
)
$ErrorActionPreference = "Stop"
if (-not $Demo -and -not $OdooDisplayUrl) {
    throw "Supply -OdooDisplayUrl with the Odoo address reachable from Computer B, or use -Demo."
}
Push-Location $PSScriptRoot
try {
    $runArgs = @("run", "python", "run_agent_view.py", "--companion-host", $CompanionHost, "--smile-product", $Product)
    if ($Demo) { $runArgs += "--demo" } else { $runArgs += "--live" }
    if ($OdooDisplayUrl) { $runArgs += @("--odoo-display-url", $OdooDisplayUrl) }
    if ($NoBrowser) { $runArgs += "--no-browser" }
    & uv @runArgs
    $runExit = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $runExit
