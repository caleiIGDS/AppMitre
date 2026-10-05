// El menú ☰: las áreas del sistema. Las que todavía no pasaron a la app abren su página
// del servidor: `ruta` es de la app, `href` es una página del servidor. `bp` es el área
// que tiene que estar montada en el servidor (/app/api/sesion lo informa) para que el link
// no lleve a un 404.

export const AREAS = [
  {
    clave: 'gestion', bp: 'gestion', nombre: 'Gestión de recursos', permiso: null,
    descripcion: 'Inventarios técnicos: recursos, ubicaciones, kits, bajas y fotos.',
    ruta: { name: 'inventarios' },
  },
  {
    clave: 'agente', bp: 'agente', nombre: 'Asistente', permiso: 'agente.leer',
    descripcion: 'Chat para consultar y cargar datos.', href: '/agente/',
  },
  {
    clave: 'salidas', bp: 'salidas', nombre: 'Salidas educativas', permiso: 'salidas.leer',
    descripcion: 'Legajo digital de cada salida y sus anexos.', href: '/salidas/',
  },
  {
    clave: 'accesos', bp: 'accesos', nombre: 'Accesos', permiso: 'accesos.admin',
    descripcion: 'Invitar y revocar dispositivos.', href: '/accesos/',
  },
]

export function areasVisibles(areasMontadas, puede) {
  return AREAS.filter((a) => areasMontadas.includes(a.bp) && (a.permiso === null || puede(a.permiso)))
}
