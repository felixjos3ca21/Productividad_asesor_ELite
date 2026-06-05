param(
    [string]$InputFolder = "C:\Users\felix.contreras\Desktop\Gestiones",
    [string]$Catalog = "asesores_catalogo.json",
    [string]$Output = "productividad_view.json"
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$scriptPy = Join-Path $repoRoot "scripts\generar_vista_productividad.py"

if (-not (Test-Path $pythonExe)) {
    Write-Error "No se encontro Python en .venv: $pythonExe"
    exit 1
}

Push-Location $repoRoot
try {
    & $pythonExe $scriptPy --input-folder $InputFolder --catalog $Catalog --output $Output
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    Write-Host "JSON actualizado: $Output"
}
finally {
    Pop-Location
}
