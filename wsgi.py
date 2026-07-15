from __future__ import annotations

import io
import os
from email.message import Message
from http import HTTPStatus
from pathlib import Path


ROOT = Path(__file__).parent
os.environ.setdefault("FINANZAS_DATA_DIR", str(ROOT / "data"))
os.environ.setdefault("FINANZAS_HOST", "0.0.0.0")

from server import App, MAX_UPLOAD_BYTES, init_db  # noqa: E402


init_db()


class WsgiApp(App):
    def send_response(self, code: int, message: str | None = None) -> None:
        self._status_code = code
        default_message = HTTPStatus(code).phrase if code in HTTPStatus._value2member_map_ else "OK"
        self._status_message = message or default_message
        self._response_headers = []

    def send_header(self, keyword: str, value: str) -> None:
        self._response_headers.append((keyword, str(value)))

    def end_headers(self) -> None:
        return None

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        text = message or (HTTPStatus(code).phrase if code in HTTPStatus._value2member_map_ else "Error")
        payload = f"{code} {text}".encode("utf-8")
        self.send_response(code, text)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def address_string(self) -> str:
        return getattr(self, "_remote_addr", "-")

    def log_message(self, fmt: str, *args) -> None:
        return None


def _headers_from_environ(environ: dict) -> Message:
    headers = Message()
    for key, value in environ.items():
        if key.startswith("HTTP_"):
            header = key[5:].replace("_", "-").title()
            headers[header] = value
    if environ.get("CONTENT_TYPE"):
        headers["Content-Type"] = environ["CONTENT_TYPE"]
    if environ.get("CONTENT_LENGTH"):
        headers["Content-Length"] = environ["CONTENT_LENGTH"]
    return headers


def application(environ, start_response):
    request = object.__new__(WsgiApp)
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO") or "/"
    query = environ.get("QUERY_STRING") or ""
    length_text = environ.get("CONTENT_LENGTH") or "0"
    try:
        length = int(length_text)
    except ValueError:
        length = 0

    if length > MAX_UPLOAD_BYTES:
        # No bufferear el cuerpo en memoria si el cliente ya anuncio un
        # Content-Length mayor al limite de la app: evita que un request
        # gigante agote memoria del worker antes de que la app lo rechace.
        payload = "413 El cuerpo de la solicitud es demasiado grande".encode("utf-8")
        start_response(
            "413 Request Entity Too Large",
            [("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", str(len(payload)))],
        )
        return [payload]

    request.command = method
    request.path = f"{path}?{query}" if query else path
    request.request_version = environ.get("SERVER_PROTOCOL", "HTTP/1.1")
    request.headers = _headers_from_environ(environ)
    request.rfile = io.BytesIO(environ["wsgi.input"].read(length) if length else b"")
    request.wfile = io.BytesIO()
    request.client_address = (environ.get("REMOTE_ADDR", "-"), 0)
    request.server = None
    request.close_connection = True
    request._remote_addr = environ.get("REMOTE_ADDR", "-")
    request._status_code = 200
    request._status_message = "OK"
    request._response_headers = []

    handler = getattr(request, f"do_{method}", None)
    if handler is None:
        request.send_error(405, "Metodo no permitido")
    else:
        try:
            handler()
        except Exception as exc:  # pragma: no cover - hosting safety net
            payload = f"Error interno: {exc}".encode("utf-8")
            request._status_code = 500
            request._status_message = "Internal Server Error"
            request._response_headers = [
                ("Content-Type", "text/plain; charset=utf-8"),
                ("Content-Length", str(len(payload))),
            ]
            request.wfile = io.BytesIO(payload)

    status = f"{request._status_code} {request._status_message}"
    start_response(status, request._response_headers)
    return [request.wfile.getvalue()]
