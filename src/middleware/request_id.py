"""
Request correlation middleware (PRD section 22).

Every request gets an `X-Request-ID` (reusing the caller's value if they
supplied one, generating a UUID4 otherwise). The ID is stashed in a
contextvar so every structured log line emitted while handling this request
-- including from deep inside services/repositories that have no direct
access to the HTTP request -- automatically carries it (see
`src/logging_config.py::RequestIdFilter`). The same value is echoed back on
the response so a client can correlate their request with server-side logs.
"""
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from src.logging_config import request_id_ctx_var

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        token = request_id_ctx_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_ctx_var.reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
