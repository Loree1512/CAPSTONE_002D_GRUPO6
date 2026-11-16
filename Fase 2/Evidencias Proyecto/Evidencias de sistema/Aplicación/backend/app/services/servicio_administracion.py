"""Administración global de usuarios: listar, invitar y promover a administrador.

El router ya comprobó que quien llama es administrador. El service role se usa solo
después de esa comprobación. Promover pasa por RPC (migración 005): cada aprobación,
el cambio de rol y su auditoría van en una transacción.
"""

import logging
import os
import unicodedata
from typing import Dict, List, Optional
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from postgrest.exceptions import APIError
from supabase import AuthError
from supabase_auth.errors import AuthApiError

from app.database.supabase import supabase_admin
from app.schemas.administracion import UsuarioCrear
from app.schemas.autenticacion import RolGlobal, UsuarioActual
from app.services import servicio_autenticacion
from app.services.servicio_banco import _una_fila

TABLA_PERFILES = "perfiles"
TABLA_PRINCIPALES = "administradores_principales"
TABLA_SOLICITUDES = "solicitudes_administrador"
TABLA_APROBACIONES = "aprobaciones_administrador"

# Migración 008: null mientras la persona no cree su contraseña.
COLUMNA_ACCESO = "acceso_configurado_at"

# Debe coincidir con c_requeridas de aprobar_solicitud_administrador.
APROBACIONES_REQUERIDAS = 3

MODOS_INVITACION = ("enlace", "correo")

logger = logging.getLogger(__name__)

# Códigos que lanzan las RPC de la 005.
ESTADOS_RPC = {
    "P0002": status.HTTP_404_NOT_FOUND,  # usuario o solicitud inexistente
    "42501": status.HTTP_403_FORBIDDEN,  # no es administrador o no es principal
    "22023": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "23505": status.HTTP_409_CONFLICT,  # solicitud o aprobación duplicada
    "55000": status.HTTP_409_CONFLICT,  # ya es administrador, solicitud completada, grupo incompleto
}


def _error_rpc(error: APIError) -> Exception:
    estado = ESTADOS_RPC.get(error.code or "")
    if estado is None:
        return error
    return HTTPException(status_code=estado, detail=error.message or "No se pudo completar la operación.")


def _rpc(nombre: str, parametros: dict) -> dict:
    try:
        return _una_fila(supabase_admin.rpc(nombre, parametros).execute().data)
    except APIError as error:
        raise _error_rpc(error)


# --- Configuración de invitaciones ----------------------------------------------------

def modo_invitacion() -> str:
    modo = os.getenv("INVITACION_MODO", "enlace").strip().lower()
    if modo not in MODOS_INVITACION:
        logger.warning("INVITACION_MODO desconocido (%s): se usa enlace.", modo)
        return "enlace"
    return modo


def _redireccion() -> Optional[str]:
    # Sin FRONTEND_URL, Supabase usa su Site URL.
    base = os.getenv("FRONTEND_URL", "").strip().rstrip("/")
    return f"{base}/acceso.html" if base else None


# --- Lecturas -------------------------------------------------------------------------

def _principales() -> List[str]:
    filas = (
        supabase_admin.table(TABLA_PRINCIPALES)
        .select("perfil_id, fecha_creacion")
        .order("fecha_creacion")
        .order("perfil_id")
        .execute()
    ).data
    return [str(f["perfil_id"]) for f in filas]


def _perfiles(ids: List[str]) -> Dict[str, dict]:
    ids = sorted({i for i in ids if i})
    if not ids:
        return {}
    filas = supabase_admin.table(TABLA_PERFILES).select("id, email, nombre").in_("id", ids).execute().data
    return {str(f["id"]): f for f in filas}


def _estado_perfil(perfil: dict) -> Optional[str]:
    """Activo solo después de crear su contraseña (migración 008). None: columna ausente."""
    if COLUMNA_ACCESO not in perfil:
        return None
    return "activo" if perfil[COLUMNA_ACCESO] else "pendiente"


