## Descripción del Proyecto

Sistema de facturación multi-sede para **Geolab**, un laboratorio de geotecnia. Gestiona el ciclo completo de facturación: registro de servicios de laboratorio realizados a empresas constructoras → generación de facturas con PDF. Construido con Django 5.2.3 + PostgreSQL.

---

## Stack Tecnológico

| Capa | Tecnología |
|------|-----------|
| Backend | Django 5.2.3, Python 3.x |
| Base de datos | PostgreSQL (psycopg2) |
| Frontend | Bootstrap 5.3.3, Bootstrap Icons 1.11.3, Google Fonts (Inter) |
| Dropdowns inteligentes | django-select2 (Select2Widget, ModelSelect2Widget) |
| Formularios | django-crispy-forms con crispy-bootstrap5 |
| PDF | WeasyPrint (HTML → PDF) |
| Gráficas | Chart.js (dashboard) |
| Auth | Django auth con modelo User custom (AbstractUser) |
| Env vars | python-decouple (`config()`) |

---

## Estructura del Proyecto

```
facturacion_geolab_temp/
├── CLAUDE.md                     ← Este archivo
├── FacturasPDF/                  ← Carpeta legacy (no trackeada en git)
└── facturacion/                  ← Proyecto Django principal
    ├── manage.py
    ├── facturacion/              ← Configuración del proyecto
    │   ├── settings.py
    │   ├── urls.py               ← URL router principal
    │   ├── wsgi.py
    │   └── asgi.py
    ├── templates/
    │   └── base.html             ← Template base con sidebar y layout
    ├── static/
    │   └── images/
    │       └── logogeolab.png    ← Logo usado en base.html y PDF
    ├── media/                    ← MEDIA_ROOT (PDFs generados)
    │   └── facturas/
    │       └── [NombreConstructora]/
    │           └── Factura_[ID]_[Obra]_[Fecha].pdf
    ├── sedes/                    ← App: Sucursales/sedes del laboratorio
    ├── clients/                  ← App: Constructoras y Obras
    ├── services/                 ← App: Catálogo de servicios y precios
    ├── invoicing/                ← App: Core de facturación (registros, facturas, PDF)
    └── users/                    ← App: Modelo de usuario personalizado
```

---

## Apps Django y sus Responsabilidades

### 1. `sedes` — Sucursales del laboratorio
- **Modelo**: `Sede` (nombre, ciudad, direccion, telefono)
- **Middleware**: `SedeSelectionMiddleware` intercepta TODAS las peticiones de usuarios autenticados (no superusers). Si no hay `sede_id` en sesión → redirige a `sedes:seleccionar_sede`
- **Flujo**: Usuario selecciona sede → se guarda `sede_id` y `sede_nombre` en `request.session`
- **Impacto**: TODAS las vistas del sistema filtran datos por `sede_id` de la sesión. Es el mecanismo de multi-tenancy

### 2. `users` — Autenticación
- **Modelo**: `User` extiende `AbstractUser` con campo `cargo` (CharField)
- **Configuración**: `AUTH_USER_MODEL = 'users.User'` en settings
- **Login**: Usa `LOGIN_URL = 'admin:login'` (login del admin de Django)

### 3. `clients` — Gestión de clientes
- **Modelos**: `Constructora`, `Obra`
- **Responsabilidad**: CRUD de empresas constructoras (clientes) y sus proyectos de obra
- **Lógica clave**: Soft delete (`esta_activa`), códigos únicos por sede, gestión de precios por obra

### 4. `services` — Catálogo de servicios
- **Modelos**: `CategoriaServicio`, `TipoServicio`, `PrecioServicio`
- **Responsabilidad**: Catálogo global de servicios de laboratorio organizados por categoría, con precios personalizables por obra
- **Lógica clave**: La categoría con código `'7'` es TRANSPORTE (tratamiento especial de IVA)

### 5. `invoicing` — Core de facturación
- **Modelos**: `RegistroServicio`, `Factura`, `Impuesto`
- **Responsabilidad**: Registrar servicios realizados, generar facturas, generar PDFs, dashboard, histórico, repositorio de facturas
- **Es la app más grande y compleja del sistema**

---

## Modelos — Esquema Completo

### Diagrama de Relaciones

