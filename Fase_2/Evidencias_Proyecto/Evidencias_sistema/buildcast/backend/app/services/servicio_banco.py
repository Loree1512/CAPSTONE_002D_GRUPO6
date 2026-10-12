from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from postgrest.exceptions import APIError
from supabase import Client

from app.database.supabase import get_user_scoped_client, supabase_admin
from app.schemas.autenticacion import UsuarioActual
from app.schemas.banco import PartidaCrear, PartidaEditar, PrecioEditar, VersionPreciosCrear

TABLA_CATEGORIAS = "categorias_partida"
TABLA_VERSIONES = "versiones_precios"
TABLA_PARTIDAS = "partidas"
TABLA_PRECIOS = "precios_partida"

COLUMNAS_PARTIDA = "id, categoria_id, codigo, nombre, unidad, es_base, vigente"

# Un valor editado por la oficina deja de ser una referencia de mercado.

MENSAJE_UNIDAD_CON_PRECIOS = (
    "La partida ya tiene precios cargados en el banco, expresados en su unidad actual. "
    "Para usar otra unidad, da de baja esta partida y crea una nueva con la unidad correcta."
)
FUENTE_EDICION = "Editado por la oficina"

# Códigos de PostgreSQL (y de las RPCs) que tienen una respuesta HTTP clara.
ESTADOS_POR_CODIGO = {
    "P0002": status.HTTP_404_NOT_FOUND,  # raise ... using errcode = 'P0002'
    "22023": status.HTTP_422_UNPROCESSABLE_CONTENT,  # parámetro inválido en RPC
    "23514": status.HTTP_422_UNPROCESSABLE_CONTENT,  # check violado
    "23505": status.HTTP_409_CONFLICT,  # unique violado
    "23503": status.HTTP_409_CONFLICT,  # FK violada
}


# PostgreSQL da estos errores en inglés; las RPCs ya los lanzan en español.
MENSAJES_POR_DEFECTO = {
    "23514": "Los datos no cumplen las reglas del banco de precios.",
    "23505": "El registro ya existe.",
    "23503": "El registro está relacionado con otro que no existe o que lo utiliza.",
}


def _error_http(error: APIError, mensajes: Optional[dict] = None) -> Exception:
    # Errores sin mapeo se relanzan: son fallas reales y deben verse como 500.
    estado = ESTADOS_POR_CODIGO.get(error.code or "")
    if estado is None:
        return error

    detalle = (
        (mensajes or {}).get(error.code)
        or MENSAJES_POR_DEFECTO.get(error.code)
        or error.message
        or "No se pudo completar la operación."
    )
    return HTTPException(status_code=estado, detail=detalle)


def _no_encontrado(detalle: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detalle)


def _una_fila(data) -> dict:
    # Una RPC que devuelve un compuesto llega como objeto; se toleran ambas formas.
    return data[0] if isinstance(data, list) else data


# --- Mapeos a la forma que espera el frontend -----------------------------------

def estado_version(fila: dict) -> str:
    """borrador (editable), vigente o historica (publicadas: no se editan)."""
    if fila["vigente"]:
        return "vigente"
    return "historica" if fila.get("fecha_publicacion") else "borrador"


def _a_version(fila: dict) -> dict:
    return {
        "id": fila["id"],
        "version": fila["version"],
        "trimestre": fila.get("trimestre"),
        "fuente": fila.get("fuente"),
        "vigente": fila["vigente"],
        "cargado_en": fila.get("fecha_carga"),
        "fecha_publicacion": fila.get("fecha_publicacion"),
        "estado": estado_version(fila),
    }


def _a_partida(fila: dict) -> dict:
    return {
        "id": fila["id"],
        "categoria_id": fila["categoria_id"],
        "codigo": fila["codigo"],
        "nombre": fila["nombre"],
        "unidad": fila["unidad"],
        "es_base": fila["es_base"],
        "vigente": fila["vigente"],
    }


def _a_fila_banco(partida: dict, precio: Optional[dict], tiene_precios: bool = False) -> dict:
    precio = precio or {}
    return {
        **_a_partida(partida),
        "precio_unitario": precio.get("precio_unitario"),
        "rendimiento_mo": precio.get("rendimiento_mo"),
        "fuente": precio.get("fuente"),
        "tiene_precios": tiene_precios,
    }


