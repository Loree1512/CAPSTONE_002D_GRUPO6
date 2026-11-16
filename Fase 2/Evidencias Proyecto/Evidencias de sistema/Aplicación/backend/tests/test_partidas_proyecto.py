"""Partidas del proyecto y plantillas, con un cliente falso que imita PostgREST + RLS.

Las RPC del falso reproducen lo que hacen las de 005_partidas_proyecto_y_plantillas.sql.

Ejecutar desde backend/:
    python -m pytest            (o python -m unittest discover -s tests -v)
"""

import copy
import itertools
import os
import re
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

# Valores ficticios antes de importar app.database: las pruebas nunca tocan Supabase.
os.environ.setdefault("SUPABASE_URL", "https://ejemplo.supabase.co")
os.environ.setdefault("SUPABASE_PUBLISHABLE_KEY", "clave-de-prueba")
os.environ.setdefault("SUPABASE_SECRET_KEY", "clave-de-prueba")

from fastapi import HTTPException  # noqa: E402
from postgrest.exceptions import APIError  # noqa: E402

from app.schemas.autenticacion import UsuarioActual  # noqa: E402
from app.schemas.partida_proyecto import (  # noqa: E402
    PartidaProyectoCrear,
    PartidaProyectoEditar,
    PartidasOrdenar,
    PlantillaAplicar,
)
from app.schemas.plantilla import PlantillaPartidasGuardar  # noqa: E402
from app.schemas.proyecto import ProyectoCrear  # noqa: E402
from app.services.resumen_proyecto import firma_partidas  # noqa: E402
from app.services import (  # noqa: E402
    servicio_estimaciones,
    servicio_historial,
    servicio_partidas_proyecto,
    servicio_plantillas,
    servicio_proyectos,
)


def _error(codigo, mensaje="error"):
    return APIError({"code": codigo, "message": mensaje, "hint": None, "details": None})


_segundos = itertools.count()


def _ahora():
    # Como now(): cada evento queda después del anterior.
    return (datetime(2026, 10, 20, 10, tzinfo=timezone.utc) + timedelta(seconds=next(_segundos))).isoformat()


# --- Base de datos falsa -------------------------------------------------------------

class _Respuesta:
    def __init__(self, data):
        self.data = data


class _Consulta:
    def __init__(self, cliente, tabla):
        self.cliente, self.tabla = cliente, tabla
        self.filtros, self.dentro, self.parecidos = [], [], []
        self.orden, self.limite, self.una = [], None, False
        self.accion, self.valores = "select", None

    def select(self, columnas="*", *_a, **_k):
        self.columnas = columnas
        return self

    def eq(self, columna, valor):
        # "tabla.columna" filtra un recurso embebido, no las filas principales.
        if "." not in columna:
            self.filtros.append((columna, valor))
        return self

    def ilike(self, columna, patron):
        # Como PostgREST: sin mayúsculas; % y * valen cualquier texto, _ un carácter, \ escapa.
        regex = "".join(
            ".*" if p in ("%", "*") else "." if p == "_" else re.escape(p[1:] if p.startswith("\\") else p)
            for p in re.findall(r"\\.|[%*_]|[^\\%*_]+", patron)
        )
        self.parecidos.append((columna, re.compile(regex, re.I | re.S)))
        return self

    def in_(self, columna, valores):
        self.dentro.append((columna, [str(v) for v in valores]))
        return self

    def order(self, columna, desc=False, **_k):
        self.orden.append((columna, desc))
        return self

    def limit(self, n, **_k):
        # Con foreign_table limita el recurso embebido, no las filas principales.
        if "foreign_table" not in _k:
            self.limite = n
        return self

    def maybe_single(self):
        self.una = True
        return self

    def insert(self, valores):
        self.accion, self.valores = "insert", valores
        return self

    def upsert(self, valores, on_conflict=""):
        self.accion, self.valores, self.conflicto = "upsert", valores, on_conflict.split(",")
        return self

    def update(self, valores):
        self.accion, self.valores = "update", valores
        return self

    def delete(self):
        self.accion = "delete"
        return self

    def _embebidos(self, fila):
        # Como PostgREST: la última estimación y las partidas del proyecto, si se piden.
        columnas = getattr(self, "columnas", "*")
        db = self.cliente.db
        if "estimaciones(" in columnas:
            propias = [e for e in db.get("estimaciones", []) if e["proyecto_id"] == fila["id"]]
            fila["estimaciones"] = copy.deepcopy(sorted(propias, key=lambda e: e["fecha_creacion"], reverse=True)[:1])
        if "proyecto_partidas(" in columnas:
            fila["proyecto_partidas"] = copy.deepcopy(
                [f for f in db["proyecto_partidas"] if f["proyecto_id"] == fila["id"]])
        # Muchos a uno por la FK estimaciones.version_modelo: un objeto o null.
        if self.tabla == "estimaciones" and "versiones_modelo(" in columnas:
            fila["versiones_modelo"] = copy.deepcopy(next(
                (v for v in db.get("versiones_modelo", []) if v["version"] == fila.get("version_modelo")), None))
        return fila

    def _coincide(self, fila):
        return all(str(fila.get(c)) == str(v) for c, v in self.filtros) and \
            all(str(fila.get(c)) in vs for c, vs in self.dentro) and \
            all(r.fullmatch(str(fila.get(c) or "")) for c, r in self.parecidos)

    def execute(self):
        db = self.cliente.db
        if self.accion == "insert":
            filas = self.valores if isinstance(self.valores, list) else [self.valores]
            creadas = [self.cliente.insertar(self.tabla, dict(f)) for f in filas]
            return _Respuesta(copy.deepcopy(creadas))

        if self.accion == "upsert":
            existente = next((f for f in db[self.tabla]
                              if all(str(f.get(c)) == str(self.valores[c]) for c in self.conflicto)), None)
            if existente is not None:
                existente.update(self.valores)
                return _Respuesta([copy.deepcopy(existente)])
            return _Respuesta([copy.deepcopy(self.cliente.insertar(self.tabla, dict(self.valores)))])

        visibles = [f for f in db[self.tabla] if self.cliente.visible(self.tabla, f) and self._coincide(f)]

        if self.accion in ("update", "delete"):
            self.cliente.exigir_escritura(self.tabla)
            modificable = self.cliente.modificable if self.accion == "update" else self.cliente.eliminable
            visibles = [f for f in visibles if modificable(self.tabla, f)]

        if self.accion == "update":
            for fila in visibles:
                fila.update(self.valores)
            return _Respuesta(copy.deepcopy(visibles))

        if self.accion == "delete":
            db[self.tabla] = [f for f in db[self.tabla] if not any(f is v for v in visibles)]
            if self.tabla == "proyectos":
                self.cliente.borrar_en_cascada([f["id"] for f in visibles])
            return _Respuesta(copy.deepcopy(visibles))

        for columna, desc in reversed(self.orden):
            visibles.sort(key=lambda f: (f.get(columna) is None, f.get(columna)), reverse=desc)
        if self.limite is not None:
            visibles = visibles[: self.limite]
        datos = copy.deepcopy(visibles)
        if self.tabla in ("proyectos", "estimaciones"):
            datos = [self._embebidos(fila) for fila in datos]
        if self.una:
            return _Respuesta(datos[0]) if datos else None
        return _Respuesta(datos)


