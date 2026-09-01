"""Project-side claims ledger for the Vivhite promotional film.

The xAR core deliberately does not decide whether a marketing statement is
true.  This module performs only structural binding: every claim must identify
the shot and evidence roles that a future Vivhite semantic validator will
inspect.  A ``verified`` status in the checked-in starter ledger is a planning
placeholder, not an automatic release approval.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


CLAIMS_SCHEMA_VERSION = 1
CLAIMS_KIND = "vivhite_promo_claims"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ClaimsError(ValueError):
    """A claims ledger is malformed or cannot be structurally bound."""


def _text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ClaimsError(f"{context} must be non-empty NUL-free text")
    return value.strip()


def _id(value: Any, context: str) -> str:
    result = _text(value, context)
    if _ID.fullmatch(result) is None:
        raise ClaimsError(f"{context} must be a portable identifier")
    return result


@dataclass(frozen=True, slots=True)
class Claim:
    claim_id: str
    category: str
    text: Mapping[str, str]
    shot_ids: tuple[str, ...]
    evidence_roles: tuple[str, ...]
    validator_id: str
    status: str = "pending"
    source_refs: tuple[str, ...] = ()

    def to_mapping(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "category": self.category,
            "text": dict(self.text),
            "shot_ids": list(self.shot_ids),
            "evidence_roles": list(self.evidence_roles),
            "validator_id": self.validator_id,
            "status": self.status,
            "source_refs": list(self.source_refs),
        }


@dataclass(frozen=True, slots=True)
class ClaimValidationReport:
    passed: bool
    checked_claim_ids: tuple[str, ...]
    blockers: tuple[str, ...] = ()


def _localized(value: Any, context: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise ClaimsError(f"{context} must contain localized text")
    return {str(locale): _text(text, f"{context}.{locale}") for locale, text in value.items()}


def _string_array(value: Any, context: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ClaimsError(f"{context} must be a non-empty array")
    result: list[str] = []
    for index, item in enumerate(value):
        result.append(_id(item, f"{context}[{index}]"))
    if len(result) != len(set(result)):
        raise ClaimsError(f"{context} must not contain duplicates")
    return tuple(result)


def _reference_array(value: Any, context: str) -> tuple[str, ...]:
    """Parse source references as normalized project paths or portable IDs."""

    if not isinstance(value, list):
        raise ClaimsError(f"{context} must be an array")
    result: list[str] = []
    for index, item in enumerate(value):
        text = _text(item, f"{context}[{index}]").replace("\\", "/")
        if text.startswith("/") or ":" in text.split("/", 1)[0] or any(part in {"", ".", ".."} for part in text.split("/")):
            raise ClaimsError(f"{context}[{index}] must be a normalized relative path or ID")
        result.append(text)
    if len(result) != len(set(result)):
        raise ClaimsError(f"{context} must not contain duplicates")
    return tuple(result)


def _claim(value: Any, context: str) -> Claim:
    if not isinstance(value, Mapping):
        raise ClaimsError(f"{context} must be an object")
    claim_id = _id(value.get("claim_id", value.get("id")), f"{context}.claim_id")
    category = _id(value.get("category", "mechanic"), f"{context}.category")
    text = _localized(value.get("text"), f"{context}.text")
    shots = _string_array(value.get("shot_ids"), f"{context}.shot_ids")
    roles = _string_array(value.get("evidence_roles"), f"{context}.evidence_roles")
    validator = _id(value.get("validator_id"), f"{context}.validator_id")
    status = _text(value.get("status", "pending"), f"{context}.status")
    if status not in {"pending", "verified", "rejected"}:
        raise ClaimsError(f"{context}.status must be pending, verified or rejected")
    refs = _reference_array(value.get("source_refs", []), f"{context}.source_refs")
    return Claim(claim_id, category, text, shots, roles, validator, status, refs)


def parse_claims(payload: Mapping[str, Any]) -> tuple[Claim, ...]:
    if not isinstance(payload, Mapping):
        raise ClaimsError("claims document must be an object")
    if payload.get("schema_version") != CLAIMS_SCHEMA_VERSION or payload.get("kind") != CLAIMS_KIND:
        raise ClaimsError("claims document must declare vivhite_promo_claims schema_version 1")
    raw = payload.get("claims")
    if not isinstance(raw, list) or not raw:
        raise ClaimsError("claims must be a non-empty array")
    result = tuple(_claim(item, f"claims[{index}]") for index, item in enumerate(raw))
    ids = [item.claim_id for item in result]
    if len(ids) != len(set(ids)):
        raise ClaimsError("claims contain duplicate claim IDs")
    return result


def load_claims(path: str | Path) -> tuple[Claim, ...]:
    source = Path(path).expanduser().resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise ClaimsError(f"could not read claims ledger {source}: {exc}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ClaimsError(f"invalid claims ledger JSON {source}: {exc}") from exc
    return parse_claims(payload)


def _span_roles(contract: Any, shot_id: str) -> set[str]:
    try:
        span = contract.span_for_shot(shot_id)
    except Exception:
        return set()
    return {item.role for item in getattr(span, "evidence", ())}


def validate_claim_bindings(
    claims: Iterable[Claim],
    contract: Any,
    *,
    required_shot_ids: Iterable[str] = (),
) -> ClaimValidationReport:
    """Check claim references without judging their marketing truth."""

    rows = tuple(claims)
    blockers: list[str] = []
    expected_shots = set(required_shot_ids)
    available_shots = set(getattr(contract, "shot_bindings", {}))
    if expected_shots - available_shots:
        blockers.append("capture is missing shots: " + ", ".join(sorted(expected_shots - available_shots)))
    checked: list[str] = []
    for claim in rows:
        checked.append(claim.claim_id)
        missing_shots = set(claim.shot_ids) - available_shots
        if missing_shots:
            blockers.append(
                f"claim {claim.claim_id!r} references missing shots: "
                + ", ".join(sorted(missing_shots))
            )
            continue
        for shot_id in claim.shot_ids:
            roles = _span_roles(contract, shot_id)
            missing_roles = set(claim.evidence_roles) - roles
            if missing_roles:
                blockers.append(
                    f"claim {claim.claim_id!r} shot {shot_id!r} lacks evidence roles: "
                    + ", ".join(sorted(missing_roles))
                )
    return ClaimValidationReport(not blockers, tuple(checked), tuple(blockers))


def to_xar_claim_bindings(claims: Iterable[Claim]) -> tuple[dict[str, object], ...]:
    """Produce a neutral shape for optional xAR assertion-binding APIs."""

    return tuple(
        {
            "claim_id": claim.claim_id,
            "evidence_roles": list(claim.evidence_roles),
            "validator_id": claim.validator_id,
            "status": claim.status,
        }
        for claim in claims
    )


__all__ = [
    "CLAIMS_SCHEMA_VERSION",
    "CLAIMS_KIND",
    "ClaimsError",
    "Claim",
    "ClaimValidationReport",
    "parse_claims",
    "load_claims",
    "validate_claim_bindings",
    "to_xar_claim_bindings",
]
