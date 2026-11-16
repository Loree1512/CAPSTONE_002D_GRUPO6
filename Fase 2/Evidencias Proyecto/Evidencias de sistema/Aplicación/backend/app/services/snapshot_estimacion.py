"""Convierte el resultado del motor en filas para guardar, y las filas en la respuesta.

La respuesta sale siempre de lo guardado, nunca de un recálculo.
"""

from decimal import Decimal
from typing import Iterable, List, Mapping, Optional, Tuple

from app.services.motor_costos import (
    CALCULADA,
    CERO,
    CIEN,
    SIN_CANTIDAD,
    SIN_PRECIO,
    ProyectoEntrada,
    ResultadoEstimacion,
    a_decimal,
)


def _texto(valor: Optional[Decimal]) -> Optional[str]:
    # Como texto para no perder precisión en el JSON.
    return None if valor is None else str(valor)


# --- Resultado → filas para la RPC crear_estimacion -------------------------------

def a_filas(
    resultado: ResultadoEstimacion,
    *,
    proyecto_id: str,
    proyecto: ProyectoEntrada,
    version: Mapping[str, object],
    parametros: Mapping[str, object],
    firma_partidas: str,
    observaciones: Optional[str] = None,
    plazo: Optional[Mapping[str, object]] = None,
) -> Tuple[dict, List[dict]]:
    estimacion = {
        "proyecto_id": str(proyecto_id),
        "version_precio_id": str(version["id"]),
        "version_precio": version["version"],
        "fuente_version_precio": version.get("fuente"),
        "comuna": proyecto.comuna,
        "tipo_obra": proyecto.tipo_obra,
        "materialidad": proyecto.materialidad,
        "superficie_m2": _texto(proyecto.superficie_m2),
        "numero_pisos": proyecto.numero_pisos,
        "estandar_terminaciones": proyecto.estandar_terminaciones,
        "parametros_snapshot": dict(parametros),
        "version_motor": resultado.version_motor,
        "aplicar_factores": resultado.factores.aplicar,
        "factor_comuna": _texto(resultado.factores.comuna),
        "factor_pisos": _texto(resultado.factores.pisos),
        "factor_ajuste": _texto(resultado.factores.ajuste),
        "costo_directo_base": _texto(resultado.costo_directo_base),
        "costo_directo": _texto(resultado.costo_directo),
        "gastos_generales_pct": _texto(resultado.gastos_generales_pct),
        "gastos_generales": _texto(resultado.gastos_generales),
        "utilidad_pct": _texto(resultado.utilidad_pct),
        "utilidad": _texto(resultado.utilidad),
        "costo_total": _texto(resultado.costo_total),
        "costo_m2": _texto(resultado.costo_m2),
        "partidas_calculadas": resultado.partidas_calculadas,
        "partidas_sin_precio": resultado.partidas_sin_precio,
        "partidas_sin_cantidad": resultado.partidas_sin_cantidad,
        "firma_partidas": firma_partidas,
        "completa": resultado.completa,
        "observaciones": observaciones,
        # Columnas del plazo (estimador_plazo.ResultadoPlazo.a_columnas).
        **(plazo or {}),
    }

    lineas = [
        {
            "orden": l.orden,
            "proyecto_partida_id": str(l.proyecto_partida_id),
            "partida_id": str(l.partida_id) if l.partida_id else None,
            "origen": l.origen,
            "codigo_partida": l.codigo,
            "nombre_partida": l.nombre,
            "unidad": l.unidad,
            "observacion": l.observacion,
            "categoria_id": l.categoria_id,
            "categoria_codigo": l.categoria_codigo,
            "categoria_nombre": l.categoria_nombre,
            "categoria_orden": l.categoria_orden,
            "estado": l.estado,
            "cantidad": _texto(l.cantidad),
            "precio_unitario_banco": _texto(l.precio_unitario_base),
            "precio_unitario_override": _texto(l.precio_unitario_override),
            "precio_unitario_usado": _texto(l.precio_unitario),
            "fuente_precio": l.fuente_precio,
            "factor_aplicado": _texto(l.factor_aplicado),
            "subtotal_base": _texto(l.subtotal_base),
            "subtotal": _texto(l.subtotal),
        }
        for l in resultado.lineas
    ]

    return estimacion, lineas


