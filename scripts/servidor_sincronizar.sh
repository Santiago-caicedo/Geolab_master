#!/usr/bin/env bash
# =============================================================================
# Sincronización completa en el SERVIDOR de producción.
#
# Corre en orden: git pull, migraciones, respaldo de Postgres, sincronización
# desde el respaldo de WordPress, descarga de PDF nuevos y (opcional) carga
# del catálogo y precios por obra de una sede desde su Excel.
#
# Normalmente NO se llama a mano: lo lanza scripts/sincronizar_produccion.ps1
# desde el PC del administrador. Pero se puede usar directo en el servidor:
#
#   bash scripts/servidor_sincronizar.sh --ensayo --dump portal_2026-09-28.sql
#   bash scripts/servidor_sincronizar.sh --dump portal_2026-09-28.sql \
#        --excel "BASE DATOS IBAGUE.xlsm" --ciudad Ibagué
#
# Opciones:
#   --ensayo         Todo en modo --dry-run: no escribe nada, no respalda, no borra.
#   --dump ARCHIVO   Respaldo .sql de WordPress (obligatorio salvo --sin-wordpress).
#   --sin-wordpress  Salta la sincronización con WordPress.
#   --excel ARCHIVO  Libro BASE DATOS <CIUDAD>.xlsm para catálogo + precios.
#   --ciudad NOMBRE  Sede del Excel (obligatorio con --excel).
#   --sin-informes   No trae informes de WordPress (más rápido).
#   --conservar      No borra el .sql al terminar.
#   --sin-respaldo   No hace pg_dump antes (NO recomendado).
#
# Todo queda registrado en logs/sincronizacion_<fecha>.log
# =============================================================================
set -euo pipefail

RUTA_PROYECTO="${RUTA_PROYECTO:-/opt/geolab_master}"
ENSAYO=0; DUMP=""; SIN_WP=0; EXCEL=""; CIUDAD=""; SIN_INFORMES=0; CONSERVAR=0; SIN_RESPALDO=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --ensayo) ENSAYO=1 ;;
        --dump) DUMP="$2"; shift ;;
        --sin-wordpress) SIN_WP=1 ;;
        --excel) EXCEL="$2"; shift ;;
        --ciudad) CIUDAD="$2"; shift ;;
        --sin-informes) SIN_INFORMES=1 ;;
        --conservar) CONSERVAR=1 ;;
        --sin-respaldo) SIN_RESPALDO=1 ;;
        -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
        *) echo "Opción desconocida: $1" >&2; exit 2 ;;
    esac
    shift
done

cd "$RUTA_PROYECTO"
mkdir -p logs respaldos
LOG="logs/sincronizacion_$(date +%F_%H%M).log"
exec > >(tee -a "$LOG") 2>&1

paso() { echo; echo "══════ $* ══════"; }
fallo() { echo "✗ $*" >&2; exit 1; }

echo "Sincronización Geolab · $(date '+%F %H:%M') · $( [[ $ENSAYO -eq 1 ]] && echo 'MODO ENSAYO (no se guarda nada)' || echo 'MODO REAL')"
echo "Log: $LOG"

# ── validaciones ─────────────────────────────────────────────────────────
if [[ $SIN_WP -eq 0 && -z "$DUMP" ]]; then fallo "Falta --dump ARCHIVO.sql (o usa --sin-wordpress)"; fi
if [[ -n "$DUMP" && ! -f "$DUMP" ]]; then fallo "No existe el respaldo de WordPress: $DUMP"; fi
if [[ -n "$EXCEL" && ! -f "$EXCEL" ]]; then fallo "No existe el Excel: $EXCEL"; fi
if [[ -n "$EXCEL" && -z "$CIUDAD" ]]; then fallo "--excel requiere --ciudad"; fi
[[ -f venv/bin/activate ]] || fallo "No se encontró venv/bin/activate en $RUTA_PROYECTO"
# shellcheck disable=SC1091
source venv/bin/activate

DRY=""; [[ $ENSAYO -eq 1 ]] && DRY="--dry-run"

# ── 1. código ────────────────────────────────────────────────────────────
paso "1/6 Actualizar código (git pull)"
git pull --ff-only
git log --oneline -1

paso "2/6 Migraciones"
python manage.py migrate --noinput

# ── 3. respaldo ──────────────────────────────────────────────────────────
paso "3/6 Respaldo de la base de datos"
if [[ $ENSAYO -eq 1 ]]; then
    echo "(ensayo: no se respalda)"
elif [[ $SIN_RESPALDO -eq 1 ]]; then
    echo "(--sin-respaldo: se omite)"
else
    command -v pg_dump >/dev/null || fallo "pg_dump no está instalado (apt install postgresql-client) o usa --sin-respaldo"
    eval "$(python - <<'PY'
from decouple import config
print(f'export PGHOST="{config("DB_HOST", default="localhost")}"')
print(f'export PGPORT="{config("DB_PORT", default="5432")}"')
print(f'export PGUSER="{config("DB_USER")}"')
print(f'export PGPASSWORD="{config("DB_PASSWORD")}"')
print(f'export PGDATABASE="{config("DB_NAME")}"')
PY
)"
    RESPALDO="respaldos/geolab_$(date +%F_%H%M).sql.gz"
    pg_dump --no-owner | gzip > "$RESPALDO"
    echo "Respaldo guardado: $RESPALDO ($(du -h "$RESPALDO" | cut -f1))"
    unset PGPASSWORD
fi

# ── 4. wordpress ─────────────────────────────────────────────────────────
paso "4/6 Sincronizar desde WordPress"
if [[ $SIN_WP -eq 1 ]]; then
    echo "(--sin-wordpress: se omite)"
else
    ARGS=(--dump "$DUMP")
    [[ $SIN_INFORMES -eq 1 ]] && ARGS+=(--sin-informes)
    # shellcheck disable=SC2086
    python manage.py sincronizar_wordpress "${ARGS[@]}" $DRY
fi

# ── 5. pdf ───────────────────────────────────────────────────────────────
paso "5/6 Descargar PDF de informes nuevos"
if [[ $ENSAYO -eq 1 || $SIN_WP -eq 1 || $SIN_INFORMES -eq 1 ]]; then
    echo "(se omite en ensayo / sin WordPress / sin informes)"
else
    python manage.py descargar_archivos
fi

# ── 6. excel ─────────────────────────────────────────────────────────────
paso "6/6 Catálogo y precios por obra desde Excel"
if [[ -z "$EXCEL" ]]; then
    echo "(sin --excel: se omite)"
else
    # shellcheck disable=SC2086
    python manage.py importar_catalogo_excel "$EXCEL" --ciudad "$CIUDAD" --crear-obras $DRY
fi

# ── limpieza ─────────────────────────────────────────────────────────────
if [[ $ENSAYO -eq 0 && $CONSERVAR -eq 0 && -n "$DUMP" ]]; then
    rm -f "$DUMP" && echo "Respaldo de WordPress eliminado del servidor: $DUMP"
fi

echo
echo "✓ Terminado $( [[ $ENSAYO -eq 1 ]] && echo '(ensayo, nada guardado)' ). Log completo en $LOG"
