# CLAUDE.md - Guía del Proyecto Geolab Master

## Quick Start (Inicio Rápido)

```bash
# 1. Activar entorno virtual
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate           # Windows

# 2. Instalar dependencias (si es primera vez)
pip install -r requirements.txt

# 3. Crear migraciones de la app solicitudes (si no existen)
python manage.py makemigrations solicitudes

# 4. Aplicar migraciones
python manage.py migrate

# 5. Crear superusuario (si no existe)
python manage.py createsuperuser

# 6. Ejecutar servidor
python manage.py runserver

# 7. Acceder al sistema
# http://127.0.0.1:8000/
```

---

## Descripción General

Portal de Gestión de Informes Técnicos para **Geolab S.A.S**, empresa de laboratorio de suelos y materiales de construcción. El sistema permite:

- Gestionar empresas constructoras (clientes)
- Administrar obras/proyectos de construcción
- Almacenar y distribuir informes técnicos (PDFs)
- Crear y gestionar remisiones de muestras digitales (Formato F-GC-05)
- Control de acceso multi-rol (Staff Geolab vs Clientes)

**Stack tecnológico:**
- Backend: Django 6.0 (Python)
- Base de datos: PostgreSQL
- Frontend: HTML5, Bootstrap 5.3, Bootstrap Icons, HTMX
- Almacenamiento: Local (dev) / AWS S3 (producción)
- Email: Console (dev) / SMTP (producción)

---

## Estructura del Proyecto

```
geolab_master/
├── config/                     # Configuración Django
│   ├── settings.py             # Settings principal
│   ├── urls.py                 # URLs raíz
│   ├── wsgi.py
│   └── asgi.py
├── core/                       # App principal (obras e informes)
│   ├── management/
│   │   └── commands/           # Comandos de migración de datos
│   │       ├── migrar_geolab.py
│   │       └── descargar_archivos.py
│   ├── models.py               # Obra, Informe
│   ├── views.py                # Dashboards, listados, detalles
│   ├── forms.py                # ConstructoraForm, ObraForm
│   └── urls.py
├── users/                      # App de usuarios
│   ├── models.py               # UsuarioBase, Constructora, FuncionarioGeolab, ClienteExterno
│   ├── forms.py                # LoginForm
│   └── admin.py
├── solicitudes/                # App de Remisiones de Muestras (F-GC-05)
│   ├── models.py               # RemisionMuestras, Muestra
│   ├── views.py                # Crear, responder, detalle, lista
│   ├── forms.py                # CrearRemisionForm, ResponderRemisionForm, MuestraFormSet, RecepcionLabForm
│   ├── urls.py
│   └── admin.py
├── ensayos/                    # App de Ensayos de Laboratorio (F-GT-05)
│   ├── models.py               # HojaTrabajo, ResultadoMuestra
│   ├── views.py                # Lista por obra, hoja de trabajo, edición
│   ├── forms.py                # ResultadoMuestraForm
│   ├── signals.py              # Auto-crear HojaTrabajo al completar remisión
│   ├── urls.py
│   ├── admin.py
│   └── management/
│       └── commands/
│           └── sincronizar_hojas.py  # Comando para sincronizar hojas faltantes
├── templates/
│   ├── base.html               # Template base con sidebars condicionales
│   ├── registration/
│   │   └── login.html
│   ├── core/                   # Templates de la app core (9 archivos)
│   │   ├── home_staff.html         # Dashboard administrativo
│   │   ├── home_client.html        # Portal de clientes
│   │   ├── lista_constructoras.html # Directorio de empresas
│   │   ├── detalle_constructora.html # Expediente de empresa
│   │   ├── detalle_obra.html       # Expediente profesional de obra
│   │   ├── lista_informes_obra.html # Lista paginada de informes
│   │   ├── lista_informes.html     # Lista general de informes
│   │   ├── editar_form.html        # Formulario genérico de edición
│   │   └── pending.html            # Usuario sin rol asignado
│   ├── solicitudes/            # Templates de remisiones (F-GC-05)
│   │   ├── base_public.html    # Base para acceso sin login
│   │   ├── crear_remision.html
│   │   ├── responder_remision.html
│   │   ├── detalle_remision.html
│   │   ├── lista_remisiones.html
│   │   ├── lista_remisiones_obra.html  # Lista por obra específica
│   │   ├── confirmacion.html
│   │   ├── remision_completada.html
│   │   └── email_remision.html
│   ├── ensayos/                # Templates de ensayos (F-GT-05)
│   │   ├── lista_obras_hojas_trabajo.html  # Lista de OBRAS con hojas de trabajo
│   │   ├── hoja_trabajo_obra.html          # Hoja de trabajo de UNA obra (todas sus muestras)
│   │   ├── detalle_hoja_trabajo.html       # Edición detallada por remisión
│   │   ├── dashboard_tecnico.html          # Dashboard simplificado para técnicos
│   │   ├── muestras_para_hoy.html          # Dashboard del técnico (legacy)
│   │   ├── lista_hojas_trabajo.html        # Lista legacy por remisión
│   │   └── partials/                       # Fragmentos HTMX
│   └── includes/               # Sidebars por rol
│       ├── sidebar_staff.html      # Admin/Supervisor (acceso completo)
│       ├── sidebar_tecnico.html    # Técnico de laboratorio (solo ensayos)
│       └── sidebar_client.html     # Clientes externos
├── static/
│   └── img/geolab-logo.png     # CSS está inline en base.html
├── media/                      # Archivos subidos (PDFs)
│   └── informes/YYYY/MM/
├── manage.py
├── requirements.txt
└── .env                        # Variables de entorno
```

---

