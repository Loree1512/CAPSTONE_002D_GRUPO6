"""Lecturas independientes a la base en paralelo.

Cada consulta a Supabase es un viaje de red de ~100 ms o más; el motor de costos tarda
menos de 1 ms. Hacer en serie lecturas que no dependen entre sí suma esos viajes sin
necesidad. Solo para LECTURAS: una escritura que depende de otra va en orden.
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, List


def en_paralelo(*tareas: Callable[[], Any]) -> List[Any]:
    """Corre las tareas a la vez y devuelve sus resultados en el mismo orden.

    Si varias fallan, lanza la excepción de la primera en el orden recibido: el error que
    ve quien llama es el mismo que habría visto ejecutándolas en serie.
    """
    if len(tareas) <= 1:
        return [tarea() for tarea in tareas]

    with ThreadPoolExecutor(max_workers=len(tareas)) as pool:
        futuros = [pool.submit(tarea) for tarea in tareas]
        # result() relanza la excepción de cada tarea, en orden.
        return [futuro.result() for futuro in futuros]
