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
- Hojas de trabajo de ensayos (F-GT-05) con macros multi-geometría
- Sistema de calidad (SGC) con explorador de archivos
- Facturación completa con precios por obra
- Control de acceso multi-rol

## Estructura del Proyecto

```
geolab_master/
├── config/             # Settings, URLs raíz
├── core/               # Obras, Informes, Dashboards
├── users/              # UsuarioBase, Constructora, ClienteExterno, FuncionarioGeolab
├── solicitudes/        # RemisionMuestras, Muestra, Notificacion
├── ensayos/            # HojaTrabajo, ResultadoMuestra, geometry.py, macros.py
├── calidad/            # AreaCalidad, Carpeta, Documento, AccesoAreaUsuario
├── facturacion/        # CategoriaServicio, TipoServicio, PrecioServicio, Factura
├── templates/          # Templates organizados por app
│   ├── base.html       # Layout principal (bloques: sidebar, panel_title, content, extra_css/js)
│   ├── base_tecnico.html      # Shell standalone del técnico
│   ├── base_facturacion.html  # Shell del módulo Facturación (extiende base.html)
│   └── includes/       # Sidebars: staff, tecnico, remitente, client, facturacion
├── static/img/         # Logo
├── media/informes/     # PDFs subidos
└── requirements.txt
```

## Modelos de Datos

### users
- **UsuarioBase**: Custom User (AbstractUser) con `es_geolab`, `es_cliente`
- **Constructora**: Empresas clientes (nombre, codigo, nit, ciudad)
- **FuncionarioGeolab**: Perfil empleados (area: admin/lab/recepcion/tecnico)
- **ClienteExterno**: Perfil clientes (empresa FK, rol: director/residente/remitente)

### core
- **Obra**: Proyectos (nombre, codigo_obra, constructora FK, residentes_asignados M2M)
- **Informe**: PDFs técnicos (titulo, obra FK, archivo FileField)

### solicitudes
- **RemisionMuestras**: Formato F-GC-05 (obra FK, orden_trabajo, estado, firmante_*, cadena custodia)
- **Muestra**: Detalle de cada muestra en la remisión
  - `dimension_especimen`: Select predefinido. Concreto: 3_pulg, 4_pulg, 6_pulg, 50_mm, 15x15_cm. Acero (varilla/malla): 1_4_pulg, 3_8_pulg, 1_2_pulg, 5_8_pulg, 3_4_pulg, 7_8_pulg, 1_pulg, 1_1_4_pulg. El front muestra el subconjunto según el tipo (JS en los 2 forms de remisión).
  - `geometria`: Campo auto-calculado (cilindro/cubo/prisma/acero) derivado de dimension_especimen
  - `tipo_muestra`: concreto, grouting, mortero, muretes, bloques, vigas, varilla, malla_elec
  - `TIPOS_SIN_HOJA = ('varilla', 'malla_elec')`: estos tipos (acero) se almacenan en la remisión pero NO generan HojaTrabajo/ResultadoMuestra (ver `crear_hoja_trabajo_y_resultados`). En remisión mixta, solo el concreto va a la hoja.
  - `numero_muestra`, `cantidad`, `localizacion`, `fecha_toma`, `edad_ensayo_dias`, `fc_resistencia`
  - Campos legacy: `diametro_longitud`, `unidad_diametro` (datos antiguos, no se usan en formularios nuevos)
- **Notificacion**: Sistema de alertas (tipo, titulo, mensaje, destinatario, leida)

### ensayos
- **HojaTrabajo**: Formato F-GT-05 (remision 1:1, estado, progreso, realizado_por)
- **ResultadoMuestra**: Mediciones y resultados por muestra
  - Mediciones comunes: `diametro_d1/d2/d3`, `longitud_l1/l2/l3`, `peso_gramos`, `carga_maxima_kn`, `forma_falla`
  - Campos de vigas (solo geometría prisma): `luz_entre_apoyos`, `distancia_falla_apoyo`, `formula_flexion` (A/B), `tipo_especimen_viga` (F/C)
  - Properties calculadas vía macros: `diametro_real`, `area_mm2`, `esfuerzo_mpa`, `porcentaje_desarrollo`