## Diagrama de Relaciones (ERD)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           MODELOS DE DATOS                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐                                                        │
│  │   UsuarioBase   │  (Custom User - extiende AbstractUser)                 │
│  │  - es_geolab    │                                                        │
│  │  - es_cliente   │                                                        │
│  └────────┬────────┘                                                        │
│           │                                                                 │
│      ┌────┴────┐                                                            │
│      │         │                                                            │
│      ▼         ▼                                                            │
│  ┌──────────────────┐    ┌──────────────────┐                               │
│  │FuncionarioGeolab │    │  ClienteExterno  │                               │
│  │ - user (1-1)     │    │ - user (1-1)     │                               │
│  │ - area           │    │ - empresa (FK)───┼──┐                            │
│  │ - codigo_empleado│    │ - rol            │  │                            │
│  └──────────────────┘    │ - cargo          │  │                            │
│                          └──────────────────┘  │                            │
│                                                │                            │
│                          ┌─────────────────────┘                            │
│                          ▼                                                  │
│                  ┌──────────────────┐                                       │
│                  │   Constructora   │                                       │
│                  │ - nombre         │                                       │
│                  │ - codigo         │                                       │
│                  │ - nit            │                                       │
│                  │ - ciudad         │                                       │
│                  └────────┬─────────┘                                       │
│                           │ 1:N                                             │
│                           ▼                                                 │
│                  ┌──────────────────┐                                       │
│                  │      Obra        │                                       │
│                  │ - nombre         │                                       │
│                  │ - codigo_obra    │                                       │
│                  │ - constructora   │                                       │
│                  │ - residentes_    │                                       │
│                  │   asignados (M2M)│                                       │
│                  └────────┬─────────┘                                       │
│                           │                                                 │
│              ┌────────────┼────────────┐                                    │
│              │ 1:N        │            │ 1:N                                │
│              ▼            │            ▼                                    │
│  ┌──────────────────┐     │    ┌───────────────────┐                        │
│  │     Informe      │     │    │ RemisionMuestras  │                        │
│  │ - titulo         │     │    │ - orden_trabajo   │                        │
│  │ - archivo        │     │    │ - token_acceso    │                        │
│  │ - fecha_creacion │     │    │ - estado          │                        │
│  └──────────────────┘     │    │ - firmante_*      │                        │
│                           │    └─────────┬─────────┘                        │
│                           │              │ 1:N                              │
│                           │              ▼                                  │
│                           │    ┌───────────────────┐                        │
│                           │    │     Muestra       │                        │
│                           │    │ - numero_muestra  │                        │
│                           │    │ - tipo_muestra    │                        │
│                           │    │ - ensayos_*       │                        │
│                           │    │ - localizacion    │                        │
│                           │    │ - fecha_toma      │                        │
│                           │    │ - edad_ensayo_dias│                        │
│                           │    │ - fc_resistencia  │                        │
│                           │    └───────────────────┘                        │
│                           │                                                 │
└───────────────────────────┴─────────────────────────────────────────────────┘
```

---

## Modelos de Datos

### App `users`

**UsuarioBase** (Custom User Model)
```python
- username, email, password     # Heredados de AbstractUser
- es_geolab: bool               # Es empleado de Geolab
- es_cliente: bool              # Es cliente externo
```

**Constructora** (Empresas clientes)
```python
- nombre: str
- codigo: str (unique)          # Ej: "52"
- nit: str
- ciudad: str (indexed)
- id_wp_original: int           # ID de migración desde WordPress
```

**FuncionarioGeolab** (Perfil empleados)
```python
- user: OneToOne → UsuarioBase
- area: choices ['admin', 'lab', 'recepcion', 'tecnico']
- codigo_empleado: str
```

**ClienteExterno** (Perfil clientes)
```python
- user: OneToOne → UsuarioBase
- empresa: FK → Constructora
- rol: choices ['director', 'residente']
- cargo: str
- telefono: str
- id_wp_original: int
```

### App `core`

**Obra** (Proyectos de construcción)
```python
- nombre: str
- codigo_obra: str              # Ej: "52-1"
- constructora: FK → Constructora
- residentes_asignados: M2M → ClienteExterno
- fecha_creacion: datetime
- id_wp_original: int
```

**Informe** (Documentos técnicos)
```python
- titulo: str
- obra: FK → Obra
- archivo: FileField            # upload_to='informes/%Y/%m/'
- fecha_creacion: datetime
- url_archivo_original: str     # URL legacy de WordPress
- id_wp_original: int
```

### App `solicitudes`

**RemisionMuestras** (Formato F-GC-05 - Modelo Maestro)
```python
# Metadatos del formato
- codigo_formato: str           # "F-GC-05" (auto)
- version_formato: str          # "01" (auto)

# Relaciones
- obra: FK → core.Obra
- solicitado_por: FK → users.UsuarioBase

# Identificador y acceso
- orden_trabajo: int            # Consecutivo automático por obra (1, 2, 3...)
- token_acceso: str             # UUID único para acceso sin login (auto)
- estado: choices ['borrador', 'enviada', 'completada', 'vencida']
- email_destinatario: email

# Constraint: unique_together = ['obra', 'orden_trabajo']

# Datos del proyecto
- cc: str                       # Centro de costos

# Cadena de custodia - Cliente
- cliente_fecha: date
- cliente_cantidad: int         # Auto-calculado (suma de cantidades de muestras)
- cliente_estado: str
- cliente_firma_nombre: str
- cliente_observaciones: text

# Cadena de custodia - Laboratorio (Geolab llena después)
- lab_fecha: date
- lab_cantidad: int
- lab_estado: str
- lab_firma_nombre: str
- lab_observaciones: text

# Control interno
- revisado_por: str
- programado: bool
- fecha_revision: date
- firma_revision: str

# Manifiesto (firma digital legal)
- firmante_nombre: str
- firmante_cedula: str          # Documento de identidad del firmante
- firmante_cargo: str
- firmante_email: email
- firmante_telefono: str
- firma_ip_address: ip          # Registrado automáticamente
- firma_user_agent: text        # Registrado automáticamente
- firma_fecha: datetime         # Registrado automáticamente
- acepta_veracidad: bool
```

**Muestra** (Modelo Detalle - cada fila del formato)
```python
- remision: FK → RemisionMuestras
- numero_muestra: int           # Numero de muestra (puede repetirse con diferente edad)
- cantidad: int                 # Cantidad de cilindros/especimenes para esta edad

# Tipo de muestra (selección única)
- tipo_muestra: choices [
    'concreto', 'grouting', 'mortero', 'muretes',
    'bloques', 'vigas', 'varilla', 'malla_elec'
  ]

# Dimensiones
- diametro_longitud: str        # En cm

# Ensayos (checkboxes - pueden ser múltiples)
- ensayo_flexion: bool
- ensayo_compresion: bool
- ensayo_absorcion: bool
- ensayo_otros: str

# Ubicación y fechas
- localizacion: text            # Ej: "T4 - Muros P1 Apto 133-136"
- fecha_toma: date
- edad_ensayo_dias: int         # Dias hasta falla (3, 7, 14, 28...)
- fc_resistencia: str           # Resistencia esperada (Psi/MPa)

# Constraint: unique_together = ['remision', 'numero_muestra', 'edad_ensayo_dias']
# Permite: Muestra #72 con 3 cilindros a 7 dias Y Muestra #72 con 4 cilindros a 28 dias
```

### App `ensayos`

**HojaTrabajo** (Formato F-GT-05 - Relación de Muestras Ensayadas)
```python
# Relación con remisión (1:1)
- remision: OneToOne → RemisionMuestras  # Se crea automáticamente

# Metadatos del formato
- codigo_formato: str           # "F-GT-05" (auto)
- version_formato: str          # "02" (auto)

# Estado del proceso
- estado: choices ['pendiente', 'en_proceso', 'completada', 'informe_generado']