class _Rpc:
    def __init__(self, funcion):
        self.funcion = funcion

    def execute(self):
        return _Respuesta(self.funcion())


class ClienteFalso:
    """Ve lo que RLS dejaría ver al dueño del token; admin ve todo.

    Por defecto imita las políticas actuales (001: solo el dueño). Con
    con_miembros=True imita las de membresía que traerá la 003: los miembros leen
    y solo propietario y editor escriben.
    """

    def __init__(self, db, uid=None, admin=False, con_miembros=False):
        self.db, self.uid, self.admin, self.con_miembros = db, uid, admin, con_miembros
        self.rpcs = []

    def _propio(self, proyecto_id, uid=None):
        uid = uid or self.uid
        return any(p["id"] == str(proyecto_id) and p["usuario_id"] == uid for p in self.db["proyectos"])

    def _rol(self, proyecto_id, uid=None):
        uid = uid or self.uid
        return next((m["rol"] for m in self.db.get("proyecto_miembros", [])
                     if m["proyecto_id"] == str(proyecto_id) and m["usuario_id"] == uid), None)

    def _lee(self, proyecto_id):
        return self._propio(proyecto_id) or (self.con_miembros and self._rol(proyecto_id) is not None)

    def _escribe(self, proyecto_id, uid=None):
        return self._propio(proyecto_id, uid) or (
            self.con_miembros and self._rol(proyecto_id, uid) in ("propietario", "editor"))

    def visible(self, tabla, fila):
        if self.admin:
            return True
        if tabla == "proyectos":
            return self._lee(fila["id"])
        if tabla in ("proyecto_partidas", "estimaciones"):
            return self._lee(fila["proyecto_id"])
        if tabla == "estimacion_partidas":
            return any(e["id"] == fila["estimacion_id"] and self._lee(e["proyecto_id"]) for e in self.db["estimaciones"])
        if tabla == "proyecto_miembros":
            # Política de la 002: los miembros ven quiénes integran su proyecto.
            return self._rol(fila["proyecto_id"]) is not None
        if tabla == "historial_proyecto":
            return self._lee(fila["proyecto_id"])
        if tabla == "administradores_principales":
            # Política de la 005: cada usuario ve solo su propia fila.
            return fila["perfil_id"] == self.uid
        return True

    def modificable(self, tabla, fila):
        if self.admin:
            return True
        if tabla == "proyectos":
            return self._escribe(fila["id"])
        if tabla == "proyecto_partidas":
            return self._escribe(fila["proyecto_id"])
        return True

    def eliminable(self, tabla, fila):
        # 004: solo el propietario borra un proyecto.
        if tabla == "proyectos" and not self.admin:
            return self._propio(fila["id"]) or (self.con_miembros and self._rol(fila["id"]) == "propietario")
        return self.modificable(tabla, fila)

    def borrar_en_cascada(self, proyecto_ids):
        # on delete cascade.
        ids = set(proyecto_ids)
        db = self.db
        estimaciones = {e["id"] for e in db.get("estimaciones", []) if e["proyecto_id"] in ids}
        db["estimacion_partidas"] = [f for f in db.get("estimacion_partidas", [])
                                     if f["estimacion_id"] not in estimaciones]
        for tabla in ("estimaciones", "proyecto_partidas", "proyecto_miembros", "historial_proyecto"):
            if tabla in db:
                db[tabla] = [f for f in db[tabla] if f["proyecto_id"] not in ids]

    def exigir_escritura(self, tabla):
        # 003: proyecto_miembros solo se escribe con sus RPC, tampoco con service role.
        if tabla == "proyecto_miembros" and self.con_miembros:
            raise _error("42501", "permission denied for table proyecto_miembros")

    def insertar(self, tabla, fila):
        if not self.admin:
            if tabla == "proyectos" and fila.get("usuario_id") != self.uid:
                raise _error("42501", "RLS")
            if tabla == "proyecto_partidas" and not self._escribe(fila["proyecto_id"]):
                raise _error("42501", "RLS")
        if tabla == "proyecto_partidas" and (fila["origen"] == "manual") != (fila.get("partida_id") is None):
            raise _error("23514")
        self.exigir_escritura(tabla)
        if tabla == "proyecto_miembros" and any(
                m["proyecto_id"] == fila["proyecto_id"] and m["usuario_id"] == fila["usuario_id"]
                for m in self.db.get("proyecto_miembros", [])):
            # unique (proyecto_id, usuario_id)
            raise _error("23505")
        fila.setdefault("id", str(uuid4()))
        if tabla == "estimaciones":
            # Como now(): cada estimación queda después de la anterior.
            fila.setdefault("fecha_creacion", _ahora())
        fila.setdefault("fecha_creacion", "2026-09-27T10:00:00+00:00")
        fila.setdefault("fecha_actualizacion", "2026-09-27T10:00:00+00:00")
        if tabla == "proyectos":
            fila.setdefault("estado", "borrador")
            fila.setdefault("plantilla_id", None)
        if tabla == "proyecto_partidas":
            for campo in ("cantidad", "precio_unitario_override", "observacion"):
                fila.setdefault(campo, None)
        if tabla == "historial_proyecto":
            fila.setdefault("fecha", _ahora())
        self.db[tabla].append(fila)
        if tabla == "proyectos" and fila.get("usuario_id"):
            # Trigger de la 002: el creador queda como propietario.
            self.db.setdefault("proyecto_miembros", []).append({
                "id": str(uuid4()), "proyecto_id": fila["id"], "usuario_id": fila["usuario_id"],
                "rol": "propietario", "agregado_por": fila["usuario_id"],
            })
        return fila

    def table(self, nombre):
        return _Consulta(self, nombre)

    def rpc(self, nombre, parametros):
        self.rpcs.append((nombre, copy.deepcopy(parametros)))
        return _Rpc(lambda: getattr(self, "_rpc_" + nombre)(**parametros))

    # Mismo comportamiento que las funciones SQL de la migración 005.

    def _rpc_aplicar_plantilla_proyecto(self, p_proyecto_id, p_plantilla_id, p_partidas, p_reemplazar=False):
        # El for update de la función exige poder modificar el proyecto.
        if not any(self.modificable("proyectos", p) and p["id"] == p_proyecto_id for p in self.db["proyectos"]):
            raise _error("P0002", "Proyecto no encontrado")
        actuales = [f for f in self.db["proyecto_partidas"] if f["proyecto_id"] == p_proyecto_id]
        if actuales and not p_reemplazar:
            raise _error("55000", "El proyecto ya tiene partidas. Confirma si quieres reemplazarlas.")
        self.db["proyecto_partidas"] = [f for f in self.db["proyecto_partidas"] if f["proyecto_id"] != p_proyecto_id]
        for r in p_partidas:
            self.insertar("proyecto_partidas", {
                "proyecto_id": p_proyecto_id, "partida_id": r["partida_id"], "categoria_id": r["categoria_id"],
                "nombre": r["nombre"], "unidad": r["unidad"], "cantidad": r.get("cantidad"),
                "precio_unitario_override": None, "origen": "plantilla", "orden": r["orden"], "observacion": None,
            })
        for p in self.db["proyectos"]:
            if p["id"] == p_proyecto_id:
                p["plantilla_id"] = p_plantilla_id
        return copy.deepcopy(sorted(
            (f for f in self.db["proyecto_partidas"] if f["proyecto_id"] == p_proyecto_id), key=lambda f: f["orden"]
        ))

    def _rpc_crear_proyecto_con_plantilla(self, p_proyecto, p_plantilla_id, p_partidas):
        # Una transacción: ante cualquier error, la base queda como estaba.
        respaldo = copy.deepcopy(self.db)
        try:
            proyecto = self.insertar("proyectos", dict(p_proyecto))
            self._rpc_aplicar_plantilla_proyecto(proyecto["id"], p_plantilla_id, p_partidas, False)
            return copy.deepcopy(proyecto)
        except APIError:
            self.db.clear()
            self.db.update(respaldo)
            raise

    def _rpc_crear_estimacion(self, p_usuario_id, p_estimacion, p_partidas):
        # 001: solo el dueño. 003: propietario o editor; un lector recibe 42501.
        if not self._escribe(p_estimacion["proyecto_id"], p_usuario_id):
            if self.con_miembros and self._rol(p_estimacion["proyecto_id"], p_usuario_id):
                raise _error("42501", "Tu permiso en este proyecto no permite generar estimaciones.")
            raise _error("P0002", "El proyecto no existe.")
        fila = copy.deepcopy(p_estimacion)
        # 009: FK a versiones_modelo, estado por defecto y columna generada.
        version = fila.get("version_modelo")
        if version and "versiones_modelo" in self.db and not any(
                v["version"] == version for v in self.db["versiones_modelo"]):
            raise _error("23503", "insert or update on table \"estimaciones\" violates foreign key constraint")
        fila["plazo_estado"] = fila.get("plazo_estado") or "no_disponible"
        fila["plazo_fuera_dominio"] = fila["plazo_estado"] != "dentro_dominio"
        # 010: el plazo profesional nunca viene del payload. Si la anterior lo tenía
        # definido o por revisar, la nueva queda por revisar con los mismos datos.
        fila.update(self._profesional_tras_recalcular(p_estimacion["proyecto_id"]))
        estimacion = self.insertar("estimaciones", {**fila, "usuario_id": p_usuario_id})
        for linea in p_partidas:
            self.insertar("estimacion_partidas", {**copy.deepcopy(linea), "estimacion_id": estimacion["id"]})
        return copy.deepcopy(estimacion)

    def _rpc_actualizar_cotizacion(self, p_usuario_id, p_estimacion_id, p_observaciones):
        # 006: copia la última estimación con otra observación; no recalcula.
        origen = next((e for e in self.db["estimaciones"] if e["id"] == p_estimacion_id), None)
        pid = origen["proyecto_id"] if origen else None
        if origen is None or not (self._propio(pid, p_usuario_id) or self._rol(pid, p_usuario_id)):
            raise _error("P0002", "Estimación no encontrada")
        if not self._escribe(pid, p_usuario_id):
            raise _error("42501", "Tu permiso en este proyecto no permite actualizar la cotización.")
        propias = [e for e in self.db["estimaciones"] if e["proyecto_id"] == pid]
        if max(propias, key=lambda e: (e["fecha_creacion"], e["id"]))["id"] != origen["id"]:
            raise _error("55000", "Solo se puede actualizar la cotización de la estimación más reciente.")
        observaciones = (p_observaciones or "").strip() or None
        if observaciones == origen.get("observaciones"):
            raise _error("55000", "La observación no cambió.")
        copia = {k: copy.deepcopy(v) for k, v in origen.items() if k not in ("id", "fecha_creacion")}
        nueva = self.insertar("estimaciones", {**copia, "usuario_id": p_usuario_id, "observaciones": observaciones})
        for linea in [l for l in self.db["estimacion_partidas"] if l["estimacion_id"] == origen["id"]]:
            datos = {k: copy.deepcopy(v) for k, v in linea.items() if k != "id"}
            self.insertar("estimacion_partidas", {**datos, "estimacion_id": nueva["id"]})
        return copy.deepcopy(nueva)

    COLUMNAS_PROFESIONAL = ("plazo_profesional_dias", "plazo_profesional_estado", "plazo_profesional_origen",
                            "plazo_profesional_fecha", "plazo_profesional_usuario_id")

    def _ultima_estimacion(self, proyecto_id):
        propias = [e for e in self.db["estimaciones"] if e["proyecto_id"] == proyecto_id]
        return max(propias, key=lambda e: (e["fecha_creacion"], e["id"])) if propias else None

    def _profesional_tras_recalcular(self, proyecto_id):
        previa = self._ultima_estimacion(proyecto_id) or {}
        if previa.get("plazo_profesional_estado") in ("definido", "por_revisar"):
            return {**{c: previa.get(c) for c in self.COLUMNAS_PROFESIONAL}, "plazo_profesional_estado": "por_revisar"}
        return {**{c: None for c in self.COLUMNAS_PROFESIONAL}, "plazo_profesional_estado": "sin_definir"}

    def _rpc_definir_plazo_profesional(self, p_usuario_id, p_estimacion_id, p_dias, p_origen):
        # 010: copia la última estimación con el plazo profesional definido; no recalcula.
        origen = next((e for e in self.db["estimaciones"] if e["id"] == p_estimacion_id), None)
        pid = origen["proyecto_id"] if origen else None
        if origen is None or not (self._propio(pid, p_usuario_id) or self._rol(pid, p_usuario_id)):
            raise _error("P0002", "Estimación no encontrada")
        if not self._escribe(pid, p_usuario_id):
            raise _error("42501", "Tu permiso en este proyecto no permite definir el plazo para la cotización.")
        if self._ultima_estimacion(pid)["id"] != origen["id"]:
            raise _error("55000", "Solo se puede definir el plazo de la estimación más reciente.")
        if p_origen not in ("sugerencia", "manual"):
            raise _error("22023", "El origen del plazo debe ser sugerencia o manual.")
        if p_origen == "sugerencia":
            dias = origen.get("plazo_dias")
            if dias is None:
                raise _error("55000", "Esta estimación no tiene un plazo sugerido por el modelo.")
        else:
            dias = p_dias
            if dias is None or not 1 <= dias <= 3650:
                raise _error("22023", "El plazo debe ser un número entero de días entre 1 y 3650.")
        if origen.get("plazo_profesional_estado") == "definido" and origen.get("plazo_profesional_dias") == dias:
            raise _error("55000", "El plazo para la cotización no cambió.")
        copia = {k: copy.deepcopy(v) for k, v in origen.items() if k not in ("id", "fecha_creacion")}
        nueva = self.insertar("estimaciones", {
            **copia, "usuario_id": p_usuario_id,
            "plazo_profesional_dias": dias, "plazo_profesional_estado": "definido",
            "plazo_profesional_origen": p_origen, "plazo_profesional_fecha": _ahora(),
            "plazo_profesional_usuario_id": p_usuario_id,
        })
        for linea in [l for l in self.db["estimacion_partidas"] if l["estimacion_id"] == origen["id"]]:
            datos = {k: copy.deepcopy(v) for k, v in linea.items() if k != "id"}
            self.insertar("estimacion_partidas", {**datos, "estimacion_id": nueva["id"]})
        return copy.deepcopy(nueva)

    def _rpc_ordenar_partidas_proyecto(self, p_proyecto_id, p_ids):
        if not self._escribe(p_proyecto_id):
            raise _error("P0002", "Proyecto no encontrado")
        propias = [f for f in self.db["proyecto_partidas"] if f["proyecto_id"] == p_proyecto_id]
        if sorted(p_ids) != sorted(f["id"] for f in propias):
            raise _error("22023", "El nuevo orden debe incluir todas las partidas del proyecto.")
        for n, id_ in enumerate(p_ids, start=1):
            next(f for f in propias if f["id"] == id_)["orden"] = n
        return copy.deepcopy(sorted(propias, key=lambda f: f["orden"]))

    # RPC de miembros de la 003: el cambio y su evento van en una transacción.

    falla_historial = False

    def _transaccion(self, operacion):
        respaldo = copy.deepcopy(self.db)
        try:
            return operacion()
        except APIError:
            self.db.clear()
            self.db.update(respaldo)
            raise

    def _comprobar_propietario(self, solicitante, proyecto_id):
        proyecto = next((p for p in self.db["proyectos"] if p["id"] == proyecto_id), None)
        rol = self._rol(proyecto_id, solicitante)
        creador = proyecto["usuario_id"] if proyecto else None
        if proyecto is None or (rol is None and creador != solicitante):
            raise _error("P0002", "Proyecto no encontrado")
        if creador != solicitante and rol != "propietario":
            raise _error("42501", "Solo el propietario administra los miembros del proyecto.")
        return creador

    def _perfil(self, usuario_id):
        return next((p for p in self.db["perfiles"] if p["id"] == usuario_id), {})

    def _evento(self, proyecto_id, solicitante, accion, entidad_id, anteriores=None, nuevos=None):
        if self.falla_historial:
            raise _error("XX000", "fallo deliberado del historial")
        self.db["historial_proyecto"].append({
            "id": str(uuid4()), "proyecto_id": proyecto_id, "usuario_id": solicitante,
            "usuario_email": self._perfil(solicitante).get("email"), "accion": accion, "entidad": "miembro",
            "entidad_id": entidad_id, "valores_anteriores": anteriores, "valores_nuevos": nuevos, "origen": "rpc",
            "fecha": _ahora(),
        })

    def _miembro(self, proyecto_id, usuario_id, creador, mensaje):
        fila = next((m for m in self.db["proyecto_miembros"]
                     if m["proyecto_id"] == proyecto_id and m["usuario_id"] == usuario_id), None)
        if usuario_id == creador or (fila and fila["rol"] == "propietario"):
            raise _error("55000", mensaje)
        if fila is None:
            raise _error("P0002", "El usuario no es miembro del proyecto.")
        return fila

    @staticmethod
    def _rol_asignable(rol):
        if rol not in ("editor", "lector"):
            raise _error("22023", "El permiso debe ser editor o lector.")

    def _respuesta_miembro(self, fila):
        perfil = self._perfil(fila["usuario_id"])
        return {"usuario_id": fila["usuario_id"], "email": perfil.get("email"), "nombre": perfil.get("nombre"),
                "rol": fila["rol"], "fecha_creacion": fila.get("fecha_creacion")}

    def _rpc_agregar_miembro_proyecto(self, p_solicitante_id, p_proyecto_id, p_email, p_rol):
        def operacion():
            creador = self._comprobar_propietario(p_solicitante_id, p_proyecto_id)
            self._rol_asignable(p_rol)
            buscado = (p_email or "").strip().lower()
            perfil = next((p for p in self.db["perfiles"] if (p.get("email") or "").strip().lower() == buscado), None)
            if perfil is None:
                raise _error("P0002", "No hay un usuario registrado con ese correo.")
            if perfil["id"] == creador or self._rol(p_proyecto_id, perfil["id"]):
                raise _error("23505", "El usuario ya es miembro del proyecto.")
            fila = {"id": str(uuid4()), "proyecto_id": p_proyecto_id, "usuario_id": perfil["id"], "rol": p_rol,
                    "agregado_por": p_solicitante_id, "fecha_creacion": "2026-10-12T10:00:00+00:00"}
            self.db["proyecto_miembros"].append(fila)
            self._evento(p_proyecto_id, p_solicitante_id, "miembro_agregado", perfil["id"],
                         nuevos={"usuario_id": perfil["id"], "email": perfil.get("email"), "rol": p_rol})
            return self._respuesta_miembro(fila)
        return self._transaccion(operacion)

    def _rpc_cambiar_rol_miembro_proyecto(self, p_solicitante_id, p_proyecto_id, p_usuario_id, p_rol):
        def operacion():
            creador = self._comprobar_propietario(p_solicitante_id, p_proyecto_id)
            self._rol_asignable(p_rol)
            fila = self._miembro(p_proyecto_id, p_usuario_id, creador,
                                 "El propietario del proyecto no puede cambiar de permiso.")
            if fila["rol"] != p_rol:
                anterior, fila["rol"] = fila["rol"], p_rol
                self._evento(p_proyecto_id, p_solicitante_id, "miembro_rol_cambiado", p_usuario_id,
                             anteriores={"rol": anterior},
                             nuevos={"rol": p_rol, "email": self._perfil(p_usuario_id).get("email")})
            return self._respuesta_miembro(fila)
        return self._transaccion(operacion)

    def _rpc_quitar_miembro_proyecto(self, p_solicitante_id, p_proyecto_id, p_usuario_id):
        def operacion():
            creador = self._comprobar_propietario(p_solicitante_id, p_proyecto_id)
            fila = self._miembro(p_proyecto_id, p_usuario_id, creador, "El propietario del proyecto no se puede quitar.")
            self.db["proyecto_miembros"] = [m for m in self.db["proyecto_miembros"] if m is not fila]
            self._evento(p_proyecto_id, p_solicitante_id, "miembro_eliminado", p_usuario_id,
                         anteriores={"usuario_id": p_usuario_id, "email": self._perfil(p_usuario_id).get("email"),
                                     "rol": fila["rol"]})
            return None
        return self._transaccion(operacion)

    def _rpc_guardar_partidas_plantilla(self, p_plantilla_id, p_partidas):
        self.db["plantilla_partidas"] = [f for f in self.db["plantilla_partidas"] if f["plantilla_id"] != p_plantilla_id]
        for r in p_partidas:
            self.insertar("plantilla_partidas", {"plantilla_id": p_plantilla_id, **r})
        return []