### calidad
- **AreaCalidad**: Las 8 áreas del SGC
- **Carpeta**: Carpetas recursivas dentro de un área
- **Documento**: Archivos subidos a una carpeta
- **AccesoAreaUsuario**: Permisos lectura/edición por área por usuario (staff)
- **AccesoCarpetaUsuario**: Permisos POR CARPETA de los Usuarios de Calidad (`puede_ver/puede_cargar/puede_eliminar`; cargar/eliminar implican ver). Sin fila = carpeta bloqueada. Sin herencia en BD: la matriz marca subcarpetas en cascada vía JS, pero lo que vale es lo guardado. Los ancestros de una carpeta permitida son "de paso" (navegables, sin documentos ni acciones) — lógica en `calidad/permisos.py`

### facturacion
- **CategoriaServicio**: Categorías (ej: CONCRETOS, SUELOS, TRANSPORTE)
- **TipoServicio**: Servicios específicos con norma técnica
- **PrecioServicio**: Precio personalizado por obra
- **Impuesto**: Configuración IVA
- **RegistroServicio**: Servicio realizado con precio congelado (price freezing)
- **Factura**: Generada por periodo, con PDF vía WeasyPrint

**Relaciones clave:**
```
Constructora 1:N Obra 1:N Informe
Obra 1:N RemisionMuestras 1:N Muestra
RemisionMuestras 1:1 HojaTrabajo 1:N ResultadoMuestra
Muestra 1:1 ResultadoMuestra
AreaCalidad 1:N Carpeta (recursiva) 1:N Documento
Obra 1:N RegistroServicio N:1 Factura
```

## Sistema de Roles

| Rol | Condición | Acceso |
|-----|-----------|--------|
| Staff Admin | `es_geolab=True`, area in [admin,lab,recepcion] | Todo |
| Técnico Lab | `es_geolab=True`, `area='tecnico'` | Solo ensayos/dashboard |
| Coord. Calidad | `es_geolab=True`, `area='calidad'` | **Solo** `/calidad/*`, pero manda dentro del SGC |
| Usuario Calidad | `es_geolab=True`, `area='calidad_usuario'` | **Solo** `/calidad/*` y solo carpetas asignadas (ver/cargar/eliminar) |
| Director | `es_cliente=True`, `rol='director'` | Todas obras de su empresa |
| Residente | `es_cliente=True`, `rol='residente'` | Solo obras asignadas |
| Remitente | `es_cliente=True`, `rol='remitente'` | Solo crear remisiones |

**Properties en UsuarioBase:** `es_tecnico_laboratorio`, `es_admin_geolab`, `es_remitente`, `es_coordinador_calidad`, `es_usuario_calidad`, `es_confinado_a_calidad`, `es_admin_sgc`

### Roles confinados al SGC (coordinador y usuarios de calidad)

Ambos necesitan `es_geolab=True` porque el módulo de calidad lo exige, pero ese
mismo flag es la puerta de ~43 vistas de core/users/solicitudes/ensayos. Por eso el
confinamiento NO vive en las vistas sino en `users/middleware.py` (aplica a
`es_confinado_a_calidad` = coordinador + usuarios de calidad):

**Usuario de Calidad** (`area='calidad_usuario'`): lo crea el coordinador desde
`/calidad/usuarios/` (lista, crear, matriz de carpetas, activar/desactivar). Solo ve
las carpetas con fila en `AccesoCarpetaUsuario` y sus ancestros "de paso"; el resto
queda bloqueado (GET y POST). Si crea una subcarpeta (permiso cargar), hereda
automáticamente su fila de permisos sobre ella. La matriz de accesos por área
(`gestionar_accesos`) lo excluye: sus permisos van por carpeta, no por área.

- **`RestriccionCalidadMiddleware`** (último en `MIDDLEWARE`, necesita `request.user` y
  `messages`): lista blanca de `/calidad/`, `/accounts/`, `/static/`, `/media/` y `/`.
  Todo lo demás redirige a `explorador_calidad`. Al ser deny-by-default, cualquier módulo
  o URL nuevo nace cerrado para este rol. Los superusuarios quedan exentos para no
  bloquearse del admin.
- **`es_admin_sgc`** = `es_admin_geolab or es_coordinador_calidad`. Es la property que
  decide quién manda *dentro* del SGC: ve las 8 áreas sin pasar por `AccesoAreaUsuario`,
  sube, crea, elimina y gestiona accesos. Usarla en calidad (views y templates) en vez
  de `es_admin_geolab`.