def _estados_cuenta() -> Dict[str, str]:
    # Respaldo sin la migración 008: el estado según Supabase Auth. Si no responde, sin estado.
    try:
        usuarios = supabase_admin.auth.admin.list_users(page=1, per_page=1000)
    except (AuthError, httpx.RequestError) as error:
        logger.warning("No se pudo leer el estado de las cuentas: %s", type(error).__name__)
        return {}
    return {
        str(u.id): "activo" if (u.email_confirmed_at or u.confirmed_at) else "pendiente"
        for u in usuarios
    }


def _armar_solicitudes(filas: List[dict], actor_id: str) -> List[dict]:
    if not filas:
        return []
    ids = [str(f["id"]) for f in filas]
    aprobaciones = (
        supabase_admin.table(TABLA_APROBACIONES)
        .select("solicitud_id, administrador_id, fecha")
        .in_("solicitud_id", ids)
        .execute()
    ).data
    principales = _principales()
    perfiles = _perfiles(principales + [str(f["usuario_id"]) for f in filas])

    solicitudes = []
    for fila in filas:
        votos = {str(a["administrador_id"]): a.get("fecha")
                 for a in aprobaciones if str(a["solicitud_id"]) == str(fila["id"])}
        objetivo = perfiles.get(str(fila["usuario_id"]), {})
        pendiente = fila["estado"] == "pendiente"
        solicitudes.append({
            "id": fila["id"],
            "usuario_id": fila["usuario_id"],
            "usuario_nombre": objetivo.get("nombre"),
            "usuario_email": objetivo.get("email"),
            "solicitado_por": fila.get("solicitado_por"),
            "estado": fila["estado"],
            "fecha_creacion": fila["fecha_creacion"],
            "fecha_resolucion": fila.get("fecha_resolucion"),
            "aprobaciones_recibidas": len(votos),
            "aprobaciones_requeridas": APROBACIONES_REQUERIDAS,
            "aprobaciones": [
                {
                    "administrador_id": p,
                    "nombre": perfiles.get(p, {}).get("nombre"),
                    "email": perfiles.get(p, {}).get("email"),
                    "aprobada": p in votos,
                    "fecha": votos.get(p),
                }
                for p in principales
            ],
            "puedo_aprobar": (pendiente and actor_id in principales and actor_id not in votos
                              and actor_id != str(fila["usuario_id"])),
        })
    return solicitudes


def _pendientes(actor_id: str) -> List[dict]:
    filas = (
        supabase_admin.table(TABLA_SOLICITUDES)
        .select("*")
        .eq("estado", "pendiente")
        .order("fecha_creacion")
        .execute()
    ).data
    return _armar_solicitudes(filas, actor_id)


def _usuario(perfil: dict, principales: List[str], estados: Dict[str, str], pendiente: Optional[dict]) -> dict:
    rol = perfil.get("rol_global") or RolGlobal.profesional.value
    return {
        "id": perfil["id"],
        "email": perfil.get("email"),
        "nombre": perfil.get("nombre"),
        "rol_global": rol,
        "es_administrador_principal": str(perfil["id"]) in principales,
        "fecha_creacion": perfil.get("fecha_creacion"),
        "estado": _estado_perfil(perfil) or estados.get(str(perfil["id"])),
        "solicitud_pendiente": pendiente,
        "puede_solicitar_administrador": rol == RolGlobal.profesional.value and pendiente is None,
    }


def listar_usuarios(admin: UsuarioActual) -> List[dict]:
    perfiles = (
        supabase_admin.table(TABLA_PERFILES)
        .select("*")
        .execute()
    ).data
    principales = _principales()
    pendientes = {str(s["usuario_id"]): s for s in _pendientes(str(admin.id))}
    estados = _estados_cuenta() if any(COLUMNA_ACCESO not in p for p in perfiles) else {}

    usuarios = [_usuario(p, principales, estados, pendientes.get(str(p["id"]))) for p in perfiles]

    # Principales primero, luego administradores y profesionales; dentro, por nombre sin tildes.
    def orden(u):
        grupo = 0 if u["es_administrador_principal"] else 1 if u["rol_global"] == RolGlobal.administrador.value else 2
        texto = unicodedata.normalize("NFKD", u["nombre"] or u["email"] or "")
        return grupo, "".join(c for c in texto if not unicodedata.combining(c)).lower()

    return sorted(usuarios, key=orden)


