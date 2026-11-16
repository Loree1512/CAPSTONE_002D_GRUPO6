import os
from pathlib import Path

from dotenv import load_dotenv
from supabase import Client, ClientOptions, create_client


# Ruta explícita: evita depender del directorio desde el que se lance uvicorn.
env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(env_path)

supabase_url = os.getenv("SUPABASE_URL")
supabase_publishable_key = os.getenv("SUPABASE_PUBLISHABLE_KEY")
supabase_secret_key = os.getenv("SUPABASE_SECRET_KEY")

if not supabase_url:
    raise RuntimeError("Falta SUPABASE_URL")

if not supabase_publishable_key:
    raise RuntimeError("Falta SUPABASE_PUBLISHABLE_KEY")

if not supabase_secret_key:
    raise RuntimeError("Falta SUPABASE_SECRET_KEY")


supabase: Client = create_client(
    supabase_url,
    supabase_publishable_key
)

supabase_admin: Client = create_client(
    supabase_url,
    supabase_secret_key
)


def get_anon_client() -> Client:
    # Cliente nuevo por request: reutilizar uno global mezclaría sesiones
    # entre usuarios concurrentes. Sin auto-refresco: si el servidor renovara la
    # sesión por su cuenta, gastaría el refresh token que guarda el navegador.
    return create_client(
        supabase_url,
        supabase_publishable_key,
        options=ClientOptions(auto_refresh_token=False, persist_session=False),
    )


def get_user_scoped_client(access_token: str) -> Client:
    # Token del usuario en PostgREST: así RLS evalúa auth.uid() correctamente.
    client = get_anon_client()
    client.postgrest.auth(access_token)
    return client