```
Sede ──1:N──► Constructora ──1:N──► Obra ──1:N──► RegistroServicio ──N:1──► Factura
               (sede FK)            (constructora  (obra FK,               (constructora FK,
                                     FK CASCADE)    tipo_servicio FK,       obra FK)
                                                    factura FK nullable)
                                        │
                                        └──1:N──► PrecioServicio ◄──N:1── TipoServicio ──N:1──► CategoriaServicio
                                                   (obra FK,               (categoria FK
                                                    tipo_servicio FK)       CASCADE)
```

### `sedes.Sede`
| Campo | Tipo | Notas |
|-------|------|-------|
| nombre | CharField(100) | unique=True |
| ciudad | CharField(100) | |
| direccion | CharField(255) | blank=True |
| telefono | CharField(20) | blank=True |

### `clients.Constructora`
| Campo | Tipo | Notas |
|-------|------|-------|
| codigo | CharField(20) | "No. Empresa". Ej: "51" |
| nombre | CharField(255) | Nombre de la empresa |
| sede | FK → Sede | on_delete=PROTECT |
| esta_activa | BooleanField | default=True. Soft delete |
| tipo_empresa | CharField(20) | Choices: REGULAR, ESPECIAL, GUBERNAMENTAL |
| nit | CharField(20) | unique=True, nullable |
| direccion | CharField(255) | blank |
| municipio | CharField(100) | blank |
| telefono | CharField(20) | blank |
| nombre_contacto | CharField(255) | blank |
| cargo_contacto | CharField(100) | blank |
| celular_contacto | CharField(20) | blank |
| email_contacto | EmailField | blank |
| observaciones | TextField | blank |
| fecha_creacion | DateTimeField | auto_now_add |

**Constraint**: `UniqueConstraint(fields=['sede', 'codigo'], condition=Q(esta_activa=True))` — Código único por sede solo entre activas.

**`__str__`**: `"({sede.nombre}) {codigo} - {nombre}"`

### `clients.Obra`
| Campo | Tipo | Notas |
|-------|------|-------|
| constructora | FK → Constructora | on_delete=CASCADE, related_name='obras' |
| codigo | CharField(50) | Formato: "{codigo_constructora}-{secuencial}". Ej: "51-1", "51-2" |
| nombre | CharField(255) | |
| ubicacion | CharField(255) | blank |
| fecha_inicio | DateField | nullable |
| esta_activa | BooleanField | default=True. Soft delete |
| fecha_creacion | DateTimeField | auto_now_add |

**Constraint**: `UniqueConstraint(fields=['constructora', 'codigo'], condition=Q(esta_activa=True))` — Código único por constructora solo entre activas.

**`__str__`**: `"{codigo} - {nombre} ({constructora.nombre})"`

### `services.CategoriaServicio`
| Campo | Tipo | Notas |
|-------|------|-------|
| codigo | CharField(20) | unique=True. Ej: "1", "2", "7" |
| nombre | CharField(255) | Ej: "CONCRETOS", "SUELOS", "TRANSPORTE" |

**IMPORTANTE**: La categoría con `codigo='7'` es **TRANSPORTE**. Tiene tratamiento especial de IVA en la facturación.

### `services.TipoServicio`
| Campo | Tipo | Notas |
|-------|------|-------|
| categoria | FK → CategoriaServicio | on_delete=CASCADE, related_name='servicios' |
| codigo | CharField(20) | unique=True. Ej: "I-1", "I-2" |
| nombre | CharField(255) | unique=True. Descripción del servicio |
| norma | CharField(100) | blank. Norma técnica aplicable |

### `services.PrecioServicio`
| Campo | Tipo | Notas |
|-------|------|-------|
| obra | FK → Obra | on_delete=CASCADE, related_name='lista_de_precios' |
| tipo_servicio | FK → TipoServicio | on_delete=CASCADE |
| precio | DecimalField(12,2) | **nullable** (null=True, blank=True). Un precio null = no configurado |

**Constraint**: `unique_together = ('obra', 'tipo_servicio')` — Un solo precio por combinación obra/servicio.

### `invoicing.Impuesto`
| Campo | Tipo | Notas |
|-------|------|-------|
| nombre | CharField(50) | unique=True. Se busca por `nombre__iexact="IVA"` |
| porcentaje | DecimalField(5,2) | Ej: 19.00 para 19% |
| activo | BooleanField | default=True |

