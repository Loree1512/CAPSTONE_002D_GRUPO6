"""Valor de la UF desde la API de la CMF y cálculo de `costo_neto_uf` (HU-13).

Fuente única: API de indicadores de la Comisión para el Mercado Financiero (CMF),
endpoint `uf/posteriores/2025/01`, que entrega un valor por día posterior a
enero de 2025, es decir, desde el 2025-02-01 hasta el día 9 del mes siguiente
al de la consulta (la CMF publica la UF por adelantado). No se usan otras fuentes (Banco Central, SII): si una fecha
no está en la caché, se informa el error en vez de buscarla en otro lado.

La clave de la API se lee de la variable de entorno `CMF_API_KEY`. Nunca se
imprime ni se escribe en archivos: la caché guarda el endpoint sin la clave y los
mensajes de error no incluyen la URL.

La primera ejecución descarga la serie y la guarda en
`ml/data/processed/uf_cmf.csv`; las siguientes usan esa caché sin llamar a la API.
Para refrescarla, borre el archivo y vuelva a ejecutar.

Solo usa la biblioteca estándar.

Uso:
    python ml/src/uf.py [ruta_csv]
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

RAIZ_ML = Path(__file__).resolve().parents[1]
CSV_POR_DEFECTO = RAIZ_ML / "data" / "processed" / "presupuestos_reales.csv"
CACHE = RAIZ_ML / "data" / "processed" / "uf_cmf.csv"

ENDPOINT = "https://api.cmfchile.cl/api-sbifv3/recursos_api/uf/posteriores/2025/01"
FECHA_MINIMA = date(2025, 2, 1)  # "posteriores/2025/01" excluye enero de 2025
VARIABLE_CLAVE = "CMF_API_KEY"
COLUMNAS_CACHE = ["fecha", "valor_uf", "fecha_descarga", "fuente"]


# ---------------------------------------------------------------------------
# Descarga
# ---------------------------------------------------------------------------

def _valor_chileno(texto: str) -> float:
    """'39.123,45' -> 39123.45"""
    return float(texto.strip().replace(".", "").replace(",", "."))


def _detalle_error_cmf(cuerpo: bytes) -> str:
    """Extrae CodigoError y Mensaje de una respuesta de error de la CMF, si vienen."""
    try:
        datos = json.loads(cuerpo.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError):
        return ""
    if not isinstance(datos, dict):
        return ""
    partes = []
    if "CodigoError" in datos:
        partes.append(f"CodigoError={datos['CodigoError']}")
    if "Mensaje" in datos:
        partes.append(f"Mensaje={datos['Mensaje']}")
    return ", ".join(partes)


def descargar_uf() -> dict[date, float]:
    """Hace UNA llamada a la CMF y devuelve {fecha: valor_uf}. No escribe nada."""
    clave = os.environ.get(VARIABLE_CLAVE, "").strip()
    if not clave:
        raise SystemExit(
            f"ERROR: la variable de entorno {VARIABLE_CLAVE} no existe o está vacía. "
            "Defínala con la clave de la API de la CMF antes de descargar la UF."
        )

    consulta = urllib.parse.urlencode({"apikey": clave, "formato": "json"})
    try:
        with urllib.request.urlopen(f"{ENDPOINT}?{consulta}", timeout=30) as resp:
            cuerpo = resp.read()
    except urllib.error.HTTPError as e:
        try:
            detalle = _detalle_error_cmf(e.read())
        except Exception:  # noqa: BLE001 - el cuerpo del error es opcional
            detalle = ""
        codigo = e.code
        raise SystemExit(
            f"ERROR: la CMF respondió HTTP {codigo}"
            + (f" ({detalle})" if detalle else "")
            + f". Endpoint: {ENDPOINT}"
        ) from None
    except urllib.error.URLError as e:
        motivo = str(e.reason)
        raise SystemExit(f"ERROR: no se pudo conectar a la CMF ({motivo}). Endpoint: {ENDPOINT}") from None
    except TimeoutError:
        raise SystemExit(f"ERROR: la CMF no respondió en 30 s. Endpoint: {ENDPOINT}") from None

    try:
        datos = json.loads(cuerpo.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise SystemExit(f"ERROR: la CMF devolvió una respuesta que no es JSON válido. Endpoint: {ENDPOINT}") from None

    if not isinstance(datos, dict) or "UFs" not in datos:
        detalle = _detalle_error_cmf(cuerpo)
        raise SystemExit(
            "ERROR: la respuesta de la CMF no trae la clave 'UFs'"
            + (f" ({detalle})" if detalle else "")
            + f". Endpoint: {ENDPOINT}"
        ) from None

    serie: dict[date, float] = {}
    try:
        for item in datos["UFs"]:
            serie[date.fromisoformat(item["Fecha"])] = _valor_chileno(item["Valor"])
    except (KeyError, TypeError, ValueError):
        raise SystemExit("ERROR: un registro de 'UFs' no tiene el formato esperado (Fecha ISO, Valor '39.123,45').") from None
    if not serie:
        raise SystemExit("ERROR: la CMF devolvió 'UFs' vacía.")
    return serie


# ---------------------------------------------------------------------------
# Caché
# ---------------------------------------------------------------------------

def guardar_cache(serie: dict[date, float], ruta: Path = CACHE) -> None:
    hoy = date.today().isoformat()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f, lineterminator="\n")
        escritor.writerow(COLUMNAS_CACHE)
        for fecha in sorted(serie):
            escritor.writerow([fecha.isoformat(), f"{serie[fecha]:.2f}", hoy, ENDPOINT])


def leer_cache(ruta: Path = CACHE) -> dict[date, float]:
    with ruta.open(encoding="utf-8", newline="") as f:
        return {date.fromisoformat(r["fecha"]): float(r["valor_uf"]) for r in csv.DictReader(f)}


def cargar_cache(ruta: Path = CACHE) -> dict[date, float]:
    """Usa la caché si existe; si no, descarga desde la CMF y la guarda."""
    if ruta.exists():
        print(f"UF: usando caché {ruta.relative_to(RAIZ_ML)} (sin llamar a la API).")
        return leer_cache(ruta)
    print(f"UF: caché inexistente; descargando desde la CMF ({ENDPOINT}).")
    serie = descargar_uf()
    guardar_cache(serie, ruta)
    print(f"UF: caché guardada en {ruta.relative_to(RAIZ_ML)} ({len(serie)} días).")
    return serie


_SERIE: dict[date, float] | None = None


def uf_del_dia(fecha: date | str) -> float:
    """Valor de la UF para una fecha, desde la caché de la CMF."""
    global _SERIE
    if isinstance(fecha, str):
        fecha = date.fromisoformat(fecha)
    if fecha < FECHA_MINIMA:
        raise ValueError(
            f"La fecha {fecha} es anterior a {FECHA_MINIMA}; la caché de la CMF solo cubre desde esa fecha "
            "y no se usan otras fuentes."
        )
    if _SERIE is None:
        _SERIE = cargar_cache()
    if fecha not in _SERIE:
        raise ValueError(f"No hay valor de UF para {fecha} en la caché de la CMF ({CACHE.name}).")
    return _SERIE[fecha]


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

def _detectar_fin_de_linea(texto: str) -> str:
    return "\r\n" if "\r\n" in texto else "\n"


def _campos_entrecomillados(texto: str) -> list[list[bool]]:
    """Para cada registro del CSV, indica qué campos venían entre comillas.

    El CSV del dataset entrecomilla siempre las columnas de texto libre
    (p. ej. notas_calidad) aunque no lo necesiten, algo que csv.DictWriter no
    puede reproducir por columna. Se registra el estilo original campo a campo
    para reescribir el archivo sin alterar nada salvo costo_neto_uf.
    """
    registros: list[list[bool]] = []
    actual: list[bool] = []
    i, n = 0, len(texto)
    inicio_campo = True
    while i < n:
        c = texto[i]
        if inicio_campo and c == '"':
            actual.append(True)
            i += 1
            while i < n:
                if texto[i] == '"':
                    if i + 1 < n and texto[i + 1] == '"':
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            inicio_campo = False
            continue
        if inicio_campo:
            actual.append(False)
            inicio_campo = False
        if c == ",":
            inicio_campo = True
        elif c in "\r\n":
            if c == "\r" and i + 1 < n and texto[i + 1] == "\n":
                i += 1
            registros.append(actual)
            actual = []
            inicio_campo = True
            i += 1
            continue
        i += 1
    if actual or not inicio_campo:
        if inicio_campo:
            actual.append(False)
        registros.append(actual)
    return registros


def _formatear_campo(valor: str, entrecomillado: bool) -> str:
    necesita = any(ch in valor for ch in ',"\r\n')
    if entrecomillado or necesita:
        return '"' + valor.replace('"', '""') + '"'
    return valor


def _serializar(encabezado: list[str], filas: list[dict[str, str]],
                estilo: list[list[bool]], fin_linea: str) -> str:
    """Escribe el CSV respetando, campo a campo, el entrecomillado original."""
    lineas = []
    for idx, valores in enumerate([dict(zip(encabezado, encabezado))] + filas):
        comillas = estilo[idx] if idx < len(estilo) else [False] * len(encabezado)
        lineas.append(",".join(
            _formatear_campo(valores[col], comillas[j] if j < len(comillas) else False)
            for j, col in enumerate(encabezado)
        ))
    return fin_linea.join(lineas) + fin_linea


def completar_costo_uf(ruta_csv: Path = CSV_POR_DEFECTO) -> tuple[int, list[tuple[str, str]]]:
    """Escribe costo_neto_uf = round(costo_neto_clp / UF del día de fecha_documento, 2).

    Filas sin fecha o sin costo quedan vacías. Fechas posteriores a hoy quedan
    vacías y se devuelven como aviso. Devuelve (filas_completadas, fechas_futuras).
    """
    crudo = ruta_csv.read_bytes()
    bom = crudo.startswith(b"\xef\xbb\xbf")
    texto = crudo.decode("utf-8-sig")
    fin_linea = _detectar_fin_de_linea(texto)

    lector = csv.DictReader(io.StringIO(texto, newline=""))
    encabezado = list(lector.fieldnames or [])
    filas = list(lector)
    if "costo_neto_uf" not in encabezado:
        raise SystemExit("ERROR: el CSV no tiene la columna costo_neto_uf.")

    hoy = date.today()
    completadas = 0
    futuras: list[tuple[str, str]] = []
    for fila in filas:
        fecha_txt = fila["fecha_documento"].strip()
        costo_txt = fila["costo_neto_clp"].strip()
        if not fecha_txt or not costo_txt:
            fila["costo_neto_uf"] = ""
            continue
        fecha = date.fromisoformat(fecha_txt)
        if fecha > hoy:
            fila["costo_neto_uf"] = ""
            futuras.append((fila["id_caso"], fecha_txt))
            continue
        fila["costo_neto_uf"] = f"{round(int(costo_txt) / uf_del_dia(fecha), 2):.2f}"
        completadas += 1

    nuevo = _serializar(encabezado, filas, _campos_entrecomillados(texto), fin_linea)
    if not texto.endswith(fin_linea):
        nuevo = nuevo[: -len(fin_linea)]
    ruta_csv.write_bytes((b"\xef\xbb\xbf" if bom else b"") + nuevo.encode("utf-8"))
    return completadas, futuras


def main(argv: list[str]) -> int:
    # stdout y stderr en UTF-8: en Windows ambos usan cp1252 por defecto cuando se
    # redirigen, y los mensajes de error (SystemExit -> stderr) mostraban "?" en
    # lugar de tildes.
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass

    ruta = Path(argv[1]) if len(argv) > 1 else CSV_POR_DEFECTO
    if not ruta.exists():
        print(f"ERROR: no existe {ruta}")
        return 2

    completadas, futuras = completar_costo_uf(ruta)
    print(f"costo_neto_uf completada en {completadas} filas de {ruta.name}.")
    if futuras:
        print(f"AVISO: {len(futuras)} fila(s) con fecha_documento posterior a hoy ({date.today()}); "
              "quedan sin costo_neto_uf:")
        for idc, fecha in futuras:
            print(f"  {idc}  {fecha}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
