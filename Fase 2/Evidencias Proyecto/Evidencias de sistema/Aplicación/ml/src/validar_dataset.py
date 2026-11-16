"""Validador del dataset de presupuestos reales (HU-13).

Comprueba el CSV contra el diccionario de variables (ml/docs/diccionario_variables.md)
y los criterios de inclusión (ml/docs/criterios_inclusion.md):

1. Encabezado, tipos, dominios y obligatoriedad de cada columna.
2. Coherencia entre columnas (clase/tipo de obra, flags de superficie, pisos y plazo).
3. Recalcula `utilizable` y `motivo_exclusion` y los compara con los del CSV.

Solo usa la biblioteca estándar. Sale con código 1 si hay errores.

Uso:
    python ml/src/validar_dataset.py [ruta_csv]
"""

from __future__ import annotations

import csv
import sys
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

RAIZ_ML = Path(__file__).resolve().parents[1]
CSV_POR_DEFECTO = RAIZ_ML / "data" / "processed" / "presupuestos_reales.csv"
DIR_RAW = RAIZ_ML / "data" / "raw"
# Mapa alias -> nombre real del PDF. Vive en data/raw/ (ignorado por git) porque
# el nombre real puede contener datos del cliente. Columnas: alias,archivo_real
MAPA_ALIAS = DIR_RAW / "alias_archivos.csv"

# ---------------------------------------------------------------------------
# Diccionario de variables (debe coincidir con ml/docs/diccionario_variables.md)
# ---------------------------------------------------------------------------

TIPOS_EDIFICACION = {"ampliacion", "obra_nueva", "alteracion_interior", "habilitacion_comercial"}
TIPOS_PUNTUAL = {
    "reparacion_mantencion",
    "terminaciones",
    "muro_cierre",
    "radier",
    "remodelacion_bano_cocina",
    "obra_menor_varia",
}
# Combinaciones válidas clase_obra -> tipo_obra. Desde el 2026-11-01 el mapeo
# tipo_obra -> clase_obra es determinista: `obra_nueva` es siempre edificación
# (R13, cobertizo, se recodificó a `obra_menor_varia`).
COMBINACIONES_VALIDAS = {
    "edificacion": TIPOS_EDIFICACION,
    "puntual": TIPOS_PUNTUAL,
}
COMUNAS = {
    "Viña del Mar", "Valparaíso", "Concón", "Quilpué", "Villa Alemana",
    "Quintero", "La Ligua",
}
BOOL = {"true", "false"}

# columna: (tipo, obligatoria, dominio)
#   tipo: str | cat | int | float | bool | date
#   obligatoria: True (siempre) | False (opcional)
#   dominio: set de valores permitidos (cat/bool) o (min, max) para numéricos
ESQUEMA: dict[str, tuple[str, bool, object]] = {
    "id_caso": ("str", True, None),
    "archivo_origen": ("str", False, None),  # obligatoria si origen_dato = real
    "revision": ("str", False, None),
    "origen_dato": ("cat", True, {"real", "sintetico"}),
    "clase_obra": ("cat", True, {"edificacion", "puntual"}),
    "tipo_obra": ("cat", True, TIPOS_EDIFICACION | TIPOS_PUNTUAL),
    "comuna": ("cat", True, COMUNAS),
    "comuna_fuente": ("cat", True, {"documento", "inferida_localidad", "sintetica"}),
    "localidad": ("str", False, None),
    "materialidad": ("cat", True, {
        "albanileria", "metalcon", "madera", "hormigon", "acero", "mixta", "no_aplica", "ni",
    }),
    "superficie_m2": ("float", False, (0.0, None)),
    "superficie_fuente": ("cat", True, {"explicita", "inferida_documento", "no_informada", "sintetica"}),
    "numero_pisos": ("int", False, (1, None)),
    "pisos_fuente": ("cat", True, {"explicito", "inferido", "no_informado", "sintetico"}),
    "estandar_terminaciones": ("cat", True, {"economico", "medio", "alto", "ni"}),
    "costo_neto_clp": ("int", False, (1, None)),  # obligatoria para utilizable (I2)
    "iva_incluido_doc": ("cat", True, {"true", "false", "ni"}),
    "costo_neto_uf": ("float", False, (0.0, None)),
    "gg_utilidad_pct": ("float", False, (0.0, 30.0)),
    "fecha_documento": ("date", False, None),
    "plazo_dias": ("int", False, (1, None)),  # variable objetivo
    "plazo_texto_original": ("str", False, None),
    "plazo_explicito": ("bool", True, BOOL),
    "plazo_es_cota": ("bool", True, BOOL),
    "tipo_plazo": ("cat", True, {"ofertado", "ejecutado"}),
    "pagina_plazo": ("int", False, (1, None)),
    "utilizable": ("bool", True, BOOL),
    "motivo_exclusion": ("cat", False, {"E2", "E3", "E4"}),
    "notas_calidad": ("str", False, None),
}