# Control
- fecha_creacion: datetime
- fecha_actualizacion: datetime
- numero_informe: str           # Código del informe generado
- realizado_por: FK → UsuarioBase
- observaciones: text

# Properties calculadas
- total_muestras                # Cantidad de resultados
- muestras_completadas          # Resultados con estado='completado'
- progreso                      # Porcentaje (0-100)
```

**ResultadoMuestra** (Resultado de ensayo por muestra)
```python
# Relaciones
- hoja_trabajo: FK → HojaTrabajo
- muestra: OneToOne → Muestra   # Link a muestra de la remisión

# Estado
- estado: choices ['pendiente', 'completado', 'fallido']
- seleccionado: bool            # Checkbox para selección en hoja global

# Mediciones del técnico (columnas del Excel)
- diametro_d1, d2, d3: Decimal  # 3 mediciones de diámetro (mm)
- longitud_l1, l2, l3: Decimal  # 3 mediciones de longitud (mm)
- peso_gramos: Decimal          # Peso del cilindro
- carga_maxima_kn: Decimal      # Carga de rotura (KN)
- forma_falla: choices          # Tipo 1-6 según norma
- fecha_ensayo: date            # Fecha real del ensayo
- observaciones: text

# Properties calculadas (fórmulas del Excel)
- fecha_falla_programada        # fecha_toma + edad_dias
- debe_fallarse_hoy             # True si fecha_falla == hoy
- dias_para_falla               # Días restantes (negativo si vencida)
- diametro_real                 # PROMEDIO(D1, D2, D3)
- longitud_real                 # PROMEDIO(L1, L2, L3)
- area_mm2                      # PI * diametro² / 4 / 100
- esfuerzo_mpa                  # (carga * 101.9716 / area) / 10
- porcentaje_desarrollo         # esfuerzo / fc * 100
- cumple_resistencia            # True si >= 100%
```

---

## Sistema de Roles y Permisos

| Rol | Condición | Acceso |
|-----|-----------|--------|
| Staff Geolab (Admin) | `user.es_geolab=True`, `area` in ['admin', 'lab', 'recepcion'] | Todo: empresas, obras, informes, remisiones. Puede editar. |
| Técnico Laboratorio | `user.es_geolab=True`, `area='tecnico'` | Solo ensayos: dashboard simplificado con muestras del día |
| Director | `user.es_cliente=True`, `rol='director'` | Todas las obras de su empresa |
| Residente | `user.es_cliente=True`, `rol='residente'` | Solo obras en `residentes_asignados` |
| Cliente Externo (token) | Accede con link único | Solo puede responder la remisión específica |

### Propiedades del Usuario para Verificar Rol

```python
# En UsuarioBase (users/models.py)

@property
def es_tecnico_laboratorio(self):
    """True si es técnico de laboratorio (rol limitado)"""
    if self.es_geolab and hasattr(self, 'perfil_geolab'):
        return self.perfil_geolab.area == 'tecnico'
    return False

@property
def es_admin_geolab(self):
    """True si es admin/staff completo de Geolab (no técnico)"""
    if self.es_geolab and hasattr(self, 'perfil_geolab'):
        return self.perfil_geolab.area in ['admin', 'lab', 'recepcion']
    return self.es_geolab