def listar_solicitudes(admin: UsuarioActual) -> List[dict]:
    return _pendientes(str(admin.id))


# --- Crear usuario --------------------------------------------------------------------

def _correo_registrado(email: str) -> bool:
    filas = supabase_admin.table(TABLA_PERFILES).select("id, email").execute().data
    return any((f.get("email") or "").strip().lower() == email for f in filas)


def _opciones_invitacion(nombre: Optional[str] = None) -> dict:
    opciones: dict = {}
    if nombre is not None:
        opciones["data"] = {"nombre": nombre}
    redireccion = _redireccion()
    if redireccion:
        opciones["redirect_to"] = redireccion
    return opciones


def _invitar(email: str, modo: str, opciones: dict):
    """(usuario de Auth, enlace). El enlace solo existe en modo enlace.

    Con un usuario existente y sin confirmar, Supabase Auth reemplaza el token (el enlace
    anterior deja de servir) y no toca su metadata; con uno confirmado responde 422.
    """
    if modo == "correo":
        return supabase_admin.auth.admin.invite_user_by_email(email, opciones).user, None
    respuesta = supabase_admin.auth.admin.generate_link({"type": "invite", "email": email, "options": opciones})
    return respuesta.user, respuesta.properties.action_link


def _error_auth(error: Exception, accion: str, conflicto: str, rechazo: str) -> HTTPException:
    # Solo el tipo y el estado: nada que pueda llevar el enlace o el correo.
    estado = getattr(error, "status", None)
    if isinstance(error, AuthApiError) and estado == 429:
        logger.warning("Supabase Auth limitó %s: %s", accion, type(error).__name__)
        return HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                             detail="Supabase limitó el envío de invitaciones. Espera unos minutos.")
    if servicio_autenticacion.es_transitorio(error):
        logger.warning("Supabase Auth no disponible al %s: %s", accion, type(error).__name__)
        return servicio_autenticacion.auth_no_disponible()
    logger.warning("Supabase Auth rechazó %s: %s %s", accion, type(error).__name__, estado)
    if isinstance(error, AuthApiError) and (estado == 422 or "registered" in (error.message or "").lower()):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=conflicto)
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=rechazo)


def _crear_en_auth(email: str, nombre: str, modo: str):
    try:
        return _invitar(email, modo, _opciones_invitacion(nombre))
    except (AuthError, httpx.RequestError) as error:
        raise _error_auth(error, "crear un usuario", "Ya existe un usuario con ese correo.",
                          "Supabase Auth no pudo crear el usuario. Revisa el correo.") from error


