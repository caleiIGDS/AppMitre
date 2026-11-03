"""Consultas de lectura: snapshot único, identidad conservadora y paginación firmada.

No importa Flask, no descarga Sheets y nunca abre una base con permiso de escritura.
"""
from contextlib import closing
import difflib
import hashlib
import json
from pathlib import Path
import re

from itsdangerous import BadData, URLSafeSerializer

from .. import config, datos

DIAS = ('lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo')
TURNOS = ('mañana', 'tarde', 'vespertino')
VACANTES = {'', 'FALTA', 'FALTAN', 'SIN ASIGNAR'}
MAX_CARACTERES = 40000
MAX_ENTIDADES = 20
MAX_PERSONAS = 50
# La planilla completa habitual debe caber en una consulta, incluso con >20 personas.
MAX_PRECEPTORES = 50


class ErrorConsulta(Exception):
    def __init__(self, codigo, mensaje=None, **detalle):
        self.codigo = codigo
        self.detalle = {'codigo': codigo, **({'mensaje': mensaje} if mensaje else {}), **detalle}
        super().__init__(codigo)


def compacto(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':'), sort_keys=True)


def norm(valor):
    return ' '.join(datos.eliminar_acentos(str(valor or '')).lower().split())


def nombre(valor):
    return datos.limpiar_profesor(str(valor or ''))


def dia(valor):
    d = norm(valor)
    if d not in DIAS:
        raise ErrorConsulta('datos_inconsistentes', 'Día no interpretable en la fuente.')
    return d


def turno(valor):
    t = norm(valor)
    if t == 'manana':
        return 'mañana'
    if t not in TURNOS:
        raise ErrorConsulta('datos_inconsistentes', 'Turno no interpretable en la fuente.')
    return t


def dias_pedidos(p):
    resultado = []
    for valor in p.get('dias', DIAS[:5]):
        d = norm(valor)
        if d not in DIAS:
            raise ErrorConsulta('parametros_invalidos', 'Día desconocido.', campo='dias')
        if d not in resultado:
            resultado.append(d)
    return sorted(resultado, key=DIAS.index)


def curso(c, d):
    c, d = str(c or '').strip(), str(d or '').strip().upper()
    if not re.fullmatch(r'[1-9]\d*', c):
        raise ErrorConsulta('datos_inconsistentes', 'Año no interpretable en la fuente.')
    return f'{int(c)}° {d}'.strip()


def resolver_curso(valor, conocidos):
    m = re.fullmatch(r'\s*([1-9]\d*)\s*[°ºo]?\s*(.*?)\s*', valor, re.IGNORECASE)
    etiqueta = curso(m[1], m[2]) if m else None
    if etiqueta not in conocidos:
        raise ErrorConsulta('no_encontrado', 'Curso desconocido.', consulta=valor)
    return etiqueta


def intervalo(fila):
    limites = []
    for campo in ('hora_inicio', 'hora_fin'):
        valor = str(fila[campo] or '').strip()
        n = datos._a_minutos(valor)
        if (not re.fullmatch(r'\d{1,2}:\d{2}(?::[0-5]\d)?', valor)
                or n is None or not 0 <= n <= 1440):
            raise ErrorConsulta('datos_inconsistentes', 'Intervalo no interpretable en la fuente.')
        limites.append(n)
    if limites[0] >= limites[1]:
        raise ErrorConsulta('datos_inconsistentes', 'Intervalo no interpretable en la fuente.')
    return limites


def candidatos(consulta, padron):
    q = norm(nombre(consulta))
    fuertes = sorted(n for n in padron if q and q in norm(n))
    if fuertes:
        return fuertes
    def puntaje(n):
        texto = norm(n)
        if q in texto:
            return 2.0
        return sum(max(difflib.SequenceMatcher(None, a, b).ratio()
                       for b in texto.split()) for a in q.split()) / len(q.split())
    valores = [(puntaje(n), n) for n in padron] if q else []
    return [n for score, n in sorted(valores, key=lambda x: (-x[0], x[1])) if score >= .6]


def ficha(n, padron):
    return {'nombre': n, 'roles': sorted(padron[n])}


def resolver_persona(valor, padron):
    n = nombre(valor)
    if n in padron:
        return n
    opciones = candidatos(valor, padron)
    if opciones:
        raise ErrorConsulta('persona_ambigua', consulta=valor,
                            candidatos=[ficha(n, padron) for n in opciones[:50]])
    raise ErrorConsulta('no_encontrado', 'Persona desconocida.', consulta=valor)


