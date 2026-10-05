// Las áreas del sistema y dónde vive cada una. Mientras dura la migración, las que todavía
// no pasaron a la app abren su versión clásica (página del servidor): `ruta` es de la app,
// `href` es una página clásica.

export const AREAS = [
  {
    clave: 'gestion', nombre: 'Gestión de recursos', permiso: 'gestion.leer',
    descripcion: 'Inventario técnico: recursos, ubicaciones, kits y fotos.',
    ruta: { name: 'inventario' },
    pestanas: [
      { nombre: 'INVENTARIO', ruta: { name: 'inventario' }, activa: ['inventario', 'recurso', 'recurso-nuevo', 'recurso-editar'] },
      { nombre: 'ALIAS', ruta: { name: 'alias' }, activa: ['alias'], permiso: 'gestion.alias' },
    ],
  },
  {
    clave: 'historia', nombre: 'Historia institucional', permiso: 'historia.leer',
    descripcion: 'Línea del tiempo: hitos y las personas que hicieron la escuela.',
    href: '/historia/',
  },
  {
    clave: 'salidas', nombre: 'Salidas educativas', permiso: 'salidas.leer',
    descripcion: 'Legajo digital de cada salida y sus anexos.',
    href: '/salidas/',
  },
  {
    clave: 'agente', nombre: 'Asistente', permiso: 'agente.leer',
    descripcion: 'Chat para consultar y cargar datos.',
    href: '/agente/',
  },
  {
    clave: 'horarios', nombre: 'Horarios', permiso: null,
    descripcion: 'Horarios por curso, profesor y aula. Público.',
    href: '/',
  },
  {
    clave: 'accesos', nombre: 'Accesos', permiso: 'accesos.admin',
    descripcion: 'Invitar y revocar dispositivos.',
    href: '/accesos/',
  },
]

export function areaPorClave(clave) {
  return AREAS.find((a) => a.clave === clave) || null
}