def _a_numero(valor: str, tipo: str):
    if tipo == "int":
        return int(valor)
    return float(valor)


def validar_campo(col: str, valor: str) -> str | None:
    """Devuelve un mensaje de error o None."""
    tipo, obligatoria, dominio = ESQUEMA[col]
    if valor == "":
        return f"'{col}' es obligatoria y está vacía" if obligatoria else None
    if tipo in ("cat", "bool"):
        if valor not in dominio:
            return f"'{col}'='{valor}' fuera de dominio {sorted(dominio)}"
    elif tipo in ("int", "float"):
        try:
            num = _a_numero(valor, tipo)
        except ValueError:
            return f"'{col}'='{valor}' no es {tipo}"
        minimo, maximo = dominio
        if minimo is not None and num < minimo:
            return f"'{col}'={valor} menor que {minimo}"
        if maximo is not None and num > maximo:
            return f"'{col}'={valor} mayor que {maximo}"
    elif tipo == "date":
        try:
            date.fromisoformat(valor)
        except ValueError:
            return f"'{col}'='{valor}' no es fecha ISO (AAAA-MM-DD)"
    return None


def validar_coherencia(fila: dict[str, str]) -> list[str]:
    errores = []
    clase, tipo = fila["clase_obra"], fila["tipo_obra"]
    if clase in COMBINACIONES_VALIDAS and tipo not in COMBINACIONES_VALIDAS[clase]:
        errores.append(f"tipo_obra '{tipo}' no es válido para clase '{clase}'")

    if fila["origen_dato"] == "real" and not fila["archivo_origen"]:
        errores.append("fila real sin archivo_origen")
    if fila["origen_dato"] == "sintetico" and fila["tipo_plazo"] == "ejecutado":
        errores.append("un sintético no puede tener tipo_plazo 'ejecutado'")

    sin_sup = fila["superficie_m2"] == ""
    if sin_sup != (fila["superficie_fuente"] == "no_informada"):
        errores.append("superficie_m2 y superficie_fuente incoherentes")
    sin_pisos = fila["numero_pisos"] == ""
    if sin_pisos != (fila["pisos_fuente"] == "no_informado"):
        errores.append("numero_pisos y pisos_fuente incoherentes")

    explicito = fila["plazo_explicito"] == "true"
    if explicito and fila["plazo_dias"] == "":
        errores.append("plazo_explicito=true pero plazo_dias vacío")
    if not explicito and fila["plazo_dias"] != "":
        errores.append("plazo_dias informado con plazo_explicito=false")
    if fila["plazo_es_cota"] == "true" and not explicito:
        errores.append("plazo_es_cota=true exige plazo_explicito=true")
    return errores


def recalcular_utilizable(fila: dict[str, str], archivos_vistos: set[str]) -> tuple[str, str]:
    """Aplica criterios_inclusion.md. Devuelve (utilizable, motivo_exclusion).

    I1: plazo explícito y numérico (> 0).       -> si falla: E2
    E3: revisión duplicada del mismo archivo.   -> E3
    I2: costo neto legible (> 0).               -> si falla: E4
    clase_obra NO filtra; plazo_es_cota NO excluye (se reporta aparte).
    """
    if fila["plazo_explicito"] != "true" or fila["plazo_dias"] == "":
        return "false", "E2"
    clave = fila["archivo_origen"]
    if fila["origen_dato"] == "real" and clave in archivos_vistos:
        return "false", "E3"
    if fila["costo_neto_clp"] == "":
        return "false", "E4"
    return "true", ""


def _nfc(texto: str) -> str:
    return unicodedata.normalize("NFC", texto)


