"""Exporta el modelo de plazo vigente a JSON para el backend (sin numpy ni joblib).

El backend no carga el .joblib: lee este JSON con la biblioteca estándar. Se copian
los parámetros tal cual (floats completos, sin redondear), así la predicción es
idéntica a `predict.predecir_plazo`. El dominio conocido sale del propio dataset de
entrenamiento (`ids_entrenamiento` del artefacto), no de valores escritos a mano.

El .joblib de P2 es un diccionario de tipos básicos. Se abre con un unpickler que
rechaza cualquier clase: si una versión futura serializa un estimador (Ridge, etc.),
este script falla y hay que exportar sus coeficientes explícitamente.

Uso:
    python ml/src/exportar_backend.py [--version v1.0-2026-11-01] [--salida backend/app/modelos]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pickle
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
DIR_MODELOS = RAIZ / "ml" / "models"
DATASET = RAIZ / "ml" / "data" / "processed" / "presupuestos_reales.csv"
SALIDA = RAIZ / "backend" / "app" / "modelos"
FORMATO = 1

# Traducción de los tipos de obra de BuildCast al vocabulario del modelo. Es una
# decisión de integración, no algo aprendido: viaja con la versión para que una
# versión futura pueda cambiarla sin tocar estimaciones antiguas.
#   Ampliación: hay ampliaciones reales en el entrenamiento.
#   Vivienda unifamiliar y Edificación habitacional: obra nueva completa, que el
#   modelo solo conoce por su clase (edificación); obra_nueva no tiene casos reales.
TRADUCCION_TIPO_OBRA = {
    "Ampliación": "ampliacion",
    "Vivienda unifamiliar": "obra_nueva",
    "Edificación habitacional": "obra_nueva",
}


class _SinClases(pickle.Unpickler):
    def find_class(self, modulo, nombre):
        raise pickle.UnpicklingError(f"el artefacto referencia {modulo}.{nombre}; exporte sus parámetros a mano")


def leer_artefacto(ruta: Path) -> dict:
    with ruta.open("rb") as f:
        return _SinClases(f).load()


def dominio(art: dict, ruta_dataset: Path = DATASET) -> dict:
    with ruta_dataset.open(encoding="utf-8") as f:
        filas = {r["id_caso"]: r for r in csv.DictReader(f)}
    faltan = [i for i in art["ids_entrenamiento"] if i not in filas]
    if faltan:
        raise SystemExit(f"ERROR: casos de entrenamiento ausentes del dataset: {faltan}")
    usados = [filas[i] for i in art["ids_entrenamiento"]]
    uf = [float(r["costo_neto_uf"]) for r in usados]
    plazos = [int(r["plazo_dias"]) for r in usados]
    return {
        "costo_uf_min": min(uf),
        "costo_uf_max": max(uf),
        "plazo_dias_min": min(plazos),
        "plazo_dias_max": max(plazos),
        "tipos_obra_representados": sorted({r["tipo_obra"] for r in usados}),
        "filas_entrenamiento": len(usados),
        "ids_entrenamiento": list(art["ids_entrenamiento"]),
        "tipo_plazo": "ofertado",
    }


def exportar(version: str, salida: Path = SALIDA) -> Path:
    ruta_joblib = DIR_MODELOS / f"plazo_{version}.joblib"
    art = leer_artefacto(ruta_joblib)
    if art["algoritmo"] != "parametrica":
        raise SystemExit(f"ERROR: solo se exporta la regla paramétrica; esta versión es {art['algoritmo']}.")
    desconocidos = sorted(set(TRADUCCION_TIPO_OBRA.values()) - set(art["tipo_a_clase"]))
    if desconocidos:
        raise SystemExit(f"ERROR: la traducción usa tipos fuera del vocabulario del modelo: {desconocidos}")

    intervalo = {k: art["intervalo"][k] for k in ("q_inf_log", "q_sup_log", "percentiles", "metodo_percentil")}
    exportado = {
        "formato": FORMATO,
        "objetivo": "plazo",
        "version": art["version"],
        "metodo": art["metodo"],
        "algoritmo": art["algoritmo"],
        "entrenado_en": art["entrenado_en"],
        "estado": "provisional" if art["provisional"] else "validado",
        "validado": bool(art["validado"]),
        "provisional": bool(art["provisional"]),
        "parametros": dict(art["parametros"]),
        "tipo_a_clase": dict(art["tipo_a_clase"]),
        "traduccion_tipo_obra": TRADUCCION_TIPO_OBRA,
        "intervalo": intervalo,
        "mediana_respaldo": dict(art["mediana_respaldo"]),
        "dominio": dominio(art),
        "metricas_loo": dict(art["metricas_loo"]),
        "fuente_uf": art["fuente_uf"],
        "origen": {
            "artefacto": f"ml/models/{ruta_joblib.name}",
            "sha256": hashlib.sha256(ruta_joblib.read_bytes()).hexdigest(),
        },
        "observaciones": (
            "Versión provisional. Regla paramétrica P2 calibrada con la totalidad del dataset "
            "histórico disponible (13 presupuestos reales de RAM, plazos ofertados). Fuera del rango "
            "de costo o de los tipos de obra representados, el resultado es una extrapolación. "
            "No se usaron datos sintéticos."
        ),
    }
    salida.mkdir(parents=True, exist_ok=True)
    destino = salida / f"plazo_{art['version']}.json"
    destino.write_text(json.dumps(exportado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destino


PARIDAD = RAIZ / "backend" / "tests" / "datos"

# Costos (CLP) y fechas de la caché de UF: cubren todo el rango del entrenamiento,
# los bordes y extrapolaciones grandes. Son entradas de prueba, no datos de entrenamiento.
COSTOS_PARIDAD = [1, 500_000, 577_300, 1_700_004, 3_869_750, 6_499_800, 12_000_000,
                  17_640_000, 40_000_000, 60_000_000, 150_000_000, 400_000_000, 2_000_000_000]
FECHAS_PARIDAD = ["2025-11-16", "2026-02-09", "2026-05-05", "2026-11-03", "2026-11-09"]


def casos_paridad(version: str) -> dict:
    """Salidas de predict.predecir_plazo (el original) para comparar con el backend.

    Requiere el entorno de ML (numpy, joblib): importa predict.py tal cual.
    """
    import os

    import predict
    from uf import uf_del_dia

    anterior = os.environ.get(predict.VARIABLE_RUTA)
    os.environ[predict.VARIABLE_RUTA] = str(DIR_MODELOS / f"plazo_{version}.joblib")
    try:
        casos = []
        for tipo in sorted(predict._artefacto()["tipo_a_clase"]):
            for costo in COSTOS_PARIDAD:
                for fecha in FECHAS_PARIDAD:
                    r = predict.predecir_plazo(tipo, costo, fecha)
                    casos.append({"tipo_obra_modelo": tipo, "costo_neto_clp": costo, "fecha": fecha,
                                  "uf": uf_del_dia(fecha), **r})
    finally:
        if anterior is None:
            os.environ.pop(predict.VARIABLE_RUTA, None)
        else:
            os.environ[predict.VARIABLE_RUTA] = anterior
    return {"version": version, "generado_con": "ml/src/predict.py", "casos": casos}


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", default="v1.0-2026-11-01")
    ap.add_argument("--salida", type=Path, default=SALIDA)
    ap.add_argument("--paridad", action="store_true",
                    help="además, escribe los casos de paridad con predict.py (requiere el entorno de ML)")
    args = ap.parse_args(argv)
    print(f"Exportado: {exportar(args.version, args.salida)}")
    if args.paridad:
        PARIDAD.mkdir(parents=True, exist_ok=True)
        destino = PARIDAD / f"paridad_plazo_{args.version}.json"
        destino.write_text(json.dumps(casos_paridad(args.version), ensure_ascii=False, indent=1) + "\n",
                           encoding="utf-8")
        print(f"Casos de paridad: {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
