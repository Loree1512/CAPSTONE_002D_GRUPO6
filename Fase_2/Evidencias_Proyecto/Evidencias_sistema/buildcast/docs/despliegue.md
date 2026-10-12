# Despliegue de BuildCast

BuildCast utiliza **Vercel** para desplegar automáticamente el frontend y el backend desde el repositorio de GitHub.

El proyecto está organizado como un monorepo:

```text
buildcast/
├── backend/
├── docs/
├── frontend/
├── ml/
├── supabase/
└── README.md
```

## Frontend

El frontend está desarrollado con **TypeScript + Vite** y se despliega como un proyecto independiente en Vercel.

- Servicio: Vercel
- Framework: Vite
- Directorio raíz: `frontend`
- Rama de producción: `main`
- URL pública: `https://buildcast-frontend.vercel.app`

### Variables de entorno

Las variables se configuran directamente en Vercel y no se almacenan con valores reales en el repositorio.

```env
VITE_API_URL=https://buildcast-backend-drab.vercel.app
VITE_SIMULACION=false
```

`VITE_API_URL` indica la dirección pública del backend y `VITE_SIMULACION=false` permite que el frontend utilice la API real.

---

## Backend

El backend está desarrollado con **FastAPI** y se despliega como un proyecto independiente en Vercel.

- Servicio: Vercel
- Framework: FastAPI
- Directorio raíz: `backend`
- Rama de producción: `main`
- URL pública: `https://buildcast-backend-drab.vercel.app`

### Variables de entorno

El backend requiere las siguientes variables:

```env
SUPABASE_URL=
SUPABASE_PUBLISHABLE_KEY=
SUPABASE_SECRET_KEY=
SUPABASE_JWKS_URL=
```

Los valores reales se configuran directamente en Vercel. Las claves privadas, especialmente `SUPABASE_SECRET_KEY`, no deben almacenarse en GitHub ni exponerse en el frontend.

---

## Despliegue automático

Vercel está conectado al repositorio de GitHub de BuildCast.

El flujo de despliegue es:

```text
Rama feature
    ↓
Pull Request
    ↓
develop
    ↓
Pull Request
    ↓
main
    ↓
Vercel detecta el nuevo commit
    ↓
Build automático
    ↓
Deploy automático
```

Cuando un cambio aprobado llega a `main`, Vercel detecta automáticamente el nuevo commit y genera una nueva versión desplegada.

Esto permite mantener `main` como la rama estable utilizada para producción.

---

## CORS

Como el frontend y el backend se ejecutan en orígenes diferentes, FastAPI utiliza `CORSMiddleware`.

Durante el desarrollo local se permiten:

```text
http://localhost:5173
http://127.0.0.1:5173
```

Para producción también se permite:

```text
https://buildcast-frontend.vercel.app
```

De esta manera, el frontend desplegado puede realizar solicitudes al backend mediante la API.

---

## Verificación del backend

Para comprobar que el backend está disponible se puede utilizar:

```text
https://buildcast-backend-drab.vercel.app/health
```

La documentación interactiva de FastAPI está disponible en:

```text
https://buildcast-backend-drab.vercel.app/docs
```

---

## Verificación del frontend

La aplicación desplegada está disponible en:

```text
https://buildcast-frontend.vercel.app
```

Desde esta versión se puede probar el flujo integrado de autenticación y gestión de proyectos utilizando el backend desplegado y Supabase.

---

## Consideraciones de seguridad

- Los archivos `.env` locales no se suben al repositorio.
- Los valores reales de las variables de entorno se administran desde Vercel.
- `SUPABASE_SECRET_KEY` se utiliza únicamente en el backend.
- El frontend solo utiliza variables que comienzan con `VITE_`.
- Los endpoints protegidos envían el token mediante `Authorization: Bearer`.
- El acceso a los proyectos está protegido mediante autenticación y políticas RLS en Supabase.