### `invoicing.RegistroServicio`
| Campo | Tipo | Notas |
|-------|------|-------|
| obra | FK → Obra | on_delete=PROTECT |
| tipo_servicio | FK → TipoServicio | on_delete=PROTECT |
| fecha_realizacion | DateField | default=timezone.now |
| cantidad | PositiveIntegerField | default=1 |
| numero_informe | CharField(100) | Número de informe del laboratorio |
| precio_unitario_congelado | DecimalField(12,2) | **PRECIO CONGELADO** al momento del registro |
| subtotal | DecimalField(14,2) | **Calculado automáticamente** en `save()`: `precio_unitario_congelado × cantidad` |
| facturar_despues | BooleanField | default=False |
| factura | FK → Factura | on_delete=SET_NULL, nullable, related_name='registros' |

**Ordering**: `['-fecha_realizacion', '-id']`

**Regla `save()`**: `self.subtotal = self.precio_unitario_congelado * self.cantidad`

### `invoicing.Factura`
| Campo | Tipo | Notas |
|-------|------|-------|
| constructora | FK → Constructora | on_delete=PROTECT, related_name='facturas' |
| obra | FK → Obra | on_delete=PROTECT, related_name='facturas' |
| fecha_inicio_periodo | DateField | Inicio del periodo facturado |
| fecha_fin_periodo | DateField | Fin del periodo facturado |
| fecha_emision | DateField | default=timezone.now |
| subtotal | DecimalField(14,2) | Suma de todos los subtotales de registros |
| monto_iva | DecimalField(14,2) | IVA calculado (default=0) |
| total | DecimalField(14,2) | subtotal + monto_iva |
| iva_transporte_facturado | BooleanField | default=False. Indica si se aplicó IVA a transportes |
| estado | CharField(10) | Choices: PENDIENTE (default), PAGADA, ANULADA |
| pdf_path | CharField(512) | Ruta absoluta al PDF generado |

**Propiedad `pdf_url`**: Calcula la URL pública relativa al MEDIA_URL para servir el PDF.

**Ordering**: `['-fecha_emision']`

### `users.User`
| Campo | Tipo | Notas |
|-------|------|-------|
| (hereda AbstractUser) | | username, email, password, etc. |
| cargo | CharField(100) | blank. Puesto del usuario |

---

## Lógica de Negocio — Detalle Completo

### 1. MULTI-TENANCY POR SEDE

**Flujo**:
1. Usuario se autentica (admin login)
2. `SedeSelectionMiddleware` detecta que no hay `sede_id` en sesión
3. Redirige a `sedes:seleccionar_sede`
4. Usuario elige sede → se guarda en sesión: `sede_id` (int) y `sede_nombre` (str)
5. **TODAS las vistas** filtran por `sede_id`:
   - Constructoras: `Constructora.objects.filter(sede_id=sede_id)`
   - Obras: `Obra.objects.filter(constructora__sede_id=sede_id)`
   - Registros: `RegistroServicio.objects.filter(obra__constructora__sede_id=sede_id)`
   - Facturas: `Factura.objects.filter(constructora__sede_id=sede_id)`

**Excepciones**: Los superusers no pasan por el middleware. El catálogo de servicios (CategoriaServicio, TipoServicio) es **global** (no se filtra por sede).

**Función helper**: `get_sede_id_from_session(request)` en `invoicing/views.py`

### 2. SOFT DELETE DE CONSTRUCTORAS Y OBRAS

**Patrón**: Campo `esta_activa` (BooleanField, default=True).

**Constructora**:
- **Desactivar** (`desactivar_constructora_view`): POST only + login_required. Cambia `esta_activa=False`. No borra datos.
- **Reactivar** (`reactivar_constructora_view`): POST only + login_required. **VERIFICA CONFLICTO**: Antes de reactivar, comprueba que no exista OTRA constructora activa con el mismo código en la misma sede. Si hay conflicto → error, no reactiva. Si no → `esta_activa=True`.
- **Listas separadas**: `ConstructoraListView` (activas), `ConstructoraInactivaListView` (inactivas). Misma template con variable de contexto `vista_inactivos`.

**Obra**: Tiene el campo `esta_activa` pero actualmente no hay vista específica de desactivación/reactivación.

**UniqueConstraints condicionales**: Solo aplican cuando `esta_activa=True`. Esto permite que existan constructoras/obras inactivas con el mismo código.

### 3. SISTEMA DE CÓDIGOS

