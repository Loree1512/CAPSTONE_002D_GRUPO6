from datetime import date
from typing import Optional

from fastapi import HTTPException, status
from postgrest.exceptions import APIError
from supabase import Client

from app.database.supabase import get_user_scoped_client, supabase_admin
from app.schemas.autenticacion import UsuarioActual
from app.schemas.configuracion import ConfiguracionEditar
from app.services.estimador_plazo import fecha_chile
from app.services.servicio_banco import _error_http

TABLA_PARAMETROS = "parametros_calculo"

# Todas las claves de la configuración. El motor actual solo usa GG, utilidad,
# comuna y pisos; el resto se conserva para uso posterior.
CLAVES_PARAMETROS = (
    "valor_hora_hombre",
    "gastos_generales_pct",
    "utilidad_pct",
    "factores_comuna",
    "tramos_pisos",
    "factores_estandar",
    "factores_materialidad",
    "capitulos_estandar",
    "capitulos_materialidad",
)

# Clave en la base → campo de la API. Solo cambia factores_materialidad (factoresMaterial en el frontend).
CAMPO_POR_CLAVE = {
    "valor_hora_hombre": "valor_hora_hombre",
    "gastos_generales_pct": "gastos_generales_pct",
    "utilidad_pct": "utilidad_pct",
    "factores_comuna": "factores_comuna",
    "tramos_pisos": "tramos_pisos",
    "factores_estandar": "factores_estandar",
    "factores_materialidad": "factores_material",
    "capitulos_estandar": "capitulos_estandar",
    "capitulos_materialidad": "capitulos_materialidad",
}


def leer_parametros(client: Client) -> dict:
    """Devuelve parametros_calculo como {clave: valor}."""
    response = client.table(TABLA_PARAMETROS).select("clave, valor").execute()
    return {fila["clave"]: fila["valor"] for fila in response.data}


def _configuracion(parametros: dict) -> dict:
    faltantes = [clave for clave in CLAVES_PARAMETROS if clave not in parametros]
    if faltantes:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La configuración del cálculo está incompleta. Falta: " + ", ".join(faltantes) + ".",
        )
    return {CAMPO_POR_CLAVE[clave]: parametros[clave] for clave in CLAVES_PARAMETROS}


def obtener_configuracion(usuario_actual: UsuarioActual) -> dict:
    client = get_user_scoped_client(usuario_actual.access_token)
    return _configuracion(leer_parametros(client))


def guardar_configuracion(editor: UsuarioActual, datos: ConfiguracionEditar) -> dict:
    valores = datos.model_dump(mode="json")

    filas = [
        {"clave": clave, "valor": valores[campo], "actualizado_por": str(editor.id)}
        for clave, campo in CAMPO_POR_CLAVE.items()
        # Si no vienen los capítulos, se conservan los guardados.
        if valores.get(campo) is not None
    ]

    # Un solo upsert: se guardan todas las claves o ninguna.
    try:
        supabase_admin.table(TABLA_PARAMETROS).upsert(filas, on_conflict="clave").execute()
    except APIError as error:
        raise _error_http(error)

    return _configuracion(leer_parametros(supabase_admin))


def buscar_uf_vigente(client: Client, hoy: date) -> dict:
    """Última UF cuya fecha ya llegó. La CMF publica días por adelantado: una fila
    futura ya cargada no es la UF de hoy. Solo lee valores_uf; no consulta la CMF."""
    filas = (
        client.table("valores_uf")
        .select("fecha, valor")
        .lte("fecha", hoy.isoformat())
        .order("fecha", desc=True)
        .limit(1)
        .execute()
        .data
    )
    if not filas or filas[0].get("valor") is None:
        return {"valor": None, "fecha": None}
    return {"valor": float(filas[0]["valor"]), "fecha": filas[0]["fecha"]}


def obtener_uf_vigente(usuario_actual: UsuarioActual, hoy: Optional[date] = None) -> dict:
    client = get_user_scoped_client(usuario_actual.access_token)
    return buscar_uf_vigente(client, hoy or fecha_chile())
