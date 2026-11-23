"""Load test for the RPC server running on Kubernetes.

Uses the unchanged Assignment 1 client (client.rpc_client.RPCClient).
Run from the project root:

    python loadtest.py --host <NODE_IP> --port 30007 --total 300 --concurrency 50

Every call opens its own connection, so kube-proxy can spread the requests
over all the Pods. The default workload is slow_task(1): each request keeps
one server worker busy for 1 s, so throughput is roughly
(replicas x workers per Pod) requests per second and the effect of scaling
is easy to see.
"""

from __future__ import annotations

import argparse
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from client.rpc_client import RPCClient, RPCError


def percentile(sorted_values: list[float], fraction: float) -> float:
    return sorted_values[min(len(sorted_values) - 1, int(len(sorted_values) * fraction))]


def main() -> None:
    parser = argparse.ArgumentParser(description="RPC load test")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=30007)
    parser.add_argument("--total", type=int, default=300, help="total number of requests")
    parser.add_argument("--concurrency", type=int, default=50, help="simultaneous clients")
    parser.add_argument("--function", default="slow_task")
    parser.add_argument("--arg", type=int, default=1, help="argument of the procedure")
    parser.add_argument("--timeout", type=float, default=60.0, help="client timeout (s)")
    args = parser.parse_args()

    rpc = RPCClient(args.host, args.port, timeout=args.timeout)

    def one_request(_: int) -> tuple[bool, float, str]:
        start = time.perf_counter()
        try:
            rpc.call(args.function, args.arg)
            return True, time.perf_counter() - start, ""
        except RPCError as exc:
            # exc.__cause__ is the original socket error: it tells a failed
            # connection apart from a reply that never arrived.
            return False, time.perf_counter() - start, f"{exc.code} <- {exc.__cause__!r}"

    print(
        f"{args.total} x {args.function}({args.arg}) with {args.concurrency} "
        f"concurrent clients -> {args.host}:{args.port}"
    )
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(one_request, range(args.total)))
    elapsed = time.perf_counter() - started

    latencies = sorted(t for ok, t, _ in results if ok)
    failures = [(t, detail) for ok, t, detail in results if not ok]

    print(f"total time : {elapsed:.2f} s")
    print(f"successful : {len(latencies)}   errors: {len(failures)}")
    if latencies:
        print(f"throughput : {len(latencies) / elapsed:.1f} successful req/s")
        print(
            f"latency    : p50={percentile(latencies, 0.50):.2f} s  "
            f"p95={percentile(latencies, 0.95):.2f} s  max={latencies[-1]:.2f} s"
        )
    if failures:
        times = [t for t, _ in failures]
        print(
            f"failed after: min={min(times):.1f} s  avg={sum(times) / len(times):.1f} s  "
            f"max={max(times):.1f} s"
        )
        for detail, count in Counter(d for _, d in failures).most_common(3):
            print(f"  {count} x {detail}")


if __name__ == "__main__":
    main()