**Constructora**:
- `codigo`: Asignado manualmente por el usuario (ej: "51")
- Único por sede solo entre activas

**Obra**:
- `codigo`: Formato `{codigo_constructora}-{secuencial}`. Ej: "51-1", "51-2", "51-3"
- Al crear una obra desde el detalle de constructora, el sistema **sugiere automáticamente** el siguiente código:
  1. Obtiene todas las obras existentes de esa constructora
  2. Parsea el número secuencial después del `-`
  3. Calcula `max(secuenciales) + 1`
  4. Sugiere `"{constructora.codigo}-{siguiente}"`
- Único por constructora solo entre activas

**API helper**: `api_codigos_usados_view` devuelve JSON con códigos y nombres de constructoras activas de la sede actual.

### 4. PRECIOS POR OBRA (PrecioServicio)

**Concepto**: Cada obra tiene su propia lista de precios. Un mismo servicio puede costar diferente en cada obra.

**Gestión** (`gestionar_precios_obra_view`):
1. Al acceder a la vista de precios de una obra, el sistema ejecuta `get_or_create` para CADA TipoServicio existente → garantiza que exista una entrada PrecioServicio por cada servicio para esa obra
2. El precio por defecto es `None` (no configurado)
3. Se muestra un formset organizado por categoría usando `modelformset_factory(PrecioServicio, form=PrecioServicioForm, extra=0)`
4. El usuario puede dejar precios en blanco o asignar valores

**Impacto**: Si un servicio no tiene precio configurado para una obra, al intentar registrarlo se obtiene `PrecioServicio.DoesNotExist` → error.

### 5. CONGELAMIENTO DE PRECIOS (Price Freezing)

**Concepto crítico**: Cuando se registra un servicio, el precio se **congela** (copia) al campo `precio_unitario_congelado` del RegistroServicio. NO se vincula al PrecioServicio.

**Flujo**:
1. Usuario registra servicio para obra X, servicio Y
2. Sistema busca `PrecioServicio.objects.get(obra=X, tipo_servicio=Y)`
3. Copia `precio_obj.precio` → `RegistroServicio.precio_unitario_congelado`
4. A futuro, si cambia el precio en PrecioServicio, los registros existentes **mantienen el precio original**

**Excepción**: Al **editar** un registro no facturado (`RegistroServicioUpdateView.form_valid`), el precio se **re-congela** desde PrecioServicio actual. Esto es intencional: al editar un registro, se actualiza al precio vigente.

### 6. REGISTRO DE SERVICIOS

**Vista**: `vista_crear_registro` — Maneja GET (formulario) y POST (AJAX JSON)

**GET**:
- Renderiza formulario con 3 pasos: 1) Constructora, 2) Obra (dependent), 3) Fecha
- Carga todos los TipoServicio disponibles
- Fecha pre-llenada con hoy

**POST** (AJAX, JSON body):
- Recibe: `obra_id`, `fecha_realizacion`, `servicios[]` (cada uno con `tipo_servicio_id`, `numero_informe`, `cantidad`)
- Valida que la obra pertenezca a la sede activa
- **Transacción atómica**: Para cada servicio:
  1. Obtiene TipoServicio
  2. Obtiene PrecioServicio para esa obra/servicio
  3. Crea RegistroServicio con `precio_unitario_congelado=precio_obj.precio`
- Retorna JSON: `{status: 'success/error', message: '...'}`

**APIs auxiliares**:
- `api_get_obras`: GET `?constructora_id=X` → JSON con obras de esa constructora
- `api_get_precio`: GET `?obra_id=X&tiposervicio_id=Y` → JSON con precio (o null si no existe)

### 7. GENERACIÓN DE FACTURAS — FLUJO COMPLETO

**Paso 1: Preview** (`vista_generar_factura` — GET)
1. Usuario selecciona: Constructora → Obra → Fecha inicio → Fecha fin
2. Sistema busca registros pendientes:
   ```python
   RegistroServicio.objects.filter(
       obra=obra,
       fecha_realizacion__range=(fecha_inicio, fecha_fin),
       factura__isnull=True  # Solo registros NO facturados
   )
   ```
3. **Separa registros en dos grupos**:
   - `registros_normales`: Todos EXCEPTO los de categoría código '7'
   - `registros_transporte`: Solo los de categoría código '7' (TRANSPORTE)
