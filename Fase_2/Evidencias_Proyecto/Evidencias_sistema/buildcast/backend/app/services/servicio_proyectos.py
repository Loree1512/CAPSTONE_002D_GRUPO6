from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from supabase import Client

from app.database.supabase import get_user_scoped_client
from app.schemas.autenticacion import UsuarioActual
from app.schemas.proyecto import ProyectoActualizar, ProyectoCrear
from app.services import servicio_plantillas
from app.services.resumen_proyecto import COLUMNAS_FIRMA, COLUMNAS_ULTIMA_ESTIMACION, con_resumen

NOMBRE_TABLA = "proyectos"

# Cada proyecto trae su última estimación (límite por proyecto) y lo justo de
# sus partidas para saber si cambiaron desde entonces.
SELECT_CON_RESUMEN = (
    f"*, estimaciones({COLUMNAS_ULTIMA_ESTIMACION}), proyecto_partidas({COLUMNAS_FIRMA})"
)


def _no_encontrado() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Proyecto no encontrado"
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

    # Recién creado: todavía no tiene estimaciones.
    return con_resumen(creado, None)


def obtener_proyectos(usuario_actual: UsuarioActual) -> List[dict]:
    client = get_user_scoped_client(usuario_actual.access_token)

    # RLS filtra proyectos y estimaciones por dueño: no hace falta filtrar a mano.
    response = _con_ultima_estimacion(
        client
        .table(NOMBRE_TABLA)
        .select(SELECT_CON_RESUMEN)
        .order("fecha_creacion", desc=True)
    ).execute()

    vigente = _version_vigente_id(client)
    return [con_resumen(fila, vigente) for fila in response.data]


def leer_proyecto(usuario_actual: UsuarioActual, proyecto_id: UUID) -> dict:
    """Fila de proyectos sin resumen, para validar dueño y leer sus datos."""
    client = get_user_scoped_client(usuario_actual.access_token)

    response = (
        client
        .table(NOMBRE_TABLA)
        .select("*")
        .eq("id", str(proyecto_id))
        .maybe_single()
        .execute()
    )

    # RLS oculta proyectos ajenos: responden 404, no 403.
    if response is None or not response.data:
        raise _no_encontrado()

    return response.data


def obtener_proyecto_por_id(usuario_actual: UsuarioActual, proyecto_id: UUID) -> dict:
    client = get_user_scoped_client(usuario_actual.access_token)

    response = _con_ultima_estimacion(
        client
        .table(NOMBRE_TABLA)
        .select(SELECT_CON_RESUMEN)
        .eq("id", str(proyecto_id))
    ).maybe_single().execute()

    # RLS oculta proyectos ajenos: responden 404, no 403.
    if response is None or not response.data:
        raise _no_encontrado()

    return con_resumen(response.data, _version_vigente_id(client))


def actualizar_proyecto(usuario_actual: UsuarioActual, proyecto_id: UUID, proyecto: ProyectoActualizar) -> dict:
    client = get_user_scoped_client(usuario_actual.access_token)

    # Valida existencia y dueño vía RLS antes de actualizar.
    leer_proyecto(usuario_actual, proyecto_id)

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
            raise _no_encontrado()

    # Se relee con el resumen: editar puede dejar la estimación por recalcular.
    return obtener_proyecto_por_id(usuario_actual, proyecto_id)