- **Se crea con `python manage.py crear_coordinador_calidad`** (ver Comandos Útiles):
  hace usuario + perfil dentro de una `transaction.atomic()`, valida la contraseña con
  los validadores de Django y verifica el rol resultante antes de terminar.
  A mano desde el admin también se puede, pero es un flujo de 2 pasos (la casilla
  `es_geolab` solo aparece al editar) y hay que asignar el **área antes** de marcar
  `es_geolab`, o el usuario queda como admin total mientras tanto (ver nota 21).

## URLs Principales

| App | Rutas clave |
|-----|-------------|
| core | `/`, `/empresas/`, `/obras/<pk>/`, `/cargar-informe/` |
| users | `/usuarios/`, `/usuarios/nuevo/`, `/usuarios/<pk>/editar/` |
| solicitudes | `/remisiones/`, `/obras/<pk>/nueva-remision/`, `/remitente/`, `/notificaciones/` |
| ensayos | `/ensayos/hojas-trabajo/`, `/ensayos/dashboard-tecnico/`, `/ensayos/hojas-trabajo/obra/<pk>/` |
| calidad | `/calidad/`, `/calidad/area/<pk>/`, `/calidad/carpeta/<pk>/` |
| facturacion | `/facturacion/`, `/facturacion/catalogo/`, `/facturacion/generar/`, `/facturacion/repositorio/` |

## Sistema de Macros de Cálculo por Geometría

El sistema rutea automáticamente a diferentes macros de cálculo según la geometría del espécimen. La geometría se deriva del campo `dimension_especimen` seleccionado en la remisión.

### Clasificación (ensayos/geometry.py)

| Dimensión (select) | Geometría | Macro |
|---------------------|-----------|-------|
| 3", 4", 6" (pulg) | `cilindro` | MacroCilindro |
| 50mm | `cubo` | MacroCubo |
| 15x15cm | `prisma` | MacroPrisma |
| 1/4"…1 1/4" (acero) | `acero` | (sin macro — no genera hoja de trabajo) |

`Muestra.save()` auto-calcula `geometria` via `clasificar_geometria()`. El campo `dimension_especimen` es un select predefinido (sin ambigüedad). Existe fallback legacy para datos antiguos con `diametro_longitud` + `unidad_diametro`. La geometría `acero` (varilla/malla) no tiene macro ni flujo de ensayo: solo se almacena.

### Strategy Pattern (ensayos/macros.py)

```
MacroBase (ABC)
├── MacroCilindro  → compresión estándar
├── MacroCubo      → compresión cubos NTC 220
└── MacroPrisma    → flexión vigas NTC 2871

get_macro(geometria) → MacroBase  (registry con fallback a cilindro)
```

`ResultadoMuestra._macro` delega todos los cálculos a la macro correcta según `muestra.geometria`.

### Fórmulas por Geometría