4. Obtiene el IVA activo desde `Impuesto.objects.get(nombre__iexact="IVA", activo=True)`
5. Renderiza preview con ambas tablas + checkboxes para seleccionar qué transportes llevan IVA

**Paso 2: Finalización** (`finalizar_factura` — POST only, login_required)

Recibe: `obra_id`, `fecha_inicio`, `fecha_fin`, `transporte_con_iva[]` (IDs de registros de transporte seleccionados para IVA)

**Dentro de `transaction.atomic()`**:

1. **Cálculo de montos**:
   ```
   subtotal_completo = SUM(subtotal) de TODOS los registros a facturar

   base_iva_normales = SUM(subtotal) de registros que NO son transporte (categoría ≠ '7')
   base_iva_transporte = SUM(subtotal) de registros de transporte SELECCIONADOS para IVA

   base_para_iva = base_iva_normales + base_iva_transporte
   monto_iva = base_para_iva × (iva_porcentaje / 100)

   total = subtotal_completo + monto_iva
   ```

   **REGLA CLAVE DE IVA**:
   - Servicios normales (no transporte): **SIEMPRE** se incluyen en la base del IVA
   - Servicios de transporte (categoría '7'): **SOLO** se incluyen en la base del IVA si el usuario los seleccionó con checkbox (`transporte_con_iva`)
   - El subtotal siempre incluye TODO (normales + transportes con y sin IVA)

2. **Creación de Factura**:
   ```python
   Factura.objects.create(
       constructora=obra.constructora,
       obra=obra,
       fecha_inicio_periodo=fecha_inicio,
       fecha_fin_periodo=fecha_fin,
       subtotal=subtotal_completo,
       monto_iva=monto_iva_calculado,
       total=total_final,
       iva_transporte_facturado=bool(ids_transporte_con_iva)
   )
   ```

3. **Vinculación**: `registros_a_facturar.update(factura=nueva_factura)` — Todos los registros quedan vinculados a la factura

4. **Generación de PDF**:
   - Template: `invoicing/factura_pdf.html`
   - Logo: `Path(STATICFILES_DIRS[0]) / 'images' / 'logogeolab.png'` convertido a URI con `.as_uri()`
   - HTML → PDF con `HTML(string=html_string).write_pdf(ruta)`
   - Ruta: `MEDIA_ROOT/facturas/{NombreConstructoraLimpio}/Factura_{ID}_{ObraLimpia}_{YYYY-MM}.pdf`
   - Sanitización de nombres: Solo alfanuméricos, espacios, `_`, `-`
   - Se guarda `pdf_path` en el objeto Factura

5. **Resultado**: Redirige a histórico con mensaje de éxito

### 8. ANULACIÓN DE FACTURAS

**Vista**: `anular_factura_view` — POST only, login_required

**Dentro de `transaction.atomic()`**:
1. Obtiene la factura validando que pertenezca a la sede activa
2. **Libera los registros**: `factura.registros.all().update(factura=None)` — Los registros quedan disponibles para ser re-facturados
3. **Cambia estado**: `factura.estado = 'ANULADA'`
4. Redirige al repositorio de obras del cliente

**IMPORTANTE**: La anulación NO borra la factura ni los registros. Solo desvincula y marca como anulada.

### 9. EDICIÓN DE REGISTROS

**Vista**: `RegistroServicioUpdateView` (UpdateView)

**Restricciones**:
- Solo registros de la sede activa
- Solo registros **NO facturados** (`factura__isnull=True`)

**Al guardar**: Re-congela el precio desde PrecioServicio actual (no mantiene el precio original). Si no existe PrecioServicio → precio = 0.

### 10. REPOSITORIO DE FACTURAS

**Navegación drill-down de 3 niveles**:

1. **Nivel 1** — Lista de Constructoras con facturas:
   - `RepositorioClienteListView`: Constructoras activas con al menos una factura
   - `RepositorioClienteInactivoListView`: Constructoras inactivas con al menos una factura
   - Toggle entre activos/inactivos en la misma template

2. **Nivel 2** — Obras de una constructora con facturas:
   - `RepositorioObraListView`: Obras que tienen al menos una factura

3. **Nivel 3** — Facturas de una obra:
   - `RepositorioFacturaListView`: Todas las facturas de una obra, ordenadas por fecha_emision desc
   - Desde aquí se puede descargar PDF o anular factura

### 11. DASHBOARD

**Vista**: `dashboard_view`

