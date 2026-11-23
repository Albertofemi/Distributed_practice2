"""RPC client layer.

`RPCClient.call()` hides message creation, serialization, the TCP
connection, sending/receiving and error handling: to the application a
remote call looks like a local one.

Every failure is reported as an `RPCError` whose `code` is either an error
code sent by the server (PROCEDURE_NOT_FOUND, INVALID_ARGUMENTS,
EXECUTION_ERROR, BAD_MESSAGE) or one of the client-side codes below.
"""

from __future__ import annotations

import json
import socket
from typing import Any

from common.protocol import recv_json, send_json

# Client-side error codes (the server never sends these).
TIMEOUT = "TIMEOUT"
CONNECTION_ERROR = "CONNECTION_ERROR"
BAD_RESPONSE = "BAD_RESPONSE"
BAD_REQUEST = "BAD_REQUEST"


class RPCError(Exception):
    """A remote call failed. `code` says why, `message` gives the detail."""

    def __init__(self, message: str, code: str = "UNKNOWN_ERROR") -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class RPCClient:
    """Stateless client: every call opens its own connection, so one
    instance can be shared between threads."""

    def __init__(self, host: str, port: int, timeout: float = 5.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout  # applies to connecting and to each socket operation

    def call(self, function: str, *args: Any) -> Any:
        """Execute a remote procedure and return its result.

        Raises:
            RPCError: on any error response or communication failure.
        """
        request = {"function": function, "args": list(args)}

        try:  # fail before touching the network if the arguments cannot be sent
            json.dumps(request, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise RPCError(f"The arguments are not JSON serializable: {exc}", BAD_REQUEST) from exc

        response = self._exchange(request)

        status = response.get("status")
        if status == "ok":
            return response.get("result")
        if status == "error":
            raise RPCError(
                response.get("message", "no detail"),
                response.get("error", "UNKNOWN_ERROR"),
            )
        raise RPCError(f"Malformed response: {response!r}", BAD_RESPONSE)

    def _exchange(self, request: dict) -> dict:
        """Send one request and return the decoded response."""
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
                send_json(sock, request)
                return recv_json(sock)
        except socket.timeout as exc:
            raise RPCError(
                f"No response from {self.host}:{self.port} within {self.timeout}s", TIMEOUT
            ) from exc
        except ValueError as exc:  # invalid JSON, invalid UTF-8, or not an object
            raise RPCError(f"Unreadable response: {exc}", BAD_RESPONSE) from exc
        except OSError as exc:  # refused, reset, DNS failure, closed before replying...
            raise RPCError(
                f"Could not communicate with {self.host}:{self.port}: {exc}", CONNECTION_ERROR
            ) from exc
