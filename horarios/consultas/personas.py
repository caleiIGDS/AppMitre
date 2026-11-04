from .comun import MAX_PERSONAS, candidatos, ficha, nombre, norm, paginar


def ejecutar(s, p, clave):
    conocidos = s.padron
    if p.get('multiples_roles'):
        conocidos = {n: r for n, r in conocidos.items() if len(r) > 1}
    if 'rol' in p:
        conocidos = {n: r for n, r in conocidos.items() if any(norm(p['rol']) in norm(rol) for rol in r)}
    if 'nombre' in p:
        exacto = nombre(p['nombre'])
        nombres = [exacto] if exacto in conocidos else candidatos(p['nombre'], conocidos)
    else:
        nombres = sorted(conocidos)
    return paginar([{'personas': [ficha(n, s.padron)]} for n in nombres], ['personas'], p,
                   s.revision, clave, 'personas', MAX_PERSONAS)
