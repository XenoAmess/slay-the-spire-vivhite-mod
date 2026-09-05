from __future__ import annotations

import copy
import hashlib
import importlib
import inspect
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


PROMO_ROOT = Path(__file__).resolve().parents[1]
if str(PROMO_ROOT) not in sys.path:
    sys.path.insert(0, str(PROMO_ROOT))

SCHEMA_PATH = PROMO_ROOT / "schemas" / "vivhite-promo-action-evidence-v2.schema.json"


class ActionEvidenceV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = importlib.import_module("vivhite_promo.action_evidence_v2")
        self.temporary = tempfile.TemporaryDirectory(prefix="vivhite-action-evidence-v2-")
        self.root = Path(self.temporary.name)
        self.identity = {
            "session_id": "capture-session-001",
            "game_run_id": "game-run-001",
            "game_process_id": "pid-1234-start-5678",
            "source_video_artifact_id": "raw-take-T03",
            "run_id": "promo-run-v2-001",
            "take_id": "T03",
            "subshot_id": "S03-cough-basic",
            "action_id": "action-001",
        }
        self.before_document = self._state_document(
            role="state.before",
            frame=110,
            timestamp=10.0,
            observation_seq=20,
            current_hp=78,
        )
        self.after_document = self._state_document(
            role="state.after",
            frame=170,
            timestamp=11.2,
            observation_seq=22,
            current_hp=77,
        )
        self.before = self._write_artifact(
            "evidence/state-before.json",
            self.before_document,
            "vivhite_promo_state_snapshot",
        )
        self.after = self._write_artifact(
            "evidence/state-after.json",
            self.after_document,
            "vivhite_promo_state_snapshot",
        )
        self.receipt_document = self._receipt_document()
        self.receipt = self._write_artifact(
            "evidence/action-receipt.json",
            self.receipt_document,
            "vivhite_promo_action_receipt",
        )
        self.setup_document = {
            "schema_version": 2,
            "kind": "vivhite_promo_staged_setup",
            "profile": "production",
            "provenance": "staged_setup",
            "capture_identity": copy.deepcopy(self.identity),
            "setup_end_frame": 80,
            "payload": {"operations": [{"kind": "deck_setup"}]},
        }
        self.setup = self._write_artifact(
            "evidence/staged-setup.json",
            self.setup_document,
            "vivhite_promo_staged_setup",
        )
        self.payload = {
            "schema_version": 2,
            "kind": "vivhite_promo_action_evidence",
            "profile": "production",
            "timebase": {"unit": "frames", "fps": 60},
            "run_id": self.identity["run_id"],
            "take_id": self.identity["take_id"],
            "subshot_id": self.identity["subshot_id"],
            "action_id": self.identity["action_id"],
            "action_kind": "play_card",
            "capture_identity": copy.deepcopy(self.identity),
            "recording_start_frame": 90,
            "display_span": {"begin_frame": 100, "end_frame": 240},
            "staged_setup": {
                "provenance": "staged_setup",
                "setup_end_frame": 80,
                "artifact": self.setup,
            },
            "state_before": {"role": "state.before", "artifact": self.before},
            "action_receipt": {
                "role": "action.receipt",
                "artifact": self.receipt,
            },
            "state_after": {"role": "state.after", "artifact": self.after},
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _state_document(
        self,
        *,
        role: str,
        frame: int,
        timestamp: float,
        observation_seq: int,
        current_hp: int,
    ) -> dict[str, object]:
        return {
            "schema_version": 2,
            "kind": "vivhite_promo_state_snapshot",
            "profile": "production",
            "status": "observed",
            "role": role,
            "capture_identity": copy.deepcopy(self.identity),
            "frame": frame,
            "monotonic_seconds": timestamp,
            "state_version": 13,
            "observation_seq": observation_seq,
            "payload": {
                "run_id": self.identity["game_run_id"],
                "state_version": 13,
                "screen": "COMBAT",
                "run": {"current_hp": current_hp},
                "hand": [{"id": "VIVHITE_CARD_LUMINOUS_PROJECTION"}],
            },
        }

    def _receipt_document(self, **overrides: object) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": 2,
            "kind": "vivhite_promo_action_receipt",
            "profile": "production",
            "role": "action.receipt",
            "capture_identity": copy.deepcopy(self.identity),
            "action_kind": "play_card",
            "input_origin": "game_ui_pointer",
            "status": "completed",
            "stable": True,
            "applied": True,
            "delivery": {"status": "sent"},
            "outcome": {"status": "applied"},
            "settled": True,
            "state_version": 13,
            "observation_seq": 21,
            "pointer_down_frame": 120,
            "pointer_up_frame": 121,
            "settled_frame": 160,
            "pointer_down_monotonic_seconds": 10.2,
            "pointer_up_monotonic_seconds": 10.21,
            "settled_monotonic_seconds": 11.0,
            "state_before_binding": {
                "sha256": self.before["sha256"],
                "state_version": 13,
                "observation_seq": 20,
            },
            "state_after_binding": {
                "sha256": self.after["sha256"],
                "state_version": 13,
                "observation_seq": 22,
            },
            "payload": self._action_payload("play_card"),
        }
        result.update(overrides)
        return result

    def _action_payload(self, action_kind: str) -> dict[str, object]:
        action_shapes = {
            "play_card": ("card", "VIVHITE_CARD_LUMINOUS_PROJECTION", {"card_id": "VIVHITE_CARD_LUMINOUS_PROJECTION"}),
            "end_turn": ("end_turn_button", "end_turn", {"control": "end_turn"}),
            "choose_reward_card": ("reward_card", "VIVHITE_CARD_AXIOM_RING", {"card_id": "VIVHITE_CARD_AXIOM_RING"}),
            "choose_map_node": ("map_node", "act1-row3-node2", {"node_id": "act1-row3-node2"}),
            "choose_rest_option": ("rest_option", "rest", {"option": "rest"}),
            "buy_card": ("shop_item", "shop-card-01", {"item_id": "shop-card-01", "item_kind": "card"}),
            "buy_relic": ("shop_item", "shop-relic-01", {"item_id": "shop-relic-01", "item_kind": "relic"}),
            "buy_potion": ("shop_item", "shop-potion-01", {"item_id": "shop-potion-01", "item_kind": "potion"}),
        }
        target_kind, target_id, parameters = action_shapes[action_kind]
        return {
            "pointer": {
                "button": "left",
                "x": 900,
                "y": 800,
                "down_frame": 120,
                "up_frame": 121,
                "down_monotonic_seconds": 10.2,
                "up_monotonic_seconds": 10.21,
            },
            "target": {"kind": target_kind, "id": target_id},
            "request": {
                "request_id": self.identity["action_id"],
                "action_kind": action_kind,
                "parameters": parameters,
            },
        }

    def _write_artifact(
        self, relative: str, value: object, document_kind: str
    ) -> dict[str, object]:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        path.write_bytes(data)
        return {
            "path": relative,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest().upper(),
            "media_type": "application/json",
            "document_kind": document_kind,
        }

    def _replace_receipt(
        self, payload: dict[str, object], document: dict[str, object], suffix: str
    ) -> None:
        payload["action_receipt"]["artifact"] = self._write_artifact(
            f"evidence/receipt-{suffix}.json",
            document,
            "vivhite_promo_action_receipt",
        )

    def _replace_state(
        self,
        payload: dict[str, object],
        section: str,
        document: dict[str, object],
        suffix: str,
    ) -> None:
        payload[section]["artifact"] = self._write_artifact(
            f"evidence/{section}-{suffix}.json",
            document,
            "vivhite_promo_state_snapshot",
        )

    def _validate(self, payload: dict[str, object] | None = None):
        return self.module.validate_action_evidence(
            self.payload if payload is None else payload,
            artifact_root=self.root,
        )

    def test_schema_declares_production_envelopes_and_shared_action_enum(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(2, schema["properties"]["schema_version"]["const"])
        self.assertEqual("production", schema["properties"]["profile"]["const"])
        self.assertEqual(60, schema["$defs"]["timebase"]["properties"]["fps"]["const"])
        self.assertEqual(
            {"path", "bytes", "sha256", "media_type", "document_kind"},
            set(schema["$defs"]["artifact"]["required"]),
        )
        kinds = set(schema["$defs"]["action_kind"]["enum"])
        self.assertTrue(
            {"play_card", "choose_map_node", "choose_rest_option", "buy_card"}
            <= kinds
        )
        self.assertNotIn("run_console_command", kinds)
        receipt = schema["$defs"]["action_receipt_document"]["properties"]
        self.assertEqual("game_ui_pointer", receipt["input_origin"]["const"])
        self.assertEqual(True, receipt["applied"]["const"])
        self.assertEqual(
            {"pointer", "target", "request"},
            set(schema["$defs"]["receipt_payload"]["required"]),
        )
        self.assertEqual(
            {"button", "x", "y", "down_frame", "up_frame",
             "down_monotonic_seconds", "up_monotonic_seconds"},
            set(schema["$defs"]["receipt_pointer"]["required"]),
        )

    def test_valid_production_contract_round_trips_and_loads(self) -> None:
        contract = self._validate()
        self.assertEqual(self.payload, contract.to_mapping())
        self.assertEqual(13, contract.state_before.state_version)
        self.assertEqual(20, contract.state_before.observation_seq)
        self.assertEqual(21, contract.action_receipt.observation_seq)
        self.assertEqual(22, contract.state_after.observation_seq)
        contract.verify_unchanged()

        path = self.root / "action-evidence.json"
        path.write_text(json.dumps(self.payload), encoding="utf-8")
        self.assertEqual(contract.to_mapping(), self.module.load_action_evidence(path).to_mapping())

    def test_action_kind_enum_covers_mechanism_map_campfire_and_shop(self) -> None:
        for index, action_kind in enumerate(
            (
                "play_card",
                "end_turn",
                "choose_reward_card",
                "choose_map_node",
                "choose_rest_option",
                "buy_card",
                "buy_relic",
                "buy_potion",
            )
        ):
            with self.subTest(action_kind=action_kind):
                payload = copy.deepcopy(self.payload)
                document = copy.deepcopy(self.receipt_document)
                document["action_kind"] = action_kind
                document["payload"] = self._action_payload(action_kind)
                payload["action_kind"] = action_kind
                self._replace_receipt(payload, document, f"kind-{index}")
                self.assertEqual(action_kind, self._validate(payload).action_kind)

    def test_direct_api_brain_console_and_debug_origins_are_rejected(self) -> None:
        for index, origin in enumerate(("direct_api", "brain", "console", "debug")):
            with self.subTest(origin=origin):
                payload = copy.deepcopy(self.payload)
                document = copy.deepcopy(self.receipt_document)
                document["input_origin"] = origin
                self._replace_receipt(payload, document, f"origin-{index}")
                with self.assertRaisesRegex(
                    self.module.ActionEvidenceError, "game_ui_pointer"
                ):
                    self._validate(payload)

    def test_payloads_recursively_reject_nonproduction_markers_and_flags(self) -> None:
        markers = (
            "direct_api",
            "brain",
            "console",
            "debug",
            "fixture",
            "synthetic",
            "pending",
            "failed",
            "Direct API v1",
            "capture-pending",
            "directApi",
            "DirectApi",
            "DIRECTAPI",
            "pendingState",
            "PENDINGSTATE",
        )
        for index, marker in enumerate(markers):
            with self.subTest(state_marker=marker):
                payload = copy.deepcopy(self.payload)
                document = copy.deepcopy(self.before_document)
                document["payload"]["nested_audit"] = [
                    {"producer_status": marker}
                ]
                self._replace_state(
                    payload, "state_before", document, f"payload-marker-{index}"
                )
                with self.assertRaisesRegex(
                    self.module.ActionEvidenceError, "prohibited production marker"
                ):
                    self._validate(payload)

        payload = copy.deepcopy(self.payload)
        receipt = copy.deepcopy(self.receipt_document)
        receipt["payload"]["request"]["parameters"]["audit"] = {
            "source": "direct_api",
            "status": "pending",
            "synthetic": True,
        }
        self._replace_receipt(payload, receipt, "nested-direct-api")
        with self.assertRaisesRegex(
            self.module.ActionEvidenceError, "prohibited production"
        ):
            self._validate(payload)

        payload = copy.deepcopy(self.payload)
        setup = copy.deepcopy(self.setup_document)
        setup["payload"]["operations"][0]["is_fixture"] = False
        setup_artifact = self._write_artifact(
            "evidence/setup-fixture-flag.json",
            setup,
            "vivhite_promo_staged_setup",
        )
        payload["staged_setup"]["artifact"] = setup_artifact
        with self.assertRaisesRegex(
            self.module.ActionEvidenceError, "prohibited production flag"
        ):
            self._validate(payload)

        payload = copy.deepcopy(self.payload)
        before = copy.deepcopy(self.before_document)
        before["payload"]["captureAudit"] = {
            "sourceTransport": "directApi",
            "isSynthetic": True,
            "producerStatus": "pendingState",
        }
        self._replace_state(payload, "state_before", before, "camelcase-bypass")
        with self.assertRaisesRegex(
            self.module.ActionEvidenceError, "prohibited production"
        ):
            self._validate(payload)

        for index, flag in enumerate(("isSynthetic", "IsSynthetic", "ISSYNTHETIC")):
            with self.subTest(flag=flag):
                payload = copy.deepcopy(self.payload)
                setup = copy.deepcopy(self.setup_document)
                setup["payload"]["operations"][0][flag] = False
                setup_artifact = self._write_artifact(
                    f"evidence/setup-flag-case-{index}.json",
                    setup,
                    "vivhite_promo_staged_setup",
                )
                payload["staged_setup"]["artifact"] = setup_artifact
                with self.assertRaisesRegex(
                    self.module.ActionEvidenceError, "prohibited production flag"
                ):
                    self._validate(payload)

        payload = copy.deepcopy(self.payload)
        after = copy.deepcopy(self.after_document)
        after["payload"]["nested_audit"] = {"synthetic_evidence": False}
        self._replace_state(payload, "state_after", after, "compound-flag")
        with self.assertRaisesRegex(
            self.module.ActionEvidenceError, "prohibited production flag"
        ):
            self._validate(payload)

    def test_receipt_payload_requires_pointer_target_and_semantic_request(self) -> None:
        cases: list[tuple[str, dict[str, object]]] = []

        irrelevant = copy.deepcopy(self.receipt_document)
        irrelevant["payload"] = {"irrelevant": True}
        cases.append(("irrelevant", irrelevant))

        missing_request = copy.deepcopy(self.receipt_document)
        del missing_request["payload"]["request"]
        cases.append(("missing-request", missing_request))

        missing_parameter = copy.deepcopy(self.receipt_document)
        missing_parameter["payload"]["request"]["parameters"] = {}
        cases.append(("missing-card-id", missing_parameter))

        wrong_target = copy.deepcopy(self.receipt_document)
        wrong_target["payload"]["target"]["id"] = "OTHER_CARD"
        cases.append(("wrong-target", wrong_target))

        wrong_request_kind = copy.deepcopy(self.receipt_document)
        wrong_request_kind["payload"]["request"]["action_kind"] = "end_turn"
        cases.append(("wrong-request-kind", wrong_request_kind))

        unrelated_request = copy.deepcopy(self.receipt_document)
        unrelated_request["payload"]["request"]["request_id"] = "unrelated-action"
        cases.append(("unrelated-request-id", unrelated_request))

        for suffix, document in cases:
            with self.subTest(case=suffix):
                payload = copy.deepcopy(self.payload)
                self._replace_receipt(payload, document, suffix)
                with self.assertRaises(self.module.ActionEvidenceError):
                    self._validate(payload)

    def test_receipt_payload_pointer_is_bound_to_envelope(self) -> None:
        mutations = (
            ("button", "right"),
            ("x", -1),
            ("x", 1920),
            ("y", 1080),
            ("down_frame", 119),
            ("up_frame", 122),
            ("down_monotonic_seconds", 10.19),
            ("up_monotonic_seconds", 10.22),
        )
        for index, (field, value) in enumerate(mutations):
            with self.subTest(field=field):
                payload = copy.deepcopy(self.payload)
                document = copy.deepcopy(self.receipt_document)
                document["payload"]["pointer"][field] = value
                self._replace_receipt(payload, document, f"pointer-binding-{index}")
                with self.assertRaises(self.module.ActionEvidenceError):
                    self._validate(payload)

    def test_action_specific_payload_shape_is_fail_closed(self) -> None:
        cases = (
            ("choose_map_node", "node_id", "wrong-node"),
            ("choose_rest_option", "option", "smith"),
            ("buy_card", "item_kind", "relic"),
            ("buy_relic", "item_kind", "potion"),
            ("buy_potion", "item_id", "different-item"),
        )
        for index, (action_kind, field, value) in enumerate(cases):
            with self.subTest(action_kind=action_kind, field=field):
                payload = copy.deepcopy(self.payload)
                payload["action_kind"] = action_kind
                document = copy.deepcopy(self.receipt_document)
                document["action_kind"] = action_kind
                document["payload"] = self._action_payload(action_kind)
                document["payload"]["request"]["parameters"][field] = value
                self._replace_receipt(payload, document, f"action-shape-{index}")
                with self.assertRaises(self.module.ActionEvidenceError):
                    self._validate(payload)

    def test_receipt_requires_positive_completed_stable_applied_outcome(self) -> None:
        invalid = (
            ("status", "pending"),
            ("stable", False),
            ("applied", False),
            ("settled", False),
            ("delivery", {"status": "queued"}),
            ("outcome", {"status": "pending"}),
        )
        for index, (field, value) in enumerate(invalid):
            with self.subTest(field=field):
                payload = copy.deepcopy(self.payload)
                document = copy.deepcopy(self.receipt_document)
                document[field] = value
                self._replace_receipt(payload, document, f"positive-{index}")
                with self.assertRaises(self.module.ActionEvidenceError):
                    self._validate(payload)

        payload = copy.deepcopy(self.payload)
        document = copy.deepcopy(self.receipt_document)
        del document["outcome"]
        self._replace_receipt(payload, document, "missing-outcome")
        with self.assertRaisesRegex(self.module.ActionEvidenceError, "missing fields"):
            self._validate(payload)

    def test_state_backing_requires_observed_production_nonempty_payload(self) -> None:
        cases = (
            ("kind", "placeholder"),
            ("profile", "fixture"),
            ("status", "pending"),
            ("payload", {}),
        )
        for index, (field, value) in enumerate(cases):
            with self.subTest(field=field):
                payload = copy.deepcopy(self.payload)
                document = copy.deepcopy(self.before_document)
                document[field] = value
                self._replace_state(payload, "state_before", document, f"envelope-{index}")
                with self.assertRaises(self.module.ActionEvidenceError):
                    self._validate(payload)

    def test_complete_capture_identity_matches_root_and_every_envelope(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["capture_identity"]["take_id"] = "different-take"
        with self.assertRaisesRegex(self.module.ActionEvidenceError, "root take_id"):
            self._validate(payload)

        for index, field in enumerate(self.identity):
            with self.subTest(field=field):
                payload = copy.deepcopy(self.payload)
                document = copy.deepcopy(self.after_document)
                document["capture_identity"][field] = "different-id"
                if field == "game_run_id":
                    document["payload"]["run_id"] = "different-id"
                self._replace_state(payload, "state_after", document, f"identity-{index}")
                with self.assertRaisesRegex(
                    self.module.ActionEvidenceError, "capture identity"
                ):
                    self._validate(payload)

    def test_protocol_state_version_is_bound_but_observation_seq_orders_action(self) -> None:
        payload = copy.deepcopy(self.payload)
        document = copy.deepcopy(self.after_document)
        document["state_version"] = 14
        document["payload"]["state_version"] = 14
        self._replace_state(payload, "state_after", document, "wrong-protocol")
        with self.assertRaisesRegex(self.module.ActionEvidenceError, "same protocol version"):
            self._validate(payload)

        for index, (before_seq, receipt_seq, after_seq) in enumerate(
            ((21, 21, 22), (20, 23, 22))
        ):
            with self.subTest(sequences=(before_seq, receipt_seq, after_seq)):
                payload = copy.deepcopy(self.payload)
                before = copy.deepcopy(self.before_document)
                before["observation_seq"] = before_seq
                after = copy.deepcopy(self.after_document)
                after["observation_seq"] = after_seq
                self._replace_state(payload, "state_before", before, f"seq-b-{index}")
                self._replace_state(payload, "state_after", after, f"seq-a-{index}")
                receipt = copy.deepcopy(self.receipt_document)
                receipt["observation_seq"] = receipt_seq
                self._replace_receipt(payload, receipt, f"seq-r-{index}")
                with self.assertRaisesRegex(
                    self.module.ActionEvidenceError, "observation_seq"
                ):
                    self._validate(payload)

    def test_receipt_binds_before_and_after_hash_version_and_sequence(self) -> None:
        for index, side in enumerate(("state_before_binding", "state_after_binding")):
            for field, value in (
                ("sha256", "0" * 64),
                ("state_version", 99),
                ("observation_seq", 99),
            ):
                with self.subTest(side=side, field=field):
                    payload = copy.deepcopy(self.payload)
                    document = copy.deepcopy(self.receipt_document)
                    document[side][field] = value
                    self._replace_receipt(payload, document, f"binding-{index}-{field}")
                    with self.assertRaisesRegex(
                        self.module.ActionEvidenceError, "does not bind"
                    ):
                        self._validate(payload)

    def test_frame_and_monotonic_sequences_are_strict_and_inside_display(self) -> None:
        frame_cases = (
            {"pointer_down_frame": 121},
            {"pointer_up_frame": 120},
            {"settled_frame": 170},
        )
        for index, overrides in enumerate(frame_cases):
            with self.subTest(overrides=overrides):
                payload = copy.deepcopy(self.payload)
                document = self._receipt_document(**overrides)
                self._replace_receipt(payload, document, f"frame-{index}")
                with self.assertRaisesRegex(self.module.ActionEvidenceError, "frames"):
                    self._validate(payload)

        payload = copy.deepcopy(self.payload)
        after = copy.deepcopy(self.after_document)
        after["frame"] = payload["display_span"]["end_frame"]
        self._replace_state(payload, "state_after", after, "display-end")
        with self.assertRaisesRegex(self.module.ActionEvidenceError, "display end"):
            self._validate(payload)

        payload = copy.deepcopy(self.payload)
        document = self._receipt_document(pointer_up_monotonic_seconds=10.2)
        self._replace_receipt(payload, document, "time-order")
        with self.assertRaisesRegex(self.module.ActionEvidenceError, "times"):
            self._validate(payload)

    def test_staged_setup_must_end_strictly_before_recording_and_display(self) -> None:
        for index, end_frame in enumerate((90, 95, 100)):
            with self.subTest(end_frame=end_frame):
                payload = copy.deepcopy(self.payload)
                setup = copy.deepcopy(self.setup_document)
                setup["setup_end_frame"] = end_frame
                artifact = self._write_artifact(
                    f"evidence/setup-late-{index}.json",
                    setup,
                    "vivhite_promo_staged_setup",
                )
                payload["staged_setup"] = {
                    "provenance": "staged_setup",
                    "setup_end_frame": end_frame,
                    "artifact": artifact,
                }
                with self.assertRaisesRegex(
                    self.module.ActionEvidenceError, "before recording_start_frame"
                ):
                    self._validate(payload)

    def test_every_artifact_requires_positive_bytes_and_unskippable_sha(self) -> None:
        for field in ("bytes", "sha256"):
            payload = copy.deepcopy(self.payload)
            del payload["state_before"]["artifact"][field]
            with self.assertRaisesRegex(self.module.ActionEvidenceError, "missing fields"):
                self._validate(payload)

        payload = copy.deepcopy(self.payload)
        payload["state_before"]["artifact"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(self.module.ActionEvidenceError, "does not match"):
            self._validate(payload)

        signature = inspect.signature(self.module.validate_action_evidence)
        self.assertNotIn("verify_hashes", signature.parameters)
        with self.assertRaises(TypeError):
            self.module.validate_action_evidence(
                self.payload,
                artifact_root=self.root,
                verify_hashes=False,
            )

    def test_renamed_dummy_and_direct_api_native_receipt_cannot_pass(self) -> None:
        dummy_path = self.root / "evidence" / "renamed-dummy.json"
        dummy_path.write_text(
            "synthetic action receipt evidence; not a production action receipt\n",
            encoding="utf-8",
        )
        data = dummy_path.read_bytes()
        payload = copy.deepcopy(self.payload)
        payload["action_receipt"]["artifact"] = {
            "path": "evidence/renamed-dummy.json",
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest().upper(),
            "media_type": "application/json",
            "document_kind": "vivhite_promo_action_receipt",
        }
        with self.assertRaisesRegex(self.module.ActionEvidenceError, "valid UTF-8 JSON"):
            self._validate(payload)

        native_direct = {
            "action": "play_card",
            "status": "completed",
            "stable": True,
            "state": {"run_id": self.identity["game_run_id"], "state_version": 13},
        }
        payload = copy.deepcopy(self.payload)
        self._replace_receipt(payload, native_direct, "native-direct-api")
        with self.assertRaisesRegex(self.module.ActionEvidenceError, "kind"):
            self._validate(payload)

    def test_paths_reject_escape_whitespace_reserved_and_nonregular_targets(self) -> None:
        for unsafe in (
            "../state-before.json",
            "/absolute/state-before.json",
            "C:/state-before.json",
            " evidence/state-before.json",
            "evidence/state-before.json ",
            "evidence\\state-before.json",
            "evi:dence/state-before.json",
            "NUL.json",
            "evidence/state-before.txt",
        ):
            with self.subTest(path=unsafe):
                payload = copy.deepcopy(self.payload)
                payload["state_before"]["artifact"]["path"] = unsafe
                with self.assertRaises(self.module.ActionEvidenceError):
                    self._validate(payload)

        directory = self.root / "evidence" / "directory.json"
        directory.mkdir()
        payload = copy.deepcopy(self.payload)
        payload["state_before"]["artifact"]["path"] = "evidence/directory.json"
        with self.assertRaisesRegex(self.module.ActionEvidenceError, "regular file"):
            self._validate(payload)

    def test_symlink_and_hardlink_artifacts_are_rejected_when_supported(self) -> None:
        source = self.root / self.before["path"]
        symlink = self.root / "evidence" / "linked-before.json"
        try:
            symlink.symlink_to(source)
        except OSError:
            pass
        else:
            payload = copy.deepcopy(self.payload)
            payload["state_before"]["artifact"]["path"] = "evidence/linked-before.json"
            with self.assertRaisesRegex(
                self.module.ActionEvidenceError, "symlink or reparse"
            ):
                self._validate(payload)

        hardlink = self.root / "evidence" / "hardlinked-before.json"
        try:
            os.link(source, hardlink)
        except OSError:
            pass
        else:
            payload = copy.deepcopy(self.payload)
            payload["state_before"]["artifact"]["path"] = "evidence/hardlinked-before.json"
            with self.assertRaisesRegex(self.module.ActionEvidenceError, "hard-linked"):
                self._validate(payload)

    def test_sidecar_itself_must_be_local_regular_unlinked_and_bounded(self) -> None:
        sidecar = self.root / "action-evidence.json"
        sidecar.write_text(json.dumps(self.payload), encoding="utf-8")
        self.module.load_action_evidence(sidecar)

        text_sidecar = self.root / "action-evidence.txt"
        text_sidecar.write_text(json.dumps(self.payload), encoding="utf-8")
        with self.assertRaisesRegex(self.module.ActionEvidenceError, "json filename"):
            self.module.load_action_evidence(text_sidecar)

        separate_root = self.root / "separate-artifact-root"
        separate_root.mkdir()
        with self.assertRaisesRegex(
            self.module.ActionEvidenceError, "inside artifact_root"
        ):
            self.module.load_action_evidence(
                sidecar,
                artifact_root=separate_root,
            )

        with self.assertRaisesRegex(
            self.module.ActionEvidenceError, "requires a sidecar path"
        ):
            self.module.load_action_evidence(
                self.payload,
                artifact_root=self.root,
            )

        directory_sidecar = self.root / "directory-sidecar.json"
        directory_sidecar.mkdir()
        with self.assertRaisesRegex(
            self.module.ActionEvidenceError, "regular file"
        ):
            self.module.load_action_evidence(directory_sidecar)

        oversized = self.root / "oversized-action-evidence.json"
        with oversized.open("wb") as handle:
            handle.seek(16 * 1024 * 1024)
            handle.write(b"x")
        with self.assertRaisesRegex(
            self.module.ActionEvidenceError, "16777216-byte limit"
        ):
            self.module.load_action_evidence(oversized)

        symlink = self.root / "linked-action-evidence.json"
        try:
            symlink.symlink_to(sidecar)
        except OSError:
            pass
        else:
            with self.assertRaisesRegex(
                self.module.ActionEvidenceError, "symlink or reparse"
            ):
                self.module.load_action_evidence(symlink)

        hardlink = self.root / "hardlinked-action-evidence.json"
        try:
            os.link(sidecar, hardlink)
        except OSError:
            pass
        else:
            with self.assertRaisesRegex(
                self.module.ActionEvidenceError, "hard-linked"
            ):
                self.module.load_action_evidence(hardlink)

    def test_unc_sidecar_and_artifact_root_are_rejected_before_access(self) -> None:
        unc_sidecar = r"\\server\share\action-evidence.json"
        unc_root = r"\\server\share\evidence-root"
        with self.assertRaisesRegex(self.module.ActionEvidenceError, "local path"):
            self.module.load_action_evidence(unc_sidecar)
        with self.assertRaisesRegex(self.module.ActionEvidenceError, "local path"):
            self.module.validate_action_evidence(
                self.payload,
                artifact_root=unc_root,
            )

    def test_artifact_root_cannot_hide_behind_directory_link(self) -> None:
        linked_root = self.root / "linked-root"
        try:
            linked_root.symlink_to(self.root, target_is_directory=True)
        except OSError:
            return
        with self.assertRaisesRegex(
            self.module.ActionEvidenceError, "symlink or reparse"
        ):
            self.module.validate_action_evidence(
                self.payload,
                artifact_root=linked_root,
            )

    def test_artifact_documents_are_recursively_immutable(self) -> None:
        source_payload = copy.deepcopy(self.payload)
        contract = self._validate(source_payload)
        with self.assertRaises(TypeError):
            contract.state_before.artifact.document["payload"]["run"]["current_hp"] = 1
        self.assertIsInstance(
            contract.state_before.artifact.document["payload"]["hand"], tuple
        )
        with self.assertRaises(TypeError):
            contract.state_before.artifact.document["payload"]["hand"][0]["id"] = "x"

        source_payload["capture_identity"]["session_id"] = "mutated"
        exported = contract.to_mapping()
        exported["capture_identity"]["session_id"] = "also-mutated"
        self.assertEqual("capture-session-001", contract.capture_identity.session_id)
        contract.verify_unchanged()

    def test_verify_unchanged_detects_backing_file_mutation(self) -> None:
        contract = self._validate()
        (self.root / self.before["path"]).write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(self.module.ActionEvidenceError, "changed"):
            contract.verify_unchanged()

    def test_outer_whitespace_in_ids_is_rejected_not_trimmed(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["run_id"] += " "
        with self.assertRaisesRegex(self.module.ActionEvidenceError, "outer whitespace"):
            self._validate(payload)


if __name__ == "__main__":
    unittest.main()
