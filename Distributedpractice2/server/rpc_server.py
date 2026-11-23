"""RPC server core: procedure registry and request dispatcher.

This module knows nothing about sockets. It only turns a request
dictionary into a response dictionary; the network layer lives in
server/server.py.

Protocol (JSON objects):
    request : {"function": "add", "args": [4, 7]}
    success : {"status": "ok", "result": 11}
    failure : {"status": "error", "error": "<ErrorCode>", "message": "<detail>"}
"""

from __future__ import annotations

import inspect
import json
from typing import Any, Callable


class ErrorCode:
    """Error codes of the protocol (the "error" field of a failure response)."""

    PROCEDURE_NOT_FOUND = "PROCEDURE_NOT_FOUND"  # unknown procedure name
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"      # wrong number of arguments
    EXECUTION_ERROR = "EXECUTION_ERROR"          # the procedure raised an exception
    BAD_MESSAGE = "BAD_MESSAGE"                  # malformed request


class RPCServer:
    """Holds the procedure table and dispatches requests to it."""

    def __init__(self) -> None:
        self._procedures: dict[str, Callable[..., Any]] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def register(self, name: str, function: Callable[..., Any]) -> None:
        """Register a remote procedure under a public name.

        Raises:
            ValueError: if the name is empty or already registered.
            TypeError: if `function` is not callable.
        """
        if not isinstance(name, str) or not name:
            raise ValueError("The procedure name must be a non-empty string")
        if not callable(function):
            raise TypeError(f"Procedure {name!r} is not callable")
        if name in self._procedures:
            raise ValueError(f"Procedure {name!r} is already registered")

        self._procedures[name] = function

    def procedures(self) -> list[str]:
        """Names of the registered procedures, sorted."""
        return sorted(self._procedures)

    def describe(self) -> dict[str, str]:
        """Map each procedure name to the first line of its docstring."""
        return {
            name: (inspect.getdoc(function) or "").split("\n")[0]
            for name, function in sorted(self._procedures.items())
        }

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    def dispatch(self, request: Any) -> dict[str, Any]:
        """Process one request and always return a response dictionary.

        This method never raises: every failure is mapped to an error response.
        """
        # 1. Validate the shape of the request.
        if not isinstance(request, dict):
            return self._error(ErrorCode.BAD_MESSAGE, "The request must be a JSON object")

        name = request.get("function")
        args = request.get("args", [])

        if not isinstance(name, str):
            return self._error(ErrorCode.BAD_MESSAGE, "'function' must be a string")
        if not isinstance(args, list):
            return self._error(ErrorCode.BAD_MESSAGE, "'args' must be a list")

        # 2. Look up the procedure.
        function = self._procedures.get(name)
        if function is None:
            return self._error(ErrorCode.PROCEDURE_NOT_FOUND, f"No such procedure: {name!r}")

        # 3. Check the arguments *before* running anything, so that a
        #    TypeError raised inside the procedure is not confused with a
        #    wrong call (that one is an EXECUTION_ERROR).
        try:
            signature = inspect.signature(function)
        except (TypeError, ValueError):
            signature = None  # some built-ins cannot be inspected

        if signature is not None:
            try:
                signature.bind(*args)
            except TypeError as exc:
                return self._error(ErrorCode.INVALID_ARGUMENTS, f"{name}: {exc}")

        # 4. Execute it.
        try:
            result = function(*args)
        except Exception as exc:  # noqa: BLE001 - any failure becomes an error response
            return self._error(ErrorCode.EXECUTION_ERROR, f"{type(exc).__name__}: {exc}")

        # 5. The result must travel as JSON; find out now instead of
        #    failing later while writing to the socket.
        try:
            json.dumps(result)
        except (TypeError, ValueError) as exc:
            return self._error(
                ErrorCode.EXECUTION_ERROR, f"The result is not JSON serializable: {exc}"
            )

        return self._result(result)

    # ------------------------------------------------------------------
    # Response builders
    # ------------------------------------------------------------------
    @staticmethod
    def _error(code: str, message: str) -> dict[str, Any]:
        return {"status": "error", "error": code, "message": message}

    @staticmethod
    def _result(result: Any) -> dict[str, Any]:
        return {"status": "ok", "result": result}
