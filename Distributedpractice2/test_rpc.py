"""Tests for the RPC system.

Run from the project root:

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import socket
import struct
import threading
import time
import unittest
from unittest import mock

from client.rpc_client import RPCClient, RPCError
from common.protocol import recv_json, send_json
from server import procedures
from server import server as server_module
from server.rpc_server import ErrorCode, RPCServer


class ProtocolTests(unittest.TestCase):
    def test_send_and_receive_json(self):
        left, right = socket.socketpair()

        try:
            expected = {
                "function": "add",
                "args": [4, 7],
            }

            send_json(left, expected)
            received = recv_json(right)

            self.assertEqual(received, expected)

        finally:
            left.close()
            right.close()


class DispatcherTests(unittest.TestCase):
    def setUp(self):
        self.rpc = server_module.build_service()

    def assertError(self, response, code):
        self.assertEqual(response["status"], "error")
        self.assertEqual(response["error"], code)
        self.assertIn("message", response)

    def test_ok(self):
        self.assertEqual(
            self.rpc.dispatch({"function": "add", "args": [4, 7]}),
            {"status": "ok", "result": 11},
        )

    def test_args_are_optional(self):
        response = self.rpc.dispatch({"function": "server_info"})
        self.assertEqual(response["status"], "ok")

    def test_unknown_procedure(self):
        self.assertError(
            self.rpc.dispatch({"function": "nope", "args": []}), ErrorCode.PROCEDURE_NOT_FOUND
        )

    def test_wrong_number_of_arguments(self):
        self.assertError(
            self.rpc.dispatch({"function": "add", "args": [1]}), ErrorCode.INVALID_ARGUMENTS
        )
        self.assertError(
            self.rpc.dispatch({"function": "add", "args": [1, 2, 3]}), ErrorCode.INVALID_ARGUMENTS
        )

    def test_exception_inside_procedure(self):
        self.assertError(
            self.rpc.dispatch({"function": "power", "args": [0, -1]}), ErrorCode.EXECUTION_ERROR
        )
        # A TypeError raised *inside* the procedure is an execution error,
        # not an argument-count problem.
        self.assertError(
            self.rpc.dispatch({"function": "add", "args": ["a", 1]}), ErrorCode.EXECUTION_ERROR
        )

    def test_bad_messages(self):
        for request in (
            [],
            "add",
            {"args": [1, 2]},
            {"function": 5, "args": []},
            {"function": ["add"], "args": []},
            {"function": "add", "args": "1,2"},
        ):
            with self.subTest(request=request):
                self.assertError(self.rpc.dispatch(request), ErrorCode.BAD_MESSAGE)

    def test_result_not_serializable(self):
        self.rpc.register("make_set", lambda: {1, 2})
        self.assertError(
            self.rpc.dispatch({"function": "make_set", "args": []}), ErrorCode.EXECUTION_ERROR
        )

    def test_register_validation(self):
        rpc = RPCServer()
        rpc.register("add", procedures.add)
        with self.assertRaises(ValueError):
            rpc.register("add", procedures.add)  # duplicate
        with self.assertRaises(TypeError):
            rpc.register("x", 42)  # not callable
        with self.assertRaises(ValueError):
            rpc.register("", procedures.add)  # empty name

    def test_list_procedures(self):
        response = self.rpc.dispatch({"function": "list_procedures", "args": []})
        self.assertIn("add", response["result"])
        self.assertIn("list_procedures", response["result"])


class ProcedureTests(unittest.TestCase):
    def test_prime_factors(self):
        self.assertEqual(procedures.prime_factors(360), [2, 2, 2, 3, 3, 5])
        self.assertEqual(procedures.prime_factors(97), [97])
        for bad in (1, 0, -5, 10**13):
            with self.assertRaises(ValueError):
                procedures.prime_factors(bad)
        for bad in (2.0, "12", True):
            with self.assertRaises(TypeError):
                procedures.prime_factors(bad)


class ServerTestCase(unittest.TestCase):
    """Starts a real server on a free local port for each test class."""

    max_workers = 8

    @classmethod
    def setUpClass(cls):
        cls.stop = threading.Event()
        ready = threading.Event()
        ports = []

        def on_ready(port):
            ports.append(port)
            ready.set()

        cls.thread = threading.Thread(
            target=server_module.serve,
            kwargs=dict(
                rpc=server_module.build_service(),
                host="127.0.0.1",
                port=0,
                max_workers=cls.max_workers,
                stop_event=cls.stop,
                on_ready=on_ready,
            ),
            daemon=True,
        )
        cls.thread.start()
        assert ready.wait(5), "the server did not start"
        cls.port = ports[0]

    @classmethod
    def tearDownClass(cls):
        cls.stop.set()
        cls.thread.join(timeout=10)

    def client(self, timeout=5.0):
        return RPCClient("127.0.0.1", self.port, timeout=timeout)


class IntegrationTests(ServerTestCase):
    def test_remote_calls(self):
        rpc = self.client()
        self.assertEqual(rpc.call("add", 4, 7), 11)
        self.assertEqual(rpc.call("multiply", 3, 5), 15)
        self.assertEqual(rpc.call("power", 2, 10), 1024)
        self.assertEqual(rpc.call("slow_task", 0.1), 0.1)

    def test_server_errors_become_rpc_errors(self):
        rpc = self.client()
        cases = [
            (("nope",), ErrorCode.PROCEDURE_NOT_FOUND),
            (("add", 1), ErrorCode.INVALID_ARGUMENTS),
            (("power", 0, -1), ErrorCode.EXECUTION_ERROR),
        ]
        for args, code in cases:
            with self.subTest(args=args):
                with self.assertRaises(RPCError) as ctx:
                    rpc.call(*args)
                self.assertEqual(ctx.exception.code, code)

    def test_unserializable_argument_never_reaches_the_network(self):
        with self.assertRaises(RPCError) as ctx:
            self.client().call("add", {1, 2}, 3)
        self.assertEqual(ctx.exception.code, "BAD_REQUEST")

    def test_client_timeout(self):
        start = time.perf_counter()
        with self.assertRaises(RPCError) as ctx:
            self.client(timeout=0.5).call("slow_task", 3)
        self.assertEqual(ctx.exception.code, "TIMEOUT")
        self.assertLess(time.perf_counter() - start, 2.0)

    def test_server_unreachable(self):
        with socket.socket() as probe:  # grab a port that nobody listens on
            probe.bind(("127.0.0.1", 0))
            closed_port = probe.getsockname()[1]
        with self.assertRaises(RPCError) as ctx:
            RPCClient("127.0.0.1", closed_port, timeout=1.0).call("add", 1, 2)
        self.assertEqual(ctx.exception.code, "CONNECTION_ERROR")

    def test_server_answers_bad_json_with_bad_message(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            payload = b"this is not json"
            sock.sendall(struct.pack("!I", len(payload)) + payload)
            response = recv_json(sock)
        self.assertEqual(response["status"], "error")
        self.assertEqual(response["error"], ErrorCode.BAD_MESSAGE)

    def test_server_answers_non_object_json_with_bad_message(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            payload = b"[1, 2, 3]"
            sock.sendall(struct.pack("!I", len(payload)) + payload)
            response = recv_json(sock)
        self.assertEqual(response["error"], ErrorCode.BAD_MESSAGE)

    def test_message_larger_than_one_recv(self):
        # The framing must cope with messages bigger than a single recv().
        text = "x" * 100_000
        self.assertEqual(self.client().call("add", text, "y"), text + "y")


class ConcurrencyTests(ServerTestCase):
    def test_clients_are_served_in_parallel(self):
        rpc = self.client()
        results = []
        lock = threading.Lock()

        def worker():
            value = rpc.call("slow_task", 1)
            with lock:
                results.append(value)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        start = time.perf_counter()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        elapsed = time.perf_counter() - start

        self.assertEqual(results, [1] * 5)
        self.assertLess(elapsed, 2.5, "5 x slow_task(1) should overlap, not take ~5 s")


class IdleClientTests(ServerTestCase):
    max_workers = 1

    def test_silent_client_does_not_block_the_server_forever(self):
        with mock.patch.object(server_module, "CLIENT_TIMEOUT", 0.5):
            with socket.create_connection(("127.0.0.1", self.port), timeout=5):
                # This connection never sends anything and occupies the only worker...
                time.sleep(0.1)
                # ...until the server-side timeout frees it.
                self.assertEqual(self.client(timeout=3.0).call("add", 1, 2), 3)


if __name__ == "__main__":
    unittest.main()