```

### Cómo Crear un Usuario Técnico de Laboratorio

1. Acceder al Django Admin: `/admin/`
2. Crear nuevo **UsuarioBase**:
   - Username: ej. `tecnico1`
   - Password: definir contraseña
   - `es_geolab`: ✅ Marcado
   - `es_cliente`: ❌ Desmarcado
3. Crear **FuncionarioGeolab** vinculado:
   - User: seleccionar el usuario creado
   - Area: `tecnico` (Técnico de Laboratorio)
   - Código empleado: opcional

Al iniciar sesión, el técnico será redirigido automáticamente a `/ensayos/dashboard-tecnico/`.

---

## URLs y Vistas

### App `core`

| Ruta | Vista | Descripción |
|------|-------|-------------|
| `/` | `dashboard_router` | Redirige según tipo de usuario |
| `/informes/` | `dashboard_client` | Lista informes del cliente |
| `/empresas/` | `lista_constructoras` | Lista empresas (solo staff) |
| `/empresas/<pk>/` | `detalle_constructora` | Detalle empresa + sus obras |
| `/empresas/<pk>/editar/` | `editar_constructora` | Formulario edición |
| `/obras/<pk>/` | `detalle_obra` | Expediente de obra (diseño profesional) |
| `/obras/<pk>/editar/` | `editar_obra` | Formulario edición |
| `/obras/<pk>/informes/` | `lista_informes_obra` | Lista paginada de informes (filtros: búsqueda, fecha) |

### App `solicitudes`

| Ruta | Vista | Descripción |
|------|-------|-------------|
| `/remisiones/` | `lista_remisiones` | Lista todas las remisiones (staff) |
| `/obras/<pk>/nueva-remision/` | `crear_remision` | Crear remisión desde una obra |
| `/obras/<pk>/remisiones/` | `lista_remisiones_obra` | Lista remisiones de una obra específica |
| `/remisiones/<pk>/` | `detalle_remision` | Ver detalle de remisión |
| `/remision/<token>/` | `responder_remision` | Formulario público (cliente sin login) |
| `/remision/<token>/confirmacion/` | `confirmacion_remision` | Confirmación post-envío |

### App `ensayos`

| Ruta | Vista | Descripción |
|------|-------|-------------|
| `/ensayos/hojas-trabajo/` | `lista_obras_hojas_trabajo` | **Lista de OBRAS** con sus hojas de trabajo |
| `/ensayos/hojas-trabajo/obra/<pk>/` | `hoja_trabajo_obra` | **Hoja de trabajo de UNA obra** (todas sus muestras) |
| `/ensayos/hojas-trabajo/hoy/` | `muestras_para_hoy` | Dashboard: muestras para fallar hoy |
| `/ensayos/dashboard-tecnico/` | `dashboard_tecnico` | **Dashboard para Técnicos** (muestras HOY + vencidas por obra) |
| `/ensayos/hojas-trabajo/remision/<pk>/` | `detalle_hoja_trabajo` | Editar mediciones por remisión |
| `/ensayos/resultado/<pk>/editar/` | `editar_resultado` | Editar resultado individual (HTMX/AJAX) |
| `/ensayos/resultado/<pk>/toggle-seleccion/` | `toggle_seleccion` | Toggle checkbox de selección (AJAX) |
| `/ensayos/hojas-trabajo/por-remision/` | `lista_hojas_trabajo` | Lista legacy por remisión |

### Autenticación

| Ruta | Vista | Descripción |
|------|-------|-------------|
| `/accounts/login/` | `LoginView` | Autenticación |
| `/admin/` | Django Admin | Panel de administración |

---

## Flujo de Remisión de Muestras (F-GC-05)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  1. STAFF GEOLAB - Desde /obras/<pk>/ (Detalle de Obra)                     │
│     └──► Click en botón [Nueva Remisión]                                    │
│     └──► Sistema muestra siguiente número de remisión (auto-generado)       │
│     └──► Ingresa: Email destinatario                                        │
│     └──► Click en [Crear y Enviar Remisión]                                 │
│                                                                             │
│  2. SISTEMA                                                                 │
│     └──► Pre-llena: Obra, Constructora, Código (automático)                 │
│     └──► Genera token único (UUID)                                          │
│     └──► Envía EMAIL automático al cliente con el link                      │
│     └──► Muestra opción "Copiar link" para compartir manualmente            │
│                                                                             │
│  3. CLIENTE (accede con link, SIN necesidad de login)                       │
│     └──► Ve formulario responsive (tabla en desktop, cards en móvil)        │
│     └──► Agrega muestras (filas de la tabla grid o tarjetas en móvil)       │
│     └──► Llena: Tipo, Dimensiones, Ensayos, Localización, Fecha, Edad, F'c  │
│     └──► Puede duplicar muestra para agregar otra edad de falla             │
│     └──► Cantidad total se calcula automáticamente                          │
│     └──► Completa cadena de custodia (fecha, estado, quien entrega)         │
│     └──► Firma digital: Nombre, Cargo, Email, Teléfono                      │
│     └──► Acepta declaración de veracidad                                    │
│     └──► Submit → Sistema registra IP, User-Agent, Timestamp                │
│                                                                             │
│  4. SISTEMA - Post envío                                                    │
│     └──► Guarda TODOS los campos en BD (para cálculos futuros)              │
│     └──► Almacena en expediente de la obra                                  │
│     └──► Estado cambia a "completada"                                       │
│     └──► Muestra página de confirmación al cliente                          │
│                                                                             │
│  5. STAFF GEOLAB - Después                                                  │
│     └──► Ve expediente profesional en /obras/<pk>/                          │
│     └──► Sidebar: Resumen (conteos), Cliente, Actividad                     │
│     └──► Documentos: últimos 5 + [Ver todos] → /obras/<pk>/informes/        │
│     └──► Remisiones: últimas 5 + [Ver todas] → /obras/<pk>/remisiones/      │
│     └──► Informes: filtros por búsqueda + rango de fechas (desde/hasta)     │
│     └──► Remisiones: filtros por búsqueda + estado                          │
│     └──► Puede completar "Recibido en Laboratorio"                          │
│     └──► Puede ver manifiesto con datos legales del firmante                │
│     └──► Los datos de muestras quedan listos para cálculos                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Flujo de Ensayos de Laboratorio (F-GT-05)

Este módulo digitaliza el proceso de ensayos que antes se hacía en Excel. **Cada OBRA tiene su propia hoja de trabajo** que agrupa todas las muestras de todas sus remisiones.

### Arquitectura: Hojas de Trabajo por Obra

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  SIDEBAR: "Hojas de Trabajo"                                                │
│     │                                                                       │
│     ▼                                                                       │
│  /hojas-trabajo/                                                            │
│  ┌─────────────────────────────────────────┐                                │
│  │  LISTA DE OBRAS CON HOJAS DE TRABAJO    │                                │
│  │                                         │                                │
│  │  [Obra 15-1] - 15 muestras - 3 HOY      │ ◄── Tarjetas con estadísticas  │
│  │  [Obra 27-1] - 8 muestras - 0 HOY       │                                │
│  │  [Obra 15-3] - 22 muestras - 5 vencidas │                                │
│  │  ...                                    │                                │
│  └────────────────┬────────────────────────┘                                │
│                   │ Click en una obra                                       │
│                   ▼                                                         │
│  /hojas-trabajo/obra/<pk>/                                                  │
│  ┌─────────────────────────────────────────┐                                │
│  │  HOJA DE TRABAJO DE LA OBRA             │                                │
│  │                                         │                                │
│  │  Obra: Torre Central (15-1)             │                                │
│  │  Progreso: ████████░░ 80%               │                                │
│  │                                         │                                │
│  │  [x] Muestra #72 - 7d  - HOY   (ROJO)   │ ◄── Auto-seleccionada         │
│  │  [x] Muestra #72 - 28d - HOY   (ROJO)   │ ◄── Parpadea en rojo          │
│  │  [ ] Muestra #73 - 7d  - en 5 días      │                                │
│  │  [✓] Muestra #74 - completada  (VERDE)  │ ◄── Ya tiene resultados       │
│  │  ...                                    │                                │
│  │                                         │                                │
│  │  [Seleccionar HOY] [Generar Informe]    │                                │
│  └─────────────────────────────────────────┘                                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Flujo Completo: Remisión → Hoja de Trabajo

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  FASE 1: REMISIÓN (F-GC-05) - Ya implementado                               │
│  ────────────────────────────────────────────                               │
│     1. Staff crea remisión → envía email al cliente                         │
│     2. Cliente llena muestras (tipo, localización, fecha, edad, F'c)        │
│     3. Cliente firma y envía → estado = 'completada'                        │
│                                                                             │
│  FASE 2: AUTO-CREACIÓN DE HOJA DE TRABAJO                                   │
│  ────────────────────────────────────────────                               │
│     4. Signal detecta estado='completada'                                   │
│     5. Crea HojaTrabajo (1:1 con RemisionMuestras)                          │
│     6. Vista crea ResultadoMuestra por cada Muestra                         │
│        (se hace en la vista DESPUÉS del formset.save())                     │
│                                                                             │
│  FASE 3: ENSAYOS EN LABORATORIO                                             │
│  ────────────────────────────────────────────                               │
│     7. Técnico va a /hojas-trabajo/ → ve lista de obras                     │
│     8. Entra a la obra → ve todas las muestras de todas las remisiones      │
│     9. Sistema detecta muestras para HOY (fecha_toma + edad = hoy)          │
│    10. Muestras de HOY aparecen en ROJO y se auto-seleccionan               │
│    11. Técnico hace clic en "Editar" → va a detalle por remisión            │
│    12. Llena: D1,D2,D3 / L1,L2,L3 / Peso / Carga máxima / Forma falla       │
│    13. Sistema calcula: diámetro real, área, esfuerzo, % desarrollo         │
│                                                                             │
│  FASE 4: GENERACIÓN DE INFORME (Pendiente)                                  │
│  ────────────────────────────────────────────                               │
│    14. Técnico selecciona muestras completadas                              │
│    15. Click en "Generar Informe" → PDF con resultados                      │
│    16. PDF se guarda como Informe en el expediente de la obra               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Detección Automática de Muestras para HOY

El sistema calcula automáticamente qué muestras deben fallarse cada día:

```python
fecha_falla_programada = fecha_toma + edad_ensayo_dias

