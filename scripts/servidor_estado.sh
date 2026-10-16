#!/usr/bin/env bash
# =============================================================================
# Estado del SERVIDOR de producción y de su base de datos. SOLO LECTURA.
#
# Revisa: servidor (disco, memoria), código desplegado (commit, cambios
# locales), servicios, migraciones pendientes, chequeo de despliegue de Django,
# últimas sincronizaciones y respaldos, y al final corre
# `python manage.py estado_sistema` (diagnóstico de la base).
#
# Normalmente lo lanza scripts/estado_produccion.ps1 desde el PC, pero se
# puede usar directo en el servidor:
#
#   bash scripts/servidor_estado.sh
#   bash scripts/servidor_estado.sh --detalle --verificar-s3
#   bash scripts/servidor_estado.sh --seccion facturacion --detalle
#
# Opciones (se pasan tal cual a estado_sistema):
#   --detalle               Lista ejemplos de cada hallazgo.
#   --limite N              Máximo de ejemplos por hallazgo (default 10).
#   --seccion NOMBRE        Solo esa sección (repetible): sistema, usuarios,
#                           constructoras, obras, informes, remisiones,
#                           ensayos, calidad, facturacion, s3.
#   --verificar-s3          Comprueba si un PDF se descarga sin credenciales.
#   --verificar-archivos N  Comprueba que existan N archivos de informes en S3.
# Propias de este script:
#   --solo-base             Salta el estado del servidor; solo estado_sistema.
#
# No escribe nada: ni git pull, ni migrate, ni archivos de log.
# =============================================================================
set -uo pipefail

RUTA_PROYECTO="${RUTA_PROYECTO:-/opt/geolab_master}"
SOLO_BASE=0
ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --solo-base) SOLO_BASE=1 ;;
        -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
        *) ARGS+=("$1") ;;
    esac
    shift
done

cd "$RUTA_PROYECTO" || { echo "✗ No existe $RUTA_PROYECTO" >&2; exit 1; }
[[ -f venv/bin/activate ]] || { echo "✗ No se encontró venv/bin/activate en $RUTA_PROYECTO" >&2; exit 1; }
# shellcheck disable=SC1091
source venv/bin/activate

paso() { echo; echo "══════ $* ══════"; }
antiguedad() {  # días desde la última modificación de un archivo
    echo $(( ( $(date +%s) - $(stat -c %Y "$1") ) / 86400 ))
}

echo "Estado de producción Geolab · $(hostname) · $(date '+%F %H:%M')"

if [[ $SOLO_BASE -eq 0 ]]; then
    paso "Servidor"
    uptime -p 2>/dev/null || uptime
    df -h "$RUTA_PROYECTO" | tail -1 | awk '{print "Disco: "$3" usados de "$2" ("$5"), libres "$4}'
    free -h 2>/dev/null | awk '/^Mem/ {print "Memoria: "$3" usada de "$2}'

    paso "Código desplegado"
    git log -1 --format='Commit: %h %ad %s' --date=short
    echo "Rama: $(git rev-parse --abbrev-ref HEAD)"
    # Compara con la última copia conocida de origin (sin hacer fetch: no escribe).
    if git rev-parse -q --verify '@{u}' >/dev/null; then
        echo "Respecto a origin (último fetch): $(git rev-list --count '@{u}..HEAD') adelante, $(git rev-list --count 'HEAD..@{u}') atrás"
    fi
    CAMBIOS=$(git status --porcelain --untracked-files=no)
    if [[ -n "$CAMBIOS" ]]; then
        echo "⚠ Archivos modificados en el servidor (fuera de git):"
        echo "$CAMBIOS" | head -20 | sed 's/^/    /'
        [[ $(echo "$CAMBIOS" | wc -l) -gt 20 ]] && echo "    … ($(echo "$CAMBIOS" | wc -l) en total)"
    else
        echo "Sin cambios locales en archivos versionados."
    fi

    paso "Servicios"
    if command -v systemctl >/dev/null; then
        systemctl list-units --type=service --state=running --no-legend 2>/dev/null \
            | grep -Ei 'gunicorn|uwsgi|nginx|apache|postgres|geolab' \
            | awk '{print "  ✓ "$1}' || echo "  (no se encontraron gunicorn/nginx/postgres corriendo)"
        systemctl list-units --type=service --state=failed --no-legend 2>/dev/null \
            | awk '{print "  ✗ FALLÓ: "$1}'
    else
        echo "  (systemctl no disponible)"
    fi

    paso "Últimas sincronizaciones (logs/)"
    if compgen -G "logs/sincronizacion_*.log" >/dev/null; then
        ls -1t logs/sincronizacion_*.log | head -5 | while read -r f; do
            if grep -q '✓ Terminado' "$f"; then estado="terminó OK"; else estado="⚠ NO terminó (revisar)"; fi
            grep -q 'MODO ENSAYO' "$f" && estado="$estado, ensayo"
            echo "  $(basename "$f") — $estado"
        done
        ULTIMO=$(ls -1t logs/sincronizacion_*.log | head -1)
        echo "  Última corrida hace $(antiguedad "$ULTIMO") días. Avisos de esa corrida:"
        AVISOS=$(awk '/^Avisos \(/{f=1} f && /^[[:space:]]*$/{exit} f' "$ULTIMO" | head -25)
        if [[ -n "$AVISOS" ]]; then echo "$AVISOS" | sed 's/^/    /'; else echo "    (ninguno)"; fi
    else
        echo "  No hay logs de sincronización: servidor_sincronizar.sh nunca se ha corrido aquí."
    fi

    paso "Respaldos de la base (respaldos/)"
    if compgen -G "respaldos/*.sql.gz" >/dev/null; then
        ls -1t respaldos/*.sql.gz | head -5 | while read -r f; do
            echo "  $(basename "$f")  $(du -h "$f" | cut -f1)"
        done
        echo "  Total: $(ls -1 respaldos/*.sql.gz | wc -l) respaldos, $(du -sh respaldos | cut -f1)"
        ULTIMO=$(ls -1t respaldos/*.sql.gz | head -1)
        DIAS=$(antiguedad "$ULTIMO")
        [[ $DIAS -gt 7 ]] && echo "  ⚠ El último respaldo tiene $DIAS días"
        gzip -t "$ULTIMO" 2>/dev/null && echo "  Último respaldo íntegro (gzip OK)" || echo "  ⚠ El último respaldo está corrupto o incompleto"
    else
        echo "  ⚠ No hay respaldos en respaldos/"
    fi
    if compgen -G "*.sql" >/dev/null; then
        echo "  ⚠ Quedaron volcados .sql de WordPress en el servidor (datos personales): $(ls -1 *.sql | tr '\n' ' ')"
    fi

    paso "Chequeo de despliegue de Django (check --deploy)"
    python manage.py check --deploy 2>&1 | tail -15
fi

paso "Base de datos (estado_sistema)"
if ! python manage.py help estado_sistema >/dev/null 2>&1; then
    echo "✗ El comando estado_sistema no existe en este servidor: falta desplegar el código"
    echo "  (git pull en $RUTA_PROYECTO, o usa -Actualizar en estado_produccion.ps1)."
    exit 1
fi
python manage.py estado_sistema "${ARGS[@]}"
