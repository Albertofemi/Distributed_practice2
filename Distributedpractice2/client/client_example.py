"""Demo client: normal calls, error handling, timeouts and concurrency.

Run from the project root (the server must be running):

    python -m client.client_example --host <EC2_PUBLIC_IP> --port 5000
"""

from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor

from client.rpc_client import RPCClient, RPCError


def attempt(rpc: RPCClient, function: str, *args) -> None:
    """Call a procedure and print either the result or the error."""
    call = f"{function}({', '.join(map(repr, args))})"
    try:
        print(f"  {call} -> {rpc.call(function, *args)!r}")
    except RPCError as exc:
        print(f"  {call} raised RPCError [{exc.code}] {exc.message}")


def main() -> None:
    parser = argparse.ArgumentParser(description="RPC demo client")
    parser.add_argument("--host", default="127.0.0.1", help="EC2 public IP/DNS (default: local)")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    rpc = RPCClient(args.host, args.port)

    print("1. Remote calls")
    attempt(rpc, "add", 4, 7)
    attempt(rpc, "multiply", 3, 5)
    attempt(rpc, "power", 2, 10)
    attempt(rpc, "prime_factors", 360)
    attempt(rpc, "image_info", "photo.jpg")
    attempt(rpc, "server_info")  # shows the machine that really ran the code
    attempt(rpc, "list_procedures")

    print("\n2. Error handling")
    attempt(rpc, "does_not_exist")       # PROCEDURE_NOT_FOUND
    attempt(rpc, "add", 1)               # INVALID_ARGUMENTS
    attempt(rpc, "power", 0, -1)         # EXECUTION_ERROR (division by zero)
    attempt(rpc, "add", {1, 2}, 3)       # BAD_REQUEST (a set is not JSON)

    print("\n3. Timeout (client waits 1 s, the task takes 3 s)")
    attempt(RPCClient(args.host, args.port, timeout=1.0), "slow_task", 3)

    print("\n4. Concurrency (4 clients, slow_task(2) each)")
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(rpc.call, "slow_task", 2) for _ in range(4)]
        results = [future.result() for future in futures]
    elapsed = time.perf_counter() - start
    print(f"  results={results} in {elapsed:.1f} s (sequential server would need ~8 s)")


if __name__ == "__main__":
    main()