CATEGORIAS = [
    {"id": 1, "codigo": "01", "nombre": "Obras preliminares", "orden": 1, "vigente": True},
    {"id": 4, "codigo": "04", "nombre": "Obra gruesa y estructura", "orden": 4, "vigente": True},
]


def base_de_datos():
    faenas = {"id": str(uuid4()), "categoria_id": 1, "codigo": "01.01", "nombre": "Instalación de faenas",
              "unidad": "gl", "vigente": True}
    radier = {"id": str(uuid4()), "categoria_id": 4, "codigo": "04.01", "nombre": "Radier",
              "unidad": "m2", "vigente": True}
    baja = {"id": str(uuid4()), "categoria_id": 4, "codigo": "04.09", "nombre": "Partida dada de baja",
            "unidad": "m2", "vigente": False}
    version = {"id": str(uuid4()), "version": "2026-T3", "vigente": True}
    plantilla = {"id": str(uuid4()), "nombre": "Ampliación · Estructura metálica", "tipo_obra": "Ampliación",
                 "materialidad": "Estructura metálica", "vigente": True, "fecha_actualizacion": None}
    inactiva = {"id": str(uuid4()), "nombre": "Vieja", "tipo_obra": "Vivienda unifamiliar",
                "materialidad": "Hormigón armado", "vigente": False, "fecha_actualizacion": None}
    return {
        "proyectos": [],
        "proyecto_miembros": [],
        "proyecto_partidas": [],
        "historial_proyecto": [],
        "perfiles": [],
        "categorias_partida": copy.deepcopy(CATEGORIAS),
        "partidas": [faenas, radier, baja],
        "versiones_precios": [version],
        "precios_partida": [
            {"partida_id": radier["id"], "version_precio_id": version["id"], "precio_unitario": 16500},
        ],
        "plantillas_presupuesto": [plantilla, inactiva],
        "plantilla_partidas": [
            {"id": str(uuid4()), "plantilla_id": plantilla["id"], "partida_id": faenas["id"], "orden": 1,
             "cantidad_sugerida": 1},
            {"id": str(uuid4()), "plantilla_id": plantilla["id"], "partida_id": radier["id"], "orden": 2,
             "cantidad_sugerida": None},
            {"id": str(uuid4()), "plantilla_id": plantilla["id"], "partida_id": baja["id"], "orden": 3,
             "cantidad_sugerida": 5},
            {"id": str(uuid4()), "plantilla_id": inactiva["id"], "partida_id": faenas["id"], "orden": 1,
             "cantidad_sugerida": 1},
        ],
    }