# --- Filas guardadas → respuesta -------------------------------------------------

def _linea(fila: Mapping[str, object]) -> dict:
    return {
        "id": fila.get("proyecto_partida_id"),
        "codigo": fila.get("codigo_partida"),
        "nombre": fila["nombre_partida"],
        "unidad": fila["unidad"],
        "categoria_codigo": fila["categoria_codigo"],
        "categoria_nombre": fila["categoria_nombre"],
        "cantidad": a_decimal(fila.get("cantidad")),
        # Precio finalmente usado, sin factor.
        "precio_unitario": a_decimal(fila.get("precio_unitario_usado")),
        "subtotal": a_decimal(fila["subtotal"]),
        "partida_id": fila.get("partida_id"),
        "origen": fila["origen"],
        "observacion": fila.get("observacion"),
        "estado": fila["estado"],
        "precio_unitario_base": a_decimal(fila.get("precio_unitario_banco")),
        "precio_unitario_override": a_decimal(fila.get("precio_unitario_override")),
        "fuente_precio": fila.get("fuente_precio"),
        "factor_aplicado": a_decimal(fila["factor_aplicado"]),
        "subtotal_base": a_decimal(fila["subtotal_base"]),
    }


def _metricas_version(estimacion: Mapping[str, object]) -> Tuple[Optional[float], Optional[str]]:
    """(error medio, estado) de la versión del modelo, embebida por la FK version_modelo.

    El error medio (MAE de la validación) describe al método de la versión (P2): con la
    mediana de respaldo no corresponde y queda en null. Nunca se escribe a mano.
    """
    version = estimacion.get("versiones_modelo")
    if not isinstance(version, Mapping):
        return None, None
    estado = version.get("estado")
    metricas = version.get("metricas")
    mae = metricas.get("mae") if isinstance(metricas, Mapping) else None
    mismo_metodo = (
        estimacion.get("plazo_dias") is not None
        and estimacion.get("plazo_metodo") is not None
        and estimacion.get("plazo_metodo") == version.get("metodo")
    )
    if not mismo_metodo or mae is None:
        return None, estado
    try:
        return float(mae), estado
    except (TypeError, ValueError):
        return None, estado


def armar_plazo(estimacion: Mapping[str, object]) -> dict:
    """Plazo sugerido por el modelo. Una fila anterior a la migración 009 no lo tiene."""
    if "plazo_estado" not in estimacion:
        return {"estado": "no_disponible", "fuera_dominio": True, "motivo": "anterior_al_modelo"}
    estado = estimacion["plazo_estado"]
    uf = estimacion.get("uf_valor")
    error_medio, estado_modelo = _metricas_version(estimacion)
    return {
        "dias": estimacion.get("plazo_dias"),
        "min_dias": estimacion.get("plazo_min_dias"),
        "max_dias": estimacion.get("plazo_max_dias"),
        "metodo": estimacion.get("plazo_metodo"),
        "estado": estado,
        "fuera_dominio": estimacion.get("plazo_fuera_dominio", estado != "dentro_dominio"),
        "provisional": estimacion.get("plazo_provisional"),
        "motivo": estimacion.get("plazo_motivo"),
        "version_modelo": estimacion.get("version_modelo"),
        "tipo_obra_modelo": estimacion.get("tipo_obra_modelo"),
        "uf_valor": None if uf is None else a_decimal(uf),
        "uf_fecha": estimacion.get("uf_fecha"),
        "error_medio_dias": error_medio,
        "estado_modelo": estado_modelo,
    }


def armar_profesional(estimacion: Mapping[str, object], usuario_nombre: Optional[str] = None) -> dict:
    """Plazo para la cotización. Una fila anterior a la migración 010 queda sin definir:
    nunca se toma el plazo del modelo como decisión del profesional."""
    if "plazo_profesional_estado" not in estimacion:
        return {"estado": "sin_definir"}
    usuario_id = estimacion.get("plazo_profesional_usuario_id")
    return {
        "dias": estimacion.get("plazo_profesional_dias"),
        "estado": estimacion.get("plazo_profesional_estado") or "sin_definir",
        "origen": estimacion.get("plazo_profesional_origen"),
        "fecha": estimacion.get("plazo_profesional_fecha"),
        "usuario_id": usuario_id,
        "usuario_nombre": usuario_nombre if usuario_id else None,
    }


