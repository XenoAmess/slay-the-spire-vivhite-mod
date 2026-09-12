"""Local-only HTTP receipt and discovery regressions; never contact the game."""
from __future__ import annotations

import http.client
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock
import urllib.error


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import client  # noqa: E402
from manual_control import BrainControlPaused  # noqa: E402


class ClientTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = client.Sts2Client(ports=(8080, 8081))
        self.transport.base_url = "http://127.0.0.1:8080"
        self.gate = self.enterContext(mock.patch.object(
            client, "ensure_action_allowed"))

    def test_pause_during_initial_discovery_prevents_post(self) -> None:
        self.transport.base_url = None
        self.gate.side_effect = [None, BrainControlPaused("paused during discovery")]
        with mock.patch.object(self.transport, "_raw_request", return_value={
                "status": "ready"}) as request:
            with self.assertRaises(BrainControlPaused):
                self.transport.act("end_turn")
        self.assertEqual(self.gate.call_count, 2)
        self.assertEqual([call.args[0] for call in request.call_args_list], ["GET"])
        self.assertTrue(request.call_args.args[1].endswith("/health"))

    def test_connected_action_keeps_one_pause_read_and_one_post(self) -> None:
        with mock.patch.object(self.transport, "_raw_request", return_value={
                "status": "completed"}) as request:
            self.assertEqual(self.transport.act("end_turn"), {"status": "completed"})
        self.gate.assert_called_once_with()
        request.assert_called_once()
        self.assertEqual(request.call_args.args[0], "POST")

    def test_lost_action_receipt_only_probes_health_without_replay(self) -> None:
        with mock.patch.object(self.transport, "_raw_request", side_effect=[
                client.ConnectionDown("receipt lost"), {"status": "ready"}]) as request:
            with self.assertRaisesRegex(client.ConnectionDown, "receipt lost"):
                self.transport.act("end_turn")
        self.assertEqual([call.args[0] for call in request.call_args_list], ["POST", "GET"])
        self.assertTrue(request.call_args.args[1].endswith("/health"))

    def test_get_retries_once_on_discovered_port(self) -> None:
        snapshot = {"screen": "MAP", "run_id": "test-run"}
        with mock.patch.object(self.transport, "_raw_request", side_effect=[
                client.ConnectionDown("old port down"),
                client.ConnectionDown("old port down"),
                {"status": "ready"}, snapshot]) as request:
            self.assertEqual(self.transport.state(), snapshot)
        self.assertEqual([call.args[1] for call in request.call_args_list], [
            "http://127.0.0.1:8080/state", "http://127.0.0.1:8080/health",
            "http://127.0.0.1:8081/health", "http://127.0.0.1:8081/state"])
        self.gate.assert_not_called()

    def test_get_second_failure_does_not_loop(self) -> None:
        with mock.patch.object(self.transport, "_raw_request", side_effect=[
                client.ConnectionDown("first failure"), {"status": "ready"},
                client.ConnectionDown("second failure")]) as request:
            with self.assertRaisesRegex(client.ConnectionDown, "second failure"):
                self.transport.state()
        self.assertEqual(request.call_count, 3)

    def test_invalid_local_payload_never_reaches_transport(self) -> None:
        with mock.patch.object(client.urllib.request, "urlopen") as urlopen:
            with self.assertRaises(client.ApiError) as failure:
                self.transport._raw_request("POST", self.transport.base_url + "/action",
                                            {"unserializable": object()})
        self.assertEqual(failure.exception.code, "invalid_request")
        self.assertEqual(failure.exception.status, 0)
        urlopen.assert_not_called()

    def test_http_rejection_preserves_fields_and_closes_response(self) -> None:
        body = io.BytesIO(json.dumps({"ok": False, "error": {
            "code": "invalid_action", "message": "not available", "retryable": True,
        }}).encode("utf-8"))
        error = urllib.error.HTTPError(self.transport.base_url + "/action", 409,
                                       "Conflict", {}, body)
        with mock.patch.object(client.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(client.ApiError) as failure:
                self.transport._raw_request("POST", error.url, {"action": "end_turn"})
        self.assertEqual(failure.exception.code, "invalid_action")
        self.assertEqual(failure.exception.status, 409)
        self.assertTrue(failure.exception.retryable)
        self.assertTrue(body.closed)

    def test_malformed_http_error_is_ambiguous_and_closes_response(self) -> None:
        body = io.BytesIO(b'{"error":')
        error = urllib.error.HTTPError(self.transport.base_url + "/action", 500,
                                       "Server error", {}, body)
        with mock.patch.object(client.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(client.ConnectionDown):
                self.transport._raw_request("POST", error.url, {"action": "end_turn"})
        self.assertTrue(body.closed)

    def test_truncated_http_error_is_ambiguous_and_closes_response(self) -> None:
        class TruncatedBody(io.BytesIO):
            def read(self, *args):
                raise http.client.IncompleteRead(b'{"ok":false,', 80)

        body = TruncatedBody()
        error = urllib.error.HTTPError(self.transport.base_url + "/action", 500,
                                       "Server error", {}, body)
        with mock.patch.object(client.urllib.request, "urlopen", side_effect=error):
            with self.assertRaisesRegex(client.ConnectionDown, "truncated HTTP error"):
                self.transport._raw_request("POST", error.url, {"action": "end_turn"})
        self.assertTrue(body.closed)


if __name__ == "__main__":
    unittest.main()
