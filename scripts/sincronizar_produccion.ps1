<#
.SYNOPSIS
  Sube el respaldo de WordPress (y opcionalmente el Excel de una sede) al
  servidor de producción y ejecuta allá toda la sincronización.

.DESCRIPTION
  Hace en un solo paso lo que antes era manual: scp de los archivos y, por
  SSH, scripts/servidor_sincronizar.sh (git pull, migraciones, respaldo de
  Postgres, sincronización con WordPress, descarga de PDF, catálogo y
  precios por obra). La salida del servidor se muestra en pantalla.

  Se ejecuta desde la carpeta del proyecto en Windows (PowerShell).
  El host y la llave se toman de scripts\produccion.env (ver ejemplo abajo)
  o de los parámetros -Servidor / -Llave.

.EXAMPLE
  # Ensayo: muestra todo lo que haría, no guarda nada
  .\scripts\sincronizar_produccion.ps1 -Dump portal_2026-09-28.sql -Ensayo

.EXAMPLE
  # Corrida real con WordPress + precios de Ibagué
  .\scripts\sincronizar_produccion.ps1 -Dump portal_2026-09-28.sql -Excel "BASE DATOS IBAGUE.xlsm" -Ciudad Ibagué

.EXAMPLE
  # Solo precios de Bucaramanga, sin tocar WordPress
  .\scripts\sincronizar_produccion.ps1 -SinWordpress -Excel "BASE DATOS BUCARAMANGA.xlsm" -Ciudad Bucaramanga

.NOTES
  scripts\produccion.env (NO se sube a git):
      GEOLAB_HOST=1.2.3.4
      GEOLAB_USUARIO=ubuntu
      GEOLAB_LLAVE=C:\Users\ASUS\.ssh\geolab.pem
      GEOLAB_RUTA=/opt/geolab_master
#>
[CmdletBinding()]
param(
    [string]$Dump,
    [string]$Excel,
    [string]$Ciudad,
    [switch]$Ensayo,
    [switch]$SinWordpress,
    [switch]$SinInformes,
    [switch]$Conservar,
    [switch]$SinRespaldo,
    [switch]$Push,
    [string]$Servidor,
    [string]$Usuario,
    [string]$Llave,
    [string]$Ruta
)

$ErrorActionPreference = 'Stop'
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

if (-not $Servidor) { throw "Falta el host del servidor: usa -Servidor o crea scripts\produccion.env (ver ayuda)." }
if (-not $Llave) { throw "Falta la llave SSH: usa -Llave o GEOLAB_LLAVE en scripts\produccion.env." }
if (-not (Test-Path $Llave)) { throw "No existe la llave: $Llave" }
if (-not $SinWordpress -and -not $Dump) { throw "Indica -Dump ARCHIVO.sql (o -SinWordpress)." }
if ($Dump -and -not (Test-Path $Dump)) { throw "No existe el respaldo: $Dump" }
if ($Excel -and -not (Test-Path $Excel)) { throw "No existe el Excel: $Excel" }
if ($Excel -and -not $Ciudad) { throw "-Excel requiere -Ciudad." }

$destino = "$Usuario@$Servidor"
$modo = if ($Ensayo) { 'ENSAYO (no guarda nada)' } else { 'REAL' }
Write-Host "Servidor: $destino  Ruta: $Ruta  Modo: $modo" -ForegroundColor Cyan

# ── 0. push opcional ──────────────────────────────────────────────────────
if ($Push) {
    Write-Host "`n>> git push origin main" -ForegroundColor Yellow
    git push origin main
    if ($LASTEXITCODE -ne 0) { throw "git push falló." }
}

# ── 1. subir archivos ─────────────────────────────────────────────────────
function Subir([string]$archivo) {
    $nombre = Split-Path -Leaf $archivo
    Write-Host "`n>> Subiendo $nombre ($([math]::Round((Get-Item $archivo).Length/1MB)) MB)..." -ForegroundColor Yellow
    scp -i $Llave -q "$archivo" "${destino}:$Ruta/$nombre"
    if ($LASTEXITCODE -ne 0) { throw "scp falló para $nombre" }
    return $nombre
}
$opciones = @()
if ($Dump)  { $opciones += @('--dump', (Subir $Dump)) }
if ($Excel) { $opciones += @('--excel', (Subir $Excel), '--ciudad', $Ciudad) }
if ($Ensayo)       { $opciones += '--ensayo' }
if ($SinWordpress) { $opciones += '--sin-wordpress' }
if ($SinInformes)  { $opciones += '--sin-informes' }
if ($Conservar)    { $opciones += '--conservar' }
if ($SinRespaldo)  { $opciones += '--sin-respaldo' }

# ── 2. ejecutar en el servidor ────────────────────────────────────────────
# El script del servidor viene con el repositorio: se actualiza primero con git pull
# para no correr una versión vieja.
$argsRemotos = ($opciones | ForEach-Object { "'" + ($_ -replace "'", "'\''") + "'" }) -join ' '
$comando = "cd '$Ruta' && git pull --ff-only -q && bash scripts/servidor_sincronizar.sh $argsRemotos"
Write-Host "`n>> Ejecutando en el servidor..." -ForegroundColor Yellow
ssh -i $Llave -t $destino $comando
if ($LASTEXITCODE -ne 0) { throw "La sincronización terminó con error (código $LASTEXITCODE). Revisa el log en $Ruta/logs/." }
Write-Host "`n✓ Listo." -ForegroundColor Green
