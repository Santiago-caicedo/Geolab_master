# CLAUDE.md - Guía del Proyecto Geolab Master

## Quick Start

```bash
source venv/bin/activate        # Linux/Mac (o venv\Scripts\activate en Windows)
pip install -r requirements.txt # Solo primera vez
python manage.py migrate
python manage.py runserver      # http://127.0.0.1:8000/
```

## Descripción General

Portal de Gestión de Informes Técnicos para **Geolab S.A.S** (laboratorio de suelos y materiales de construcción).

**Stack:** Django 6.0, PostgreSQL, Bootstrap 5.3, HTMX, AWS S3 (prod)

**Funcionalidades:**
- Gestión de empresas constructoras y obras
- Almacenamiento y distribución de informes técnicos (PDFs)
- Remisiones de muestras digitales (F-GC-05)
- Hojas de trabajo de ensayos (F-GT-05)
- Control de acceso multi-rol

## Estructura del Proyecto

```
geolab_master/
├── config/             # Settings, URLs raíz
├── core/               # Obras, Informes, Dashboards
├── users/              # UsuarioBase, Constructora, ClienteExterno, FuncionarioGeolab
├── solicitudes/        # RemisionMuestras, Muestra, Notificacion
├── ensayos/            # HojaTrabajo, ResultadoMuestra
├── templates/          # 42 templates organizados por app
│   └── includes/       # Sidebars: staff, tecnico, remitente, client
├── static/img/         # Logo
├── media/informes/     # PDFs subidos
└── requirements.txt
```

## Modelos de Datos

### users
- **UsuarioBase**: Custom User con `es_geolab`, `es_cliente`
- **Constructora**: Empresas clientes (nombre, codigo, nit, ciudad)
- **FuncionarioGeolab**: Perfil empleados (area: admin/lab/recepcion/tecnico)
- **ClienteExterno**: Perfil clientes (empresa FK, rol: director/residente/remitente)

### core
- **Obra**: Proyectos (nombre, codigo_obra, constructora FK, residentes_asignados M2M)
- **Informe**: PDFs técnicos (titulo, obra FK, archivo FileField)

### solicitudes
- **RemisionMuestras**: Formato F-GC-05 (obra FK, orden_trabajo, estado, firmante_*, cadena custodia)
- **Muestra**: Detalle (remision FK, numero_muestra, tipo_muestra, ensayos, localizacion, fecha_toma, edad_ensayo_dias, fc_resistencia)
- **Notificacion**: Sistema de alertas (tipo, titulo, mensaje, destinatario, leida)

### ensayos
- **HojaTrabajo**: Formato F-GT-05 (remision 1:1, estado, progreso)
- **ResultadoMuestra**: Mediciones (muestra 1:1, diametro_d1/d2/d3, longitud_l1/l2/l3, peso_gramos, carga_maxima_kn, forma_falla)

**Relaciones clave:**
```
Constructora 1:N Obra 1:N Informe
Obra 1:N RemisionMuestras 1:N Muestra
RemisionMuestras 1:1 HojaTrabajo 1:N ResultadoMuestra
Muestra 1:1 ResultadoMuestra
```

## Sistema de Roles

| Rol | Condición | Acceso |
|-----|-----------|--------|
| Staff Admin | `es_geolab=True`, area in [admin,lab,recepcion] | Todo |
| Técnico Lab | `es_geolab=True`, `area='tecnico'` | Solo ensayos/dashboard |
| Director | `es_cliente=True`, `rol='director'` | Todas obras de su empresa |
| Residente | `es_cliente=True`, `rol='residente'` | Solo obras asignadas |
| Remitente | `es_cliente=True`, `rol='remitente'` | Solo crear remisiones |

**Properties en UsuarioBase:** `es_tecnico_laboratorio`, `es_admin_geolab`, `es_remitente`

## URLs Principales

| App | Rutas clave |
|-----|-------------|
| core | `/`, `/empresas/`, `/obras/<pk>/`, `/cargar-informe/` |
| users | `/usuarios/`, `/usuarios/nuevo/`, `/usuarios/<pk>/editar/` |
| solicitudes | `/remisiones/`, `/obras/<pk>/nueva-remision/`, `/remitente/`, `/notificaciones/` |
| ensayos | `/ensayos/hojas-trabajo/`, `/ensayos/dashboard-tecnico/`, `/ensayos/hojas-trabajo/obra/<pk>/` |

## Flujos Principales

### Remisión (Remitente)
1. Login → `/remitente/` → Seleccionar obra → Crear remisión con muestras
2. Sistema: Guarda con transacción atómica, crea HojaTrabajo+ResultadoMuestra, notifica Staff
3. Staff ve campana → detalle remisión → completa recepción lab

### Ensayos (Técnico)
1. `/ensayos/dashboard-tecnico/` → Muestras HOY + vencidas por obra
2. Llena mediciones (D1-D3, L1-L3, Peso, Carga, Forma Falla)
3. Sistema calcula: diámetro_real, área, esfuerzo_mpa, porcentaje_desarrollo

**Fórmulas:**
```python
fecha_falla = fecha_toma + edad_ensayo_dias
diametro_real = promedio(D1, D2, D3)
area_mm2 = PI * diametro² / 4 / 100
esfuerzo_mpa = (carga_kn * 101.9716 / area) / 10
porcentaje_desarrollo = esfuerzo / fc * 100
```

## Comandos Útiles

```bash
python manage.py makemigrations [app]
python manage.py migrate
python manage.py createsuperuser
python manage.py sincronizar_hojas  # Crea hojas faltantes
python manage.py migrar_geolab      # Migración desde WordPress
python manage.py descargar_archivos # Descarga PDFs pendientes
```

## Variables de Entorno (.env)

```env
DEBUG=True
SECRET_KEY=...
DB_NAME=geolabmaster_db
DB_USER=postgres
DB_PASSWORD=...
# Producción: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, EMAIL_HOST_*
```

## Identidad Visual

```css
--brand-blue: #008ed6;
--sidebar-bg: #1c2e4a;
--bg-body: #f8fafc;
--text-main: #334155;
```

## Notas Técnicas Importantes

1. **Custom User Model:** `users.UsuarioBase` como AUTH_USER_MODEL
2. **Transacción atómica:** `responder_remision` y `crear_remision_cliente` usan `transaction.atomic()`
3. **Auto-creación:** Al completar remisión se crea HojaTrabajo + ResultadoMuestra automáticamente
4. **Muestras múltiples edades:** Una muestra puede tener varias filas con diferentes `edad_ensayo_dias`
5. **Detección automática HOY:** `fecha_falla = fecha_toma + edad_dias`, marca en ROJO si == hoy
6. **Firma automática remitente:** Datos del firmante se toman del usuario logueado
7. **Notificación dual:** Email + campana al crear remisión
8. **Sidebar condicional:** 4 sidebars según rol (staff, tecnico, remitente, client)
9. **Signal desactivado:** La creación de HojaTrabajo está en la vista, no en signal
10. **Validación PDFs:** Doble validación cliente (JS) y servidor (Django)
11. **HTMX:** Usado para edición inline en hojas de trabajo y toggles
12. **Campos DEPRECADOS:** `token_acceso` y `email_destinatario` en RemisionMuestras (sistema antiguo)

## Seguridad

- CSRF habilitado globalmente
- Validadores de contraseña activos
- Logging con `logging.getLogger(__name__)`
- IP y User-Agent registrados en firma de remisiones

**Producción (agregar en settings.py):**
```python
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
```
