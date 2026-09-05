#!/usr/bin/env python3
"""Publish immutable local manifests for the reviewed editorial v2 delivery."""

from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import datetime, timezone
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[3]
RUN = ROOT / "tools/promo/runs/run-20260903T0012-director-v2-a1"
EDL = RUN / "edl"
QA = EDL / "qa"


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def record(path: pathlib.Path) -> dict[str, Any]:
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)}


def write_new(path: pathlib.Path, value: Any) -> None:
    body = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != body:
            raise FileExistsError(f"refusing to overwrite differing final record: {path}")
        return
    with path.open("xb") as stream:
        stream.write(body)


def main() -> int:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    technical_path = QA / "editorial-deliverables-v2-technical-audit.json"
    technical = json.loads(technical_path.read_text(encoding="utf-8-sig"))
    if technical.get("status") != "passed":
        raise RuntimeError("technical audit has not passed")

    v1_edl_path = EDL / "editorial-master-540-v1.json"
    v2_edl_path = EDL / "editorial-master-540-v2.json"
    v1 = json.loads(v1_edl_path.read_text(encoding="utf-8-sig"))
    v2 = json.loads(v2_edl_path.read_text(encoding="utf-8-sig"))
    if len(v1["segments"]) != len(v2["segments"]):
        raise RuntimeError("v1/v2 segment count differs")
    changed: list[dict[str, Any]] = []
    for left, right in zip(v1["segments"], v2["segments"], strict=True):
        if left["source"] != right["source"] or left.get("note") != right.get("note"):
            changed.append({
                "segment_id": right["segment_id"],
                "subshot_id": right["subshot_id"],
                "timeline": right["timeline"],
                "v1_source": left["source"],
                "v2_source": right["source"],
            })
    expected_changed = {"vd-009", "vd-010", "vd-011"}
    if {row["segment_id"] for row in changed} != expected_changed:
        raise RuntimeError(f"unexpected v1/v2 content delta: {[row['segment_id'] for row in changed]}")

    contacts = {
        "v1_opening_rejection": QA / "master-opening-contact.jpg",
        "v2_opening_pass": QA / "master-v2-opening-contact.jpg",
        "unchanged_middle": QA / "master-middle-contact.jpg",
        "unchanged_late": QA / "master-late-contact.jpg",
        "unchanged_finale": QA / "master-finale-contact.jpg",
        "hero_60": QA / "hero-60-contact.jpg",
        "cut_30": QA / "cut-30-contact.jpg",
        "cut_15": QA / "cut-15-contact.jpg",
        "v2_opening_30": QA / "v2-opening-30.png",
        "v2_opening_40": QA / "v2-opening-40.png",
        "v2_opening_52": QA / "v2-opening-52.png",
    }
    for path in contacts.values():
        if not path.is_file():
            raise FileNotFoundError(path)

    rejection_path = QA / "editorial-master-540-v1-rejection.json"
    write_new(rejection_path, {
        "schema_version": 1,
        "kind": "vivhite_promo_editorial_rejection_v1",
        "status": "rejected_preserved_do_not_deliver",
        "artifact": record(EDL / "editorial-master-540-v1-narrated-upper.mp4"),
        "reason": "sampled opening contains the base-game main menu and Ironclad during the Vivhite identity section",
        "evidence": record(contacts["v1_opening_rejection"]),
        "replacement": record(EDL / "editorial-master-540-v2-narrated-upper.mp4"),
        "preservation": "v1 remains immutable for audit and must not be presented as the current deliverable",
    })

    visual_path = QA / "editorial-deliverables-v2-visual-review.json"
    write_new(visual_path, {
        "schema_version": 1,
        "kind": "vivhite_promo_editorial_visual_review_v2",
        "status": "passed_sampled_editorial_review",
        "reviewed_at_utc": now,
        "master": record(EDL / "editorial-master-540-v2-narrated-upper.mp4"),
        "review_method": {
            "final_encoded_surfaces": True,
            "sampled_contact_sheets": True,
            "exact_changed_opening_frames": [1800, 2400, 3120],
            "full_decode": "passed_by_bound_technical_audit",
            "full_duration_human_playback": False,
        },
        "v1_to_v2_delta": {
            "changed_segments": changed,
            "all_other_segments_unchanged_in_edl": True,
            "finding": "v1 identity error removed; 00:28-00:58 now remains on the clean T20/a07 Vivhite character screen",
        },
        "observations": {
            "opening_vivhite_identity_continuous": True,
            "main_menu_or_ironclad_in_v2_opening": False,
            "placeholder_frames_observed": False,
            "upper_subtitles_avoid_primary_hud": True,
            "t15_optional_gap_replaced_by_result_and_build_recap_without_second_action_claim": True,
            "t16_crimson_phase_chain_visible": True,
            "t18_margin_drain_healing_return_chain_visible": True,
            "finale_vivhite_identity_and_end_card_visible": True,
            "short_variants_have_deliberate_end_cards": True,
            "forbidden_capture_surfaces_observed": [],
        },
        "contacts": {name: record(path) for name, path in contacts.items()},
        "technical_audit": record(technical_path),
        "boundary": {
            "editorial_visual_review": "passed",
            "strict_native_triads": "T16/T18 still missing and not claimed",
            "director_or_user_full_playback_signoff": "pending",
            "publishing_approval": False,
        },
    })

    manifest_path = QA / "editorial-delivery-v2-manifest.json"
    deliverables = {row["label"]: row["artifact"] for row in technical["deliverables"]}
    write_new(manifest_path, {
        "schema_version": 1,
        "kind": "vivhite_promo_editorial_delivery_manifest_v2",
        "status": "editorial_delivery_ready_for_user_review",
        "created_at_utc": now,
        "run_id": RUN.name,
        "master_edl": record(v2_edl_path),
        "deliverables": deliverables,
        "short_variant_edls": {
            "hero-60": record(EDL / "editorial-hero-60-v1.json"),
            "cut-30": record(EDL / "editorial-cut-30-v1.json"),
            "cut-15": record(EDL / "editorial-cut-15-v1.json"),
        },
        "audio": {"game_audio": True, "voice": "zh-CN-XiaoxiaoNeural", "bilingual_upper_subtitles": True, "bgm": False},
        "audits": {
            "technical": record(technical_path),
            "visual_sampled": record(visual_path),
            "rejected_predecessor": record(rejection_path),
            "director_or_user_full_playback": "pending",
        },
        "progress": {
            "required_takes_editorially_usable": "19/19",
            "strict_production_rows": "17/19",
            "editorial_outputs_rendered": "4/4",
            "technical_outputs_passed": "4/4",
        },
        "release_boundary": {
            "editorial_delivery_complete": True,
            "strict_binder_signoff": False,
            "human_signoff": False,
            "published": False,
        },
    })
    print(json.dumps({
        "status": "editorial_delivery_ready_for_user_review",
        "manifest": record(manifest_path),
        "visual_review": record(visual_path),
        "rejected_v1": record(rejection_path),
        "deliverables": deliverables,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
