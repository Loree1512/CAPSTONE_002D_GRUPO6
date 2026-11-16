"""Migración 003: comprobaciones sobre el texto del SQL.

El comportamiento real se verifica contra la base con
supabase/tests/verificar_003_rls_permisos_proyecto.sql.

Ejecutar desde backend/:
    python -m pytest
"""

import re
import unittest
from pathlib import Path

MIGRACIONES = Path(__file__).resolve().parents[2] / "supabase" / "migrations"
M001 = (MIGRACIONES / "001_schema_buildcast.sql").read_text(encoding="utf-8")
M003 = (MIGRACIONES / "003_rls_permisos_proyecto.sql").read_text(encoding="utf-8")

RPC_MIEMBROS = ("agregar_miembro_proyecto", "cambiar_rol_miembro_proyecto", "quitar_miembro_proyecto")


def _funciones(sql):
    """nombre → (cabecera hasta el cuerpo, cuerpo)."""
    return {
        nombre: (cabecera, cuerpo)
        for nombre, cabecera, cuerpo in re.findall(
            r"create or replace function public\.(\w+)\((.*?)\bas \$\$(.*?)\$\$;", sql, flags=re.S)
    }


def _politicas(sql):
    return set(re.findall(r'create policy "(\w+)"\s+on public\.(\w+)', sql))


class Migracion003(unittest.TestCase):

    def test_reemplaza_todas_las_politicas_por_dueno(self):
        de_proyecto = {"proyectos", "proyecto_partidas", "estimaciones", "estimacion_partidas"}
        anteriores = {(n, t) for n, t in _politicas(M001) if t in de_proyecto}
        eliminadas = set(re.findall(r'drop policy "(\w+)" on public\.(\w+)', M003))

        # Solo sobrevive la de insertar: cada uno crea proyectos a su nombre.
        self.assertEqual(anteriores - eliminadas, {("proyectos_insertar_propios", "proyectos")})
        self.assertEqual({(n, t) for n, t in _politicas(M003) if t in de_proyecto}, {
            ("proyectos_seleccionar_miembros", "proyectos"),
            ("proyectos_actualizar_editores", "proyectos"),
            ("proyecto_partidas_seleccionar_miembros", "proyecto_partidas"),
            ("proyecto_partidas_insertar_editores", "proyecto_partidas"),
            ("proyecto_partidas_actualizar_editores", "proyecto_partidas"),
            ("proyecto_partidas_eliminar_editores", "proyecto_partidas"),
            ("estimaciones_seleccionar_miembros", "estimaciones"),
            ("estimacion_partidas_seleccionar_miembros", "estimacion_partidas"),
        })

    def test_el_rol_global_no_da_acceso_a_proyectos(self):
        self.assertNotIn("es_administrador", M003)
        self.assertNotIn("rol_global", M003)

    def test_un_editor_no_puede_ponerse_como_creador(self):
        self.assertIn("revoke update on public.proyectos from authenticated;", M003)
        columnas = re.search(r"grant update \((.*?)\) on public\.proyectos to authenticated;", M003, flags=re.S).group(1)
        self.assertEqual({c.strip() for c in columnas.split(",")}, {
            "nombre", "comuna", "tipo_obra", "materialidad", "superficie_m2", "numero_pisos",
            "estandar_terminaciones", "estado", "plantilla_id",
        })

    def test_rpc_de_miembros_solo_para_service_role(self):
        funciones = _funciones(M003)
        for nombre in (*RPC_MIEMBROS, "comprobar_propietario_proyecto", "puede_leer_proyecto", "puede_editar_proyecto"):
            cabecera, _ = funciones[nombre]
            self.assertIn("security definer", cabecera, nombre)
            self.assertIn("set search_path = ''", cabecera, nombre)

        for nombre in RPC_MIEMBROS:
            _, cuerpo = funciones[nombre]
            self.assertRegex(M003, rf"revoke execute on function public\.{nombre}\([^)]*\) from public, anon, authenticated;")
            self.assertRegex(M003, rf"grant execute on function public\.{nombre}\([^)]*\) to service_role;")
            # Vuelve a comprobar al propietario y deja su evento en la misma función.
            self.assertIn("public.comprobar_propietario_proyecto(p_solicitante_id, p_proyecto_id)", cuerpo)
            self.assertIn("insert into public.historial_proyecto", cuerpo)
            self.assertIn("'rpc'", cuerpo)

        self.assertIn(
            "revoke execute on function public.comprobar_propietario_proyecto(uuid, uuid) "
            "from public, anon, authenticated, service_role;", M003)
        self.assertEqual(re.findall(r"grant execute [^;]* to ([^;]*authenticated[^;]*);", M003),
                         ["authenticated, service_role", "authenticated, service_role"])  # solo puede_leer/puede_editar

    def test_proyecto_miembros_solo_se_escribe_con_las_rpc(self):
        self.assertIn("revoke insert, update, delete on public.proyecto_miembros from service_role;", M003)
        self.assertNotRegex(M003, r"grant [^;]*\bon public\.proyecto_miembros\b")

    def test_indice_de_correo_normal(self):
        self.assertIn("create index perfiles_email_normalizado_idx\n    on public.perfiles (lower(btrim(email)));", M003)
        self.assertNotIn("unique index", M003)

    def test_funciones_de_la_001_conservan_su_firma(self):
        antes, ahora = _funciones(M001), _funciones(M003)
        for nombre in ("aplicar_plantilla_proyecto", "ordenar_partidas_proyecto", "crear_estimacion"):
            self.assertEqual(" ".join(antes[nombre][0].split()), " ".join(ahora[nombre][0].split()), nombre)

        # crear_estimacion sigue siendo solo de service role; las de partidas siguen con RLS.
        self.assertIn(
            "revoke execute on function public.crear_estimacion(uuid, jsonb, jsonb) from public, anon, authenticated;", M003)
        for nombre in ("aplicar_plantilla_proyecto", "ordenar_partidas_proyecto"):
            self.assertIn("security invoker", ahora[nombre][0])


if __name__ == "__main__":
    unittest.main()