# Ejemplo:
# Muestra tomada el 2024-01-10 con edad de 7 días
# → Debe fallarse el 2024-01-17

# En la hoja de trabajo:
# - Si fecha_falla == HOY → ROJO (parpadea) + auto-seleccionada
# - Si fecha_falla < HOY → AMARILLO (vencida) + auto-seleccionada
# - Si fecha_falla en próximos 3 días → badge INFO
# - Si completada → VERDE
```

### Accesos Rápidos

| Desde | Acción | Destino |
|-------|--------|---------|
| Sidebar | Click "Hojas de Trabajo" | Lista de obras `/hojas-trabajo/` |
| Sidebar | Click "Ensayos del Día" | Dashboard `/hojas-trabajo/hoy/` |
| Expediente de obra | Botón amarillo "Hoja de Trabajo" | Hoja de esa obra |
| Hoja de obra | Botón "Editar" en muestra | Detalle por remisión |

### Comando de Sincronización

Si hay remisiones completadas que no tienen hojas de trabajo (por ejemplo, completadas antes de implementar el módulo), ejecutar:

```bash
python manage.py sincronizar_hojas
```

Este comando:
1. Busca remisiones con estado='completada' sin HojaTrabajo
2. Crea la HojaTrabajo faltante
3. Crea ResultadoMuestra para cada Muestra
4. Reporta cuántas hojas y resultados fueron creados

---

## Proceso Actual de Laboratorio (Pre-Software)

Este apartado documenta cómo funciona actualmente el proceso de ensayos en Geolab **antes de la digitalización completa**. Se utiliza el archivo Excel `PLANTILLA MACRO.xlsx` (Formato F-GT-05) para registrar los resultados de los ensayos de compresión.

### Flujo Manual Actual

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  1. RECEPCIÓN (F-GC-05 - Ya digitalizado)                                   │
│     └──► Cliente entrega muestras con remisión digital                      │
│     └──► Se registra en sistema: número, localización, fecha, edad, F'c     │
│                                                                             │
│  2. PROGRAMACIÓN                                                            │
│     └──► Laboratorio programa fallas según edades (3, 7, 14, 28 días)       │
│     └──► Sistema calcula automáticamente: FECHA_FALLA = FECHA_TOMA + EDAD   │
│                                                                             │
│  3. ENSAYO FÍSICO (Día de la falla)                                         │
│     └──► Técnico mide 3 veces el DIÁMETRO con vernier (D1, D2, D3)          │
│     └──► Técnico mide 3 veces la LONGITUD con vernier (L1, L2, L3)          │
│     └──► Técnico pesa el cilindro en balanza (gramos)                       │
│     └──► Técnico somete a prensa hidráulica                                 │
│     └──► Máquina registra CARGA MÁXIMA (KN)                                 │
│     └──► Técnico observa y clasifica FORMA DE FALLA                         │
│                                                                             │
│  4. REGISTRO EN EXCEL (F-GT-05 - PLANTILLA MACRO.xlsx)                      │
│     └──► Los datos de la remisión se copian al encabezado                   │
│     └──► Los datos de cada muestra se copian a las filas                    │
│     └──► El técnico completa las mediciones y carga máxima                  │
│     └──► Excel calcula automáticamente los resultados                       │
│                                                                             │
│  5. GENERACIÓN DE INFORME                                                   │
│     └──► Se genera PDF con los resultados                                   │
│     └──► Se sube al sistema como Informe de la Obra                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Estructura del Excel F-GT-05 (PLANTILLA MACRO.xlsx)

**Información del formato:**
- Código: F-GT-05
- Versión: 02
- Título: "Relación de Muestras Ensayadas de Cilindros, Grouting, Morteros y Vigas"

**Encabezado (Filas 5-7) - Datos de la Obra:**
```
B5: CLIENTE. C.C:  ←── RemisionMuestras.cc / Constructora.codigo
B6: NOMBRE OBRA    ←── Obra.nombre
B7: C.O:           ←── Obra.codigo_obra
```

**Columnas de Datos (Fila 11+):**

| Columna | Encabezado | Origen | Descripción |
|---------|------------|--------|-------------|
| **A** | MUESTRA No | Remisión | `Muestra.numero_muestra` |
| **B** | LOCALIZACIÓN | Remisión | `Muestra.localizacion` |
| **C** | FECHA TOMA | Remisión | `Muestra.fecha_toma` |
| **D** | FECHA FALLA | Calculado | `=C+E` (fecha_toma + edad) |
| **E** | EDAD (DÍAS) | Remisión | `Muestra.edad_ensayo_dias` |
| **F** | DIÁMETRO TEÓRICO | Remisión | `Muestra.diametro_longitud` (3", 4", 6") |
| **G** | F'c (MPa) | Remisión | `Muestra.fc_resistencia` |
| **H,I,J** | D1, D2, D3 | Laboratorio | 3 mediciones de diámetro (mm) |
| **K** | DIÁMETRO REAL | Calculado | `=AVERAGE(H:J)` |
| **L** | ÁREA (mm²) | Calculado | `=PI()*K²/4/100` |
| **M,N,O** | L1, L2, L3 | Laboratorio | 3 mediciones de longitud (mm) |
| **P** | LONGITUD REAL | Calculado | `=AVERAGE(M:O)` |
| **Q** | PESO (g) | Laboratorio | Peso del cilindro |
| **R** | CARGA MÁXIMA (KN) | Laboratorio | Carga de rotura |
| **S** | ESFUERZO (MPa) | Calculado | `=(R*101.9716/L)/10` |
| **T** | % DESARROLLO | Calculado | `=S/G` (real vs esperado) |
| **U** | NÚMERO DE INFORME | Laboratorio | Código del informe generado |
| **W** | FORMA FALLA | Laboratorio | Tipo de falla observada |

### Fórmulas del Excel

```
FECHA FALLA:      =FECHA_TOMA + EDAD_DIAS
DIÁMETRO REAL:    =PROMEDIO(D1, D2, D3)
ÁREA:             =PI() × DIÁMETRO² / 4 / 100
LONGITUD REAL:    =PROMEDIO(L1, L2, L3)
ESFUERZO (MPa):   =(CARGA_KN × 101.9716 / ÁREA) / 10
% DESARROLLO:     =ESFUERZO / F'c × 100
```

### Correcciones de Instrumento

El Excel incluye factores de corrección para calibración de instrumentos:

**Corrección de Diámetro:**
| Tamaño | Corrección |
|--------|------------|
| 3" | -0.077 mm |
| 4" | -0.0245 mm |
| 6" | +0.003 mm |

**Corrección de Longitud:**
| Tamaño | Corrección |
|--------|------------|
| 3" | +0.17 mm |
| 4" | +0.1 mm |
| 6" | +0.072 mm |

**Coeficientes de Calibración Polinomial (Curva de carga):**
```
f(R) = A0 + A1×R + A2×R² + A3×R³

