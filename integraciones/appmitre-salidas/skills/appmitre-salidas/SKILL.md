---
name: appmitre-salidas
description: Consultá los anexos de Salidas Educativas y creá o editá legajos con datos confirmados de la Técnica Emilio Mitre.
---

Usá las herramientas MCP de AppMitre Salidas.

1. Consultá `listar_anexos`. Leé el Anexo I para requisitos e instructivo, el II para plazos y responsables y, uno por uno, los anexos III a IX que correspondan. Citá el anexo que respalda lo que indiques.
2. Si hace falta acceso, indicá conectar AppMitre y autorizar en su pantalla de Salidas. Las credenciales se ingresan en AppMitre.
3. Usá `esquema_legajo` para saber qué campos cargar. Usá información aportada o confirmada por la persona. Las fechas usan AAAA-MM-DD y las horas HH:MM. Dejá vacíos los datos que falten. Las firmas, autorizaciones y declaraciones corresponden a sus responsables.
4. Para crear, comprobá con `buscar_salidas` si el proyecto ya existe. Usá `crear_salida` con un identificador de operación único. Reutilizalo al reintentar la misma creación.
5. Para editar, buscá el ID, llamá a `consultar_salida` y usá la revisión devuelta en `editar_salida`. Mandá sólo los campos que cambian. Para modificar la nómina, conservá las personas y los datos existentes que no cambien.

Crear y editar guardan el legajo en AppMitre. Compartí el enlace devuelto para revisarlo. Si la persona pide una propuesta sin guardar, usá `consultar_campos` y `rellenar_formulario` con el código de su pestaña de edición.
