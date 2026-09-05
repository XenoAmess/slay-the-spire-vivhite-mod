from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


PROMO_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = Path(__file__).resolve().parent
for candidate in (PROMO_ROOT, TEST_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from test_director_v2_validator import storyboard as make_storyboard  # noqa: E402
from vivhite_promo import action_evidence_v2 as action_evidence  # noqa: E402
from vivhite_promo import production_binder_v2 as binder  # noqa: E402


class ProductionFixture:
    def __init__(self, root: Path, *, crown_heal: int = 16) -> None:
        self.root = root
        self.board = make_storyboard()
        self.crown_heal = crown_heal
        self.action_sidecars: dict[str, Path] = {}
        self.manifest = self._build()
        self.storyboard_path = self.root / "storyboard.json"
        self.manifest_path = self.root / "take-manifest.json"
        self._write_json_absolute(self.storyboard_path, self.board)
        self._write_json_absolute(self.manifest_path, self.manifest)

    def _write_json_absolute(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _write(self, relative: str, payload: object) -> dict[str, object]:
        path = self.root / relative
        self._write_json_absolute(path, payload)
        data = path.read_bytes()
        return {
            "path": relative,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest().upper(),
        }

    def _source(self, take_id: str) -> tuple[dict[str, object], dict[str, str]]:
        relative = f"raw/{take_id}.mkv"
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"VIVHITE-PRODUCTION-TAKE\0" + take_id.encode("ascii"))
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest().upper()
        capture = {
            "session_id": "session-production-001",
            "game_run_id": f"game-run-{take_id}",
            "game_process_id": "game-pid-444-start-001",
            "source_video_artifact_id": f"raw-take-{take_id}",
            "run_id": "promo-run-v2-001",
            "take_id": take_id,
        }
        source: dict[str, object] = {
            "artifact": relative,
            "duration_seconds": 60,
            "bytes": len(data),
            "sha256": digest,
            "capture_identity": capture,
            "game_process": {
                "pid": 444,
                "identity": capture["game_process_id"],
                "started_utc": "2026-09-03T00:00:00Z",
            },
            "recorder_process": {
                "pid": 555,
                "identity": "obs-pid-555-start-001",
                "started_utc": "2026-09-03T00:01:00Z",
            },
            "recording": {
                "start_frame": 100,
                "end_frame": 3700,
                "started_monotonic_seconds": 100,
                "stopped_monotonic_seconds": 160,
            },
        }
        probe = {
            "schema_version": 2,
            "kind": "vivhite_promo_source_probe_v2",
            "status": "completed",
            "source": {"path": relative, "bytes": len(data), "sha256": digest},
            "result": {
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "pix_fmt": "yuv420p",
                        "width": 1920,
                        "height": 1080,
                        "r_frame_rate": "60/1",
                        "avg_frame_rate": "60/1",
                        "nb_read_frames": "3600",
                        "duration": "60.000000",
                        "start_time": "0.000000",
                    },
                    {
                        "codec_type": "audio",
                        "codec_name": "aac",
                        "sample_rate": "48000",
                        "channels": 2,
                        "channel_layout": "stereo",
                        "duration": "60.000000",
                        "start_time": "0.000000",
                    },
                ],
                "format": {"duration": "60.000000"},
            },
        }
        source["ffprobe"] = self._write(f"probe/{take_id}.json", probe)
        return source, capture

    def _state_document(
        self,
        *,
        identity: dict[str, str],
        role: str,
        frame: int,
        timestamp: float,
        sequence: int,
        after: bool,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "run_id": identity["game_run_id"],
            "state_version": 13,
            "run": {
                "current_hp": 70 if after else 50,
                "max_hp": 78,
            },
            "relics": [{"id": "VIVHITE_RELIC_ORIGIN_STAR_CHART"}],
            "hand": ([{"id": "CARD_AFTER"}] if after else [{"id": "CARD_BEFORE"}]),
        }
        if after:
            payload["production_observations"] = {
                "actual_drain_healing": 4,
                "solitary_crown_actual_healing": self.crown_heal,
                "actual_draw_delta": 1,
                "actual_energy_gain": 1,
                "enemy_deaths": 2,
                "event_order": [
                    "drain_healing",
                    "solitary_crown_recovery",
                    "card_draw",
                    "energy_gain",
                ],
            }
        return {
            "schema_version": 2,
            "kind": "vivhite_promo_state_snapshot",
            "profile": "production",
            "status": "observed",
            "role": role,
            "capture_identity": identity,
            "frame": frame,
            "monotonic_seconds": timestamp,
            "state_version": 13,
            "observation_seq": sequence,
            "payload": payload,
        }

    def _formal_action(
        self,
        *,
        take_id: str,
        subshot_id: str,
        capture: dict[str, str],
        card_id: str,
        before_ref: str,
        receipt_ref: str,
        after_ref: str,
    ) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
        action_id = f"action-{take_id}"
        identity = {
            **capture,
            "subshot_id": subshot_id,
            "action_id": action_id,
        }
        before = self._write(
            f"evidence/{take_id}/state-before.json",
            self._state_document(
                identity=identity,
                role="state.before",
                frame=310,
                timestamp=105,
                sequence=20,
                after=False,
            ),
        )
        before.update(
            {
                "media_type": "application/json",
                "document_kind": "vivhite_promo_state_snapshot",
            }
        )
        after = self._write(
            f"evidence/{take_id}/state-after.json",
            self._state_document(
                identity=identity,
                role="state.after",
                frame=350,
                timestamp=105.8,
                sequence=22,
                after=True,
            ),
        )
        after.update(
            {
                "media_type": "application/json",
                "document_kind": "vivhite_promo_state_snapshot",
            }
        )
        receipt_document = {
            "schema_version": 2,
            "kind": "vivhite_promo_action_receipt",
            "profile": "production",
            "role": "action.receipt",
            "capture_identity": identity,
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
            "pointer_down_frame": 330,
            "pointer_up_frame": 331,
            "settled_frame": 340,
            "pointer_down_monotonic_seconds": 105.2,
            "pointer_up_monotonic_seconds": 105.21,
            "settled_monotonic_seconds": 105.5,
            "state_before_binding": {
                "sha256": before["sha256"],
                "state_version": 13,
                "observation_seq": 20,
            },
            "state_after_binding": {
                "sha256": after["sha256"],
                "state_version": 13,
                "observation_seq": 22,
            },
            "payload": {
                "pointer": {
                    "button": "left",
                    "x": 900,
                    "y": 800,
                    "down_frame": 330,
                    "up_frame": 331,
                    "down_monotonic_seconds": 105.2,
                    "up_monotonic_seconds": 105.21,
                },
                "target": {"kind": "card", "id": card_id},
                "request": {
                    "request_id": action_id,
                    "action_kind": "play_card",
                    "parameters": {"card_id": card_id},
                },
            },
        }
        receipt = self._write(f"evidence/{take_id}/receipt.json", receipt_document)
        receipt.update(
            {
                "media_type": "application/json",
                "document_kind": "vivhite_promo_action_receipt",
            }
        )
        setup_document = {
            "schema_version": 2,
            "kind": "vivhite_promo_staged_setup",
            "profile": "production",
            "provenance": "staged_setup",
            "capture_identity": identity,
            "setup_end_frame": 80,
            "payload": {"operations": [{"kind": "deck_setup"}]},
        }
        setup = self._write(f"setup/{take_id}.json", setup_document)
        setup.update(
            {
                "media_type": "application/json",
                "document_kind": "vivhite_promo_staged_setup",
            }
        )
        contract = {
            "schema_version": 2,
            "kind": "vivhite_promo_action_evidence",
            "profile": "production",
            "timebase": {"unit": "frames", "fps": 60},
            "run_id": capture["run_id"],
            "take_id": take_id,
            "subshot_id": subshot_id,
            "action_id": action_id,
            "action_kind": "play_card",
            "capture_identity": identity,
            "recording_start_frame": 100,
            "display_span": {"begin_frame": 300, "end_frame": 360},
            "staged_setup": {
                "provenance": "staged_setup",
                "setup_end_frame": 80,
                "artifact": setup,
            },
            "state_before": {"role": "state.before", "artifact": before},
            "action_receipt": {"role": "action.receipt", "artifact": receipt},
            "state_after": {"role": "state.after", "artifact": after},
        }
        sidecar = self._write(f"contracts/{take_id}.json", contract)
        self.action_sidecars[take_id] = self.root / str(sidecar["path"])
        entry = {
            "step_id": f"play-{take_id}",
            "action_id": action_id,
            "sidecar": sidecar,
            "pointer_hitbox": {"left": 800, "top": 700, "right": 1000, "bottom": 900},
            "visible_state_paths": ["/run/current_hp", "/hand/0/id"],
        }
        refs = {
            before_ref: before,
            receipt_ref: receipt,
            after_ref: after,
        }
        return entry, refs

    def _build(self) -> dict[str, object]:
        takes: list[dict[str, object]] = []
        action_subshots = {
            str(subshot["take"]["take_id"]): subshot
            for shot in self.board["shots"]
            for subshot in shot["subshots"]
            if subshot["asset_type"] == "mechanism_action"
        }
        board_takes = {str(row["take_id"]): row for row in self.board["takes"]}
        for take_id, subshot in action_subshots.items():
            board_takes[take_id]["formal_action_chain"] = {
                "steps": [
                    {
                        "step_id": f"play-{take_id}",
                        "input": "card_click",
                        "card_id": f"VIVHITE_CARD_TEST_{take_id}",
                        "state_before_ref": f"{take_id}.state.before",
                        "receipt_ref": f"{take_id}.action.receipt",
                        "state_after_ref": f"{take_id}.state.after",
                    }
                ]
            }
        for index in range(1, 21):
            take_id = f"T{index:02d}"
            source, capture = self._source(take_id)
            ref_files: dict[str, dict[str, object]] = {}
            action_entries: list[dict[str, object]] = []
            if take_id in action_subshots:
                subshot = action_subshots[take_id]
                entry, bound = self._formal_action(
                    take_id=take_id,
                    subshot_id=str(subshot["subshot_id"]),
                    capture=capture,
                    card_id=f"VIVHITE_CARD_TEST_{take_id}",
                    before_ref=f"{take_id}.state.before",
                    receipt_ref=f"{take_id}.action.receipt",
                    after_ref=f"{take_id}.state.after",
                )
                action_entries.append(entry)
                ref_files.update(bound)
            evidence_rows: list[dict[str, object]] = []
            for evidence in board_takes[take_id]["evidence_refs"]:
                ref_id = str(evidence["ref_id"])
                descriptor = ref_files.get(ref_id)
                if descriptor is None:
                    descriptor = self._write(
                        f"evidence/{take_id}/{str(evidence['role']).replace('.', '-')}.json",
                        {
                            "schema_version": 2,
                            "kind": "vivhite_promo_support_evidence_v2",
                            "status": "observed",
                            "ref_id": ref_id,
                        },
                    )
                evidence_rows.append(
                    {
                        "ref_id": ref_id,
                        "role": evidence["role"],
                        "status": "verified",
                        **descriptor,
                    }
                )
            spans = []
            if take_id in action_subshots:
                spans.append(
                    {
                        "subshot_id": action_subshots[take_id]["subshot_id"],
                        "in_seconds": 3,
                        "out_seconds": 55,
                    }
                )
            takes.append(
                {
                    "take_id": take_id,
                    "independent": True,
                    "source": source,
                    "evidence_refs": evidence_rows,
                    "action_evidence": action_entries,
                    "spans": spans,
                }
            )
        return {
            "schema_version": 2,
            "kind": "vivhite_promo_take_manifest_v2",
            "batch_id": "batch-v2-production-001",
            "run_id": "promo-run-v2-001",
            "source_strategy": "independent_take_files",
            "from_legacy_a4": False,
            "takes": takes,
        }

    def rewrite_manifest(self) -> None:
        self._write_json_absolute(self.manifest_path, self.manifest)