class Snapshot:
    def __init__(self, ruta):
        # mode=ro impide crear una base inexistente; query_only refuerza la intención.
        try:
            import sqlite3
            with closing(sqlite3.connect(Path(ruta).resolve().as_uri() + '?mode=ro',
                                         uri=True, timeout=3)) as con:
                con.row_factory = sqlite3.Row
                con.execute('PRAGMA query_only = ON')
                con.execute('BEGIN')
                self.clases = [dict(r) for r in con.execute(
                    'SELECT curso, division, materia, profesor, aula, dia, hora_inicio, hora_fin, '
                    'grupo, superposicion, suplente_activo, prof_suplente FROM clases')]
                self.preceptores = [dict(r) for r in con.execute(
                    'SELECT curso, division, turno, preceptor, dia FROM horarios_preceptores')]
                self.personal = [dict(r) for r in con.execute(
                    'SELECT nombre, rol, dia, hora_inicio, hora_fin FROM personal_no_docente')]
        except sqlite3.Error as e:
            raise ErrorConsulta('datos_no_disponibles', 'No se pudo leer la copia de Horarios.') from e
        if not (self.clases or self.preceptores or self.personal):
            raise ErrorConsulta('datos_no_disponibles', 'La copia de Horarios está vacía.')
        self.pisos = {p: sorted(set(datos.limpiar_aula(a) for a in aulas))
                      for p, aulas in config.FLOOR_MAPPING.items()}
        self.nominales = {curso(c, d): turno(t) for (c, d), t in config.TURNO_CURSOS.items()}
        self.cursos = sorted({curso(r['curso'], r['division'])
                              for r in self.clases + self.preceptores if str(r['curso'] or '').strip()},
                             key=lambda c: (int(c.split('°')[0]), c))
        self.aulas = sorted({datos.limpiar_aula(r['aula']) for r in self.clases if r['aula']}
                            | {a for aulas in self.pisos.values() for a in aulas})
        self.padron = {}
        def agregar(n, rol):
            n = nombre(n)
            if n and n not in VACANTES:
                self.padron.setdefault(n, set()).add(rol)
        for r in self.clases:
            agregar(r['profesor'], 'docente')
            if activo(r['suplente_activo']):
                agregar(r['prof_suplente'], 'docente')
        for r in self.personal:
            if not str(r['rol'] or '').strip():
                raise ErrorConsulta('datos_inconsistentes', 'Cargo sin identificar en la fuente.')
            agregar(r['nombre'], r['rol'].strip())
        for r in self.preceptores:
            agregar(r['preceptor'], 'preceptor')
        contenido = [sorted(self.clases, key=compacto), sorted(self.preceptores, key=compacto),
                     sorted(self.personal, key=compacto), self.pisos, self.nominales, datos._NOMBRE_MAPEOS]
        self.revision = hashlib.sha256(compacto(contenido).encode()).hexdigest()

    def seleccionar_cursos(self, p, campo='valores'):
        if 'anio' in p:
            cursos = [c for c in self.cursos if int(c.split('°')[0]) == p['anio']]
            if not cursos:
                raise ErrorConsulta('no_encontrado', 'Año sin cursos registrados.', anio=p['anio'])
            return cursos
        return list(dict.fromkeys(resolver_curso(v, self.cursos) for v in p[campo]))


def activo(valor):
    return str(valor or '').strip().lower() in ('1', 'true', 'verdadero')


def paginar(unidades, raiz, p, revision, clave, operacion, limite=MAX_ENTIDADES, contexto=None):
    """Una unidad contiene una entidad entera, incluidos todos sus días/asignaciones."""
    contexto = contexto or {}
    filtros = {k: v for k, v in p.items() if k != 'cursor'}
    huella = hashlib.sha256(compacto([operacion, filtros]).encode()).hexdigest()
    firma = URLSafeSerializer(clave, salt='horarios-consultas-v1')
    inicio = 0
    if 'cursor' in p:
        try:
            token = firma.loads(p['cursor'])
            if (token['consulta'] != huella or token['revision'] != revision
                    or token['contexto'] != contexto or type(token['pos']) is not int
                    or not 0 <= token['pos'] < len(unidades)):
                raise ValueError()
            inicio = token['pos']
        except (BadData, KeyError, TypeError, ValueError) as e:
            raise ErrorConsulta('consulta_vencida', 'Repetí la consulta desde el principio.') from e
    def armar(fin):
        salida = {k: [] for k in raiz}
        salida.update(contexto)
        for unidad in unidades[inicio:fin]:
            for k, valores in unidad.items():
                salida.setdefault(k, []).extend(valores)
        if fin < len(unidades):
            salida['siguiente'] = firma.dumps({'consulta': huella, 'revision': revision,
                                               'pos': fin, 'contexto': contexto})
        return salida
    fin, cantidad = inicio, 0
    while fin < len(unidades):
        # Los metadatos no consumen cupos de persona; sí el presupuesto de caracteres.
        peso = len(unidades[fin].get('preceptores', [])) if operacion == 'preceptores' else 1
        if cantidad + peso > limite:
            break
        if len(compacto(armar(fin + 1))) > MAX_CARACTERES:
            break
        fin += 1
        cantidad += peso
    if fin == inicio and fin < len(unidades):
        raise ErrorConsulta('consulta_demasiado_amplia', 'Una entidad excede el límite; acotá días o rango.')
    return armar(fin)