Donde:
  A0 = -1.36143
  A1 = 1.07562
  A2 = -0.000180408
  A3 = 9.45963e-08
```

### Mapeo Remisión → Excel

Cuando se llena el Excel, los datos fluyen así:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  EJEMPLO: Remisión con 3 muestras                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  RemisionMuestras:                                                          │
│    obra: "Torres del Parque" (codigo: "52-3")                               │
│    cc: "CC-2024-001"                                                        │
│                                                                             │
│  Muestras:                                                                  │
│    #1: num=72, loc="T1-Col C5", fecha=2024-01-10, edad=7,  Ø=4", F'c=21    │
│    #2: num=72, loc="T1-Col C5", fecha=2024-01-10, edad=28, Ø=4", F'c=21    │
│    #3: num=73, loc="T1-Viga V2", fecha=2024-01-10, edad=7,  Ø=4", F'c=28   │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  EXCEL RESULTANTE:                                                          │
│                                                                             │
│  B5: CC-2024-001                                                            │
│  B6: Torres del Parque                                                      │
│  B7: 52-3                                                                   │
│                                                                             │
│  ┌────┬───────────────┬────────────┬────────────┬──────┬─────┬───────┬────┐ │
│  │ A  │      B        │     C      │     D      │  E   │  F  │   G   │... │ │
│  │ Nº │ LOCALIZACIÓN  │ FECHA TOMA │ FECHA FALLA│ EDAD │  Ø  │  F'c  │    │ │
│  ├────┼───────────────┼────────────┼────────────┼──────┼─────┼───────┼────┤ │
│  │ 72 │ T1-Col C5     │ 2024-01-10 │ 2024-01-17 │   7  │ 4"  │  21   │    │ │
│  │ 72 │ T1-Col C5     │ 2024-01-10 │ 2024-02-07 │  28  │ 4"  │  21   │    │ │
│  │ 73 │ T1-Viga V2    │ 2024-01-10 │ 2024-01-17 │   7  │ 4"  │  28   │    │ │
│  └────┴───────────────┴────────────┴────────────┴──────┴─────┴───────┴────┘ │
│                                                                             │
│  Columnas H-W: El técnico completa después del ensayo físico                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Campos Pendientes de Digitalización

Para automatizar completamente este proceso, el modelo `Muestra` necesitará estos campos adicionales:

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `diametro_d1` | Decimal | Primera medición de diámetro (mm) |
| `diametro_d2` | Decimal | Segunda medición de diámetro (mm) |
| `diametro_d3` | Decimal | Tercera medición de diámetro (mm) |
| `longitud_l1` | Decimal | Primera medición de longitud (mm) |
| `longitud_l2` | Decimal | Segunda medición de longitud (mm) |
| `longitud_l3` | Decimal | Tercera medición de longitud (mm) |
| `peso_gramos` | Decimal | Peso del cilindro |
| `carga_maxima_kn` | Decimal | Carga de rotura en KN |
| `forma_falla` | Char | Tipo de falla observada |
| `numero_informe` | Char | Código del informe generado |

Y propiedades calculadas (Python):
- `diametro_real` → promedio de D1, D2, D3
- `longitud_real` → promedio de L1, L2, L3
- `area_mm2` → π × diametro_real² / 4 / 100
- `esfuerzo_mpa` → (carga_maxima_kn × 101.9716 / area) / 10
- `porcentaje_desarrollo` → esfuerzo_mpa / fc_resistencia × 100

> **Estado:** ✅ Este módulo ya está implementado en la app `ensayos`. Ver sección "App ensayos" en Modelos de Datos y URLs.

---

## Configuración de Entornos

### Desarrollo (DEBUG=True)
```
- Base de datos: PostgreSQL local (geolabmaster_db)
- Static files: /static/
- Media files: /media/
- Email: Console (se muestra en terminal)
```

### Producción (DEBUG=False)
```
- Base de datos: PostgreSQL
- Static files: S3 → s3://vadomdata/geolab/static/
- Media files: S3 → s3://vadomdata/geolab/media/
- Dominio: portalgeolab.com
- Email: SMTP (configurar en .env)
```

---

## Comandos de Migración de Datos (WordPress → Django)

### 1. `migrar_geolab` - Migración de estructura y datos

**Ubicación:** `core/management/commands/migrar_geolab.py`

**Uso:**
```bash
python manage.py migrar_geolab
```

**Función:** Migra datos desde WordPress (MySQL) a Django (PostgreSQL)

**Proceso:**
1. Conecta a base de datos MySQL: `wp_backup` (localhost, root, sin password)
2. **Fase 1 - Migra Obras:**
   - Consulta tabla `wpf3_posts` donde `post_type='proyectos'`
   - Extrae metadatos: código-cliente, razón social, municipio
   - Deduce/crea `Constructora` basándose en el código de cliente
   - Crea `Obra` vinculada a cada constructora
3. **Fase 2 - Migra Informes:**
   - Consulta informes con sus relaciones
   - Usa nombre del archivo PDF como título
   - Vincula a `Obra` según `id_wp_original`
   - Procesa en lotes de 2000 registros

**Base de datos MySQL requerida:**
```
Host: localhost
User: root
Password: (vacío)
Database: wp_backup
```

---

### 2. `descargar_archivos` - Descarga/enlace de PDFs

**Ubicación:** `core/management/commands/descargar_archivos.py`

**Uso:**
```bash
python manage.py descargar_archivos
```

**Función:** Enlaza archivos locales existentes o descarga faltantes desde URLs originales

**Proceso:**
1. Escanea `/media/` y crea diccionario de archivos existentes
2. Por cada Informe con `url_archivo_original`:
   - Si existe localmente → Enlaza
   - Si no existe → Descarga desde URL original
3. Configuración segura con User-Agent, Referer, y reintentos

---

### Flujo completo de migración

```
1. Tener backup MySQL de WordPress en 'wp_backup'
         │
         ▼
2. python manage.py migrar_geolab
   (Crea: Constructoras → Obras → Informes)
         │
         ▼
3. Copiar archivos PDF existentes a /media/
         │
         ▼
4. python manage.py descargar_archivos
   (Enlaza locales + descarga faltantes)
         │
         ▼
5. Verificar en admin que todo esté correcto
```

---

## Comandos Útiles

```bash
# Servidor de desarrollo
python manage.py runserver

# Migraciones de esquema
python manage.py makemigrations
python manage.py makemigrations solicitudes  # Para la nueva app
python manage.py makemigrations ensayos      # Para app de ensayos
python manage.py migrate

# Crear superusuario
python manage.py createsuperuser

# Migración de datos desde WordPress
python manage.py migrar_geolab