def _con_precios(client: Client) -> set:
    # Vista de la 005: una fila por partida con precio en alguna versión.
    response = client.table("partidas_con_precios").select("partida_id").execute()
    return {fila["partida_id"] for fila in response.data}


def _tiene_precios(client: Client, partida_id) -> bool:
    response = (
        client
        .table(TABLA_PRECIOS)
        .select("partida_id")
        .eq("partida_id", str(partida_id))
        .limit(1)
        .execute()
    )
    return bool(response.data)


# --- Consultas de apoyo ---------------------------------------------------------

def _obtener_version(client: Client, version_id: UUID) -> dict:
    response = (
        client
        .table(TABLA_VERSIONES)
        .select("*")
        .eq("id", str(version_id))
        .maybe_single()
        .execute()
    )

    if response is None or not response.data:
        raise _no_encontrado("La versión de precios no existe.")

    return response.data


def _obtener_partida(client: Client, partida_id: UUID) -> dict:
    response = (
        client
        .table(TABLA_PARTIDAS)
        .select(COLUMNAS_PARTIDA)
        .eq("id", str(partida_id))
        .maybe_single()
        .execute()
    )

    if response is None or not response.data:
        raise _no_encontrado("La partida no existe.")

    return response.data


# --- Lecturas (cliente del usuario: respeta RLS) --------------------------------

def listar_categorias(usuario_actual: UsuarioActual) -> List[dict]:
    client = get_user_scoped_client(usuario_actual.access_token)

    response = (
        client
        .table(TABLA_CATEGORIAS)
        .select("id, codigo, nombre, orden")
        .eq("vigente", True)
        .order("orden")
        .execute()
    )

    return response.data


def listar_versiones(usuario_actual: UsuarioActual) -> List[dict]:
    client = get_user_scoped_client(usuario_actual.access_token)

    response = (
        client
        .table(TABLA_VERSIONES)
        .select("*")
        .order("fecha_carga", desc=True)
        .execute()
    )

    return [_a_version(fila) for fila in response.data]


def listar_banco(usuario_actual: UsuarioActual, version_id: Optional[UUID]) -> List[dict]:
    client = get_user_scoped_client(usuario_actual.access_token)

    if version_id is not None:
        # Id explícito inexistente: 404 en vez de un banco vacío engañoso.
        version_id = _obtener_version(client, version_id)["id"]
    else:
        vigente = (
            client
            .table(TABLA_VERSIONES)
            .select("id")
            .eq("vigente", True)
            .limit(1)
            .execute()
        )
        version_id = vigente.data[0]["id"] if vigente.data else None

    if version_id is None:
        # Sin versión vigente: todas las partidas, sin valores.
        response = (
            client
            .table(TABLA_PARTIDAS)
            .select(COLUMNAS_PARTIDA)
            .order("codigo")
            .execute()
        )
        con_precios = _con_precios(client)
        return [_a_fila_banco(partida, None, partida["id"] in con_precios) for partida in response.data]

    # Funciona como left join: una partida sin precio en la versión llega con [].
    response = (
        client
        .table(TABLA_PARTIDAS)
        .select(f"{COLUMNAS_PARTIDA}, precios_partida(precio_unitario, rendimiento_mo, fuente)")
        .eq("precios_partida.version_precio_id", str(version_id))
        .order("codigo")
        .execute()
    )

    con_precios = _con_precios(client)
    return [
        _a_fila_banco(partida, (partida.get("precios_partida") or [None])[0], partida["id"] in con_precios)
        for partida in response.data
    ]


# --- Escrituras (service role: solo tras exigir_editor_banco) ---------------------

def crear_version(datos: VersionPreciosCrear) -> dict:
    try:
        response = supabase_admin.rpc(
            "crear_version_precios",
            {
                "p_version": datos.version,
                "p_copiar_de": str(datos.copiar_de) if datos.copiar_de else None,
            },
        ).execute()
    except APIError as error:
        raise _error_http(error, {"23505": "Ya existe una versión con ese nombre."})

    return _a_version(_una_fila(response.data))


def publicar_version(version_id: UUID) -> dict:
    try:
        response = supabase_admin.rpc(
            "publicar_version_precios",
            {"p_version_id": str(version_id)},
        ).execute()
    except APIError as error:
        raise _error_http(error)

    return _a_version(_una_fila(response.data))


