"""Concurrent TCP server for the RPC system.

The main thread only accepts connections; each connection is handled by a
worker of a thread pool. A client that connects and stays silent cannot
block a worker forever (see CLIENT_TIMEOUT).

Run from the project root:

    python -m server.server [--host 0.0.0.0] [--port 5000] [--workers 16]
"""

from __future__ import annotations

import argparse
import logging
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from common.protocol import recv_json, send_json
from server import procedures
from server.rpc_server import ErrorCode, RPCServer

HOST = "0.0.0.0"
PORT = 5000
MAX_WORKERS = 16        # simultaneous requests; the rest wait in the pool queue
CLIENT_TIMEOUT = 10.0   # seconds a worker waits for a client's request
ACCEPT_POLL = 0.5       # accept() wakes up this often to check the stop event

log = logging.getLogger("rpc.server")


def build_service() -> RPCServer:
    """Create the RPCServer and register every public procedure."""
    rpc = RPCServer()

    for function in (
        procedures.add,
        procedures.multiply,
        procedures.power,
        procedures.slow_task,
        procedures.image_info,
        procedures.grayscale,
        procedures.resize,
        procedures.server_info,
        procedures.prime_factors,
    ):
        rpc.register(function.__name__, function)

    rpc.register("list_procedures", rpc.describe)
    return rpc


def handle(rpc: RPCServer, connection: socket.socket, address: tuple) -> None:
    """Serve one request on one connection (runs in a worker thread)."""
    with connection:
        connection.settimeout(CLIENT_TIMEOUT)

        try:
            request = recv_json(connection)
        except ValueError as exc:
            # json.JSONDecodeError and UnicodeDecodeError are ValueErrors too,
            # as is a valid JSON that is not an object.
            log.warning("%s: unreadable message: %s", address, exc)
            response = {
                "status": "error",
                "error": ErrorCode.BAD_MESSAGE,
                "message": str(exc),
            }
        except OSError as exc:  # timeout, reset, closed before the full message
            log.warning("%s: no request received: %s", address, exc)
            return
        else:
            log.info("%s -> %s", address, request.get("function"))
            try:
                response = rpc.dispatch(request)
            except Exception:  # noqa: BLE001 - dispatch should not raise; be defensive
                log.exception("%s: unexpected failure in dispatch", address)
                response = {
                    "status": "error",
                    "error": ErrorCode.EXECUTION_ERROR,
                    "message": "Internal server error",
                }

        try:
            send_json(connection, response)
        except OSError as exc:
            log.warning("%s: could not reply: %s", address, exc)


def serve(
    rpc: RPCServer,
    host: str = HOST,
    port: int = PORT,
    max_workers: int = MAX_WORKERS,
    stop_event: threading.Event | None = None,
    on_ready: Callable[[int], None] | None = None,
) -> None:
    """Accept connections until `stop_event` is set.

    `port=0` picks a free port; `on_ready(port)` is called once the server is
    listening (used by the tests). accept() uses a short timeout so the loop
    can check the stop event and so Ctrl+C also works on Windows.
    """
    stop_event = stop_event or threading.Event()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(("0.0.0.0", 5000))
        server_socket.listen()
        server_socket.settimeout(ACCEPT_POLL)

        bound_port = server_socket.getsockname()[1]
        log.info("Listening on %s:%s (%d workers)", host, bound_port, max_workers)
        log.info("Procedures: %s", ", ".join(rpc.procedures()))
        if on_ready is not None:
            on_ready(bound_port)

        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="rpc") as pool:
            while not stop_event.is_set():
                try:
                    connection, address = server_socket.accept()
                except socket.timeout:
                    continue
                pool.submit(handle, rpc, connection, address)


def main() -> None:
    parser = argparse.ArgumentParser(description="RPC server")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        serve(build_service(), args.host, args.port, args.workers)
    except KeyboardInterrupt:
        log.info("Shutting down")


if __name__ == "__main__":
    main()