def armar_resumen(estimacion: Mapping[str, object], usuario_nombre: Optional[str] = None) -> dict:
    return {
        "id": estimacion["id"],
        "proyecto_id": estimacion["proyecto_id"],
        "fecha_creacion": estimacion["fecha_creacion"],
        "version_motor": estimacion["version_motor"],
        "version_precios": {
            "id": estimacion["version_precio_id"],
            "version": estimacion["version_precio"],
            "fuente": estimacion.get("fuente_version_precio"),
        },
        "costo_directo": a_decimal(estimacion["costo_directo"]),
        "total": a_decimal(estimacion["costo_total"]),
        "costo_m2": a_decimal(estimacion["costo_m2"]),
        "completa": estimacion["completa"],
        "partidas_calculadas": estimacion["partidas_calculadas"],
        "partidas_sin_precio": estimacion["partidas_sin_precio"],
        "partidas_sin_cantidad": estimacion["partidas_sin_cantidad"],
        "plazo": armar_plazo(estimacion),
        "plazo_profesional": armar_profesional(estimacion, usuario_nombre),
    }


def armar_respuesta(
    estimacion: Mapping[str, object],
    filas: Iterable[Mapping[str, object]],
    usuario_nombre: Optional[str] = None,
) -> dict:
    """`usuario_nombre`: quién definió el plazo para la cotización (nombre o correo)."""
    filas = sorted(filas, key=lambda f: f["orden"])
    costo_directo = a_decimal(estimacion["costo_directo"])

    # Agrupa por capítulo solo las líneas que suman.
    capitulos: List[dict] = []
    por_codigo = {}
    for fila in filas:
        if fila["estado"] != CALCULADA:
            continue
        codigo = fila["categoria_codigo"]
        if codigo not in por_codigo:
            por_codigo[codigo] = {
                "codigo": codigo,
                "nombre": fila["categoria_nombre"],
                "subtotal": CERO,
                "incidencia": CERO,
                "lineas": [],
            }
            capitulos.append(por_codigo[codigo])
        linea = _linea(fila)
        por_codigo[codigo]["lineas"].append(linea)
        por_codigo[codigo]["subtotal"] += linea["subtotal"]

    capitulos = [c for c in capitulos if c["subtotal"] > 0]
    for c in capitulos:
        c["incidencia"] = (c["subtotal"] / costo_directo) * CIEN if costo_directo else CERO

    return {
        **armar_resumen(estimacion, usuario_nombre),
        "proyecto": {
            "comuna": estimacion["comuna"],
            "tipo_obra": estimacion["tipo_obra"],
            "materialidad": estimacion["materialidad"],
            "superficie_m2": a_decimal(estimacion["superficie_m2"]),
            "numero_pisos": estimacion["numero_pisos"],
            "estandar_terminaciones": estimacion["estandar_terminaciones"],
        },
        "capitulos": capitulos,
        "costo_directo_base": a_decimal(estimacion["costo_directo_base"]),
        "gastos_generales_pct": a_decimal(estimacion["gastos_generales_pct"]),
        "gastos_generales": a_decimal(estimacion["gastos_generales"]),
        "utilidad_pct": a_decimal(estimacion["utilidad_pct"]),
        "utilidad": a_decimal(estimacion["utilidad"]),
        "aplicar_factores": estimacion["aplicar_factores"],
        "factores": {
            "comuna": a_decimal(estimacion["factor_comuna"]),
            "pisos": a_decimal(estimacion["factor_pisos"]),
            "ajuste": a_decimal(estimacion["factor_ajuste"]),
        },
        "sin_precio": [_linea(f) for f in filas if f["estado"] == SIN_PRECIO],
        "sin_cantidad": [_linea(f) for f in filas if f["estado"] == SIN_CANTIDAD],
        "observaciones": estimacion.get("observaciones"),
    }
