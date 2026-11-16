from typing import List, Optional
from uuid import UUID

from supabase import Client

from app.database.supabase import get_user_scoped_client
from app.dependencies import permisos_proyecto
from app.schemas.autenticacion import UsuarioActual
from app.schemas.proyecto import ProyectoActualizar, ProyectoCrear, RolProyecto
from app.services import servicio_historial, servicio_plantillas
from app.services.resumen_proyecto import COLUMNAS_FIRMA, COLUMNAS_ULTIMA_ESTIMACION, con_resumen

NOMBRE_TABLA = "proyectos"

# Cada proyecto trae su última estimación (límite por proyecto) y lo justo de
# sus partidas para saber si cambiaron desde entonces.
SELECT_CON_RESUMEN = (
    f"*, estimaciones({COLUMNAS_ULTIMA_ESTIMACION}), proyecto_partidas({COLUMNAS_FIRMA})"
)


def _con_ultima_estimacion(consulta):
    # id desc desempata dos estimaciones con la misma fecha.
    return (
        consulta
        .order("fecha_creacion", desc=True, foreign_table="estimaciones")
        .order("id", desc=True, foreign_table="estimaciones")
        .limit(1, foreign_table="estimaciones")
    )


def _version_vigente_id(client: Client) -> Optional[str]:
    response = (
        client
        .table("versiones_precios")
        .select("id")
        .eq("vigente", True)
        .limit(1)
        .execute()
    )
    return response.data[0]["id"] if response.data else None


def crear_proyecto(usuario_actual: UsuarioActual, proyecto: ProyectoCrear) -> dict:
    client = get_user_scoped_client(usuario_actual.access_token)

    payload = proyecto.model_dump(mode="json")
    # usuario_id viene del token, no del cliente: evita crear proyectos a nombre de otro.
    payload["usuario_id"] = str(usuario_actual.id)

    # Partidas iniciales desde la plantilla de tipo de obra + materialidad.
    plantilla = servicio_plantillas.buscar_vigente(client, payload["tipo_obra"], payload["materialidad"])

    if plantilla is None:
        # Sin plantilla, el proyecto nace con la lista vacía.
        creado = client.table(NOMBRE_TABLA).insert(payload).execute().data[0]
    else:
        # Proyecto y partidas en una transacción: si falla la copia, no queda nada a medias.
        creado = servicio_plantillas.crear_proyecto_con_plantilla(client, payload, plantilla["id"])

    # Recién creado: todavía no tiene estimaciones. Quien lo crea es su propietario.
    return {**con_resumen(creado, None), "mi_rol": RolProyecto.propietario}


def obtener_proyectos(usuario_actual: UsuarioActual) -> List[dict]:
    client = get_user_scoped_client(usuario_actual.access_token)

    # RLS deja ver solo los proyectos del usuario: no hace falta filtrar a mano.
    response = _con_ultima_estimacion(
        client
        .table(NOMBRE_TABLA)
        .select(SELECT_CON_RESUMEN)
        .order("fecha_creacion", desc=True)
    ).execute()

    roles = permisos_proyecto.roles_en_proyectos(client, usuario_actual, response.data)
    vigente = _version_vigente_id(client)
    return [
        {**con_resumen(fila, vigente), "mi_rol": roles[str(fila["id"])]}
        for fila in response.data
        if roles[str(fila["id"])] is not None
    ]


def leer_proyecto(
    usuario_actual: UsuarioActual,
    proyecto_id: UUID,
    minimo: RolProyecto = RolProyecto.lector,
) -> dict:
    """Fila de proyectos sin resumen, con `mi_rol`. Valida el permiso mínimo pedido.

    Quien no pertenece al proyecto recibe 404; con un rol menor al pedido, 403.
    """
    client = get_user_scoped_client(usuario_actual.access_token)
    return permisos_proyecto.exigir_acceso(client, usuario_actual, proyecto_id, minimo)


def obtener_proyecto_por_id(usuario_actual: UsuarioActual, proyecto_id: UUID) -> dict:
    client = get_user_scoped_client(usuario_actual.access_token)

    response = _con_ultima_estimacion(
        client
        .table(NOMBRE_TABLA)
        .select(SELECT_CON_RESUMEN)
        .eq("id", str(proyecto_id))
    ).maybe_single().execute()

    # Inexistente u oculto por RLS: 404.
    if response is None or not response.data:
        raise permisos_proyecto.proyecto_no_encontrado()

    rol = permisos_proyecto.rol_en_proyecto(client, usuario_actual, response.data)
    if rol is None:
        raise permisos_proyecto.proyecto_no_encontrado()

    return {**con_resumen(response.data, _version_vigente_id(client)), "mi_rol": rol}


def actualizar_proyecto(usuario_actual: UsuarioActual, proyecto_id: UUID, proyecto: ProyectoActualizar) -> dict:
    client = get_user_scoped_client(usuario_actual.access_token)

    # Editar los datos del proyecto exige ser propietario o editor.
    actual = leer_proyecto(usuario_actual, proyecto_id, RolProyecto.editor)

    payload = proyecto.model_dump(mode="json", exclude_unset=True)

    if payload:
        response = (
            client
            .table(NOMBRE_TABLA)
            .update(payload)
            .eq("id", str(proyecto_id))
            .execute()
        )

        if not response.data:
            raise permisos_proyecto.proyecto_no_encontrado()

        anteriores, nuevos = servicio_historial.diferencias(actual, payload, payload.keys())
        if nuevos:
            servicio_historial.registrar(usuario_actual, proyecto_id, "proyecto_editado", "proyecto",
                                         proyecto_id, anteriores, nuevos)

    # Se relee con el resumen: editar puede dejar la estimación por recalcular.
    return obtener_proyecto_por_id(usuario_actual, proyecto_id)


def eliminar_proyecto(usuario_actual: UsuarioActual, proyecto: dict) -> None:
    """Elimina el proyecto; las relaciones dependientes se borran en cascada."""
    client = get_user_scoped_client(usuario_actual.access_token)

    response = (
        client
        .table(NOMBRE_TABLA)
        .delete()
        .eq("id", str(proyecto["id"]))
        .execute()
    )

    # Cero filas: ya no existe o RLS lo rechazó.
    if not response.data:
        raise permisos_proyecto.proyecto_no_encontrado()
