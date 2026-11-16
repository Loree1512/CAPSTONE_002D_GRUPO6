"""Permiso del usuario en un proyecto: propietario, editor o lector.

Quien no pertenece al proyecto recibe 404; quien pertenece pero no tiene permiso
suficiente, 403. Las consultas usan el cliente del usuario, así que RLS sigue
siendo la segunda barrera.
"""

from typing import Dict, List, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from supabase import Client

from app.database.supabase import get_user_scoped_client
from app.dependencies.autenticacion import obtener_usuario_actual
from app.schemas.autenticacion import UsuarioActual
from app.schemas.proyecto import RolProyecto

TABLA_PROYECTOS = "proyectos"
TABLA_MIEMBROS = "proyecto_miembros"

# Cada rol incluye lo que pueden los anteriores.
_NIVEL = {RolProyecto.lector: 1, RolProyecto.editor: 2, RolProyecto.propietario: 3}


def proyecto_no_encontrado() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proyecto no encontrado")


def _sin_permiso() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Tu permiso en este proyecto no permite realizar esta acción.",
    )


def _a_rol(valor) -> Optional[RolProyecto]:
    try:
        return RolProyecto(valor)
    except ValueError:
        return None


def _es_creador(usuario_actual: UsuarioActual, proyecto: dict) -> bool:
    return str(proyecto.get("usuario_id")) == str(usuario_actual.id)


def rol_en_proyecto(client: Client, usuario_actual: UsuarioActual, proyecto: dict) -> Optional[RolProyecto]:
    """Rol del usuario en un proyecto ya leído; None si no pertenece."""
    # El creador es propietario aunque le falte la fila en proyecto_miembros.
    if _es_creador(usuario_actual, proyecto):
        return RolProyecto.propietario

    response = (
        client
        .table(TABLA_MIEMBROS)
        .select("rol")
        .eq("proyecto_id", str(proyecto["id"]))
        .eq("usuario_id", str(usuario_actual.id))
        .maybe_single()
        .execute()
    )
    if response is None or not response.data:
        return None
    return _a_rol(response.data.get("rol"))


def roles_en_proyectos(
    client: Client,
    usuario_actual: UsuarioActual,
    proyectos: List[dict],
) -> Dict[str, Optional[RolProyecto]]:
    """Rol del usuario en cada proyecto de un listado, con una consulta como máximo."""
    roles = {
        str(p["id"]): RolProyecto.propietario if _es_creador(usuario_actual, p) else None
        for p in proyectos
    }

    # Solo se consultan las membresías si hay proyectos creados por otro.
    if any(rol is None for rol in roles.values()):
        filas = (
            client
            .table(TABLA_MIEMBROS)
            .select("proyecto_id, rol")
            .eq("usuario_id", str(usuario_actual.id))
            .execute()
        ).data
        for fila in filas:
            if roles.get(str(fila["proyecto_id"]), True) is None:
                roles[str(fila["proyecto_id"])] = _a_rol(fila.get("rol"))

    return roles


def exigir_acceso(
    client: Client,
    usuario_actual: UsuarioActual,
    proyecto_id: UUID,
    minimo: RolProyecto = RolProyecto.lector,
) -> dict:
    """Fila del proyecto con `mi_rol`. 404 si no pertenece; 403 si su rol no alcanza."""
    response = (
        client
        .table(TABLA_PROYECTOS)
        .select("*")
        .eq("id", str(proyecto_id))
        .maybe_single()
        .execute()
    )

    # Inexistente u oculto por RLS: no se revela que existe.
    if response is None or not response.data:
        raise proyecto_no_encontrado()

    proyecto = response.data
    rol = rol_en_proyecto(client, usuario_actual, proyecto)

    if rol is None:
        raise proyecto_no_encontrado()
    if _NIVEL[rol] < _NIVEL[minimo]:
        raise _sin_permiso()

    return {**proyecto, "mi_rol": rol}


def _exigir(minimo: RolProyecto):
    def dependencia(
        proyecto_id: UUID,
        usuario_actual: UsuarioActual = Depends(obtener_usuario_actual),
    ) -> dict:
        client = get_user_scoped_client(usuario_actual.access_token)
        return exigir_acceso(client, usuario_actual, proyecto_id, minimo)

    return dependencia


# Para rutas con {proyecto_id}: devuelven el proyecto con `mi_rol`.
exigir_miembro_proyecto = _exigir(RolProyecto.lector)
exigir_editor_proyecto = _exigir(RolProyecto.editor)
exigir_propietario_proyecto = _exigir(RolProyecto.propietario)