class ProductionBinderV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="vivhite-production-binder-")
        self.root = Path(self.temporary.name).resolve()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _convert_take_to_ui_action(
        fixture: ProductionFixture,
        *,
        action_kind: str,
        take_id: str = "T03",
        target_id: str | None = None,
    ) -> None:
        """Turn one synthetic mechanism take into a strict public UI action.

        The fixture's sidecar is already a fully hash-bound game-UI receipt;
        only its semantic request and declaration owner are changed.  Keeping
        all mutations in this helper lets the tests exercise reward, map,
        campfire, and shop actions through the exact same binder path.
        """

        target_id = target_id or f"VIVHITE_CARD_TEST_{take_id}"
        action_shapes: dict[str, tuple[str, str, dict[str, str], str]] = {
            "choose_reward_card": (
                "reward_card",
                "card_id",
                {"card_id": target_id},
                "target_card_id",
            ),
            "choose_map_node": (
                "map_node",
                "node_id",
                {"node_id": target_id},
                "target_node_id",
            ),
            "choose_rest_option": (
                "rest_option",
                "option",
                {"option": "rest"},
                "rest_option",
            ),
            "buy_card": (
                "shop_item",
                "item_id",
                {"item_id": target_id, "item_kind": "card"},
                "target_item_id",
            ),
        }
        target_kind, _parameter_key, parameters, entry_field = action_shapes[action_kind]

        board_take = next(row for row in fixture.board["takes"] if row["take_id"] == take_id)
        board_take.pop("formal_action_chain", None)
        board_take["asset_type"] = "ui_gameplay"
        subshot = next(
            subshot
            for shot in fixture.board["shots"]
            for subshot in shot["subshots"]
            if subshot.get("take", {}).get("take_id") == take_id
            and subshot.get("asset_type") == "mechanism_action"
        )
        subshot["asset_type"] = "ui_gameplay"
        subshot_id = str(subshot["subshot_id"])

        take = next(row for row in fixture.manifest["takes"] if row["take_id"] == take_id)
        entry = take["action_evidence"][0]
        sidecar_path = fixture.root / entry["sidecar"]["path"]
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        action_id = str(sidecar["action_id"])
        receipt_artifact = sidecar["action_receipt"]["artifact"]
        receipt_path = fixture.root / receipt_artifact["path"]
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["action_kind"] = action_kind
        receipt["payload"] = {
            "pointer": receipt["payload"]["pointer"],
            "target": {"kind": target_kind, "id": target_id if action_kind != "choose_rest_option" else "rest"},
            "request": {
                "request_id": action_id,
                "action_kind": action_kind,
                "parameters": parameters,
            },
        }
        fixture._write_json_absolute(receipt_path, receipt)
        receipt_data = receipt_path.read_bytes()
        receipt_descriptor = {
            "path": receipt_artifact["path"],
            "bytes": len(receipt_data),
            "sha256": hashlib.sha256(receipt_data).hexdigest().upper(),
            "media_type": "application/json",
            "document_kind": "vivhite_promo_action_receipt",
        }
        sidecar["action_kind"] = action_kind
        sidecar["action_receipt"]["artifact"] = receipt_descriptor
        fixture._write_json_absolute(sidecar_path, sidecar)
        sidecar_data = sidecar_path.read_bytes()
        sidecar_descriptor = {
            "path": entry["sidecar"]["path"],
            "bytes": len(sidecar_data),
            "sha256": hashlib.sha256(sidecar_data).hexdigest().upper(),
        }
        entry.update(
            {
                "step_id": action_kind.replace("_", "-"),
                "subshot_id": subshot_id,
                "action_kind": action_kind,
                "state_before_ref": f"{take_id}.state.before",
                "receipt_ref": f"{take_id}.action.receipt",
                "state_after_ref": f"{take_id}.state.after",
                entry_field: target_id if action_kind != "choose_rest_option" else "rest",
                "sidecar": sidecar_descriptor,
            }
        )
        for evidence in take["evidence_refs"]:
            if evidence["ref_id"] == f"{take_id}.action.receipt":
                evidence.update(
                    {
                        "path": receipt_descriptor["path"],
                        "bytes": receipt_descriptor["bytes"],
                        "sha256": receipt_descriptor["sha256"],
                    }
                )
                break
        fixture._write_json_absolute(fixture.storyboard_path, fixture.board)
        fixture.rewrite_manifest()

    @staticmethod
    def _convert_take_to_ui_buy_card(fixture: ProductionFixture, take_id: str = "T03") -> None:
        ProductionBinderV2Tests._convert_take_to_ui_action(
            fixture, action_kind="buy_card", take_id=take_id
        )

    def test_ui_action_branch_consumes_buy_card_without_formal_chain(self) -> None:
        fixture = ProductionFixture(self.root / "ui-buy-card")
        self._convert_take_to_ui_buy_card(fixture)
        result = binder.build_production_edl_v2(
            fixture.storyboard_path,
            fixture.manifest_path,
            artifact_root=fixture.root,
        )
        self.assertEqual(9, result["authoring"]["verified_formal_action_count"])
        self.assertEqual(1, result["authoring"]["verified_ui_action_count"])
        segment = next(
            row for row in result["segments"] if row["subshot_id"] == "SS03-action"
        )
        self.assertFalse(segment["formal_action_claimed"])
        self.assertTrue(segment["ui_action_claimed"])
        self.assertEqual("buy_card", segment["action_bindings"][0]["action_kind"])
        self.assertTrue(segment["action_bindings"][0]["ui_action"])
        self.assertFalse(segment["action_bindings"][0]["formal_action"])

    def test_ui_action_branch_consumes_reward_map_and_rest_actions(self) -> None:
        """Public UI actions are independently bound, never formal card steps."""

        cases = (
            (
                "choose_reward_card",
                "VIVHITE_CARD_AXIOM_RING",
                "target_card_id",
                "reward-card",
            ),
            ("choose_map_node", "act1-row3-node2", "target_node_id", "map-node"),
            ("choose_rest_option", "rest", "rest_option", "rest-option"),
        )
        for action_kind, target_id, entry_field, directory in cases:
            with self.subTest(action_kind=action_kind):
                fixture = ProductionFixture(self.root / directory)
                self._convert_take_to_ui_action(
                    fixture,
                    action_kind=action_kind,
                    target_id=target_id,
                )
                result = binder.build_production_edl_v2(
                    fixture.storyboard_path,
                    fixture.manifest_path,
                    artifact_root=fixture.root,
                )
                self.assertEqual(9, result["authoring"]["verified_formal_action_count"])
                self.assertEqual(1, result["authoring"]["verified_ui_action_count"])
                segment = next(
                    row for row in result["segments"] if row["subshot_id"] == "SS03-action"
                )
                binding = segment["action_bindings"][0]
                self.assertEqual(action_kind, binding["action_kind"])
                self.assertFalse(binding["formal_action"])
                self.assertTrue(binding["ui_action"])

                # The declaration must carry the action-specific target field;
                # no generic/implicit target is inferred by the binder.
                entry = next(
                    row
                    for row in fixture.manifest["takes"]
                    if row["take_id"] == "T03"
                )["action_evidence"][0]
                self.assertEqual(target_id, entry[entry_field])

    def test_ui_action_branch_rejects_wrong_target_semantics(self) -> None:
        """A valid sidecar cannot be relabelled to another UI target."""

        fixture = ProductionFixture(self.root / "ui-reward-wrong-card")
        self._convert_take_to_ui_action(
            fixture,
            action_kind="choose_reward_card",
            target_id="VIVHITE_CARD_AXIOM_RING",
        )
        entry = fixture.manifest["takes"][2]["action_evidence"][0]
        entry["target_card_id"] = "VIVHITE_CARD_CLOSED_PROJECTION"
        fixture.rewrite_manifest()
        with self.assertRaisesRegex(
            binder.ProductionBinderV2Error,
            "action target does not match the UI-action entry",
        ):
            binder.build_production_edl_v2(
                fixture.storyboard_path,
                fixture.manifest_path,
                artifact_root=fixture.root,
            )

        fixture = ProductionFixture(self.root / "ui-rest-wrong-option")
        self._convert_take_to_ui_action(
            fixture,
            action_kind="choose_rest_option",
            target_id="rest",
        )
        entry = fixture.manifest["takes"][2]["action_evidence"][0]
        entry["rest_option"] = "smith"
        fixture.rewrite_manifest()
        with self.assertRaisesRegex(binder.ProductionBinderV2Error, "must be 'rest'"):
            binder.build_production_edl_v2(
                fixture.storyboard_path,
                fixture.manifest_path,
                artifact_root=fixture.root,
            )

    def test_ui_action_branch_requires_explicit_owner_and_artifact_refs(self) -> None:
        fixture = ProductionFixture(self.root / "ui-missing-owner")
        self._convert_take_to_ui_buy_card(fixture)
        take = next(row for row in fixture.manifest["takes"] if row["take_id"] == "T03")
        entry = take["action_evidence"][0]
        entry.pop("subshot_id")
        fixture.rewrite_manifest()
        with self.assertRaisesRegex(binder.ProductionBinderV2Error, "subshot_id"):
            binder.build_production_edl_v2(
                fixture.storyboard_path,
                fixture.manifest_path,
                artifact_root=fixture.root,
            )

        fixture = ProductionFixture(self.root / "ui-wrong-artifact")
        self._convert_take_to_ui_buy_card(fixture)
        take = next(row for row in fixture.manifest["takes"] if row["take_id"] == "T03")
        entry = take["action_evidence"][0]
        entry["receipt_ref"] = "T03.state.before"
        fixture.rewrite_manifest()
        with self.assertRaisesRegex(binder.ProductionBinderV2Error, "role 'action.receipt'"):
            binder.build_production_edl_v2(
                fixture.storyboard_path,
                fixture.manifest_path,
                artifact_root=fixture.root,
            )

        fixture = ProductionFixture(self.root / "ui-strict-sidecar-dropped")
        self._convert_take_to_ui_buy_card(fixture)
        take = next(row for row in fixture.manifest["takes"] if row["take_id"] == "T03")
        entry = take["action_evidence"][0]
        take["strict_action_sidecar"] = {
            "action_id": entry["action_id"],
            "action_kind": entry["action_kind"],
            "sidecar": copy.deepcopy(entry["sidecar"]),
            "status": "passed",
        }
        take["action_evidence"] = []
        fixture.rewrite_manifest()
        with self.assertRaisesRegex(binder.ProductionBinderV2Error, "mapped into action_evidence"):
            binder.build_production_edl_v2(
                fixture.storyboard_path,
                fixture.manifest_path,
                artifact_root=fixture.root,
            )

    def test_formal_receipt_owner_is_the_mechanism_subshot(self) -> None:
        board = {
            "shots": [
                {
                    "subshots": [
                        {
                            "subshot_id": "cold-open-excerpt",
                            "asset_type": "montage",
                            "take": {"take_id": "T03"},
                            "evidence_refs": ["T03-action-receipt"],
                        },
                        {
                            "subshot_id": "mechanism-main",
                            "asset_type": "mechanism_action",
                            "take": {"take_id": "T03"},
                            "evidence_refs": ["T03-action-receipt"],
                        },
                    ]
                }
            ]
        }
        self.assertEqual(
            "mechanism-main",
            binder._step_subshot(
                board, take_id="T03", receipt_ref="T03-action-receipt"
            ),
        )

        board["shots"][0]["subshots"].pop()
        with self.assertRaisesRegex(
            binder.ProductionBinderV2Error, "mechanism_action subshot"
        ):
            binder._step_subshot(
                board, take_id="T03", receipt_ref="T03-action-receipt"
            )

    @staticmethod
    def _add_t01_montage_lineage(fixture: ProductionFixture) -> None:
        shot = fixture.board["shots"][0]
        action = shot["subshots"][1]
        action["timeline"] = {
            "start_seconds": 2,
            "end_seconds": 28,
            "duration_seconds": 26,
        }
        montage = copy.deepcopy(action)
        montage.update(
            {
                "subshot_id": "SS01-montage",
                "asset_type": "montage",
                "timeline": {
                    "start_seconds": 28,
                    "end_seconds": 54,
                    "duration_seconds": 26,
                },
                "montage_lineage": {
                    "source_subshot_id": "SS01-action",
                    "reuse_kind": "editorial_excerpt",
                    "formal_action_claimed": False,
                },
                "evidence_refs": ["T01.action.sequence", "T01.frame.end"],
            }
        )
        montage["cue"]["cue_id"] = "C01-montage"
        shot["subshots"].append(montage)
        take = next(
            row for row in fixture.manifest["takes"] if row["take_id"] == "T01"
        )
        take["spans"][0]["out_seconds"] = 29
        take["spans"].append(
            {
                "subshot_id": "SS01-montage",
                "in_seconds": 29,
                "out_seconds": 55,
            }
        )
        fixture._write_json_absolute(fixture.storyboard_path, fixture.board)
        fixture.rewrite_manifest()

    def test_montage_lineage_binds_without_claiming_or_aliasing_action_receipt(self) -> None:
        fixture = ProductionFixture(self.root / "montage-lineage")
        self._add_t01_montage_lineage(fixture)
        result = binder.build_production_edl_v2(
            fixture.storyboard_path,
            fixture.manifest_path,
            artifact_root=fixture.root,
        )
        segment = next(
            row for row in result["segments"] if row["subshot_id"] == "SS01-montage"
        )
        self.assertEqual("SS01-action", segment["montage_lineage"]["source_subshot_id"])
        self.assertFalse(segment["formal_action_claimed"])
        self.assertNotIn("action_bindings", segment)

        fixture = ProductionFixture(self.root / "montage-receipt-alias")
        self._add_t01_montage_lineage(fixture)
        take = next(
            row for row in fixture.manifest["takes"] if row["take_id"] == "T01"
        )
        evidence = {row["ref_id"]: row for row in take["evidence_refs"]}
        receipt = evidence["T01.action.receipt"]
        sequence = evidence["T01.action.sequence"]
        for field in ("path", "bytes", "sha256"):
            sequence[field] = receipt[field]
        fixture.rewrite_manifest()
        with self.assertRaisesRegex(
            binder.ProductionBinderV2Error, "exposes its source formal action receipt"
        ):
            binder.build_production_edl_v2(
                fixture.storyboard_path,
                fixture.manifest_path,
                artifact_root=fixture.root,
            )

    def test_builds_only_after_real_files_probe_and_path_loaded_actions_verify(self) -> None:
        fixture = ProductionFixture(self.root)
        subshot = fixture.board["shots"][0]["subshots"][1]
        subshot["visual_requirements"] = {"preserve_full_hud": True}
        subshot["cue"]["template_fields"] = ["runtime_hp"]
        subshot["cue"]["template_evidence"] = {
            "runtime_hp": "T01.state.after"
        }
        fixture.manifest["takes"][0]["template_values"] = [
            {
                "field": "runtime_hp",
                "evidence_ref": "T01.state.after",
                "json_pointer": "/payload/run/current_hp",
                "display_value": "70",
            }
        ]
        fixture._write_json_absolute(fixture.storyboard_path, fixture.board)
        fixture.rewrite_manifest()
        original = action_evidence.load_action_evidence
        with mock.patch.object(
            action_evidence,
            "load_action_evidence",
            wraps=original,
        ) as loader:
            result = binder.build_production_edl_v2(
                fixture.storyboard_path,
                fixture.manifest_path,
                artifact_root=self.root,
            )
        self.assertEqual("production_verified", result["authoring"]["status"])
        self.assertEqual(
            "bytes_sha256_ffprobe_verified",
            result["authoring"]["source_verification"],
        )
        self.assertEqual(10, result["authoring"]["verified_formal_action_count"])
        self.assertEqual(10, loader.call_count)
        self.assertTrue(all(isinstance(call.args[0], Path) for call in loader.call_args_list))
        actions = [row for row in result["segments"] if row["asset_type"] == "mechanism_action"]
        self.assertTrue(all(row["formal_action_claimed"] for row in actions))
        self.assertEqual(60, actions[0]["source"]["probe"]["fps"])
        self.assertEqual(
            {"preserve_full_hud": True}, actions[0]["visual_requirements"]
        )
        cue = next(row for row in result["cues"] if row["cue_id"] == "C01-action")
        self.assertEqual({"runtime_hp": "70"}, cue["template_values"])
        self.assertFalse(result["production_binding"]["staged_setup_in_edl"])
        self.assertTrue(
            all(
                "staged_setup" not in segment
                and "staged_setup" not in segment["source"]
                for segment in result["segments"]
            )
        )

    def test_rejects_changed_source_probe_identity_and_pointer_outside_hitbox(self) -> None:
        with self.subTest("changed source"):
            fixture = ProductionFixture(self.root / "changed-source")
            (fixture.root / "raw/T01.mkv").write_bytes(b"changed")
            with self.assertRaisesRegex(binder.ProductionBinderV2Error, "bytes/SHA-256"):
                binder.build_production_edl_v2(
                    fixture.storyboard_path,
                    fixture.manifest_path,
                    artifact_root=fixture.root,
                )

        with self.subTest("probe bound to another source"):
            fixture = ProductionFixture(self.root / "wrong-probe")
            take = fixture.manifest["takes"][0]
            probe_path = fixture.root / take["source"]["ffprobe"]["path"]
            probe = json.loads(probe_path.read_text(encoding="utf-8"))
            probe["source"]["sha256"] = "0" * 64
            descriptor = fixture._write(str(take["source"]["ffprobe"]["path"]), probe)
            take["source"]["ffprobe"] = descriptor
            fixture.rewrite_manifest()
            with self.assertRaisesRegex(binder.ProductionBinderV2Error, "does not bind"):
                binder.build_production_edl_v2(
                    fixture.storyboard_path,
                    fixture.manifest_path,
                    artifact_root=fixture.root,
                )

        with self.subTest("pointer outside hitbox"):
            fixture = ProductionFixture(self.root / "bad-hitbox")
            fixture.manifest["takes"][0]["action_evidence"][0]["pointer_hitbox"] = {
                "left": 0,
                "top": 0,
                "right": 100,
                "bottom": 100,
            }
            fixture.rewrite_manifest()
            with self.assertRaisesRegex(binder.ProductionBinderV2Error, "outside.*hitbox"):
                binder.build_production_edl_v2(
                    fixture.storyboard_path,
                    fixture.manifest_path,
                    artifact_root=fixture.root,
                )

    def test_matroska_container_duration_uses_aac_packet_tolerance(self) -> None:
        fixture = ProductionFixture(self.root / "matroska-duration")
        take = fixture.manifest["takes"][0]
        source = binder._verify_file(
            fixture.root,
            {
                "path": take["source"]["artifact"],
                "bytes": take["source"]["bytes"],
                "sha256": take["source"]["sha256"],
            },
            "test.source",
        )
        probe_path = fixture.root / take["source"]["ffprobe"]["path"]
        baseline = json.loads(probe_path.read_text(encoding="utf-8"))
        video = baseline["result"]["streams"][0]
        audio = baseline["result"]["streams"][1]
        frame_count = 2701
        decoded_duration = frame_count / 60
        tolerance = max(1 / 60, 1024 / 48_000) + 0.001
        video["nb_read_frames"] = str(frame_count)
        video["duration"] = "N/A"
        audio["duration"] = "N/A"

        with self.subTest("legitimate Matroska/AAC mux duration"):
            probe = copy.deepcopy(baseline)
            probe["result"]["format"]["duration"] = "45.034000"
            result = binder._validate_source_probe(
                probe,
                source=source,
                declared_duration=decoded_duration,
                context="test.probe",
            )
            self.assertEqual(frame_count, result["frame_count"])

        with self.subTest("exact AAC packet boundary"):
            probe = copy.deepcopy(baseline)
            probe["result"]["format"]["duration"] = decoded_duration + tolerance
            binder._validate_source_probe(
                probe,
                source=source,
                declared_duration=decoded_duration,
                context="test.probe",
            )

        with self.subTest("just over AAC packet boundary"):
            probe = copy.deepcopy(baseline)
            probe["result"]["format"]["duration"] = (
                decoded_duration + tolerance + 0.000001
            )
            with self.assertRaisesRegex(
                binder.ProductionBinderV2Error,
                "format duration does not match decoded video duration",
            ):
                binder._validate_source_probe(
                    probe,
                    source=source,
                    declared_duration=decoded_duration,
                    context="test.probe",
                )

        with self.subTest("declared duration remains frame-bound"):
            probe = copy.deepcopy(baseline)
            probe["result"]["format"]["duration"] = decoded_duration
            with self.assertRaisesRegex(
                binder.ProductionBinderV2Error,
                "frame count does not match declared duration",
            ):
                binder._validate_source_probe(
                    probe,
                    source=source,
                    declared_duration=decoded_duration + (1 / 60) + 0.000001,
                    context="test.probe",
                )

    def test_rejects_missing_formal_sidecar_and_process_start_identity_mismatch(self) -> None:
        fixture = ProductionFixture(self.root / "missing")
        fixture.manifest["takes"][0]["action_evidence"] = []
        fixture.rewrite_manifest()
        with self.assertRaisesRegex(binder.ProductionBinderV2Error, "every formal step"):
            binder.build_production_edl_v2(
                fixture.storyboard_path,
                fixture.manifest_path,
                artifact_root=fixture.root,
            )

        fixture = ProductionFixture(self.root / "process")
        fixture.manifest["takes"][0]["source"]["game_process"]["identity"] = "other-process"
        fixture.rewrite_manifest()
        with self.assertRaisesRegex(binder.ProductionBinderV2Error, "PID/start identity"):
            binder.build_production_edl_v2(
                fixture.storyboard_path,
                fixture.manifest_path,
                artifact_root=fixture.root,
            )

        fixture = ProductionFixture(self.root / "no-visible-delta")
        fixture.manifest["takes"][0]["action_evidence"][0][
            "visible_state_paths"
        ] = ["/run/max_hp"]
        fixture.rewrite_manifest()
        with self.assertRaisesRegex(binder.ProductionBinderV2Error, "no change"):
            binder.build_production_edl_v2(
                fixture.storyboard_path,
                fixture.manifest_path,
                artifact_root=fixture.root,
            )

    def test_t14_t15_require_actual_crown_healing_draw_energy_and_order(self) -> None:
        fixture = ProductionFixture(self.root / "crown-good")
        contract = action_evidence.load_action_evidence(
            fixture.action_sidecars["T01"], artifact_root=fixture.root
        )
        chain = {"steps": [{"step_id": "proof"}]}
        binder._validate_crown_semantics("T14", chain, {"proof": contract})

        fixture = ProductionFixture(self.root / "crown-zero", crown_heal=0)
        contract = action_evidence.load_action_evidence(
            fixture.action_sidecars["T01"], artifact_root=fixture.root
        )
        with self.assertRaisesRegex(
            binder.ProductionBinderV2Error, "solitary_crown_actual_healing"
        ):
            binder._validate_crown_semantics("T15", chain, {"proof": contract})

    def test_t16_chain_and_source_spans_must_be_continuous(self) -> None:
        def state(frame: int, seq: int, payload: object) -> SimpleNamespace:
            return SimpleNamespace(
                frame=frame,
                monotonic_seconds=frame / 60,
                observation_seq=seq,
                state_version=13,
                payload=payload,
            )

        phase0 = {"phase": 0}
        phase1 = {"phase": 1}
        contracts = {
            "ritual": SimpleNamespace(
                state_before=state(100, 1, {"phase": -1}),
                state_after=state(120, 2, phase0),
            ),
            "end-turn": SimpleNamespace(
                state_before=state(120, 2, phase0),
                state_after=state(140, 3, phase1),
            ),
            "attack": SimpleNamespace(
                state_before=state(140, 3, phase1),
                state_after=state(160, 4, {"phase": 1, "damage": 12}),
            ),
        }
        chain = {
            "steps": [
                {"step_id": "ritual", "state_after_ref": "phase0"},
                {
                    "step_id": "end-turn",
                    "state_before_ref": "phase0",
                    "state_after_ref": "phase1",
                },
                {"step_id": "attack", "state_before_ref": "attack-before"},
            ],
            "state_handoff": {
                "left_ref": "phase1",
                "right_ref": "attack-before",
                "must_be_identical_snapshot": True,
            },
        }
        binder._validate_chain_order("T16", chain, contracts)
        contracts["attack"].state_before.frame = 130
        with self.assertRaisesRegex(binder.ProductionBinderV2Error, "continuous ordered"):
            binder._validate_chain_order("T16", chain, contracts)

        board = {
            "shots": [
                {
                    "subshots": [
                        {
                            "subshot_id": "phase0",
                            "continuity_group": "T16-chain",
                            "timeline": {"start_seconds": 0},
                        },
                        {
                            "subshot_id": "phase1",
                            "continuity_group": "T16-chain",
                            "timeline": {"start_seconds": 1},
                        },
                    ]
                }
            ]
        }
        bindings = {
            "phase0": {"take_id": "T16", "in_seconds": 3, "out_seconds": 10},
            "phase1": {"take_id": "T16", "in_seconds": 10, "out_seconds": 20},
        }
        binder._validate_continuity_groups(board, bindings)
        bindings["phase1"]["in_seconds"] = 10.5
        with self.assertRaisesRegex(binder.ProductionBinderV2Error, "gap or overlap"):
            binder._validate_continuity_groups(board, bindings)

    def test_writer_creates_one_hash_bound_edl_and_never_overwrites(self) -> None:
        fixture = ProductionFixture(self.root / "writer")
        (fixture.root / "edl").mkdir()
        receipt = binder.write_production_edl_v2(
            fixture.storyboard_path,
            fixture.manifest_path,
            artifact_root=fixture.root,
            output_relative_path="edl/master-540.production.json",
        )
        output = fixture.root / str(receipt["path"])
        data = output.read_bytes()
        self.assertEqual(len(data), receipt["bytes"])
        self.assertEqual(hashlib.sha256(data).hexdigest().upper(), receipt["sha256"])
        with self.assertRaisesRegex(binder.ProductionBinderV2Error, "already exists"):
            binder.write_production_edl_v2(
                fixture.storyboard_path,
                fixture.manifest_path,
                artifact_root=fixture.root,
                output_relative_path="edl/master-540.production.json",
            )


if __name__ == "__main__":
    unittest.main()