def crear_partida(datos: PartidaCrear) -> dict:
    try:
        response = supabase_admin.rpc(
            "crear_partida_banco",
            {
                "p_categoria_id": datos.categoria_id,
                "p_nombre": datos.nombre,
                "p_unidad": datos.unidad,
            },
        ).execute()
    except APIError as error:
        raise _error_http(error, {
            "23505": "El código generado ya está en uso. Intenta nuevamente.",
            "23514": "La unidad de la partida no es válida.",
        })

    return _a_partida(_una_fila(response.data))


def editar_partida(partida_id: UUID, datos: PartidaEditar) -> dict:
    partida = _obtener_partida(supabase_admin, partida_id)

    if not partida["vigente"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La partida está dada de baja: no se puede editar.",
        )

    cambios = datos.model_dump(mode="json", exclude_unset=True)
    if "categoria_id" in cambios:
        if cambios["categoria_id"] is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="La categoría es obligatoria.",
            )
        categoria = (
            supabase_admin
            .table(TABLA_CATEGORIAS)
            .select("id")
            .eq("id", cambios["categoria_id"])
            .eq("vigente", True)
            .limit(1)
            .execute()
        )
        if not categoria.data:
            raise _no_encontrado("La categoría no existe.")

    if not cambios:
        return _a_partida(partida)

    # Los precios cargados están en esa unidad: si alguna vez tuvo precios, no cambia.
    if cambios.get("unidad", partida["unidad"]) != partida["unidad"] and _tiene_precios(supabase_admin, partida_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=MENSAJE_UNIDAD_CON_PRECIOS)

    # El código se conserva aunque cambie la categoría: mantiene la trazabilidad.
    # Proyectos y estimaciones guardan su propia copia de nombre y unidad.
    try:
        response = (
            supabase_admin
            .table(TABLA_PARTIDAS)
            .update(cambios)
            .eq("id", str(partida_id))
            .execute()
        )
    except APIError as error:
        # El trigger de la 005 frena la misma regla en la base.
        if error.code == "55000":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=MENSAJE_UNIDAD_CON_PRECIOS)
        raise _error_http(error, {"23514": "La unidad de la partida no es válida."})

    return _a_partida(response.data[0])


def dar_de_baja_partida(partida_id: UUID) -> dict:
    partida = _obtener_partida(supabase_admin, partida_id)

    if partida["es_base"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Las partidas del catálogo base no se pueden dar de baja.",
        )

    if not partida["vigente"]:
        return _a_partida(partida)

    response = (
        supabase_admin
        .table(TABLA_PARTIDAS)
        .update({"vigente": False})
        .eq("id", str(partida_id))
        .execute()
    )

    return _a_partida(response.data[0])


MENSAJE_VERSION_PUBLICADA = (
    "Una versión publicada no se puede modificar. Para cambiar precios, crea una nueva versión "
    "copiando la vigente, edítala y publícala."
)


def guardar_precio(version_id: UUID, partida_id: UUID, datos: PrecioEditar) -> dict:
    version = _obtener_version(supabase_admin, version_id)

    # Publicada alguna vez = inmutable, aunque ya no sea la vigente.
    if version.get("fecha_publicacion") or version["vigente"]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=MENSAJE_VERSION_PUBLICADA)

    partida = _obtener_partida(supabase_admin, partida_id)

    if not partida["vigente"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La partida está dada de baja: no se pueden editar sus valores.",
        )

    # Sin precio ni rendimiento la fila no aporta nada: se elimina.
    if datos.precio_unitario is None and datos.rendimiento_mo is None:
        (
            supabase_admin
            .table(TABLA_PRECIOS)
            .delete()
            .eq("partida_id", str(partida_id))
            .eq("version_precio_id", str(version_id))
            .execute()
        )
        return _a_fila_banco(partida, None)

    # Solo toca la fila de esta versión: las demás conservan sus valores.
    fila = {
        "partida_id": str(partida_id),
        "version_precio_id": str(version_id),
        "precio_unitario": datos.precio_unitario,
        "rendimiento_mo": datos.rendimiento_mo,
        "fuente": datos.fuente or FUENTE_EDICION,
    }

    try:
        response = (
            supabase_admin
            .table(TABLA_PRECIOS)
            .upsert(fila, on_conflict="partida_id,version_precio_id")
            .execute()
        )
    except APIError as error:
        # Carrera con una publicación: lo frena el trigger de la 005.
        if error.code == "55000":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=MENSAJE_VERSION_PUBLICADA)
        raise _error_http(error)

    return _a_fila_banco(partida, response.data[0])
