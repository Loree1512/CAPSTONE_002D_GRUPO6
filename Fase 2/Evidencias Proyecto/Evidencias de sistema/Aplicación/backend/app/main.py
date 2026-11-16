import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database.supabase import supabase, supabase_admin
from app.dependencies.autenticacion import CABECERA_ACCESO
from app.errores import ErroresInesperados
from app.routers import (
    administracion,
    autenticacion,
    banco,
    configuracion,
    estimaciones,
    historial,
    miembros,
    partidas_proyecto,
    plantillas,
    proyectos,
)

app = FastAPI(
    title="BuildCast API",
    description="API backend para BuildCast",
    version="0.1.0"
)

# Antes que CORS: cada add_middleware envuelve a los anteriores, así CORS queda por
# fuera y también firma los 500.
app.add_middleware(ErroresInesperados)

# Frontend Vite local (dev). Autorización va por header Bearer, no por cookies.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "https://buildcast-frontend.vercel.app"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    # El frontend la lee para mandar a «Crea tu contraseña» a un invitado pendiente.
    expose_headers=[CABECERA_ACCESO],
)

app.include_router(autenticacion.router)
app.include_router(proyectos.router)
app.include_router(banco.router)
app.include_router(estimaciones.router)
app.include_router(configuracion.router)
app.include_router(partidas_proyecto.router)
app.include_router(plantillas.router)
app.include_router(miembros.router)
app.include_router(historial.router)
app.include_router(administracion.router)

# Sin FRONTEND_URL las invitaciones no piden volver a /acceso.html: Supabase usa su Site URL.
if not os.getenv("FRONTEND_URL", "").strip():
    logging.getLogger("buildcast").warning(
        "FRONTEND_URL vacía: los enlaces de invitación vuelven a la Site URL de Supabase, no a /acceso.html."
    )


@app.get("/health", tags=["Sistema"])
def health_check():
    return {
        "status": "ok",
        "service": "BuildCast API"
    }

@app.get("/supabase-test", tags=["Sistema"])
def supabase_test():
    try:
        response = supabase.auth.get_session()

        return {
            "status": "ok",
            "message": "Cliente de Supabase inicializado correctamente"
        }

    except Exception as error:
        return {
            "status": "error",
            "message": str(error)
        }


@app.get("/db-test", tags=["Sistema"])
def database_test():
    # Bypassa RLS con supabase_admin solo para probar conectividad.
    response = (
        supabase_admin
        .table("proyectos")
        .select("id")
        .limit(1)
        .execute()
    )

    return {
        "status": "ok",
        "database": "Supabase PostgreSQL",
        "proyectos_encontrados": len(response.data)
    }