**Cilindro (compresión estándar) — réplica EXACTA de la macro Excel original (PLANTILLA MACRO.xlsx, F-GT-05):**
```
D.P = promedio(D1,D2,D3) + corrección_diámetro[3"|4"|6"]   (tabla CORRECCION_DIAMETRO_MM)
L.P = promedio(L1,L2,L3) + corrección_longitud[3"|4"|6"]   (tabla CORRECCION_LONGITUD_MM)
area = π × D.P² / 4 / 100                                   (cm²)
carga_corr = A0 + A1·R + A2·R² + A3·R³                      (polinomio calibración prensa; R = kN tal cual)
esfuerzo_mpa = (carga_corr × 101.9716 / area) / 10
% desarrollo = esfuerzo_mpa / fc_mpa × 100
```
- **Corrección de instrumento**: tablas y polinomio en `ensayos/macros.py` (vienen del certificado de calibración — actualizar ahí al recalibrar). Se elige según `dimension_especimen`; muestras legacy sin dimensión NO se corrigen.
- **SIN redondeos intermedios**: la cadena se calcula en precisión completa (como Excel) vía `MacroCilindro.calcular_valores_exactos()`; el redondeo es solo de presentación con `redondear_half_up()` (half-away-from-zero, como muestra Excel — `round()` de Python usa banker's). La carga en kN se registra/muestra tal cual; el polinomio se aplica en las columnas de resistencia.
- Paridad verificada contra el Excel original con `ensayos/tests.py` (`python manage.py test ensayos`) — no modificar fórmulas sin correr esos tests.

**Cubo (compresión NTC 220):**
```
ancho = promedio(A1, A2, A3) mm
largo = promedio(L1, L2, L3) mm
area_cm2 = (ancho/10) × (largo/10)
esfuerzo_kgcm2 = (carga_kn × 101.96) / area_cm2
esfuerzo_mpa = esfuerzo_kgcm2 × 0.09807
% desarrollo = esfuerzo_mpa / fc_mpa × 100
```

**Viga/Prisma (flexión NTC 2871):**
```
b = promedio(b1, b2, b3) mm  (ancho)
d = promedio(d1, d2, d3) mm  (altura)
P_kgf = carga_kn × 101.96

Fórmula A (falla en tercio medio):  R_mpa = (P_kgf × L) / (b × d²) × 10
Fórmula B (falla fuera del tercio):  R_mpa = (3 × P_kgf × a) / (b × d²) × 10

% desarrollo = R_mpa / MR_kgcm2 × 1000
(MR/fc para vigas se ingresa en kg/cm²)
```

### Campos específicos de vigas en ResultadoMuestra
- `luz_entre_apoyos`: L, distancia entre apoyos (mm)
- `distancia_falla_apoyo`: a, distancia falla al apoyo más próximo (mm)
- `formula_flexion`: 'A' (tercio medio) o 'B' (fuera del tercio)
- `tipo_especimen_viga`: 'F' (fundido) o 'C' (cortado)

### JavaScript (client-side)
`hoja_trabajo_obra.html` tiene `calcularAreaPorGeometria()` y `calcularEsfuerzoPorGeometria()` que replican las fórmulas del backend para cálculo en tiempo real. Cada `<tr>` tiene `data-geometria` para el dispatch JS.

## Flujo Principal Completo

### 1. Remisión (Remitente)
1. Login → `/remitente/` → Seleccionar obra → Crear remisión con muestras
2. Por cada muestra: selecciona `dimension_especimen` (ej: "6 pulg") → `Muestra.save()` auto-clasifica `geometria='cilindro'`
3. Sistema: Guarda con `transaction.atomic()`, crea HojaTrabajo + ResultadoMuestra, notifica Staff (email + campana)

### 2. Recepción Lab (Staff)
1. Staff ve campana → detalle remisión → completa cadena custodia lab (`lab_fecha`, `lab_cantidad`, etc.)

### 3. Ensayos (Técnico)
1. `/ensayos/dashboard-tecnico/` → Muestras HOY + vencidas por obra
2. El sistema detecta `geometria` de cada muestra y muestra campos según tipo:
   - **Cilindro/Cubo**: D1-D3, L1-L3, Peso, Carga, Forma Falla
   - **Viga**: b1-b3, d1-d3, Carga, Luz L, Distancia a, Fórmula A/B, Tipo F/C
3. Al guardar mediciones vía HTMX → `_macro` calcula automáticamente → JSON response con valores calculados
4. Auto-completa estado='completado' cuando todas las mediciones están llenas
5. `HojaTrabajo.actualizar_estado()` actualiza progreso

### 4. Informe (GAP)
- No hay generación automática de PDF de resultados
- Staff sube PDFs manualmente como `Informe` asociado a una `Obra`
- `HojaTrabajo.estado='informe_generado'` y `numero_informe` existen en el modelo pero no se usan aún

## Comandos Útiles

```bash
python manage.py makemigrations [app]
python manage.py migrate
python manage.py createsuperuser
python manage.py sincronizar_hojas  # Crea hojas faltantes
python manage.py migrar_geolab      # Migración desde WordPress
python manage.py descargar_archivos # Descarga PDFs pendientes
python manage.py importar_calidad   # Areas y carpetas SGC
python manage.py limpiar_remisiones # Borra TODAS las remisiones (cascada). Flags: --noinput, --informes

# Crea el rol Coordinador de Calidad (usuario + perfil en una transacción,
# evitando la ventana en que es_admin_geolab lo dejaría como admin total).
python manage.py crear_coordinador_calidad <usuario> \
    --nombre "Maria" --apellido "Gomez" --email maria@geolab.com --codigo-empleado GC-01
# Sin --password la pide oculta por consola. Otros flags: --actualizar (convierte
# un usuario existente, conserva su clave si no se pasa --password), --noinput.
```

## Variables de Entorno (.env)

```env
DEBUG=True
SECRET_KEY=...
DB_NAME=geolabmaster_db
DB_USER=postgres
DB_PASSWORD=...
DB_HOST=localhost
DB_PORT=5432
# Opcional: ruta a LibreOffice para convertir informes XLSX→PDF
# Windows: LIBREOFFICE_PATH=C:\Program Files\LibreOffice\program\soffice.exe
# Linux:   LIBREOFFICE_PATH=/usr/bin/soffice
LIBREOFFICE_PATH=
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
3. **Auto-creación:** Al completar remisión se crea HojaTrabajo + ResultadoMuestra automáticamente (función helper `crear_hoja_trabajo_y_resultados`, no signal)
4. **Muestras múltiples edades:** Una muestra puede tener varias filas con diferentes `edad_ensayo_dias`
5. **Detección automática HOY:** `fecha_falla = fecha_toma + edad_dias`, marca en ROJO si == hoy
6. **Firma automática remitente:** Datos del firmante se toman del usuario logueado
7. **Notificación dual:** Email + campana al crear remisión
8. **Sidebar condicional:** 5 sidebars según rol (staff, tecnico, calidad, remitente, client)
9. **Validación PDFs:** Doble validación cliente (JS) y servidor (Django)
10. **HTMX:** Usado para edición inline en hojas de trabajo y toggles
11. **Campos DEPRECADOS:** `token_acceso` y `email_destinatario` en RemisionMuestras (sistema de tokens eliminado)
12. **Campos LEGACY:** `diametro_longitud` y `unidad_diametro` en Muestra (reemplazados por `dimension_especimen`)
13. **Macro dispatch:** `ResultadoMuestra._macro` → `get_macro(muestra.geometria)` → Strategy Pattern
14. **Price freezing:** `RegistroServicio.precio_unitario_congelado` captura precio al momento del registro
15. **Producción:** dominio `portalgeolab.com`, S3 bucket `vadomdata/geolab/`
16. **URLs montadas en RAÍZ:** TODAS las apps se incluyen con `path('', include(...))` en `config/urls.py` (sin prefijo de app). Las rutas reales son p.ej. `/resultado/<pk>/editar/`, NO `/ensayos/resultado/...`. En `fetch()` usar la ruta sin prefijo de app.
17. **Acero sin hoja de trabajo:** tipos `varilla`/`malla_elec` (`Muestra.TIPOS_SIN_HOJA`) → geometría `acero`, se almacenan pero no generan HojaTrabajo/ResultadoMuestra.
18. **`forma_falla` canónico:** valores `tipo_1`..`tipo_6` (NO `1`..`6`). `informes._tipo_falla_num()` exige el prefijo `tipo_`.
19. **PDF de informes de ensayo:** XLSX siempre (inyección XML sobre plantilla); el PDF requiere LibreOffice headless. Ruta vía `settings.LIBREOFFICE_PATH` (config desde `.env`, default None) → fallback a `soffice`/`libreoffice` en PATH. Sin LibreOffice, solo se genera el XLSX.
20. **Layouts / sub-apps:** `base.html` expone `{% block sidebar %}` y `{% block panel_title %}` (defaults por rol). Facturación es un "sub-aplicativo": sus templates extienden `base_facturacion.html` (que sobreescribe esos bloques con `sidebar_facturacion.html`), y el sidebar de staff entra con un solo enlace "Facturación". `factura_pdf.html` NO extiende base (es standalone para WeasyPrint). El técnico usa `base_tecnico.html` (standalone).
21. **`es_admin_geolab` tiene un fallback peligroso:** si un usuario tiene `es_geolab=True` pero le falta el perfil `FuncionarioGeolab`, la property devuelve `es_geolab` → queda como **admin total**. Por eso todo usuario Geolab (y en especial el Coordinador de Calidad) debe crearse siempre con su perfil. Corregirlo a `return False` es lo correcto, pero antes hay que revisar en producción qué usuarios quedarían sin acceso.

## Seguridad

- CSRF habilitado globalmente
- Validadores de contraseña activos
- Logging con `logging.getLogger(__name__)`
- IP y User-Agent registrados en firma de remisiones
- FBV exclusivamente con `@login_required`, permisos manuales por vista

**Producción (agregar en settings.py):**
```python
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
```
