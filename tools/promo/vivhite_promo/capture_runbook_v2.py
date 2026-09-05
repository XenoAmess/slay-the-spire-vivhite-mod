"""Offline loader and source-bound validator for the Vivhite v2 capture runbook.

The runbook is an operator checklist, not proof that a take was recorded.  This
module therefore reads only repository files, never starts the game/OBS and
never creates capture receipts.  In particular, T06 is rebound against the
current C# registration and localization sources every time the runbook is
validated so an obsolete reward-card ID cannot slip into production.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


KIND = "vivhite_capture_runbook_v2"
STORYBOARD_KIND = "vivhite_promo_storyboard_v2"
EXPECTED_TAKE_IDS = tuple(f"T{number:02d}" for number in range(1, 21))
CONDITIONAL_TAKE_ID = "T15"
T06_CARD_ID = "VIVHITE_CARD_TANGENT_STARLIGHT"
REWARD_RARITIES = frozenset({"Common", "Uncommon", "Rare"})

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUNBOOK_PATH = REPO_ROOT / "tools" / "promo" / "v2" / "capture-runbook.json"
DEFAULT_STORYBOARD_PATH = REPO_ROOT / "tools" / "promo" / "v2" / "storyboard.json"
DEFAULT_CARD_SOURCE_ROOT = (
    REPO_ROOT / "Vivhite" / "VivhiteCode" / "Cards" / "Conservation"
)
DEFAULT_LOCALIZATION_PATH = (
    REPO_ROOT / "Vivhite" / "Vivhite" / "localization" / "zhs" / "cards.json"
)


class CaptureRunbookV2Error(ValueError):
    """Raised when the checked-in operator plan is internally inconsistent."""


@dataclass(frozen=True, slots=True)
class RegisteredRewardCard:
    """One source-proven Vivhite reward card."""

    card_id: str
    class_name: str
    base_class: str
    rarity: str
    source_path: Path
    localization_key: str
    localized_title: str


_REGISTERED_CARD = re.compile(
    r"\[RegisterCard\(typeof\(VivhiteCardPool\)\)\]\s*"
    r"public\s+sealed\s+class\s+(?P<class_name>[A-Za-z][A-Za-z0-9_]*)\s*"
    r":\s*(?P<base_class>[A-Za-z][A-Za-z0-9_]*)"
    r"(?P<body>.*?)(?=\n\[RegisterCard\(typeof\(VivhiteCardPool\)\)\]|\Z)",
    re.DOTALL,
)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CaptureRunbookV2Error(f"cannot read JSON {path}: {error}") from error


def _pascal_to_upper_snake(value: str) -> str:
    with_acronym_breaks = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", value)
    with_word_breaks = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", with_acronym_breaks)
    return with_word_breaks.upper()


def discover_registered_conservation_reward_cards(
    source_root: Path = DEFAULT_CARD_SOURCE_ROOT,
    localization_path: Path = DEFAULT_LOCALIZATION_PATH,
) -> tuple[RegisteredRewardCard, ...]:
    """Parse registered, reward-eligible Conservation cards from current sources."""

    source_root = Path(source_root)
    localization_path = Path(localization_path)
    localization = _load_json(localization_path)
    if not isinstance(localization, Mapping):
        raise CaptureRunbookV2Error("card localization must be a JSON object")

    cards: list[RegisteredRewardCard] = []
    for source_path in sorted(source_root.glob("*.cs")):
        try:
            source = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise CaptureRunbookV2Error(
                f"cannot read card source {source_path}: {error}"
            ) from error
        if "namespace Vivhite.Cards.Conservation;" not in source:
            continue
        for match in _REGISTERED_CARD.finditer(source):
            class_name = match.group("class_name")
            body = match.group("body")
            constructor = re.search(
                rf"public\s+{re.escape(class_name)}\s*\(\s*\)\s*"
                r":\s*base\((?P<arguments>[^)]*)\)",
                body,
                re.DOTALL,
            )
            if constructor is None:
                continue
            rarity_match = re.search(
                r"CardRarity\.(?P<rarity>Basic|Common|Uncommon|Rare|Special)",
                constructor.group("arguments"),
            )
            if rarity_match is None:
                continue
            rarity = rarity_match.group("rarity")
            if rarity not in REWARD_RARITIES:
                continue

            card_id = f"VIVHITE_CARD_{_pascal_to_upper_snake(class_name)}"
            localization_key = f"{card_id}.title"
            localized_title = localization.get(localization_key)
            if not isinstance(localized_title, str) or not localized_title.strip():
                raise CaptureRunbookV2Error(
                    f"registered reward card {card_id} lacks {localization_key}"
                )
            cards.append(
                RegisteredRewardCard(
                    card_id=card_id,
                    class_name=class_name,
                    base_class=match.group("base_class"),
                    rarity=rarity,
                    source_path=source_path,
                    localization_key=localization_key,
                    localized_title=localized_title,
                )
            )
    if not cards:
        raise CaptureRunbookV2Error(
            f"no registered Conservation reward cards found under {source_root}"
        )
    return tuple(sorted(cards, key=lambda card: card.card_id))


def resolve_t06_reward_card(
    source_root: Path = DEFAULT_CARD_SOURCE_ROOT,
    localization_path: Path = DEFAULT_LOCALIZATION_PATH,
) -> RegisteredRewardCard:
    """Resolve the director-approved T06 card from the current implementation."""

    cards = discover_registered_conservation_reward_cards(
        source_root=source_root,
        localization_path=localization_path,
    )
    matches = [card for card in cards if card.card_id == T06_CARD_ID]
    if len(matches) != 1:
        raise CaptureRunbookV2Error(
            f"T06 requires exactly one current {T06_CARD_ID}; found {len(matches)}"
        )
    card = matches[0]
    if card.base_class != "ConservationCard":
        raise CaptureRunbookV2Error(
            f"T06 card must inherit ConservationCard, got {card.base_class}"
        )
    return card


def load_capture_runbook(
    path: Path = DEFAULT_RUNBOOK_PATH,
    *,
    storyboard_path: Path = DEFAULT_STORYBOARD_PATH,
    source_root: Path = DEFAULT_CARD_SOURCE_ROOT,
    localization_path: Path = DEFAULT_LOCALIZATION_PATH,
) -> Mapping[str, Any]:
    """Load and validate the checked-in runbook without performing media work."""

    runbook = _load_json(Path(path))
    storyboard = _load_json(Path(storyboard_path))
    if not isinstance(runbook, Mapping):
        raise CaptureRunbookV2Error("capture runbook must be a JSON object")
    if not isinstance(storyboard, Mapping):
        raise CaptureRunbookV2Error("storyboard must be a JSON object")
    validate_capture_runbook(
        runbook,
        storyboard,
        source_root=source_root,
        localization_path=localization_path,
    )
    return runbook


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CaptureRunbookV2Error(message)


def _trimmed_strings(value: object, label: str) -> tuple[str, ...]:
    _require(isinstance(value, list) and bool(value), f"{label} must be a non-empty list")
    result: list[str] = []
    for index, item in enumerate(value):
        _require(
            isinstance(item, str) and item.strip() == item and bool(item),
            f"{label}[{index}] must be a non-empty trimmed string",
        )
        result.append(item)
    return tuple(result)


def validate_capture_runbook(
    runbook: Mapping[str, Any],
    storyboard: Mapping[str, Any],
    *,
    source_root: Path = DEFAULT_CARD_SOURCE_ROOT,
    localization_path: Path = DEFAULT_LOCALIZATION_PATH,
) -> None:
    """Validate operational coverage and the four high-risk action chains."""

    _require(runbook.get("schema_version") == 2, "runbook schema_version must be 2")
    _require(runbook.get("kind") == KIND, f"runbook kind must be {KIND}")
    _require(
        storyboard.get("kind") == STORYBOARD_KIND,
        f"storyboard kind must be {STORYBOARD_KIND}",
    )
    round_scope = storyboard.get("round_scope")
    _require(isinstance(round_scope, Mapping), "storyboard round_scope must be an object")
    _require(
        round_scope.get("mode") == "production_authorized",
        "storyboard round_scope must reflect the user's production authorization",
    )
    for capability in (
        "game_launch_allowed",
        "obs_allowed",
        "capture_allowed",
        "render_allowed",
    ):
        _require(
            round_scope.get(capability) is True,
            f"storyboard round_scope must enable {capability}",
        )
    binding = runbook.get("storyboard_binding")
    _require(isinstance(binding, Mapping), "storyboard_binding must be an object")
    _require(
        binding.get("revision_id") == storyboard.get("revision_id"),
        "runbook/storyboard revision_id mismatch",
    )

    authorization = runbook.get("authorization")
    _require(isinstance(authorization, Mapping), "authorization must be an object")
    _require(
        authorization.get("media_operations_authorized") is True,
        "runbook must reflect the explicit media gate lift",
    )
    _require(
        set(authorization.get("scope", []))
        == {"game_launch", "obs", "capture", "render"},
        "authorization scope must cover game_launch/obs/capture/render",
    )

    contract = runbook.get("recording_contract")
    _require(isinstance(contract, Mapping), "recording_contract must be an object")
    _require(contract.get("width") == 1920, "capture width must be 1920")
    _require(contract.get("height") == 1080, "capture height must be 1080")
    _require(contract.get("fps") == 60, "capture fps must be 60")
    _require(contract.get("playback_speed") == 1, "formal playback must be 1x")
    _require(
        contract.get("one_independent_source_per_take") is True,
        "every take needs its own source file",
    )
    _require(contract.get("setup_phase") == "before_recording_mark_only", "setup phase must end before mark")
    _require(contract.get("pre_roll_seconds") == 2, "clean pre-roll must be 2 seconds")
    _require(
        contract.get("post_result_seconds") == {"minimum": 3, "maximum": 4},
        "result hold must be 3-4 seconds",
    )
    _require(
        contract.get("formal_action_to_settlement_uncut") is True,
        "formal actions must remain uncut through settlement",
    )
    forbidden = set(
        _trimmed_strings(
            contract.get("forbidden_after_recording_mark"),
            "recording_contract.forbidden_after_recording_mark",
        )
    )
    _require(
        {"console", "system_cursor", "OBS", "Brain/AI panel", "ASCEND-VISION"}
        <= forbidden,
        "post-mark forbidden list is incomplete",
    )

    storyboard_takes = storyboard.get("takes")
    _require(isinstance(storyboard_takes, list), "storyboard takes must be a list")
    storyboard_by_id = {
        take.get("take_id"): take
        for take in storyboard_takes
        if isinstance(take, Mapping)
    }
    _require(
        tuple(sorted(storyboard_by_id)) == EXPECTED_TAKE_IDS,
        "storyboard must contain exactly T01-T20",
    )

    takes = runbook.get("takes")
    _require(isinstance(takes, list), "runbook takes must be a list")
    runbook_by_id: dict[str, Mapping[str, Any]] = {}
    for take in takes:
        _require(isinstance(take, Mapping), "each runbook take must be an object")
        take_id = take.get("take_id")
        _require(take_id in EXPECTED_TAKE_IDS, f"unknown take_id {take_id!r}")
        _require(take_id not in runbook_by_id, f"duplicate take {take_id}")
        runbook_by_id[take_id] = take
    _require(
        tuple(sorted(runbook_by_id)) == EXPECTED_TAKE_IDS,
        "runbook must contain exactly T01-T20",
    )

    batch_take_ids: list[str] = []
    batches = runbook.get("batches")
    _require(isinstance(batches, list) and batches, "batches must be a non-empty list")
    batch_ids: set[str] = set()
    for batch in batches:
        _require(isinstance(batch, Mapping), "each batch must be an object")
        batch_id = batch.get("batch_id")
        _require(isinstance(batch_id, str) and batch_id, "batch_id must be non-empty")
        _require(batch_id not in batch_ids, f"duplicate batch {batch_id}")
        batch_ids.add(batch_id)
        ids = _trimmed_strings(batch.get("take_ids"), f"{batch_id}.take_ids")
        batch_take_ids.extend(ids)
    _require(
        sorted(batch_take_ids) == list(EXPECTED_TAKE_IDS),
        "batches must cover each take exactly once",
    )

    formal_input_kinds = {
        "game_ui_click",
        "game_ui_hover",
        "game_ui_scroll",
        "game_ui_wait",
    }
    for take_id, take in runbook_by_id.items():
        storyboard_take = storyboard_by_id[take_id]
        _require(
            take.get("requirement") == storyboard_take.get("requirement"),
            f"{take_id} requirement differs from storyboard",
        )
        _require(take.get("batch_id") in batch_ids, f"{take_id} has unknown batch_id")
        _trimmed_strings(take.get("setup_before_mark"), f"{take_id}.setup_before_mark")
        _trimmed_strings(take.get("clean_frame_gate"), f"{take_id}.clean_frame_gate")
        _trimmed_strings(take.get("accept_if"), f"{take_id}.accept_if")
        _trimmed_strings(take.get("reject_if"), f"{take_id}.reject_if")
        _require(take.get("pre_roll_seconds") == 2, f"{take_id} pre-roll must be 2 seconds")
        _require(
            take.get("post_result_seconds") == {"minimum": 3, "maximum": 4},
            f"{take_id} post-result hold must be 3-4 seconds",
        )
        _require(
            take.get("source_file_template")
            == f"raw/takes/{take_id}/{{attempt_id}}.mkv",
            f"{take_id} source path must be an independent attempt file",
        )
        sequence = take.get("formal_sequence")
        _require(isinstance(sequence, list) and sequence, f"{take_id} formal sequence is empty")
        for operation in sequence:
            _require(isinstance(operation, Mapping), f"{take_id} operation must be an object")
            _require(
                operation.get("input") in formal_input_kinds,
                f"{take_id} formal sequence contains a non-game input",
            )
            _require(
                operation.get("continuous") is True,
                f"{take_id} formal operations must be continuous",
            )

    _require(
        runbook_by_id[CONDITIONAL_TAKE_ID].get("activation_condition")
        == storyboard_by_id[CONDITIONAL_TAKE_ID].get("activation_condition"),
        "T15 activation condition must match storyboard",
    )

    source_card = resolve_t06_reward_card(source_root, localization_path)
    t06_binding = runbook.get("t06_source_binding")
    _require(isinstance(t06_binding, Mapping), "t06_source_binding must be an object")
    _require(t06_binding.get("status") == "bound", "T06 card binding must be bound")
    for field, expected in (
        ("card_id", source_card.card_id),
        ("class_name", source_card.class_name),
        ("base_class", source_card.base_class),
        ("rarity", source_card.rarity),
        ("localization_key", source_card.localization_key),
        ("localized_title", source_card.localized_title),
    ):
        _require(t06_binding.get(field) == expected, f"T06 source binding mismatch: {field}")
    _require(
        source_card.card_id not in {"VIVHITE_CARD_AXIOM_RING", "VIVHITE_CARD_CLOSED_PROJECTION"},
        "T06 must not repeat either T05 card",
    )
    t06_actions = [operation.get("target") for operation in runbook_by_id["T06"]["formal_sequence"]]
    _require(source_card.card_id in t06_actions, "T06 sequence does not play its bound card")

    for take_id in ("T14", "T15"):
        take = runbook_by_id[take_id]
        assertions = set(take.get("critical_assertions", []))
        _require("starter_relic_is_solitary_crown" in assertions, f"{take_id} must verify Solitary Crown")
        _require("actual_crown_healing_greater_than_zero" in assertions, f"{take_id} must require real Crown healing")
        _require("actual_drain_healing_greater_than_zero" in assertions, f"{take_id} must require real Drain healing")
        _require("actual_draw_delta_greater_than_zero" in assertions, f"{take_id} must require a real draw delta")
        _require("actual_energy_gain_greater_than_zero" in assertions, f"{take_id} must require a real energy gain")

    t16 = runbook_by_id["T16"]
    _require(t16.get("single_continuous_source") is True, "T16 must use one continuous source")
    _require(t16.get("setup_between_formal_actions_allowed") is False, "T16 cannot inject setup mid-chain")
    _require(
        [operation.get("target") for operation in t16["formal_sequence"]]
        == [
            "VIVHITE_CARD_VIVHITES_CRIMSON_TRANSFORMATION_RITUAL",
            "end_turn_button",
            "VIVHITE_CARD_LUMINOUS_PROJECTION",
        ],
        "T16 must continuously record ritual -> end turn -> phase-1 attack",
    )

    t18 = runbook_by_id["T18"]
    _require(t18.get("single_continuous_source") is True, "T18 must use one continuous source")
    _require(
        [operation.get("target") for operation in t18["formal_sequence"]]
        == ["VIVHITE_CARD_CLOSED_DOMAIN_MAPPING", "VIVHITE_CARD_TRICHROMATIC_WALTZ"],
        "T18 must record the complete Cough-to-Drain chain",
    )
    _require(
        t18.get("critical_assertions")
        == [
            "margin_decreases_after_cough",
            "drain_percent_increases_after_margin_offset",
            "drain_attack_actual_damage_greater_than_zero",
            "actual_healing_at_least_runtime_divisor",
            "final_margin_greater_than_post_cough_margin",
        ],
        "T18 critical assertion order must match the visible chain",
    )


def format_take_checklist(runbook: Mapping[str, Any], take_id: str) -> str:
    """Render a compact operator checklist for one take."""

    takes = runbook.get("takes", [])
    take = next(
        (item for item in takes if isinstance(item, Mapping) and item.get("take_id") == take_id),
        None,
    )
    if take is None:
        raise CaptureRunbookV2Error(f"unknown take {take_id}")

    lines = [f"{take_id} — {take['name']}", f"输出：{take['source_file_template']}", "录制标记前："]
    lines.extend(f"  - {item}" for item in take["setup_before_mark"])
    lines.append("干净画面门：")
    lines.extend(f"  - {item}" for item in take["clean_frame_gate"])
    lines.append("正式动作（同一原始文件、1×、不中断）：")
    for operation in take["formal_sequence"]:
        lines.append(f"  - {operation['instruction']}")
    lines.append("通过条件：")
    lines.extend(f"  - {item}" for item in take["accept_if"])
    lines.append("作废条件：")
    lines.extend(f"  - {item}" for item in take["reject_if"])
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runbook", type=Path, default=DEFAULT_RUNBOOK_PATH)
    parser.add_argument("--storyboard", type=Path, default=DEFAULT_STORYBOARD_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate", help="validate the runbook and current T06 source")
    show = subparsers.add_parser("show", help="print one operator take checklist")
    show.add_argument("take_id", choices=EXPECTED_TAKE_IDS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    runbook = load_capture_runbook(args.runbook, storyboard_path=args.storyboard)
    if args.command == "show":
        print(format_take_checklist(runbook, args.take_id))
    else:
        print(
            "capture runbook v2: PASS "
            f"({len(runbook['takes'])} take slots; T15 conditional; T06={T06_CARD_ID})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CaptureRunbookV2Error",
    "DEFAULT_RUNBOOK_PATH",
    "EXPECTED_TAKE_IDS",
    "KIND",
    "RegisteredRewardCard",
    "T06_CARD_ID",
    "discover_registered_conservation_reward_cards",
    "format_take_checklist",
    "load_capture_runbook",
    "resolve_t06_reward_card",
    "validate_capture_runbook",
]
