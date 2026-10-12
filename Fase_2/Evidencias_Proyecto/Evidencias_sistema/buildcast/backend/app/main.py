from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database.supabase import supabase, supabase_admin
from app.routers import (
    autenticacion,
    banco,
    configuracion,
    estimaciones,
    partidas_proyecto,
    plantillas,
    proyectos,
)

app = FastAPI(
    title="BuildCast API",
    description="API backend para BuildCast",
    version="0.1.0"
)

# Frontend Vite local (dev). Autorización va por header Bearer, no por cookies.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "https://buildcast-frontend.vercel.app"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(autenticacion.router)
app.include_router(proyectos.router)
app.include_router(banco.router)
app.include_router(estimaciones.router)
app.include_router(configuracion.router)
app.include_router(partidas_proyecto.router)
app.include_router(plantillas.router)


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