# BuildCast — frontend

Aplicación web de BuildCast. TypeScript + Vite + Alpine.js, multipágina, sin framework de componentes.

## Puesta en marcha

```bash
cd frontend
npm install
cp .env.example .env
npm run dev          # http://localhost:5173
```

`npm run build` verifica los tipos con `tsc --noEmit` y genera `dist/`, que es lo que se publica.

## Modo demostración

Con `VITE_SIMULACION=true` la aplicación funciona sin API y sin usuario real:
las llamadas se resuelven con datos de ejemplo guardados en el navegador.
Sirve para recorrer las pantallas, mostrar el avance al cliente y trabajar la
interfaz mientras el backend no está disponible.

El acceso entra con cualquier credencial, el listado trae cinco proyectos de
ejemplo, y crear y editar realmente modifican los datos hasta que se presiona
«Reiniciar datos» en la barra superior. Una marca visible en la barra recuerda
que nada de eso viene de la API.

Para trabajar contra el backend, `VITE_SIMULACION=false`.

## Configuración

`VITE_API_URL` apunta a la API de FastAPI. Por defecto `http://127.0.0.1:8000`.
La API debe permitir el origen del frontend en su middleware de CORS,
tanto `http://localhost:5173` en desarrollo como el dominio de producción.

## Estructura

```
index.html        acceso            HU-01
proyectos.html    listado y vacío   HU-04, HU-06
proyecto.html     crear y editar    HU-02, HU-03, HU-05
src/lib/api.ts        selector entre cliente real y simulado
src/lib/apiReal.ts    cliente tipado, Bearer automático, manejo de 401
src/lib/apiSimulada.ts  datos de ejemplo del modo demostración
src/lib/sesion.ts     token en localStorage y guardia de página
src/lib/formato.ts    pesos chilenos, superficie, plazos, fechas
src/lib/catalogos.ts  comunas, tipos de obra, materialidades, estados
src/paginas/*.ts      un módulo Alpine por pantalla
src/estilos/base.css  sistema visual: tokens y componentes
```

## Pendiente de confirmar con el backend

`src/lib/sesion.ts` normaliza el token de `POST /autenticacion/iniciar-sesion`
aceptando `access_token`, `token` o `session.access_token`. Cuando se confirme
la forma real de la respuesta, se ajusta ahí y en ningún otro lugar.

El cliente envía `{ correo, password }` al iniciar sesión. Si el backend espera
otros nombres de campo, se corrige en `src/lib/api.ts`.