# Descarga/enlace de archivos PDF
python manage.py descargar_archivos

# Sincronizar hojas de trabajo faltantes
# (para remisiones completadas antes de implementar el módulo ensayos)
python manage.py sincronizar_hojas

# Shell de Django
python manage.py shell

# Collectstatic (producción)
python manage.py collectstatic
```

---

## Variables de Entorno (.env)

```env
# General
DEBUG=True
SECRET_KEY=tu-secret-key-segura
ALLOWED_HOSTS=.localhost,127.0.0.1

# Base de datos PostgreSQL
DB_NAME=geolabmaster_db
DB_USER=postgres
DB_PASSWORD=tu-password
DB_HOST=localhost
DB_PORT=5432

# AWS S3 (solo producción)
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_STORAGE_BUCKET_NAME=vadomdata

# Email (solo producción)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=tu-email@gmail.com
EMAIL_HOST_PASSWORD=tu-app-password
```

---

## Dependencias Principales

| Paquete | Versión | Uso |
|---------|---------|-----|
| Django | 6.0 | Framework web |
| psycopg2-binary | 2.9.11 | Conector PostgreSQL |
| mysqlclient | 2.2.7 | Conector MySQL (migraciones desde WP) |
| python-decouple | 3.8 | Variables de entorno |
| pillow | 12.0.0 | Procesamiento de imágenes |
| requests | 2.32.5 | Descargas HTTP |
| django-filter | 25.2 | Filtrado en vistas y querysets |
| django-storages | - | Storage backends (S3) - requerido en prod |
| boto3 | - | Cliente AWS - requerido en prod |

---

## Identidad Visual

**Paleta de colores (CSS Variables):**
```css
--brand-blue: #008ed6;      /* Azul Vibrante (Acentos) */
--brand-grey: #9ca3af;      /* Gris Suave */
--sidebar-bg: #1c2e4a;      /* Azul Oscuro Profundo (Fondo Sidebar) */
--accent-color: #008ed6;
--bg-body: #f8fafc;         /* Fondo General */
--text-main: #334155;       /* Texto Principal */
--text-muted: #94a3b8;      /* Texto Secundario */
--border-color: #e2e8f0;    /* Bordes Suaves */
```

**Logo:** `static/img/geolab-logo.png`

**Tipografía:** Inter (Google Fonts)

---

## Cómo Probar el Flujo de Remisiones

### Requisitos Previos
```bash
# Asegúrate de tener las migraciones aplicadas
python manage.py makemigrations solicitudes
python manage.py migrate

# Tener al menos un usuario Staff Geolab
# (crear en admin o con createsuperuser y marcar es_geolab=True)

