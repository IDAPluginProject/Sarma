"""Built-in network exchange tools."""

from __future__ import annotations

import http.client
import json
import socket
import ssl
from typing import Any
from urllib.parse import urlparse


def build_packet_exchange_tool() -> Any:
    """Build the built-in LangChain packet exchange tool."""
    from langchain_core.tools import tool

    @tool("packet_exchange")
    def packet_exchange(
        host: str,
        port: int,
        protocol: str = "tcp",
        payload: str = "",
        payload_hex: str = "",
        timeout: float = 5.0,
        recv_bytes: int = 4096,
        verify_tls: bool = False,
    ) -> str:
        """Send one low-level TCP/UDP/TLS payload and return the response.

        Args:
            host: Target host or IP.
            port: Target port.
            protocol: tcp, udp, or tls.
            payload: UTF-8 text payload to send.
            payload_hex: Hex payload to send. Takes precedence over payload.
            timeout: Socket timeout in seconds.
            recv_bytes: Maximum response bytes to receive.
            verify_tls: Whether to verify TLS certificates for protocol=tls.
        """
        return exchange_packet(
            host=host,
            port=port,
            protocol=protocol,
            payload=payload,
            payload_hex=payload_hex,
            timeout=timeout,
            recv_bytes=recv_bytes,
            verify_tls=verify_tls,
        )

    return packet_exchange


def build_http_exchange_tool() -> Any:
    """Build the built-in LangChain HTTP/HTTPS exchange tool."""
    from langchain_core.tools import tool

    @tool("http_exchange")
    def http_exchange(
        url: str = "",
        host: str = "",
        port: int = 0,
        scheme: str = "",
        method: str = "GET",
        path: str = "/",
        headers_json: str = "",
        body: str = "",
        body_hex: str = "",
        timeout: float = 10.0,
        max_response_bytes: int = 16384,
        verify_tls: bool = True,
    ) -> str:
        """Send one HTTP/HTTPS request for service and port testing.

        Args:
            url: Optional full URL. If set, it overrides host/port/scheme/path.
            host: Target host or IP when url is empty.
            port: Target port. Defaults to 80 for HTTP or 443 for HTTPS.
            scheme: http or https when url is empty.
            method: HTTP method, for example GET, POST, HEAD, OPTIONS.
            path: Request path when url is empty.
            headers_json: Optional JSON object of request headers.
            body: UTF-8 request body.
            body_hex: Hex request body. Takes precedence over body.
            timeout: Network timeout in seconds.
            max_response_bytes: Maximum response body bytes to read.
            verify_tls: Whether to verify TLS certificates for HTTPS.
        """
        return exchange_http(
            url=url,
            host=host,
            port=port,
            scheme=scheme,
            method=method,
            path=path,
            headers_json=headers_json,
            body=body,
            body_hex=body_hex,
            timeout=timeout,
            max_response_bytes=max_response_bytes,
            verify_tls=verify_tls,
        )

    return http_exchange


def exchange_packet(
    *,
    host: str,
    port: int,
    protocol: str = "tcp",
    payload: str = "",
    payload_hex: str = "",
    timeout: float = 5.0,
    recv_bytes: int = 4096,
    verify_tls: bool = False,
) -> str:
    host = host.strip()
    if not host:
        return "packet_exchange requires a host."
    if not (0 < int(port) <= 65535):
        return "packet_exchange port must be between 1 and 65535."

    proto = protocol.strip().lower()
    try:
        data = _payload_bytes(payload=payload, payload_hex=payload_hex)
    except ValueError as exc:
        return f"packet_exchange invalid payload_hex: {exc}"
    max_recv = max(1, min(int(recv_bytes or 4096), 1024 * 1024))
    socket_timeout = max(0.1, float(timeout or 5.0))

    try:
        if proto == "tcp":
            response = _tcp_exchange(host, int(port), data, socket_timeout, max_recv)
        elif proto in {"tls", "ssl"}:
            response = _tls_exchange(
                host,
                int(port),
                data,
                socket_timeout,
                max_recv,
                verify_tls=verify_tls,
            )
        elif proto == "udp":
            response = _udp_exchange(host, int(port), data, socket_timeout, max_recv)
        else:
            return "packet_exchange protocol must be 'tcp', 'udp', or 'tls'."
    except Exception as exc:
        return f"packet_exchange failed: {exc}"

    return _format_response(proto, host, int(port), data, response)


def exchange_http(
    *,
    url: str = "",
    host: str = "",
    port: int = 0,
    scheme: str = "",
    method: str = "GET",
    path: str = "/",
    headers_json: str = "",
    body: str = "",
    body_hex: str = "",
    timeout: float = 10.0,
    max_response_bytes: int = 16384,
    verify_tls: bool = True,
) -> str:
    try:
        target = _resolve_http_target(url, host, port, scheme, path)
    except ValueError as exc:
        return f"http_exchange invalid target: {exc}"

    try:
        headers = _parse_headers(headers_json)
        data = _payload_bytes(payload=body, payload_hex=body_hex)
    except ValueError as exc:
        return f"http_exchange invalid input: {exc}"

    request_method = method.strip().upper() or "GET"
    max_body = max(1, min(int(max_response_bytes or 16384), 1024 * 1024))
    socket_timeout = max(0.1, float(timeout or 10.0))
    connection_cls: type[http.client.HTTPConnection]
    connection_kwargs: dict[str, Any] = {"timeout": socket_timeout}

    if target["scheme"] == "https":
        connection_cls = http.client.HTTPSConnection
        if not verify_tls:
            connection_kwargs["context"] = _tls_context(verify_tls=False)
    else:
        connection_cls = http.client.HTTPConnection

    try:
        conn = connection_cls(
            target["host"],
            target["port"],
            **connection_kwargs,
        )
        try:
            conn.request(request_method, target["path"], body=data, headers=headers)
            response = conn.getresponse()
            response_body = response.read(max_body)
            response_headers = response.getheaders()
            return _format_http_response(
                target,
                request_method,
                len(data),
                response.status,
                response.reason,
                response_headers,
                response_body,
            )
        finally:
            conn.close()
    except Exception as exc:
        return f"http_exchange failed: {exc}"