**Métricas calculadas (filtradas por sede)**:
- Total de constructoras activas
- Total de obras (de constructoras activas)
- Facturas emitidas este mes (count y sum total)
- Registros creados este mes
- Top 3 clientes por facturación histórica (annotate Sum total)
- Top 3 servicios más registrados últimos 90 días (annotate Count)

**Gráfica dinámica** (AJAX):
- `api_facturacion_mensual_view`: Retorna facturación mensual últimos 6 meses
- Agrupa por `TruncMonth('fecha_emision')` → `Sum('total')`
- Formato JSON para Chart.js: `{labels: [...], data: [...]}`

### 12. HISTÓRICO

**Vista**: `vista_historico`

**Filtros** (todos opcionales):
- Constructora (Select2 con búsqueda por código o nombre)
- Obra (Select2 dependiente de constructora)
- Tipo de servicio (Select2 con búsqueda por código o nombre)
- Rango de fechas (fecha_inicio, fecha_fin)

Muestra todos los RegistroServicio de la sede activa, ordenados por fecha descendente.

---

## URLs Completas

### Router Principal (`facturacion/urls.py`)
| Ruta | Destino |
|------|---------|
| `/` | Redirect → `/invoicing/` |
| `/admin/` | Django Admin |
| `/accounts/` | `django.contrib.auth.urls` (login, logout, password) |
| `/invoicing/` | App invoicing |
| `/clientes/` | App clients |
| `/sedes/` | App sedes |
| `/servicios/` | App services |
| `/select2/` | django-select2 (autocomplete AJAX) |
| `/media/...` | Archivos media (solo en DEBUG) |

### Invoicing (`invoicing/urls.py`, namespace=`invoicing`)
| Ruta | Name | Vista | Método |
|------|------|-------|--------|
| `/invoicing/` | `dashboard` | `dashboard_view` | GET |
| `/invoicing/registro/crear/` | `crear_registro` | `vista_crear_registro` | GET/POST(JSON) |
| `/invoicing/historico/` | `historico` | `vista_historico` | GET |
| `/invoicing/facturacion/generar/` | `generar_factura` | `vista_generar_factura` | GET |
| `/invoicing/facturacion/finalizar/` | `finalizar_factura` | `finalizar_factura` | POST |
| `/invoicing/factura/<pk>/anular/` | `factura_anular` | `anular_factura_view` | POST |
| `/invoicing/registro/<pk>/editar/` | `registro_update` | `RegistroServicioUpdateView` | GET/POST |
| `/invoicing/repositorio/` | `repositorio_clientes` | `RepositorioClienteListView` | GET |
| `/invoicing/repositorio/cliente/<pk>/` | `repositorio_obras_cliente` | `RepositorioObraListView` | GET |
| `/invoicing/repositorio/obra/<pk>/` | `repositorio_facturas_obra` | `RepositorioFacturaListView` | GET |
| `/invoicing/repositorio/inactivos/` | `repositorio_clientes_inactivos` | `RepositorioClienteInactivoListView` | GET |
| `/invoicing/api/get-obras/` | `api_get_obras` | `api_get_obras` | GET |
| `/invoicing/api/get-precio/` | `api_get_precio` | `api_get_precio` | GET |
| `/invoicing/api/facturacion-mensual/` | `api_facturacion_mensual` | `api_facturacion_mensual_view` | GET |

### Clients (`clients/urls.py`, namespace=`clients`)
| Ruta | Name | Vista | Método |
|------|------|-------|--------|
| `/clientes/constructoras/` | `constructora_list` | `ConstructoraListView` | GET |
| `/clientes/constructoras/nueva/` | `constructora_create` | `ConstructoraCreateView` | GET/POST |
| `/clientes/constructoras/<pk>/` | `constructora_detail` | `ConstructoraDetailView` | GET |
| `/clientes/constructoras/<pk>/editar/` | `constructora_update` | `ConstructoraUpdateView` | GET/POST |
| `/clientes/constructoras/<pk>/eliminar/` | `constructora_delete` | `ConstructoraDeleteView` | GET/POST |
| `/clientes/constructoras/<pk>/desactivar/` | `constructora_desactivar` | `desactivar_constructora_view` | POST |
| `/clientes/constructoras/<pk>/reactivar/` | `constructora_reactivar` | `reactivar_constructora_view` | POST |
| `/clientes/constructoras/inactivas/` | `constructora_inactiva_list` | `ConstructoraInactivaListView` | GET |
| `/clientes/constructoras/<pk>/obras/nueva/` | `obra_create_for_constructora` | `ObraCreateView` | GET/POST |
| `/clientes/obras/<pk>/editar/` | `obra_update` | `ObraUpdateView` | GET/POST |
| `/clientes/obras/<pk>/precios/` | `obra_gestionar_precios` | `gestionar_precios_obra_view` | GET/POST |
| `/clientes/api/codigos-usados/` | `api_codigos_usados` | `api_codigos_usados_view` | GET |

