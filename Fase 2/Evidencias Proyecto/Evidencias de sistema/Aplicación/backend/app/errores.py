"""Errores no controlados: 500 en JSON, con el detalle solo en el log."""

import logging

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MENSAJE_ERROR_INTERNO = "Error interno del servidor."

logger = logging.getLogger("buildcast.errores")


class ErroresInesperados:
    """Middleware ASGI que convierte una excepción sin capturar en un 500 JSON.

    Debe quedar por dentro de CORSMiddleware: el 500 que arma Starlette por defecto
    lo envía la capa más externa, sin cabeceras CORS, y el navegador lo ve como un
    fallo de red.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        iniciada = False

        async def enviar(mensaje: Message) -> None:
            nonlocal iniciada
            if mensaje["type"] == "http.response.start":
                iniciada = True
            await send(mensaje)

        try:
            await self.app(scope, receive, enviar)
        except Exception:
            # Solo método y ruta: ni cabeceras ni query, que podrían llevar datos sensibles.
            logger.exception("Error no controlado en %s %s", scope.get("method"), scope.get("path"))
            if iniciada:
                # Ya se enviaron cabeceras: no se puede responder otra cosa.
                raise
            respuesta = JSONResponse({"detail": MENSAJE_ERROR_INTERNO}, status_code=500)
            await respuesta(scope, receive, send)