def _resolve_http_target(
    url: str,
    host: str,
    port: int,
    scheme: str,
    path: str,
) -> dict[str, Any]:
    if url.strip():
        parsed = urlparse(url.strip())
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("url scheme must be http or https")
        if not parsed.hostname:
            raise ValueError("url must include a host")
        target_path = parsed.path or "/"
        if parsed.query:
            target_path += f"?{parsed.query}"
        return {
            "scheme": parsed.scheme,
            "host": parsed.hostname,
            "port": parsed.port or (443 if parsed.scheme == "https" else 80),
            "path": target_path,
        }

    target_host = host.strip()
    if not target_host:
        raise ValueError("host is required when url is empty")
    target_scheme = (scheme.strip().lower() or "http")
    if target_scheme not in {"http", "https"}:
        raise ValueError("scheme must be http or https")
    target_port = int(port or (443 if target_scheme == "https" else 80))
    if not (0 < target_port <= 65535):
        raise ValueError("port must be between 1 and 65535")
    target_path = path.strip() or "/"
    if not target_path.startswith("/"):
        target_path = f"/{target_path}"
    return {
        "scheme": target_scheme,
        "host": target_host,
        "port": target_port,
        "path": target_path,
    }


def _parse_headers(headers_json: str) -> dict[str, str]:
    text = headers_json.strip()
    if not text:
        return {}
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("headers_json must be a JSON object")
    return {str(key): str(value) for key, value in parsed.items()}


def _payload_bytes(*, payload: str, payload_hex: str) -> bytes:
    if payload_hex.strip():
        return bytes.fromhex("".join(payload_hex.split()))
    return payload.encode("utf-8")


def _tcp_exchange(
    host: str,
    port: int,
    data: bytes,
    timeout: float,
    recv_bytes: int,
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        if data:
            sock.sendall(data)
        try:
            while total < recv_bytes:
                chunk = sock.recv(min(4096, recv_bytes - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
        except (TimeoutError, socket.timeout):
            pass
    return b"".join(chunks)


def _tls_exchange(
    host: str,
    port: int,
    data: bytes,
    timeout: float,
    recv_bytes: int,
    *,
    verify_tls: bool,
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    context = _tls_context(verify_tls=verify_tls)
    with socket.create_connection((host, port), timeout=timeout) as raw_sock:
        raw_sock.settimeout(timeout)
        with context.wrap_socket(raw_sock, server_hostname=host) as sock:
            sock.settimeout(timeout)
            if data:
                sock.sendall(data)
            try:
                while total < recv_bytes:
                    chunk = sock.recv(min(4096, recv_bytes - total))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
            except (TimeoutError, socket.timeout):
                pass
    return b"".join(chunks)


def _udp_exchange(
    host: str,
    port: int,
    data: bytes,
    timeout: float,
    recv_bytes: int,
) -> bytes:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(data, (host, port))
        try:
            response, _addr = sock.recvfrom(recv_bytes)
        except (TimeoutError, socket.timeout):
            return b""
    return response


def _tls_context(*, verify_tls: bool) -> ssl.SSLContext:
    if verify_tls:
        return ssl.create_default_context()
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _format_response(
    protocol: str,
    host: str,
    port: int,
    sent: bytes,
    response: bytes,
) -> str:
    text = response.decode("utf-8", errors="replace")
    if len(text) > 2000:
        text = text[:1997] + "..."
    return (
        f"packet_exchange {protocol.upper()} {host}:{port}\n"
        f"sent_bytes={len(sent)} received_bytes={len(response)}\n"
        f"response_text={text!r}\n"
        f"response_hex={response[:512].hex()}"
    )


def _format_http_response(
    target: dict[str, Any],
    method: str,
    sent_bytes: int,
    status: int,
    reason: str,
    headers: list[tuple[str, str]],
    response: bytes,
) -> str:
    text = response.decode("utf-8", errors="replace")
    if len(text) > 4000:
        text = text[:3997] + "..."
    header_lines = "\n".join(f"{name}: {value}" for name, value in headers[:40])
    return (
        f"http_exchange {method} "
        f"{target['scheme']}://{target['host']}:{target['port']}{target['path']}\n"
        f"status={status} reason={reason!r} sent_bytes={sent_bytes} "
        f"received_bytes={len(response)}\n"
        f"response_headers:\n{header_lines}\n"
        f"response_text={text!r}\n"
        f"response_hex={response[:512].hex()}"
    )