### Services (`services/urls.py`, namespace=`services`)
| Ruta | Name | Vista | Método |
|------|------|-------|--------|
| `/servicios/` | `tiposervicio_list` | `TipoServicioListView` | GET |
| `/servicios/nuevo/` | `tiposervicio_create` | `TipoServicioCreateView` | GET/POST |
| `/servicios/<pk>/editar/` | `tiposervicio_update` | `TipoServicioUpdateView` | GET/POST |
| `/servicios/<pk>/eliminar/` | `tiposervicio_delete` | `TipoServicioDeleteView` | GET/POST |
| `/servicios/categorias/` | `categoria_list` | `CategoriaServicioListView` | GET |
| `/servicios/categorias/nueva/` | `categoria_create` | `CategoriaServicioCreateView` | GET/POST |
| `/servicios/categorias/<pk>/editar/` | `categoria_update` | `CategoriaServicioUpdateView` | GET/POST |
| `/servicios/categorias/<pk>/eliminar/` | `categoria_delete` | `CategoriaServicioDeleteView` | GET/POST |
| `/servicios/api/buscar/` | `api_buscar_servicios` | `api_buscar_servicios` | GET |

### Sedes (`sedes/urls.py`, namespace=`sedes`)
| Ruta | Name | Vista |
|------|------|-------|
| `/sedes/seleccionar/` | `seleccionar_sede` | `seleccionar_sede_view` |

---

## Templates

### Base (`templates/base.html`)
- Layout fijo con sidebar (260px) + contenido principal
- **Sidebar**: Logo, navegación principal (Dashboard, Registrar, Histórico, Generar Factura, Repositorio), sección Gestión (Clientes, Catálogo), info de sede activa con botón cambiar
- Mensajes Django (alerts Bootstrap dismissible)
- Blocks: `title`, `styles`, `content`, `scripts`
- CDNs: Bootstrap 5.3.3, Bootstrap Icons 1.11.3, Google Fonts Inter, Chart.js

### Templates por App
- `invoicing/dashboard.html` — KPIs + gráfica Chart.js
- `invoicing/crear_registro_form.html` — Formulario AJAX multi-paso con líneas dinámicas
- `invoicing/historico_list.html` — Tabla filtrable de registros
- `invoicing/generar_factura.html` — Preview de factura con separación normal/transporte
- `invoicing/factura_pdf.html` — Template HTML para WeasyPrint (tamaño letter, 1cm margin)
- `invoicing/registro_servicio_form_edit.html` — Edición de registro
- `invoicing/repositorio_cliente_list.html` — Lista drill-down nivel 1 (reutilizada activos/inactivos)
- `invoicing/repositorio_obra_list.html` — Lista drill-down nivel 2
- `invoicing/repositorio_factura_list.html` — Lista drill-down nivel 3
- `clients/constructora_list.html` — Lista (reutilizada activas/inactivas)
- `clients/constructora_detail.html` — Detalle con obras activas
- `clients/constructora_form.html` — Crear/editar constructora
- `clients/constructora_confirm_delete.html` — Confirmar eliminación
- `clients/obra_form.html` — Crear/editar obra
- `clients/gestionar_precios_obra.html` — Formset de precios por categoría
- `services/tiposervicio_list.html` — Servicios agrupados por categoría
- `services/tiposervicio_form.html` — Crear/editar servicio
- `services/categoria_list.html` — Lista de categorías
- `services/categoria_form.html` — Crear/editar categoría
- `sedes/seleccionar_sede.html` — Dropdown de sedes

---

## Formularios

