"""
Lectura de los proyectos (obras) e informes del WordPress viejo (portal.geolabsas.co).

Dos fuentes con la misma salida:
- FuenteMySQL: conexión directa a la base viva (WP_DB_* del .env). Es la que
  se usa en producción para traer todo "a la fecha".
- FuenteDump: un volcado .sql de phpMyAdmin (p. ej. portal.sql). Sirve para
  probar la sincronización sin tocar WordPress.

Estructura en WordPress (tabla wpf3_posts + wpf3_postmeta):
- post_type 'proyectos' = obra. post_title = código de obra ("BUC 46-9").
  Meta: codigo-cliente_743 (código de empresa "BUC 46"; en algunas trae guion
  y es código de obra), codigo-proyecto (código de obra), nombre-proyecto
  (nombre real), razon-social, municipio, direccion, telefono,
  persona-de-contacto-1/2, celular-1/2, usuario.
- post_type 'informes' = informe PDF, ligado al proyecto por
  wpf3_jet_rel_default (rel_id=10, parent=proyecto, child=informe); el PDF es
  un attachment cuyo ID está en el meta galeria-pdf y su URL en posts.guid.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime

PREFIJO_TABLAS = 'wpf3_'
REL_INFORME_PROYECTO = '10'
META_PROYECTO = (
    'codigo-cliente_743', 'codigo-proyecto', 'nombre-proyecto', 'razon-social',
    'municipio', 'direccion', 'telefono', 'persona-de-contacto-1', 'celular-1',
    'persona-de-contacto-2', 'celular-2', 'usuario',
)


@dataclass
class ProyectoWP:
    id: int
    titulo: str
    fecha: datetime | None
    estado: str
    meta: dict = field(default_factory=dict)

    def m(self, clave):
        return (self.meta.get(clave) or '').strip()


@dataclass
class InformeWP:
    id: int
    titulo: str
    fecha: datetime | None
    estado: str
    proyecto_id: int | None
    url_pdf: str | None


def _fecha(valor):
    if not valor or str(valor).startswith('0000'):
        return None
    if isinstance(valor, datetime):
        return valor
    try:
        return datetime.strptime(str(valor)[:19], '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return None


# ═══════════════════════════════════════════════════════════════════════════
class FuenteMySQL:
    """Lee de la base viva de WordPress."""

    def __init__(self, host, user, password, db, prefijo=PREFIJO_TABLAS):
        import MySQLdb  # solo hace falta con esta fuente
        self.db = MySQLdb.connect(host=host, user=user, passwd=password, db=db, charset='utf8mb4')
        self.p = prefijo

    def proyectos(self):
        cur = self.db.cursor()
        cur.execute(f"SELECT ID, post_title, post_date, post_status FROM {self.p}posts WHERE post_type='proyectos'")
        proyectos = {int(r[0]): ProyectoWP(int(r[0]), r[1] or '', _fecha(r[2]), r[3]) for r in cur.fetchall()}
        if proyectos:
            marcas = ','.join(['%s'] * len(META_PROYECTO))
            cur.execute(
                f"SELECT post_id, meta_key, meta_value FROM {self.p}postmeta WHERE meta_key IN ({marcas})",
                META_PROYECTO,
            )
            for post_id, k, v in cur.fetchall():
                if int(post_id) in proyectos:
                    proyectos[int(post_id)].meta[k] = v
        return list(proyectos.values())

    def informes(self):
        cur = self.db.cursor()
        cur.execute(f"""
            SELECT p.ID, p.post_title, p.post_date, p.post_status, rel.parent_object_id, pdf.guid
            FROM {self.p}posts p
            LEFT JOIN {self.p}jet_rel_default rel
                   ON rel.child_object_id = p.ID AND rel.rel_id = {REL_INFORME_PROYECTO}
            LEFT JOIN {self.p}postmeta pm ON pm.post_id = p.ID AND pm.meta_key = 'galeria-pdf'
            LEFT JOIN {self.p}posts pdf ON pdf.ID = pm.meta_value
            WHERE p.post_type = 'informes'
        """)
        out = []
        while True:
            filas = cur.fetchmany(2000)
            if not filas:
                break
            for i, t, f, e, padre, guid in filas:
                out.append(InformeWP(int(i), t or '', _fecha(f), e, int(padre) if padre else None, guid or None))
        return out

    def cerrar(self):
        self.db.close()


# ═══════════════════════════════════════════════════════════════════════════
class FuenteDump:
    """Lee un volcado .sql de phpMyAdmin/mysqldump (INSERT extendidos)."""

    def __init__(self, ruta, prefijo=PREFIJO_TABLAS):
        self.ruta = ruta
        self.p = prefijo
        self._cargado = False

    # ── parser ──────────────────────────────────────────────────────────
    @staticmethod
    def _tuplas(texto):
        """Genera las tuplas de un 'VALUES (...),(...);' respetando comillas y escapes."""
        i, n = 0, len(texto)
        esc = {'n': '\n', 'r': '\r', '0': '\0', 't': '\t', 'Z': '\x1a'}
        while i < n:
            while i < n and texto[i] != '(':
                i += 1
            if i >= n:
                return
            i += 1
            vals, cur, tipo = [], [], None       # tipo: 'S' en cadena, 'D' cadena cerrada, 'U' sin comillas
            while i < n:
                c = texto[i]
                if tipo == 'S':
                    if c == '\\':
                        cur.append(esc.get(texto[i + 1], texto[i + 1]))
                        i += 2
                        continue
                    if c == "'":
                        tipo = 'D'
                        i += 1
                        continue
                    cur.append(c)
                    i += 1
                    continue
                if c == "'" and tipo is None:
                    tipo, cur = 'S', []
                    i += 1
                    continue
                if c in ',)':
                    if tipo == 'D':
                        vals.append(''.join(cur))
                    elif tipo == 'U':
                        tok = ''.join(cur).strip()
                        vals.append(None if tok == 'NULL' else tok)
                    cur, tipo = [], None
                    i += 1
                    if c == ')':
                        yield vals
                        break
                    continue
                if not c.isspace() and tipo is None:
                    tipo = 'U'
                if tipo == 'U':
                    cur.append(c)
                i += 1

    def _cargar(self):
        if self._cargado:
            return
        tablas = {f'{self.p}posts': None, f'{self.p}postmeta': None, f'{self.p}jet_rel_default': None}
        self._posts, self._meta, self._rel, self._guid = {}, {}, [], {}
        buf, tabla, en_create, create_buf = [], None, False, []
        with open(self.ruta, encoding='utf-8', errors='replace') as f:
            for linea in f:
                if linea.startswith('CREATE TABLE `'):
                    en_create, create_buf = True, [linea]
                    continue
                if en_create:
                    create_buf.append(linea)
                    if linea.startswith(')'):
                        en_create = False
                        t = re.search(r'CREATE TABLE `([A-Za-z_0-9]+)`', create_buf[0]).group(1)
                        if t in tablas:
                            tablas[t] = re.findall(r'^\s*`([A-Za-z_0-9]+)`', ''.join(create_buf[1:]), flags=re.M)
                    continue
                m = re.match(r'INSERT INTO `([A-Za-z_0-9]+)`', linea)
                if m:
                    tabla = m.group(1) if m.group(1) in tablas else None
                    buf = [linea] if tabla else []
                    if not (tabla and linea.rstrip().endswith(';')):
                        continue
                elif tabla and buf:
                    buf.append(linea)
                    if not linea.rstrip().endswith(';'):
                        continue
                else:
                    continue
                self._procesar(tabla, ''.join(buf), tablas[tabla])
                buf, tabla = [], None
        self._cargado = True

    def _procesar(self, tabla, texto, cols):
        cab = texto[:texto.index('VALUES')]
        m = re.search(r'\(([^)]*)\)', cab)
        if m:
            cols = re.findall(r'`([A-Za-z_0-9]+)`', m.group(1))
        cuerpo = texto[texto.index('VALUES') + 6:]
        for tup in self._tuplas(cuerpo):
            if len(tup) != len(cols):
                continue
            row = dict(zip(cols, tup))
            if tabla == f'{self.p}posts':
                tipo = row['post_type']
                if tipo in ('proyectos', 'informes'):
                    self._posts[int(row['ID'])] = row
                elif tipo == 'attachment':
                    self._guid[int(row['ID'])] = row['guid']
            elif tabla == f'{self.p}postmeta':
                k = row['meta_key']
                if k in META_PROYECTO or k == 'galeria-pdf':
                    self._meta.setdefault(int(row['post_id']), {})[k] = row['meta_value']
            else:
                if row['rel_id'] == REL_INFORME_PROYECTO:
                    self._rel.append((int(row['parent_object_id']), int(row['child_object_id'])))

    # ── salida ──────────────────────────────────────────────────────────
    def proyectos(self):
        self._cargar()
        return [
            ProyectoWP(i, r['post_title'] or '', _fecha(r['post_date']), r['post_status'],
                       {k: v for k, v in self._meta.get(i, {}).items() if k in META_PROYECTO})
            for i, r in self._posts.items() if r['post_type'] == 'proyectos'
        ]

    def informes(self):
        self._cargar()
        padre = {hijo: p for p, hijo in self._rel}
        out = []
        for i, r in self._posts.items():
            if r['post_type'] != 'informes':
                continue
            pdf_id = self._meta.get(i, {}).get('galeria-pdf')
            url = self._guid.get(int(pdf_id)) if pdf_id and str(pdf_id).isdigit() else None
            out.append(InformeWP(i, r['post_title'] or '', _fecha(r['post_date']), r['post_status'], padre.get(i), url))
        return out

    def cerrar(self):
        pass