# Tener al menos una Obra en el sistema
```

### Pasos para Probar

| Paso | Acción | URL/Detalle |
|------|--------|-------------|
| 1 | Iniciar servidor | `python manage.py runserver` |
| 2 | Login como Staff | `/accounts/login/` |
| 3 | Ir a Directorio Empresas | `/empresas/` |
| 4 | Seleccionar una Empresa | Click en "Abrir Expediente" |
| 5 | Seleccionar una Obra | Click en la obra deseada |
| 6 | Crear Remisión | Click en botón verde **[Nueva Remisión]** |
| 7 | Llenar datos | Orden de Trabajo (ej: `12854`) + Email |
| 8 | Enviar | Click en **[Crear y Enviar Remisión]** |
| 9 | Copiar link del email | **Ver en terminal** (DEBUG mode) |
| 10 | Abrir link en incógnito | El cliente ve el formulario sin login |
| 11 | Llenar formulario | Agregar muestras + Cadena de custodia + Firma |
| 12 | Enviar remisión | Click en **[Enviar Remisión de Muestras]** |
| 13 | Ver confirmación | Página de éxito para el cliente |
| 14 | Verificar en Staff | Volver a `/obras/<pk>/` y ver la remisión |
| 15 | Ver todas las remisiones | Click en **[Ver todas]** → lista completa con filtros |
| 16 | Ver todos los informes | Click en **[Ver todos]** en Documentación → lista paginada |
| 17 | Filtrar informes por fecha | Usar campos "Desde" y "Hasta" + click **[Filtrar]** |

### Notas de Prueba

- **Email en DEBUG:** El email se muestra en la **terminal** donde corre el servidor (no se envía realmente)
- **Acceso sin login:** El link con token funciona sin necesidad de cuenta de usuario
- **Agregar muestras:** Usa el botón "Agregar Muestra" para añadir filas a la tabla
- **Duplicar muestras:** Botón "Duplicar" copia todos los datos (tipo, ensayos, localización, etc.) y permite editar solo edad y cantidad. Los campos bloqueados usan `pointer-events: none` en lugar de `disabled` para garantizar que los valores se envíen al servidor.
- **Cantidad total:** Se calcula automáticamente sumando las cantidades de todas las muestras
- **Datos del firmante:** Nombre, cargo y email son obligatorios para completar la remisión
- **IP y Timestamp:** Se registran automáticamente al enviar
- **Vista móvil:** En pantallas pequeñas (<768px) las muestras se muestran como tarjetas en lugar de tabla

---

## Notas Importantes

1. **Custom User Model:** Se usa `users.UsuarioBase` como AUTH_USER_MODEL
2. **Archivos sensibles:** No commitear `.env` con credenciales reales
3. **IDs originales:** Los campos `id_wp_original` permiten rastrear datos migrados
4. **Paginación:** Listados paginados a 10-20 items por página
5. **Búsqueda:** Filtros por título de informe y nombre de obra
6. **Token de acceso:** Las remisiones usan UUID para acceso seguro sin login
7. **Manifiesto legal:** Se registra IP, User-Agent y timestamp como evidencia
8. **Muestras en BD:** Todos los campos de muestras se guardan individualmente para cálculos futuros
9. **Numeración de remisiones:** Consecutivo automático por obra (1, 2, 3...) para identificación: "Obra 15-1, Remisión 5"
10. **Muestras con múltiples edades:** Una muestra (#72) puede tener múltiples filas con diferentes edades de falla (ej: 3 cilindros a 7 días + 4 cilindros a 28 días). Botón "Duplicar" copia datos y solo permite editar edad y cantidad. Técnicamente: usa `selectedIndex` para copiar selects y `pointer-events: none` (no `disabled`) para que los valores se envíen correctamente.
11. **Cantidad total auto-calculada:** El sistema suma automáticamente las cantidades de todas las muestras registradas.
12. **Formulario público responsive:** El formulario de remisión está optimizado para móviles con vista de tarjetas en pantallas pequeñas y tabla en desktop.
13. **Sección de recepción separada:** La recepción en laboratorio solo se muestra en el detalle interno (Staff), no en el formulario público del cliente.
14. **Diseño visual del formulario público:** Logo de 70px, encabezados de tabla con fondo oscuro y texto blanco para consistencia visual con las secciones.
15. **Hojas de trabajo por OBRA:** Cada obra tiene su propia hoja de trabajo que agrupa todas las muestras de todas sus remisiones. No es una hoja por remisión.
16. **Auto-creación de resultados:** Cuando el cliente completa una remisión, el sistema crea automáticamente la HojaTrabajo (signal) y los ResultadoMuestra (vista). Los resultados se crean en la vista `responder_remision` DESPUÉS de guardar el formset, no en el signal.
17. **Detección automática de muestras:** El sistema calcula `fecha_falla = fecha_toma + edad_dias` y marca en ROJO las que coinciden con HOY. Estas se auto-seleccionan al cargar la página.
18. **Comando de sincronización:** Si hay remisiones completadas sin hojas de trabajo, ejecutar `python manage.py sincronizar_hojas`.
19. **Hoja de trabajo profesional (F-GT-05):** El template `hoja_trabajo_obra.html` incluye TODOS los campos del Excel F-GT-05:
    - Datos de remisión: Nº muestra, localización, fecha toma, fecha falla, días restantes, edad, diámetro teórico, F'c
    - Mediciones editables: D1, D2, D3, L1, L2, L3, Peso (g), Carga máxima (KN)
    - Valores calculados: Diámetro real, Área (mm²), Longitud real, Esfuerzo (MPa), % Desarrollo
    - Forma de falla: Selector 1-6 según NTC 673
    - Diseño corporativo con encabezado tipo documento técnico, barra de estadísticas, y estilos para impresión
20. **Template base con bloques extensibles:** `base.html` incluye `{% block title %}` y `{% block extra_css %}` para personalizar título y estilos en templates hijos.
21. **Edición parcial de resultados:** La vista `editar_resultado` soporta actualizaciones parciales via AJAX (solo envía campos modificados) y retorna JSON con valores calculados actualizados.
22. **Datos de muestra en hoja de trabajo:** En la vista `hoja_trabajo_obra`, los datos de la muestra se pasan explícitamente en el diccionario (`'muestra': resultado.muestra`) para garantizar acceso en el template como `item.muestra.xxx`.
23. **Botón guardar flotante:** Aparece automáticamente cuando hay cambios pendientes en la hoja de trabajo. Advierte antes de salir si hay cambios sin guardar.
24. **Cálculos JavaScript en tiempo real:** Al editar mediciones en la hoja de trabajo, los valores calculados (diámetro real, área, esfuerzo) se actualizan visualmente antes de guardar.
25. **Rol Técnico de Laboratorio:** Nuevo rol con acceso limitado (`area='tecnico'`). Solo ve el dashboard de ensayos del día, sin acceso a empresas, obras o informes. El sistema detecta el rol con `user.es_tecnico_laboratorio` y redirige automáticamente a `/ensayos/dashboard-tecnico/`.
26. **Dashboard del técnico:** Vista simplificada que muestra solo muestras del día + vencidas, agrupadas por obra. Cada fila tiene campos editables (D1-D3, L1-L3, Peso, Carga, Forma Falla) con botón "OK" para guardar via AJAX. Las muestras completadas desaparecen automáticamente de la lista.
27. **Sidebar condicional:** `base.html` usa `{% if user.es_tecnico_laboratorio %}` para mostrar el sidebar correcto. El técnico ve `sidebar_tecnico.html` con solo 2 opciones: "Ensayos del Día" y "Muestras Pendientes".
28. **Template base para técnicos:** `base_tecnico.html` es un template separado usado por `dashboard_tecnico.html`, con diseño simplificado y header "Panel de Laboratorio".

---

## Estadísticas del Proyecto

| Métrica | Cantidad |
|---------|----------|
| **Apps Django** | 4 (users, core, solicitudes, ensayos) |
| **Modelos** | 10 (UsuarioBase, Constructora, FuncionarioGeolab, ClienteExterno, Obra, Informe, RemisionMuestras, Muestra, HojaTrabajo, ResultadoMuestra) |
| **Vistas** | 26 (9 en core + 7 en solicitudes + 10 en ensayos) |
| **URLs** | 21 (6 en core + 7 en solicitudes + 8 en ensayos) |
| **Formularios** | 10 |
| **Templates HTML** | 31 (~4500 líneas) |
| **Sidebars** | 3 (staff, tecnico, client) |
| **Migraciones** | 7 (2 users + 1 core + 2 solicitudes + 2 ensayos) |
| **Comandos de gestión** | 3 (migrar_geolab, descargar_archivos, sincronizar_hojas) |
| **Dependencias Python** | 14 (+3 opcionales para producción) |

---

## Arquitectura Visual

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         GEOLAB MASTER                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   FRONTEND                        BACKEND                 DATOS         │
│  ┌─────────────┐                ┌─────────────┐        ┌─────────────┐  │
│  │ Bootstrap   │                │   Django    │        │ PostgreSQL  │  │
│  │ 5.3 + HTMX  │ ◄────────────► │    6.0      │ ◄────► │   + AWS S3  │  │
│  │ + Icons     │                │  (Python)   │        │   (prod)    │  │
│  └─────────────┘                └─────────────┘        └─────────────┘  │
│        │                              │                      │          │
│        ▼                              ▼                      ▼          │
│  ┌─────────────┐                ┌─────────────┐        ┌─────────────┐  │
│  │ 26 Templates│                │  4 Apps:    │        │ 10 Modelos  │  │
│  │ (Jinja2)    │                │ users, core │        │  6 Migrac.  │  │
│  │             │                │ solicitudes │        │             │  │
│  │             │                │ ensayos     │        │             │  │
│  └─────────────┘                └─────────────┘        └─────────────┘  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Flujo de Datos Principal

```
Usuario ──► Login ──► Router ──┬──► Staff (Admin) ──► Empresas ──► Obras ──► Remisiones
                               │
                               ├──► Técnico Lab ──► Dashboard Técnico ──► Ensayos del día
                               │                    (muestras HOY + vencidas por obra)
                               │
                               └──► Cliente ──► Portal ──► Informes

FLUJO DE REMISIÓN Y ENSAYOS:
Staff ──► Crear Remisión ──► Email ──► Cliente (token) ──► Formulario ──► BD
                                                                          │
                                                                          ▼
                                                         [Signal: HojaTrabajo]
                                                         [Vista: ResultadoMuestra]
                                                                          │
                                                                          ▼
Técnico ──► /ensayos/dashboard-tecnico/ ──► Muestras agrupadas por obra
                                                              │
                                                              ▼
                              Tabla simplificada con campos de medición
                              (D1-D3, L1-L3, Peso, Carga, Forma Falla)
                                                              │
                                                              ▼
                              Guardar via AJAX ──► Muestra desaparece ──► Siguiente
```
