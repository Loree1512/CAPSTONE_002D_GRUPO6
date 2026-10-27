"""Resumen de la última estimación de un proyecto. Puro, sin Supabase."""

import hashlib
import json
from decimal import Decimal
from typing import Iterable, Mapping, Optional

SIN_ESTIMAR = "sin_estimar"
VIGENTE = "vigente"
RECALCULAR = "recalcular"

# Datos del proyecto que la estimación guarda como snapshot.
CAMPOS_SNAPSHOT = (
    "comuna",
    "tipo_obra",
    "materialidad",
    "superficie_m2",
    "numero_pisos",
    "estandar_terminaciones",
)
CAMPOS_NUMERICOS = ("superficie_m2", "numero_pisos")

# Campos de proyecto_partidas que cambian el costo. Nombre, orden u
# observación no obligan a recalcular.
CAMPOS_FIRMA = ("id", "partida_id", "cantidad", "precio_unitario_override")
COLUMNAS_FIRMA = ", ".join(CAMPOS_FIRMA)

# Columnas de la última estimación que se embeben en cada proyecto.
COLUMNAS_ULTIMA_ESTIMACION = ", ".join(
    ("id", "fecha_creacion", "version_precio_id", "costo_total", "costo_m2", "firma_partidas", *CAMPOS_SNAPSHOT)
)


def _igual(campo: str, actual, estimado) -> bool:
    # numeric puede llegar como 142 o 142.0: se compara por valor.
    if campo in CAMPOS_NUMERICOS and actual is not None and estimado is not None:
        return Decimal(str(actual)) == Decimal(str(estimado))
    return actual == estimado


def _numero(valor) -> Optional[str]:
    # 3, 3.0 y "3.00" dan la misma firma.
    if valor is None:
        return None
    return format(Decimal(str(valor)).normalize(), "f")


def firma_partidas(filas: Iterable[Mapping[str, object]]) -> str:
    """Huella de las partidas que afectan el costo; no depende del orden."""
    datos = sorted(
        [
            str(f["id"]),
            str(f["partida_id"]) if f.get("partida_id") else None,
            _numero(f.get("cantidad")),
            _numero(f.get("precio_unitario_override")),
        ]
        for f in filas
    )
    texto = json.dumps(datos, separators=(",", ":"))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def proyecto_cambio(proyecto: dict, ultima: dict) -> bool:
    """true si algún dato del proyecto difiere del snapshot de la estimación."""
    return any(not _igual(c, proyecto.get(c), ultima.get(c)) for c in CAMPOS_SNAPSHOT)


def partidas_cambiaron(partidas: Iterable[Mapping[str, object]], ultima: dict) -> bool:
    return ultima.get("firma_partidas") != firma_partidas(partidas)


def estado_estimacion(
    proyecto: dict,
    ultima: Optional[dict],
    version_vigente_id: Optional[str],
    partidas: Optional[Iterable[Mapping[str, object]]] = None,
) -> str:
    if not ultima:
        return SIN_ESTIMAR

    # Se comparan datos, no fechas: guardar sin cambios no invalida la estimación.
    if proyecto_cambio(proyecto, ultima):
        return RECALCULAR

    if partidas_cambiaron(partidas or [], ultima):
        return RECALCULAR

    # Hay otra versión de precios vigente. Sin vigente no hay con qué recalcular.
    if version_vigente_id and str(ultima["version_precio_id"]) != str(version_vigente_id):
        return RECALCULAR

    return VIGENTE


def con_resumen(proyecto: dict, version_vigente_id: Optional[str]) -> dict:
    """Agrega el resumen al proyecto.

    `estimaciones` trae 0 o 1 fila (la última) y `proyecto_partidas` las
    columnas de la firma; ninguno de los dos se devuelve.
    """
    fila = dict(proyecto)
    embebidas = fila.pop("estimaciones", None) or []
    partidas = fila.pop("proyecto_partidas", None) or []
    ultima = embebidas[0] if embebidas else None

    fila.update(
        ultima_estimacion_id=ultima["id"] if ultima else None,
        costo_total=ultima["costo_total"] if ultima else None,
        costo_m2=ultima["costo_m2"] if ultima else None,
        fecha_estimacion=ultima["fecha_creacion"] if ultima else None,
        estado_estimacion=estado_estimacion(fila, ultima, version_vigente_id, partidas),
        # El plazo todavía no está integrado.
        plazo_dias=None,
    )
    return fila
