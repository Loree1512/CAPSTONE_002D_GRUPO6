"""Miembros del proyecto: quién lo integra y con qué permiso.

Los permisos llegan resueltos desde el router (exigir_miembro_proyecto /
exigir_propietario_proyecto) y el service role se usa solo después de esa
comprobación. Agregar, cambiar y quitar pasan por RPC que hacen el cambio y
anexan su evento al historial en una sola transacción; la tabla no se escribe
de otra forma (migración 003).
"""

from typing import Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from postgrest.exceptions import APIError

from app.database.supabase import supabase_admin
from app.schemas.autenticacion import UsuarioActual
from app.schemas.miembro import MiembroAgregar, MiembroCambiarRol
from app.schemas.proyecto import RolProyecto
from app.services.servicio_banco import _una_fila

TABLA = "proyecto_miembros"
TABLA_PERFILES = "perfiles"

COLUMNAS = "usuario_id, rol, fecha_creacion"
LIMITE_CANDIDATOS = 20

_ORDEN = {RolProyecto.propietario.value: 0, RolProyecto.editor.value: 1, RolProyecto.lector.value: 2}

# Códigos que lanzan las RPC de miembros.
ESTADOS_RPC = {
    "P0002": status.HTTP_404_NOT_FOUND,  # proyecto, correo o miembro inexistente
    "42501": status.HTTP_403_FORBIDDEN,  # quien llama no es propietario
    "22023": status.HTTP_422_UNPROCESSABLE_CONTENT,  # permiso distinto de editor o lector
    "23505": status.HTTP_409_CONFLICT,  # ya es miembro
    "55000": status.HTTP_409_CONFLICT,  # el propietario no cambia ni se quita
}


def _error_rpc(error: APIError) -> Exception:
    # Errores sin mapeo se relanzan: son fallas reales y deben verse como 500.
    estado = ESTADOS_RPC.get(error.code or "")
    if estado is None:
        return error
    # El unique de la tabla responde en inglés; las RPC, en español.
    detalle = "El usuario ya es miembro del proyecto." if error.code == "23505" else error.message
    return HTTPException(status_code=estado, detail=detalle or "No se pudo completar la operación.")


def _rpc(nombre: str, parametros: dict):
    try:
        return supabase_admin.rpc(nombre, parametros).execute().data
    except APIError as error:
        raise _error_rpc(error)


def _perfiles(ids: List[str]) -> Dict[str, dict]:
    if not ids:
        return {}
    filas = supabase_admin.table(TABLA_PERFILES).select("id, email, nombre").in_("id", ids).execute().data
    return {f["id"]: f for f in filas}


def _a_respuesta(fila: dict, perfil: Optional[dict]) -> dict:
    perfil = perfil or {}
    return {
        "usuario_id": fila["usuario_id"],
        "email": perfil.get("email"),
        "nombre": perfil.get("nombre"),
        "rol": fila["rol"],
        "fecha_creacion": fila.get("fecha_creacion"),
    }


# --- Operaciones ---------------------------------------------------------------------

def listar(proyecto: dict) -> List[dict]:
    # Con service role: RLS no muestra los miembros a un creador sin fila propia.
    filas = supabase_admin.table(TABLA).select(COLUMNAS).eq("proyecto_id", str(proyecto["id"])).execute().data

    # El creador es propietario aunque le falte la fila.
    creador = proyecto.get("usuario_id")
    if creador and not any(str(f["usuario_id"]) == str(creador) for f in filas):
        filas.append({"usuario_id": creador, "rol": RolProyecto.propietario.value})

    perfiles = _perfiles([str(f["usuario_id"]) for f in filas])
    miembros = [_a_respuesta(f, perfiles.get(str(f["usuario_id"]))) for f in filas]
    return sorted(miembros, key=lambda m: (_ORDEN.get(m["rol"], 9), m["email"] or ""))


def candidatos(proyecto: dict, buscar: Optional[str] = None) -> List[dict]:
    """Usuarios registrados que se pueden agregar. El router ya exigió ser propietario."""
    actuales = {
        str(f["usuario_id"])
        for f in supabase_admin.table(TABLA).select("usuario_id").eq("proyecto_id", str(proyecto["id"])).execute().data
    }
    if proyecto.get("usuario_id"):
        actuales.add(str(proyecto["usuario_id"]))

    # Se filtra aquí y no con ilike: el texto llega tal cual, sin comodines ni sintaxis de PostgREST.
    texto = (buscar or "").strip().casefold()
    filas = supabase_admin.table(TABLA_PERFILES).select("id, email, nombre").execute().data
    elegibles = [
        {"usuario_id": f["id"], "nombre": f.get("nombre"), "email": f["email"]}
        for f in filas
        if (f.get("email") or "").strip() and str(f["id"]) not in actuales
        and (not texto or texto in (f.get("nombre") or "").casefold() or texto in f["email"].casefold())
    ]
    elegibles.sort(key=lambda c: ((c["nombre"] or c["email"]).casefold(), c["email"].casefold()))
    return elegibles[:LIMITE_CANDIDATOS]


def agregar(propietario: UsuarioActual, proyecto: dict, datos: MiembroAgregar) -> dict:
    # Correo exacto (sin distinguir mayúsculas): no hay búsqueda ni listado de usuarios.
    return _una_fila(_rpc("agregar_miembro_proyecto", {
        "p_solicitante_id": str(propietario.id),
        "p_proyecto_id": str(proyecto["id"]),
        "p_email": datos.email,
        "p_rol": datos.rol.value,
    }))


def cambiar_rol(propietario: UsuarioActual, proyecto: dict, usuario_id: UUID, datos: MiembroCambiarRol) -> dict:
    return _una_fila(_rpc("cambiar_rol_miembro_proyecto", {
        "p_solicitante_id": str(propietario.id),
        "p_proyecto_id": str(proyecto["id"]),
        "p_usuario_id": str(usuario_id),
        "p_rol": datos.rol.value,
    }))


def quitar(propietario: UsuarioActual, proyecto: dict, usuario_id: UUID) -> None:
    _rpc("quitar_miembro_proyecto", {
        "p_solicitante_id": str(propietario.id),
        "p_proyecto_id": str(proyecto["id"]),
        "p_usuario_id": str(usuario_id),
    })
