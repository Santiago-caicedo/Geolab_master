<#
.SYNOPSIS
  Consulta el estado del servidor de producción y de su base de datos
  (SOLO LECTURA) y guarda el informe en logs\estado_produccion_<fecha>.txt.

.DESCRIPTION
  Por SSH ejecuta scripts/servidor_estado.sh, que revisa servidor, código
  desplegado, servicios, sincronizaciones, respaldos, `check --deploy` y
  corre `python manage.py estado_sistema` (usuarios, constructoras, obras,
  informes, remisiones, ensayos, calidad y facturación).

  No modifica nada en el servidor. La única excepción es -Actualizar, que
  hace `git pull` antes (necesario la primera vez para que exista el
  comando estado_sistema allá).

  Se ejecuta desde la carpeta del proyecto en Windows (PowerShell). Host y
  llave salen de scripts\produccion.env, igual que sincronizar_produccion.ps1.

.EXAMPLE
  .\scripts\estado_produccion.ps1

.EXAMPLE
  # Con ejemplos de cada hallazgo y prueba de si los PDF de S3 son públicos
  .\scripts\estado_produccion.ps1 -Detalle -VerificarS3

.EXAMPLE
  # Solo facturación y obras, con ejemplos
  .\scripts\estado_produccion.ps1 -Seccion facturacion,obras -Detalle

.EXAMPLE
  # Primera vez: despliega el código (git pull) y luego consulta
  .\scripts\estado_produccion.ps1 -Push -Actualizar
#>
[CmdletBinding()]
param(
    [switch]$Detalle,
    [int]$Limite = 0,
    [ValidateSet('sistema', 'usuarios', 'constructoras', 'obras', 'informes',
                 'remisiones', 'ensayos', 'calidad', 'facturacion', 's3')]
    [string[]]$Seccion,
    [switch]$VerificarS3,
    [int]$VerificarArchivos = 0,
    [switch]$SoloBase,
    [switch]$Actualizar,
    [switch]$Push,
    [string]$Servidor,
    [string]$Usuario,
    [string]$Llave,
    [string]$Ruta
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

# ── configuración ─────────────────────────────────────────────────────────
$cfg = @{}
$archivoCfg = Join-Path $PSScriptRoot 'produccion.env'
if (Test-Path $archivoCfg) {
    Get-Content $archivoCfg | Where-Object { $_ -match '^\s*([A-Z_]+)\s*=\s*(.+?)\s*$' } | ForEach-Object {
        $cfg[$Matches[1]] = $Matches[2].Trim('"').Trim("'")
    }
}
if (-not $Servidor) { $Servidor = $cfg['GEOLAB_HOST'] }
if (-not $Usuario) { $Usuario = if ($cfg['GEOLAB_USUARIO']) { $cfg['GEOLAB_USUARIO'] } else { 'ubuntu' } }
if (-not $Llave)   { $Llave   = $cfg['GEOLAB_LLAVE'] }
if (-not $Ruta)    { $Ruta    = if ($cfg['GEOLAB_RUTA']) { $cfg['GEOLAB_RUTA'] } else { '/opt/geolab_master' } }

if (-not $Servidor) { throw "Falta el host del servidor: usa -Servidor o crea scripts\produccion.env." }
if (-not $Llave) { throw "Falta la llave SSH: usa -Llave o GEOLAB_LLAVE en scripts\produccion.env." }
if (-not (Test-Path $Llave)) { throw "No existe la llave: $Llave" }

$destino = "$Usuario@$Servidor"
Write-Host "Servidor: $destino  Ruta: $Ruta  (solo lectura)" -ForegroundColor Cyan

if ($Push) {
    Write-Host "`n>> git push origin main" -ForegroundColor Yellow
    git push origin main
    if ($LASTEXITCODE -ne 0) { throw "git push falló." }
}

# ── opciones para el servidor ─────────────────────────────────────────────
$opciones = @()
if ($Detalle)           { $opciones += '--detalle' }
if ($Limite -gt 0)      { $opciones += @('--limite', $Limite) }
foreach ($s in $Seccion) { $opciones += @('--seccion', $s) }
if ($VerificarS3)       { $opciones += '--verificar-s3' }
if ($VerificarArchivos -gt 0) { $opciones += @('--verificar-archivos', $VerificarArchivos) }
if ($SoloBase)          { $opciones += '--solo-base' }
$argsRemotos = ($opciones | ForEach-Object { "'" + ("$_" -replace "'", "'\''") + "'" }) -join ' '

$pull = if ($Actualizar) { "git pull --ff-only -q && " } else { "" }
$comando = "cd '$Ruta' && ${pull}RUTA_PROYECTO='$Ruta' bash scripts/servidor_estado.sh $argsRemotos 2>&1"

# ── ejecutar y guardar ────────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path (Join-Path $raiz 'logs') | Out-Null
$salida = Join-Path $raiz ("logs\estado_produccion_{0}.txt" -f (Get-Date -Format 'yyyy-MM-dd_HHmm'))
Write-Host "`n>> Consultando el servidor..." -ForegroundColor Yellow
ssh -i $Llave $destino $comando | ForEach-Object {
    $linea = "$_"
    Write-Host $linea
    Add-Content -Path $salida -Value $linea -Encoding UTF8
}
$codigo = $LASTEXITCODE
Write-Host "`nInforme guardado en $salida" -ForegroundColor Cyan
if ($codigo -ne 0) {
    if (-not $Actualizar) {
        Write-Host "Si dice que falta servidor_estado.sh o estado_sistema, corre con -Actualizar (y -Push si no has subido el código)." -ForegroundColor Yellow
    }
    throw "La consulta terminó con error (código $codigo)."
}
Write-Host "✓ Listo." -ForegroundColor Green