def crear_usuario(admin: UsuarioActual, datos: UsuarioCrear) -> dict:
    email = datos.email.strip().lower()
    if _correo_registrado(email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe un usuario con ese correo.")

    modo = modo_invitacion()
    usuario_auth, enlace = _crear_en_auth(email, datos.nombre, modo)

    perfil = {"id": str(usuario_auth.id), "email": email, "nombre": datos.nombre,
              "rol_global": RolGlobal.profesional.value, "fecha_creacion": None, COLUMNA_ACCESO: None}
    try:
        perfil = _rpc("registrar_usuario_creado", {
            "p_actor_id": str(admin.id),
            "p_usuario_id": str(usuario_auth.id),
            "p_nombre": datos.nombre,
            "p_modo": modo,
        })
    except Exception as error:
        # La cuenta ya existe en Auth: se responde igual para no perder el enlace.
        logger.error("Usuario %s creado sin registrar nombre ni auditoría: %s",
                     usuario_auth.id, getattr(error, "detail", type(error).__name__))

    return {
        "usuario": _usuario(perfil, [], {str(usuario_auth.id): "pendiente"}, None),
        "modo": modo,
        "enlace": enlace,
    }


# --- Renovar invitación -----------------------------------------------------------------

YA_ACTIVO = "La cuenta ya está activa: no tiene una invitación pendiente."


def _cuenta_en_auth(usuario_id: str):
    try:
        return supabase_admin.auth.admin.get_user_by_id(usuario_id).user
    except (AuthError, httpx.RequestError) as error:
        if isinstance(error, AuthApiError) and getattr(error, "status", None) == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El usuario no existe.") from error
        raise _error_auth(error, "leer una cuenta", YA_ACTIVO,
                          "Supabase Auth no pudo leer la cuenta.") from error


def _recuperacion(email: str, modo: str, opciones: dict) -> Optional[str]:
    """Para una cuenta que ya abrió un enlace (Auth la confirmó) pero no creó su contraseña:
    invite ya no aplica, así que se usa un enlace de recuperación. Lleva al mismo formulario."""
    if modo == "correo":
        supabase_admin.auth.reset_password_for_email(email, {"redirect_to": opciones["redirect_to"]}
                                                     if "redirect_to" in opciones else {})
        return None
    respuesta = supabase_admin.auth.admin.generate_link({"type": "recovery", "email": email, "options": opciones})
    return respuesta.properties.action_link


def _renovar_en_auth(email: str, modo: str, confirmada: bool) -> Optional[str]:
    # Sin data: la metadata de la cuenta no cambia.
    opciones = _opciones_invitacion()
    if not confirmada:
        try:
            return _invitar(email, modo, opciones)[1]
        except AuthApiError as error:
            # 422: abrió el enlace entre la lectura y este paso; Auth ya la confirmó.
            if getattr(error, "status", None) != 422:
                raise
    return _recuperacion(email, modo, opciones)


def renovar_invitacion(admin: UsuarioActual, usuario_id: UUID) -> dict:
    """Enlace nuevo mientras la persona no haya creado su contraseña. Misma cuenta, perfil y rol.

    Supabase reemplaza el token al generar otro enlace: solo el último sirve.
    """
    uid = str(usuario_id)
    filas = supabase_admin.table(TABLA_PERFILES).select("*").eq("id", uid).execute().data
    perfil = filas[0] if filas else None
    if not perfil:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El usuario no existe.")

    cuenta = _cuenta_en_auth(uid)
    if cuenta is None or not cuenta.email:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El usuario no existe.")
    confirmada = bool(cuenta.email_confirmed_at or cuenta.confirmed_at)

    # Activo = creó su contraseña. Abrir el enlace no basta. Sin la 008, se usa Auth.
    estado = _estado_perfil(perfil) or ("activo" if confirmada else "pendiente")
    if estado == "activo":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=YA_ACTIVO)

    modo = modo_invitacion()
    try:
        enlace = _renovar_en_auth(cuenta.email, modo, confirmada)
    except (AuthError, httpx.RequestError) as error:
        raise _error_auth(error, "renovar una invitación", YA_ACTIVO,
                          "Supabase Auth no pudo renovar la invitación.") from error

    try:
        _rpc("registrar_invitacion_renovada", {"p_actor_id": str(admin.id), "p_usuario_id": uid, "p_modo": modo})
    except Exception as error:
        # El enlace ya es válido: se entrega igual.
        logger.error("Invitación de %s renovada sin auditoría: %s", uid, getattr(error, "detail", type(error).__name__))

    principales = _principales()
    pendiente = next((s for s in _pendientes(str(admin.id)) if str(s["usuario_id"]) == uid), None)
    return {
        "usuario": _usuario({**perfil, COLUMNA_ACCESO: None}, principales, {}, pendiente),
        "modo": modo,
        "enlace": enlace,
    }


def configuracion() -> dict:
    return {"modo_invitacion": modo_invitacion()}


# --- Promoción a administrador ----------------------------------------------------------

def solicitar_administrador(admin: UsuarioActual, usuario_id: UUID) -> dict:
    fila = _rpc("solicitar_administrador", {"p_actor_id": str(admin.id), "p_usuario_id": str(usuario_id)})
    return _armar_solicitudes([fila], str(admin.id))[0]


def aprobar_solicitud(admin: UsuarioActual, solicitud_id: UUID) -> dict:
    fila = _rpc("aprobar_solicitud_administrador", {"p_actor_id": str(admin.id), "p_solicitud_id": str(solicitud_id)})
    return _armar_solicitudes([fila], str(admin.id))[0]