| Form | App | Tipo | Campos | Notas |
|------|-----|------|--------|-------|
| `ConstructoraForm` | clients | ModelForm | codigo, tipo_empresa, nombre, nit, direccion, municipio, telefono, contacto... | Excluye `sede` (se asigna en vista) |
| `ObraForm` | clients | ModelForm | constructora, codigo, nombre, ubicacion, fecha_inicio | `__init__` recibe `sede_id`, filtra constructoras activas. Select2Widget para constructora |
| `PrecioServicioForm` | services | ModelForm | precio | Usado en formset para gestión masiva de precios |
| `TipoServicioForm` | services | ModelForm | (campos del modelo) | CRUD básico |
| `CategoriaServicioForm` | services | ModelForm | (campos del modelo) | CRUD básico |
| `RegistroHeaderForm` | invoicing | Form | constructora, obra, fecha_realizacion | 3 pasos. Obra dependiente de constructora (Select2) |
| `FiltroHistoricoForm` | invoicing | Form | constructora, obra, tipo_servicio, fecha_inicio, fecha_fin | Todos opcionales. Select2 con búsqueda |
| `GenerarFacturaForm` | invoicing | Form | constructora, obra, fecha_inicio, fecha_fin | Select2 con dependent_fields |
| `RegistroServicioForm` | invoicing | ModelForm | obra, tipo_servicio, fecha_realizacion, numero_informe, cantidad | Para edición. Filtra obras por sede |

**Patrón común**: Todos los formularios que manejan constructoras/obras reciben `sede_id` en `__init__` y filtran querysets para mostrar solo datos de la sede activa.

---

## Configuración (settings.py)

```python
DEBUG = True
DATABASES = PostgreSQL → 'facturacion_db', user='postgres', password=config('DB_PASSWORD')
AUTH_USER_MODEL = 'users.User'
LOGIN_URL = 'admin:login'
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
CRISPY_TEMPLATE_PACK = 'bootstrap5'
RUTA_BASE_FACTURAS = 'C:/Users/ASUS/Documents/Facturacion_geolab_temp/FacturasPDF'  # Legacy, no usado activamente
```

**Middleware chain**:
1. SecurityMiddleware
2. SessionMiddleware
3. CommonMiddleware
4. CsrfViewMiddleware
5. AuthenticationMiddleware
6. **SedeSelectionMiddleware** ← Custom (requiere sede en sesión)
7. MessageMiddleware
8. XFrameOptionsMiddleware

---

## Protección de Datos (on_delete)

| Relación | on_delete | Razón |
|----------|-----------|-------|
| Constructora → Sede | PROTECT | No borrar sede si tiene constructoras |
| Obra → Constructora | CASCADE | Si se borra constructora, se borran sus obras |
| TipoServicio → Categoria | CASCADE | Si se borra categoría, se borran sus servicios |
| PrecioServicio → Obra | CASCADE | Si se borra obra, se borran sus precios |
| PrecioServicio → TipoServicio | CASCADE | Si se borra servicio, se borran sus precios |
| RegistroServicio → Obra | PROTECT | No borrar obra si tiene registros |
| RegistroServicio → TipoServicio | PROTECT | No borrar servicio si tiene registros |
| RegistroServicio → Factura | SET_NULL | Si se borra factura, el registro se desvincula |
| Factura → Constructora | PROTECT | No borrar constructora si tiene facturas |
| Factura → Obra | PROTECT | No borrar obra si tiene facturas |

---

## Convenciones del Proyecto

- **Idioma del código**: Español (nombres de modelos, campos, variables, mensajes)
- **Idioma de la UI**: Español
- **Views**: Mezcla de function-based views (para lógica compleja) y class-based views (para CRUD estándar)
- **Seguridad**: `@login_required` + `@require_POST` para acciones destructivas
- **Transacciones**: `transaction.atomic()` para operaciones multi-paso (facturación, anulación, registro masivo)
- **AJAX**: JSON responses para APIs internas, formularios POST estándar para acciones principales
- **Select2**: Para todos los dropdowns de búsqueda (constructoras, obras, servicios)
- **Mensajes**: `django.contrib.messages` para feedback al usuario (success, error, warning)

---

## Comandos Útiles

```bash
cd facturacion
python manage.py runserver          # Iniciar servidor de desarrollo
python manage.py makemigrations     # Crear migraciones
python manage.py migrate            # Aplicar migraciones
python manage.py createsuperuser    # Crear admin
python manage.py shell              # Shell interactivo
```

**Variable de entorno requerida**: `DB_PASSWORD` (password de PostgreSQL)