def datos_proyecto(**cambios):
    datos = {
        "nombre": "Ampliación Quiroz", "comuna": "Quilpué", "tipo_obra": "Ampliación",
        "materialidad": "Estructura metálica", "superficie_m2": 48, "numero_pisos": 1,
        "estandar_terminaciones": "economico",
    }
    datos.update(cambios)
    return ProyectoCrear.model_validate(datos)


class PartidasDelProyecto(unittest.TestCase):

    def setUp(self):
        self.db = base_de_datos()
        self.a = UsuarioActual(id=uuid4(), email="a@x.cl", access_token="")
        self.b = UsuarioActual(id=uuid4(), email="b@x.cl", access_token="")
        self.a.access_token = f"token-{self.a.id}"
        self.b.access_token = f"token-{self.b.id}"
        self.clientes = []

        def cliente_de(token):
            cliente = ClienteFalso(self.db, uid=token.removeprefix("token-"))
            self.clientes.append(cliente)
            return cliente

        for modulo in (servicio_proyectos, servicio_partidas_proyecto, servicio_plantillas):
            parche = patch.object(modulo, "get_user_scoped_client", side_effect=cliente_de)
            parche.start()
            self.addCleanup(parche.stop)

        self.admin = ClienteFalso(self.db, admin=True)
        for modulo in (servicio_plantillas, servicio_historial):
            parche = patch.object(modulo, "supabase_admin", self.admin)
            parche.start()
            self.addCleanup(parche.stop)

        self.plantilla = self.db["plantillas_presupuesto"][0]
        self.faenas, self.radier, self.baja = self.db["partidas"]

    def partidas_de(self, proyecto_id):
        return sorted((f for f in self.db["proyecto_partidas"] if f["proyecto_id"] == proyecto_id),
                      key=lambda f: f["orden"])

    def rpcs(self):
        return [nombre for c in self.clientes for nombre, _ in c.rpcs]

    # --- Plantillas al crear --------------------------------------------------------

    def test_1_crear_proyecto_con_plantilla(self):
        proyecto = servicio_proyectos.crear_proyecto(self.a, datos_proyecto())
        self.assertEqual(proyecto["plantilla_id"], self.plantilla["id"])
        self.assertEqual(proyecto["estado_estimacion"], "sin_estimar")

        filas = self.partidas_de(proyecto["id"])
        # La partida dada de baja no se propone.
        self.assertEqual([f["nombre"] for f in filas], ["Instalación de faenas", "Radier"])
        self.assertEqual([f["origen"] for f in filas], ["plantilla", "plantilla"])
        self.assertEqual([f["cantidad"] for f in filas], ["1", None])
        self.assertEqual([f["unidad"] for f in filas], ["gl", "m2"])
        self.assertEqual([f["orden"] for f in filas], [1, 2])

        respuesta = servicio_partidas_proyecto.listar(self.a, proyecto["id"])
        self.assertEqual(respuesta["plantilla_aplicada"]["id"], self.plantilla["id"])
        radier = respuesta["partidas"][1]
        self.assertEqual((radier["precio_banco"], radier["estado"], radier["subtotal"]), (16500, "sin_cantidad", None))
        self.assertEqual(radier["codigo"], "04.01")
        self.assertEqual(respuesta["partidas"][0]["estado"], "sin_precio")

    def test_crear_con_plantilla_es_una_sola_operacion(self):
        servicio_proyectos.crear_proyecto(self.a, datos_proyecto())
        self.assertEqual(self.rpcs(), ["crear_proyecto_con_plantilla"])

    def test_si_falla_la_copia_no_queda_el_proyecto(self):
        invalida = [{"partida_id": None, "categoria_id": 4, "nombre": "x", "unidad": "m2", "cantidad": None, "orden": 1}]
        with patch.object(servicio_plantillas, "filas_desde_plantilla", return_value=invalida):
            with self.assertRaises(HTTPException) as error:
                servicio_proyectos.crear_proyecto(self.a, datos_proyecto())
        # Error visible (no silencioso) y sin proyecto a medias.
        self.assertEqual(error.exception.status_code, 422)
        self.assertEqual(self.db["proyectos"], [])
        self.assertEqual(self.db["proyecto_partidas"], [])

    def test_2_proyecto_sin_plantilla(self):
        proyecto = servicio_proyectos.crear_proyecto(
            self.a, datos_proyecto(tipo_obra="Vivienda unifamiliar", materialidad="Albañilería confinada")
        )
        self.assertIsNone(proyecto["plantilla_id"])
        self.assertEqual(self.partidas_de(proyecto["id"]), [])
        self.assertEqual(self.rpcs(), [])
        respuesta = servicio_partidas_proyecto.listar(self.a, proyecto["id"])
        self.assertEqual(respuesta["partidas"], [])
        self.assertIsNone(respuesta["plantilla_aplicada"])
        self.assertIsNone(respuesta["plantilla_sugerida"])

    def test_plantilla_no_vigente_no_se_aplica(self):
        proyecto = servicio_proyectos.crear_proyecto(
            self.a, datos_proyecto(tipo_obra="Vivienda unifamiliar", materialidad="Hormigón armado")
        )
        self.assertIsNone(proyecto["plantilla_id"])
        self.assertEqual(self.partidas_de(proyecto["id"]), [])

    def test_18_modificar_la_plantilla_no_cambia_proyectos_creados(self):
        proyecto = servicio_proyectos.crear_proyecto(self.a, datos_proyecto())
        antes = copy.deepcopy(self.partidas_de(proyecto["id"]))

        # La oficina reconfigura la plantilla y renombra una partida del catálogo.
        servicio_plantillas.guardar_partidas(
            self.plantilla["id"],
            PlantillaPartidasGuardar.model_validate({"partidas": [{"partida_id": self.radier["id"], "cantidad_sugerida": 99}]}),
        )
        self.radier["nombre"] = "Radier renombrado"

        self.assertEqual(self.partidas_de(proyecto["id"]), antes)
        detalle = servicio_plantillas.obtener(self.a, self.plantilla["id"])
        # En la base es numeric; el falso lo guarda como texto.
        self.assertEqual([(p["nombre"], float(p["cantidad_sugerida"])) for p in detalle["partidas"]],
                         [("Radier renombrado", 99)])

    # --- CRUD --------------------------------------------------------------------------

    def _proyecto_vacio(self, usuario=None):
        return servicio_proyectos.crear_proyecto(
            usuario or self.a, datos_proyecto(tipo_obra="Vivienda unifamiliar", materialidad="Albañilería confinada")
        )

    def test_3_crud_de_partidas(self):
        proyecto = self._proyecto_vacio()
        pid = proyecto["id"]

        desde_catalogo = servicio_partidas_proyecto.crear(self.a, pid, PartidaProyectoCrear.model_validate(
            {"origen": "catalogo", "partida_id": self.radier["id"], "cantidad": 3}
        ))
        self.assertEqual((desde_catalogo["nombre"], desde_catalogo["unidad"], desde_catalogo["categoria_id"]),
                         ("Radier", "m2", 4))
        self.assertEqual((desde_catalogo["precio_unitario"], desde_catalogo["subtotal"]), (16500, 49500))
        self.assertEqual((desde_catalogo["origen"], desde_catalogo["orden"]), ("catalogo", 1))

        manual = servicio_partidas_proyecto.crear(self.a, pid, PartidaProyectoCrear.model_validate(
            {"origen": "manual", "categoria_id": 4, "nombre": "Equipo de trabajo", "unidad": "día",
             "cantidad": 10, "precio_unitario_override": 45000}
        ))
        self.assertIsNone(manual["partida_id"])
        self.assertEqual((manual["subtotal"], manual["orden"], manual["estado"]), (450000, 2, "calculada"))
        # No se agregó al catálogo global.
        self.assertEqual(len(self.db["partidas"]), 3)

        editada = servicio_partidas_proyecto.editar(self.a, pid, desde_catalogo["id"], PartidaProyectoEditar.model_validate(
            {"nombre": "Hormigón radier", "cantidad": "3.5", "precio_unitario_override": 150000}
        ))
        self.assertEqual(editada["nombre"], "Hormigón radier")
        self.assertEqual((editada["precio_banco"], editada["precio_unitario"], editada["subtotal"]), (16500, 150000, 525000))
        # El catálogo no cambia.
        self.assertEqual(self.radier["nombre"], "Radier")

        sin_override = servicio_partidas_proyecto.editar(self.a, pid, desde_catalogo["id"], PartidaProyectoEditar.model_validate(
            {"precio_unitario_override": None}
        ))
        self.assertEqual(sin_override["precio_unitario"], 16500)

        with self.assertRaises(HTTPException) as error:
            servicio_partidas_proyecto.editar(self.a, pid, desde_catalogo["id"],
                                              PartidaProyectoEditar.model_validate({"unidad": "m3"}))
        self.assertEqual(error.exception.status_code, 422)

        servicio_partidas_proyecto.editar(self.a, pid, manual["id"], PartidaProyectoEditar.model_validate({"unidad": "jornada"}))

        servicio_partidas_proyecto.eliminar(self.a, pid, manual["id"])
        self.assertEqual([f["id"] for f in self.partidas_de(pid)], [desde_catalogo["id"]])
        with self.assertRaises(HTTPException) as error:
            servicio_partidas_proyecto.eliminar(self.a, pid, manual["id"])
        self.assertEqual(error.exception.status_code, 404)

    def test_partida_de_catalogo_dada_de_baja_no_se_agrega(self):
        proyecto = self._proyecto_vacio()
        with self.assertRaises(HTTPException) as error:
            servicio_partidas_proyecto.crear(self.a, proyecto["id"], PartidaProyectoCrear.model_validate(
                {"origen": "catalogo", "partida_id": self.baja["id"]}
            ))
        self.assertEqual(error.exception.status_code, 422)

    def test_ordenar(self):
        proyecto = servicio_proyectos.crear_proyecto(self.a, datos_proyecto())
        ids = [f["id"] for f in self.partidas_de(proyecto["id"])]
        filas = servicio_partidas_proyecto.ordenar(self.a, proyecto["id"], PartidasOrdenar(ids=list(reversed(ids))))
        self.assertEqual([f["id"] for f in filas], list(reversed(ids)))
        with self.assertRaises(HTTPException):
            servicio_partidas_proyecto.ordenar(self.a, proyecto["id"], PartidasOrdenar(ids=ids[:1]))

    def test_4_usuario_b_no_ve_ni_modifica_partidas_de_a(self):
        proyecto_a = servicio_proyectos.crear_proyecto(self.a, datos_proyecto())
        partida_a = self.partidas_de(proyecto_a["id"])[0]
        proyecto_b = self._proyecto_vacio(self.b)

        intentos = {
            "listar": lambda: servicio_partidas_proyecto.listar(self.b, proyecto_a["id"]),
            "crear": lambda: servicio_partidas_proyecto.crear(self.b, proyecto_a["id"], PartidaProyectoCrear.model_validate(
                {"origen": "catalogo", "partida_id": self.radier["id"]})),
            "editar": lambda: servicio_partidas_proyecto.editar(self.b, proyecto_a["id"], partida_a["id"],
                                                                PartidaProyectoEditar.model_validate({"cantidad": 1})),
            "eliminar": lambda: servicio_partidas_proyecto.eliminar(self.b, proyecto_a["id"], partida_a["id"]),
            "aplicar": lambda: servicio_partidas_proyecto.aplicar_plantilla(self.b, proyecto_a["id"],
                                                                            PlantillaAplicar(reemplazar=True)),
            # Con su propio proyecto en la ruta y la partida de A: RLS la oculta igual.
            "editar cruzado": lambda: servicio_partidas_proyecto.editar(self.b, proyecto_b["id"], partida_a["id"],
                                                                        PartidaProyectoEditar.model_validate({"cantidad": 1})),
            "eliminar cruzado": lambda: servicio_partidas_proyecto.eliminar(self.b, proyecto_b["id"], partida_a["id"]),
        }
        for nombre, intento in intentos.items():
            with self.subTest(intento=nombre):
                with self.assertRaises(HTTPException) as error:
                    intento()
                self.assertEqual(error.exception.status_code, 404)

        self.assertEqual(self.partidas_de(proyecto_a["id"])[0], partida_a)
        self.assertEqual(len(self.partidas_de(proyecto_a["id"])), 2)

    # --- Aplicar plantilla manualmente ------------------------------------------------------

    def test_reaplicar_exige_confirmacion(self):
        proyecto = servicio_proyectos.crear_proyecto(self.a, datos_proyecto())
        pid = proyecto["id"]
        servicio_partidas_proyecto.editar(self.a, pid, self.partidas_de(pid)[1]["id"],
                                          PartidaProyectoEditar.model_validate({"cantidad": 12}))

        with self.assertRaises(HTTPException) as error:
            servicio_partidas_proyecto.aplicar_plantilla(self.a, pid, PlantillaAplicar())
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.partidas_de(pid)[1]["cantidad"], "12")  # nada se tocó

        respuesta = servicio_partidas_proyecto.aplicar_plantilla(self.a, pid, PlantillaAplicar(reemplazar=True))
        self.assertEqual([p["cantidad"] for p in respuesta["partidas"]], ["1", None])

    def test_aplicar_a_proyecto_existente_sin_partidas(self):
        proyecto = self._proyecto_vacio()
        with self.assertRaises(HTTPException) as error:
            # No hay plantilla para Vivienda unifamiliar · Albañilería confinada.
            servicio_partidas_proyecto.aplicar_plantilla(self.a, proyecto["id"], PlantillaAplicar())
        self.assertEqual(error.exception.status_code, 404)

        respuesta = servicio_partidas_proyecto.aplicar_plantilla(
            self.a, proyecto["id"], PlantillaAplicar(plantilla_id=self.plantilla["id"])
        )
        self.assertEqual(len(respuesta["partidas"]), 2)
        self.assertEqual(respuesta["plantilla_aplicada"]["id"], self.plantilla["id"])

    def test_no_se_aplica_una_plantilla_inactiva(self):
        proyecto = self._proyecto_vacio()
        inactiva = self.db["plantillas_presupuesto"][1]
        with self.assertRaises(HTTPException) as error:
            servicio_partidas_proyecto.aplicar_plantilla(self.a, proyecto["id"], PlantillaAplicar(plantilla_id=inactiva["id"]))
        self.assertEqual(error.exception.status_code, 404)

    def test_estimacion_guardada_no_cambia_y_el_proyecto_pide_recalcular(self):
        """Flujo completo: plantilla → cantidades → estimación guardada → cambios posteriores."""
        version = self.db["versiones_precios"][0]
        self.db["parametros_calculo"] = [
            {"clave": "gastos_generales_pct", "valor": 10},
            {"clave": "utilidad_pct", "valor": 10},
            {"clave": "factores_comuna", "valor": {"Quilpué": 1.0}},
            {"clave": "tramos_pisos", "valor": [{"desde": 1, "hasta": 99, "factor": 1.0}]},
        ]
        self.db["estimaciones"], self.db["estimacion_partidas"] = [], []

        proyecto = servicio_proyectos.crear_proyecto(self.a, datos_proyecto())
        pid = proyecto["id"]
        faenas, radier = self.partidas_de(pid)
        servicio_partidas_proyecto.editar(self.a, pid, faenas["id"], PartidaProyectoEditar.model_validate(
            {"precio_unitario_override": 1000000}))
        servicio_partidas_proyecto.editar(self.a, pid, radier["id"], PartidaProyectoEditar.model_validate({"cantidad": 20}))

        cliente = lambda t: ClienteFalso(self.db, uid=t.removeprefix("token-"))
        with patch.object(servicio_estimaciones, "get_user_scoped_client", side_effect=cliente), \
                patch.object(servicio_estimaciones, "supabase_admin", self.admin):
            creada = servicio_estimaciones.crear_estimacion(self.a, pid, None)
            # 1 gl × 1.000.000 + 20 m2 × 16.500 = 1.330.000; GG y utilidad 10 %.
            self.assertEqual((creada["costo_directo"], creada["gastos_generales"], creada["utilidad"], creada["total"]),
                             (1330000, 133000, 133000, 1596000))
            self.assertEqual(creada["version_precios"]["id"], version["id"])
            lineas = [l for c in creada["capitulos"] for l in c["lineas"]]
            self.assertEqual({l["origen"] for l in lineas}, {"plantilla"})
            self.assertEqual(servicio_proyectos.obtener_proyecto_por_id(self.a, pid)["estado_estimacion"], "vigente")

            # Se edita y se borra una partida: lo guardado no se mueve.
            servicio_partidas_proyecto.editar(self.a, pid, radier["id"], PartidaProyectoEditar.model_validate({"cantidad": 99}))
            servicio_partidas_proyecto.eliminar(self.a, pid, faenas["id"])
            releida = servicio_estimaciones.obtener_estimacion(self.a, pid, creada["id"])
            self.assertEqual(releida, creada)
            self.assertEqual(servicio_proyectos.obtener_proyecto_por_id(self.a, pid)["estado_estimacion"], "recalcular")

            with self.assertRaises(HTTPException) as ajena:
                servicio_estimaciones.obtener_estimacion(self.b, pid, creada["id"])
            self.assertEqual(ajena.exception.status_code, 404)

    def test_firma_con_operaciones_reales(self):
        """Lo que cambia el costo cambia la firma; nombre, observación y orden no."""
        proyecto = servicio_proyectos.crear_proyecto(self.a, datos_proyecto())
        pid = proyecto["id"]
        firma = lambda: firma_partidas(self.partidas_de(pid))
        primera, segunda = (f["id"] for f in self.partidas_de(pid))
        editar = lambda id_, **c: servicio_partidas_proyecto.editar(self.a, pid, id_, PartidaProyectoEditar.model_validate(c))

        base = firma()
        editar(primera, nombre="Faenas y bodega", observacion="incluye bodega")
        servicio_partidas_proyecto.ordenar(self.a, pid, PartidasOrdenar(ids=[segunda, primera]))
        self.assertEqual(firma(), base)

        cambios = [
            lambda: editar(segunda, cantidad=4),
            lambda: editar(segunda, precio_unitario_override=20000),
            lambda: editar(segunda, precio_unitario_override=None),
            lambda: servicio_partidas_proyecto.crear(self.a, pid, PartidaProyectoCrear.model_validate(
                {"origen": "manual", "categoria_id": 4, "nombre": "Maestro", "unidad": "día",
                 "cantidad": 1, "precio_unitario_override": 1})),
            lambda: servicio_partidas_proyecto.eliminar(self.a, pid, primera),
        ]
        for cambio in cambios:
            antes = firma()
            cambio()
            self.assertNotEqual(firma(), antes)

    def test_listado_de_plantillas_cuenta_partidas(self):
        filas = {p["nombre"]: p["cantidad_partidas"] for p in servicio_plantillas.listar(self.a)}
        self.assertEqual(filas, {"Ampliación · Estructura metálica": 3, "Vieja": 1})


if __name__ == "__main__":
    unittest.main()
