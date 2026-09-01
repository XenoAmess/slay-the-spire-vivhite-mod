"""Evidence-driven semantic gate for the Vivhite promotional project.

The generic xAR package deliberately stops at structural claim/evidence
bindings.  This module is the project-side boundary that adds the small
amount of policy needed by the Vivhite ledger:

* every ``source_refs`` entry must be a real path inside the project root;
* every claim shot and evidence role must resolve through the verified capture
  contract; and
* a project-owned validator must provide an explicit result before a claim can
  pass.

No game API, OCR engine, xAR audit object, review response, or sign-off record
is inspected here.  In particular, an object that merely says ``approved`` or
``signoff`` is not a semantic validator result.  The caller supplies the
domain validator (or a previously recorded result map) and remains responsible
for deciding what the claim means.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Iterable, Mapping

from .capture_contract import CaptureContractError, VivhiteCaptureContract, load_capture_contract
from .claims import Claim, ClaimsError, load_claims


_PASS_RESULTS = frozenset({"pass", "passed", "ok", "valid", "verified", "true"})
_FAIL_RESULTS = frozenset({"fail", "failed", "invalid", "rejected", "false"})
_PENDING_RESULTS = frozenset({"pending", "unknown", "unverified", "not_checked"})
_DRIVE = re.compile(r"^[A-Za-z]:")


class SemanticAuditError(ValueError):
    """Raised when the project semantic gate cannot be satisfied."""


@dataclass(frozen=True, slots=True)
class ValidatorResult:
    """One explicit result emitted by a project validator.

    ``result`` is normalized to ``pass``, ``fail`` or ``pending``.  The
    callback may return a bool, a string, or a mapping with an explicit
    ``result``/``status``/``passed`` field; all forms are converted to this
    immutable record before they affect the gate.
    """

    claim_id: str
    validator_id: str
    result: str
    source: str = "callback"
    details: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.claim_id, str) or not self.claim_id.strip():
            raise SemanticAuditError("validator result claim_id must be non-empty")
        if not isinstance(self.validator_id, str) or not self.validator_id.strip():
            raise SemanticAuditError("validator result validator_id must be non-empty")
        normalized = _normalize_result(self.result, "validator result.result")
        object.__setattr__(self, "result", normalized)
        if not isinstance(self.source, str) or not self.source.strip():
            raise SemanticAuditError("validator result source must be non-empty")
        if self.details is not None and not isinstance(self.details, str):
            raise SemanticAuditError("validator result details must be text or null")

    @property
    def passed(self) -> bool:
        """Whether this explicit result is a semantic pass."""

        return self.result == "pass"

    def to_mapping(self) -> dict[str, object]:
        value: dict[str, object] = {
            "claim_id": self.claim_id,
            "validator_id": self.validator_id,
            "result": self.result,
            "source": self.source,
        }
        if self.details is not None:
            value["details"] = self.details
        return value


@dataclass(frozen=True, slots=True)
class ClaimSemanticAudit:
    """Diagnostics for one claim in a :class:`SemanticAuditReport`."""

    claim_id: str
    source_refs: tuple[str, ...]
    shot_ids: tuple[str, ...]
    evidence_roles: tuple[str, ...]
    validator_result: ValidatorResult | None
    blockers: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.blockers and self.validator_result is not None and self.validator_result.passed

    def to_mapping(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "source_refs": list(self.source_refs),
            "shot_ids": list(self.shot_ids),
            "evidence_roles": list(self.evidence_roles),
            "validator_result": None
            if self.validator_result is None
            else self.validator_result.to_mapping(),
            "blockers": list(self.blockers),
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class SemanticAuditReport:
    """Complete, deterministic result of the project-side semantic gate."""

    passed: bool
    checked_claim_ids: tuple[str, ...]
    claims: tuple[ClaimSemanticAudit, ...]
    blockers: tuple[str, ...] = ()

    @property
    def semantic_passed(self) -> bool:
        """An explicit name for callers that also hold xAR audit results."""

        return self.passed

    def raise_if_blocked(self) -> "SemanticAuditReport":
        if not self.passed:
            detail = "; ".join(self.blockers) or "semantic audit did not pass"
            raise SemanticAuditError(detail)
        return self

    # ``require`` reads naturally at a production gate and is intentionally a
    # pure alias; it does not write a sign-off row or mutate a manifest.
    require = raise_if_blocked

    def to_mapping(self) -> dict[str, object]:
        return {
            "kind": "vivhite-semantic-audit",
            "format_version": 1,
            "passed": self.passed,
            "checked_claim_ids": list(self.checked_claim_ids),
            "claims": [item.to_mapping() for item in self.claims],
            "blockers": list(self.blockers),
        }


def _normalize_result(value: Any, context: str) -> str:
    """Normalize an explicit result without accepting review/sign-off words."""

    if isinstance(value, bool):
        return "pass" if value else "fail"
    if not isinstance(value, str):
        raise SemanticAuditError(
            f"{context} must be a bool or one of pass/fail/pending"
        )
    normalized = value.strip().casefold()
    if normalized in _PASS_RESULTS:
        return "pass"
    if normalized in _FAIL_RESULTS:
        return "fail"
    if normalized in _PENDING_RESULTS:
        return "pending"
    # Deliberately do not treat ``approved`` as pass.  That word belongs to
    # human review, not to the project semantic validator contract.
    raise SemanticAuditError(
        f"{context} must be pass, fail or pending; review/signoff decisions are not validator results"
    )


def _project_root(value: str | Path) -> Path:
    try:
        root = Path(value).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, TypeError) as exc:
        raise SemanticAuditError(f"project_root cannot be resolved: {value!r}") from exc
    if not root.is_dir():
        raise SemanticAuditError(f"project_root is not a directory: {root}")
    return root


def _resolve_source_ref(root: Path, reference: Any, context: str) -> Path:
    """Resolve one source reference under ``root`` with reparse protection."""

    if not isinstance(reference, str) or not reference.strip():
        raise SemanticAuditError(f"{context} must be non-empty text")
    text = reference.strip().replace("\\", "/")
    if "\x00" in text or "\r" in text or "\n" in text:
        raise SemanticAuditError(f"{context} contains a control character")
    # Check both POSIX and Windows interpretations.  The latter matters when
    # a receipt is validated on a non-Windows CI host.
    if text.startswith("/") or text.startswith("//") or _DRIVE.match(text):
        raise SemanticAuditError(f"{context} must be a relative project path")
    windows = PureWindowsPath(text)
    if windows.drive or windows.root or windows.anchor:
        raise SemanticAuditError(f"{context} must be a relative project path")
    parts = PurePosixPath(text).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise SemanticAuditError(f"{context} must be normalized and cannot contain '..'")
    candidate = (root.joinpath(*parts)).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SemanticAuditError(f"{context} resolves outside project_root") from exc
    if not candidate.exists():
        raise SemanticAuditError(f"{context} does not exist: {text}")
    return candidate


def _claim_rows(claims: Iterable[Claim] | str | Path) -> tuple[Claim, ...]:
    if isinstance(claims, (str, Path)):
        try:
            return tuple(load_claims(claims))
        except ClaimsError as exc:
            raise SemanticAuditError(str(exc)) from exc
    try:
        rows = tuple(claims)
    except TypeError as exc:
        raise SemanticAuditError("claims must be an iterable or a JSON path") from exc
    if not rows:
        raise SemanticAuditError("claims must contain at least one claim")
    if any(not isinstance(item, Claim) for item in rows):
        raise SemanticAuditError("claims iterable must contain vivhite_promo.claims.Claim values")
    return rows


def _contract_value(
    contract: VivhiteCaptureContract | Mapping[str, Any] | str | Path,
    *,
    artifact_root: str | Path | None,
) -> VivhiteCaptureContract:
    if isinstance(contract, VivhiteCaptureContract):
        return contract
    root = None if artifact_root is None else Path(artifact_root).expanduser().resolve()
    try:
        return load_capture_contract(contract, artifact_root=root, verify_files=True)
    except (CaptureContractError, OSError, TypeError, ValueError) as exc:
        raise SemanticAuditError(f"capture contract is not valid: {exc}") from exc


def _invoke_validator(
    validator: Callable[..., Any],
    claim: Claim,
    contract: VivhiteCaptureContract,
    project_root: Path,
) -> Any:
    """Call a project validator using the documented 3/2/1 argument forms.

    Signature binding is done before invocation so a ``TypeError`` raised by
    validator *logic* is never mistaken for an arity mismatch and retried.
    """

    if not callable(validator):
        raise SemanticAuditError("validator must be callable")
    try:
        signature = inspect.signature(validator)
    except (TypeError, ValueError):
        # Some extension/builtin callables have no inspectable signature.  The
        # documented form is the safest fallback for those objects.
        return validator(claim, contract, project_root)
    candidates = (
        (claim, contract, project_root),
        (claim, contract),
        (claim,),
    )
    for args in candidates:
        try:
            signature.bind(*args)
        except TypeError:
            continue
        return validator(*args)
    raise SemanticAuditError(
        "validator must accept (claim, contract, project_root), (claim, contract), or (claim)"
    )


def _coerce_validator_result(value: Any, claim: Claim, *, source: str) -> ValidatorResult:
    """Convert one callback/result-map value into a typed explicit result."""

    if isinstance(value, ValidatorResult):
        result = value
        if result.claim_id != claim.claim_id:
            raise SemanticAuditError(
                f"validator result claim_id {result.claim_id!r} does not match {claim.claim_id!r}"
            )
        if result.validator_id != claim.validator_id:
            raise SemanticAuditError(
                f"validator result for {claim.claim_id!r} uses {result.validator_id!r}; expected {claim.validator_id!r}"
            )
        return result
    if isinstance(value, Mapping):
        # A review response/audit object can contain ``decision`` or
        # ``signoff`` but no semantic ``result``.  Do not infer pass from it.
        if any(
            key in value
            for key in ("decision", "review", "signoff", "signoff_recorded", "is_signoff")
        ):
            raise SemanticAuditError(
                f"validator result for {claim.claim_id!r} must be a project semantic result; "
                "review/signoff fields are not accepted"
            )
        if "result" in value:
            raw_result = value["result"]
        elif "status" in value:
            raw_result = value["status"]
        elif "passed" in value and isinstance(value["passed"], bool):
            raw_result = value["passed"]
        elif "ok" in value and isinstance(value["ok"], bool):
            raw_result = value["ok"]
        else:
            raise SemanticAuditError(
                f"validator result for {claim.claim_id!r} lacks an explicit result/status/passed field"
            )
        observed_claim = value.get("claim_id", value.get("id", claim.claim_id))
        if observed_claim != claim.claim_id:
            raise SemanticAuditError(
                f"validator result claim_id {observed_claim!r} does not match {claim.claim_id!r}"
            )
        observed_validator = value.get("validator_id", claim.validator_id)
        if observed_validator != claim.validator_id:
            raise SemanticAuditError(
                f"validator result for {claim.claim_id!r} uses {observed_validator!r}; expected {claim.validator_id!r}"
            )
        details = value.get("details", value.get("message"))
        if details is not None and not isinstance(details, str):
            details = str(details)
        return ValidatorResult(
            claim.claim_id,
            claim.validator_id,
            _normalize_result(raw_result, f"validator result for {claim.claim_id!r}"),
            source=source,
            details=details,
        )
    if isinstance(value, (bool, str)):
        return ValidatorResult(
            claim.claim_id,
            claim.validator_id,
            _normalize_result(value, f"validator result for {claim.claim_id!r}"),
            source=source,
        )
    raise SemanticAuditError(
        f"validator result for {claim.claim_id!r} must be a bool, string, mapping or ValidatorResult"
    )


def _claim_structure_blockers(
    claim: Claim,
    contract: VivhiteCaptureContract,
    *,
    root: Path,
) -> list[str]:
    blockers: list[str] = []
    if not claim.source_refs:
        blockers.append(f"claim {claim.claim_id!r} has no source_refs")
    for index, reference in enumerate(claim.source_refs):
        try:
            _resolve_source_ref(root, reference, f"claim {claim.claim_id!r}.source_refs[{index}]")
        except SemanticAuditError as exc:
            blockers.append(str(exc))
    available_shots = set(contract.shot_bindings)
    for shot_id in claim.shot_ids:
        if shot_id not in available_shots:
            blockers.append(f"claim {claim.claim_id!r} references missing shot {shot_id!r}")
            continue
        try:
            span = contract.span_for_shot(shot_id)
        except (CaptureContractError, KeyError, ValueError) as exc:
            blockers.append(f"claim {claim.claim_id!r} shot {shot_id!r} is not closed: {exc}")
            continue
        evidence = tuple(getattr(span, "evidence", ()))
        roles = {getattr(item, "role", None) for item in evidence}
        missing = sorted(set(claim.evidence_roles) - roles)
        if missing:
            blockers.append(
                f"claim {claim.claim_id!r} shot {shot_id!r} lacks evidence roles: "
                + ", ".join(missing)
            )
        # The capture parser normally verifies these files.  Re-check the
        # references here so a manually constructed contract cannot silently
        # make a semantic claim look closed.
        for item in evidence:
            artifact = getattr(item, "artifact", None)
            path = getattr(artifact, "path", None)
            if path is None:
                blockers.append(
                    f"claim {claim.claim_id!r} shot {shot_id!r} has malformed evidence artifact"
                )
                continue
            try:
                resolved = Path(path).expanduser().resolve(strict=True)
                resolved.relative_to(contract.artifact_root)
            except (OSError, RuntimeError, ValueError) as exc:
                blockers.append(
                    f"claim {claim.claim_id!r} shot {shot_id!r} evidence artifact is not closed: {exc}"
                )
    return blockers


def audit_claims(
    claims: Iterable[Claim] | str | Path,
    contract: VivhiteCaptureContract | Mapping[str, Any] | str | Path,
    *,
    project_root: str | Path,
    artifact_root: str | Path | None = None,
    validator: Callable[..., Any] | None = None,
    validator_results: Mapping[str, Any] | None = None,
    required_shot_ids: Iterable[str] = (),
    allow_declared_verified: bool = False,
) -> SemanticAuditReport:
    """Run the project semantic gate without mutating any project state.

    ``validator`` is the preferred input.  It is called once per claim and
    must return an explicit bool/string/mapping result.  A precomputed
    ``validator_results`` mapping is useful when a project stores validator
    output in a sidecar.  Supplying both is rejected to avoid ambiguous
    provenance.

    The checked-in ledger's ``status`` is intentionally *not* considered an
    execution result by default: ``pending`` and ``verified`` are planning
    metadata until a project validator (or result sidecar) explicitly emits a
    result.  ``allow_declared_verified`` exists only for offline migration of
    an already independently validated ledger; it is opt-in and still does
    not inspect xAR audit/review/sign-off state.
    """

    if validator is not None and validator_results is not None:
        raise SemanticAuditError("provide validator or validator_results, not both")
    root = _project_root(project_root)
    rows = _claim_rows(claims)
    capture = _contract_value(
        contract,
        artifact_root=(project_root if artifact_root is None else artifact_root),
    )
    blockers: list[str] = []
    claim_ids = [item.claim_id for item in rows]
    duplicate_claim_ids = sorted(
        {claim_id for claim_id in claim_ids if claim_ids.count(claim_id) > 1}
    )
    if duplicate_claim_ids:
        blockers.append(
            "claims contain duplicate IDs: " + ", ".join(duplicate_claim_ids)
        )
    try:
        capture.verify_unchanged()
    except Exception as exc:  # contract implementations expose domain errors
        blockers.append(f"capture evidence is stale or unavailable: {exc}")
    expected = {str(item) for item in required_shot_ids}
    missing_expected = sorted(expected - set(capture.shot_bindings))
    if missing_expected:
        blockers.append("capture is missing required shots: " + ", ".join(missing_expected))
    if validator_results is not None:
        unknown = sorted(set(validator_results) - {item.claim_id for item in rows})
        if unknown:
            blockers.append("validator_results contain unknown claims: " + ", ".join(unknown))

    audits: list[ClaimSemanticAudit] = []
    for claim in rows:
        row_blockers = _claim_structure_blockers(claim, capture, root=root)
        result: ValidatorResult | None = None
        try:
            if validator is not None:
                result = _coerce_validator_result(
                    _invoke_validator(validator, claim, capture, root),
                    claim,
                    source="callback",
                )
            elif validator_results is not None:
                if claim.claim_id not in validator_results:
                    raise SemanticAuditError(
                        f"claim {claim.claim_id!r} has no explicit validator result"
                    )
                result = _coerce_validator_result(
                    validator_results[claim.claim_id], claim, source="result-sidecar"
                )
            elif allow_declared_verified and claim.status == "verified":
                # Explicitly labelled as a migration escape hatch in the
                # report; this is never the default production path.
                result = ValidatorResult(
                    claim.claim_id,
                    claim.validator_id,
                    "pass",
                    source="declared-ledger-status",
                    details="accepted only because allow_declared_verified=True",
                )
            else:
                raise SemanticAuditError(
                    f"claim {claim.claim_id!r} has no explicit validator result"
                )
        except SemanticAuditError as exc:
            row_blockers.append(str(exc))
        if result is not None:
            if result.result != "pass":
                row_blockers.append(
                    f"claim {claim.claim_id!r} validator result is {result.result!r}"
                )
            # A rejected/pending ledger row cannot be silently resurrected by
            # a callback result; the project must update the claim deliberately.
            if claim.status == "rejected" and result.passed:
                row_blockers.append(
                    f"claim {claim.claim_id!r} is marked rejected but validator returned pass"
                )
        audits.append(
            ClaimSemanticAudit(
                claim_id=claim.claim_id,
                source_refs=tuple(claim.source_refs),
                shot_ids=tuple(claim.shot_ids),
                evidence_roles=tuple(claim.evidence_roles),
                validator_result=result,
                blockers=tuple(dict.fromkeys(row_blockers)),
            )
        )
        blockers.extend(f"{claim.claim_id}: {item}" for item in row_blockers)
    checked = tuple(item.claim_id for item in rows)
    return SemanticAuditReport(
        passed=not blockers and all(item.passed for item in audits),
        checked_claim_ids=checked,
        claims=tuple(audits),
        blockers=tuple(dict.fromkeys(blockers)),
    )


def enforce_semantic_gate(*args: Any, **kwargs: Any) -> SemanticAuditReport:
    """Run :func:`audit_claims` and raise unless every claim is proven."""

    return audit_claims(*args, **kwargs).raise_if_blocked()


# Friendly aliases for callers that use the noun/verb ordering differently.
validate_semantic_gate = audit_claims
run_semantic_audit = audit_claims
semantic_audit = audit_claims


__all__ = [
    "SemanticAuditError",
    "ValidatorResult",
    "ClaimSemanticAudit",
    "SemanticAuditReport",
    "audit_claims",
    "enforce_semantic_gate",
    "validate_semantic_gate",
    "run_semantic_audit",
    "semantic_audit",
]
