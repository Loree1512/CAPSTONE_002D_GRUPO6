"""Actualiza public.valores_uf con la UF diaria de la CMF.

Tarea separada: no corre dentro de las peticiones. El estimador de plazo solo lee
valores_uf. Fuente única, la misma del entrenamiento: API de indicadores de la CMF
(`uf/posteriores/AAAA/MM`). Si la CMF no responde, no se busca en otro lado.

- La clave se lee de CMF_API_KEY y nunca se escribe en logs, errores ni en la base.
- Escribe con el service role (SUPABASE_SECRET_KEY) y no pisa días ya cargados.
- Pide desde el mes anterior al último día guardado: la CMF publica hasta el día 9
  del mes siguiente, así que el último mes guardado puede estar incompleto.

Uso, desde backend/:
    python -m scripts.actualizar_uf            # completa desde el último día guardado
    python -m scripts.actualizar_uf --desde 2025-01
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from dotenv import load_dotenv

ENDPOINT = "https://api.cmfchile.cl/api-sbifv3/recursos_api/uf/posteriores/{anio}/{mes:02d}"
VARIABLE_CLAVE = "CMF_API_KEY"
DESDE_POR_DEFECTO = (2025, 1)
TABLA = "valores_uf"

logger = logging.getLogger("buildcast.actualizar_uf")


class ErrorUF(Exception):
    """Mensajes sin la clave ni la URL con la clave."""


def valor_chileno(texto: str) -> Decimal:
    """'39.643,59' -> Decimal('39643.59')"""
    return Decimal(texto.strip().replace(".", "").replace(",", "."))


def parsear(cuerpo: bytes) -> Dict[date, Decimal]:
    try:
        datos = json.loads(cuerpo.decode("utf-8"))
        serie = {date.fromisoformat(i["Fecha"]): valor_chileno(i["Valor"]) for i in datos["UFs"]}
    except (ValueError, KeyError, TypeError, UnicodeDecodeError, InvalidOperation):
        raise ErrorUF("La CMF respondió con un formato inesperado.") from None
    if not serie or any(v <= 0 for v in serie.values()):
        raise ErrorUF("La CMF no entregó valores válidos de UF.")
    return serie


def descargar(clave: str, anio: int, mes: int,
              abrir: Callable = urllib.request.urlopen) -> Tuple[Dict[date, Decimal], str]:
    """(serie, endpoint sin clave)."""
    endpoint = ENDPOINT.format(anio=anio, mes=mes)
    consulta = urllib.parse.urlencode({"apikey": clave, "formato": "json"})
    try:
        with abrir(f"{endpoint}?{consulta}", timeout=30) as respuesta:
            cuerpo = respuesta.read()
    except urllib.error.HTTPError as error:
        raise ErrorUF(f"La CMF respondió HTTP {error.code}.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ErrorUF("No se pudo conectar con la CMF.") from None
    return parsear(cuerpo), endpoint


def mes_anterior(fecha: date) -> Tuple[int, int]:
    return (fecha.year - 1, 12) if fecha.month == 1 else (fecha.year, fecha.month - 1)


def ultimo_dia_guardado(cliente) -> Optional[date]:
    filas = cliente.table(TABLA).select("fecha").order("fecha", desc=True).limit(1).execute().data
    return date.fromisoformat(filas[0]["fecha"]) if filas else None


def filas_para_guardar(serie: Dict[date, Decimal], fuente: str, ahora: datetime) -> list:
    return [{"fecha": f.isoformat(), "valor": str(v), "fuente": fuente, "fecha_actualizacion": ahora.isoformat()}
            for f, v in sorted(serie.items())]


def actualizar(cliente, clave: str, desde: Optional[Tuple[int, int]] = None,
               abrir: Callable = urllib.request.urlopen) -> int:
    """Guarda los días que falten. Devuelve cuántos días trajo la CMF."""
    if desde is None:
        ultimo = ultimo_dia_guardado(cliente)
        desde = mes_anterior(ultimo) if ultimo else DESDE_POR_DEFECTO
    serie, fuente = descargar(clave, *desde, abrir=abrir)
    filas = filas_para_guardar(serie, fuente, datetime.now(timezone.utc))
    # Los valores publicados no cambian: un día ya cargado no se reescribe.
    cliente.table(TABLA).upsert(filas, on_conflict="fecha", ignore_duplicates=True).execute()
    return len(filas)


def cargar_entorno() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _mes(texto: str) -> Tuple[int, int]:
    anio, mes = texto.split("-")
    return int(anio), int(mes)


def main(argv: Optional[list] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--desde", type=_mes, help="AAAA-MM: pide los días posteriores a ese mes")
    args = ap.parse_args(argv)

    cargar_entorno()
    clave = os.getenv(VARIABLE_CLAVE, "").strip()
    if not clave:
        logger.error("Falta %s.", VARIABLE_CLAVE)
        return 2
    try:
        from app.database.supabase import supabase_admin

        cantidad = actualizar(supabase_admin, clave, args.desde)
    except ErrorUF as error:
        logger.error("No se actualizó la UF: %s", error)
        return 1
    logger.info("UF: %s días recibidos de la CMF; los ya guardados no se modificaron.", cantidad)
    return 0


if __name__ == "__main__":
    sys.exit(main())