def cargar_alias(avisos: list[str]) -> dict[str, str]:
    """Lee data/raw/alias_archivos.csv (alias -> nombre real). Vacío si no existe."""
    if not MAPA_ALIAS.exists():
        avisos.append("No existe data/raw/alias_archivos.csv; los alias no se resuelven.")
        return {}
    with MAPA_ALIAS.open(encoding="utf-8-sig", newline="") as f:
        return {_nfc(r["alias"]): _nfc(r["archivo_real"]) for r in csv.DictReader(f)}


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

    ruta = Path(argv[1]) if len(argv) > 1 else CSV_POR_DEFECTO
    if not ruta.exists():
        print(f"ERROR: no existe {ruta}")
        return 2

    with ruta.open(encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f)
        encabezado = lector.fieldnames or []
        filas = list(lector)

    errores: list[str] = []
    avisos: list[str] = []

    faltantes = [c for c in ESQUEMA if c not in encabezado]
    sobrantes = [c for c in encabezado if c not in ESQUEMA]
    if faltantes:
        errores.append(f"Columnas faltantes: {faltantes}")
    if sobrantes:
        errores.append(f"Columnas no documentadas: {sobrantes}")
    if faltantes:
        _imprimir(ruta, filas, errores, avisos, Counter(), 0, [])
        return 1

    ids = Counter(f["id_caso"] for f in filas)
    for id_dup, n in ids.items():
        if n > 1:
            errores.append(f"id_caso duplicado: {id_dup} ({n} veces)")

    errores_dominio = 0
    discrepancias: list[str] = []
    archivos_vistos: set[str] = set()
    motivos = Counter()

    for fila in filas:
        idc = fila["id_caso"] or "?"
        for col in ESQUEMA:
            msg = validar_campo(col, fila[col].strip())
            if msg:
                errores.append(f"[{idc}] {msg}")
                errores_dominio += 1
        for msg in validar_coherencia(fila):
            errores.append(f"[{idc}] {msg}")

        util, motivo = recalcular_utilizable(fila, archivos_vistos)
        if fila["origen_dato"] == "real":
            archivos_vistos.add(fila["archivo_origen"])
        if (util, motivo) != (fila["utilizable"], fila["motivo_exclusion"]):
            discrepancias.append(
                f"[{idc}] CSV utilizable={fila['utilizable']}/{fila['motivo_exclusion'] or '-'}"
                f" vs recalculado {util}/{motivo or '-'}"
            )
        if motivo:
            motivos[motivo] += 1

    errores.extend(f"Discrepancia de criterios: {d}" for d in discrepancias)

    reales = [f for f in filas if f["origen_dato"] == "real"]
    if reales and all(f["costo_neto_uf"] == "" for f in reales):
        avisos.append("costo_neto_uf vacía en todas las filas reales (UF pendiente de carga; ver diccionario, sección Fuente de la UF).")
    if reales and all(f["numero_pisos"] == "" for f in reales):
        avisos.append("numero_pisos no informado en ningún caso real (ver hallazgos_hu13.md).")
    if reales and all(f["estandar_terminaciones"] == "ni" for f in reales):
        avisos.append("estandar_terminaciones = 'ni' en todos los casos reales (ver hallazgos_hu13.md).")
    if reales and all(f["tipo_plazo"] == "ofertado" for f in reales):
        avisos.append("Todos los plazos reales son ofertados; ninguno ejecutado.")

    if DIR_RAW.exists():
        alias = cargar_alias(avisos)
        en_disco = {_nfc(p.name) for p in DIR_RAW.glob("*.pdf")}
        referenciados = set()
        for f in reales:
            nombre = _nfc(alias.get(_nfc(f["archivo_origen"]), f["archivo_origen"]))
            referenciados.add(nombre)
            if nombre not in en_disco:
                avisos.append(f"[{f['id_caso']}] archivo_origen no encontrado en data/raw/: {f['archivo_origen']}")
        for nombre in sorted(en_disco - referenciados):
            avisos.append(f"PDF en data/raw/ sin fila en el dataset: {nombre}")
    else:
        avisos.append("data/raw/ no existe en esta máquina; se omite el cruce con los PDF.")

    _imprimir(ruta, filas, errores, avisos, motivos, errores_dominio, discrepancias)
    return 1 if errores else 0


def _imprimir(ruta, filas, errores, avisos, motivos, errores_dominio, discrepancias) -> None:
    util = [f for f in filas if f.get("utilizable") == "true"]
    print("=" * 64)
    print("Validación dataset HU-13")
    print(f"Archivo: {ruta}")
    print("=" * 64)
    print(f"Filas totales:              {len(filas)}")
    print(f"  por origen_dato:          {dict(Counter(f.get('origen_dato') for f in filas))}")
    print(f"  por clase_obra:           {dict(Counter(f.get('clase_obra') for f in filas))}")
    print(f"Utilizables (CSV):          {len(util)}")
    print(f"  por clase_obra:           {dict(Counter(f.get('clase_obra') for f in util))}")
    cotas = [f["id_caso"] for f in util if f.get("plazo_es_cota") == "true"]
    print(f"  con plazo_es_cota=true:   {len(cotas)} {cotas} (se reportan aparte)")
    print(f"No utilizables por motivo:  {dict(motivos)}")
    print(f"  ids E2:                   {[f['id_caso'] for f in filas if f.get('motivo_exclusion') == 'E2']}")
    print(f"Errores de dominio/tipo:    {errores_dominio}")
    print(f"Discrepancias de criterios: {len(discrepancias)}")
    print(f"Errores totales:            {len(errores)}")
    for e in errores:
        print(f"  ERROR  {e}")
    print(f"Avisos:                     {len(avisos)}")
    for a in avisos:
        print(f"  AVISO  {a}")
    print("Resultado:", "OK" if not errores else "CON ERRORES")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
