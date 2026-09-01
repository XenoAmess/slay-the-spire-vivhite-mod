"""Offline tests for the Vivhite project semantic gate.

These tests use the tiny checked-in capture fixture only.  No game, OBS,
FFmpeg, OCR provider, xAR process, or network service is started.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[3]
PROMO_ROOT = ROOT / "tools" / "promo"
FIXTURE_ROOT = PROMO_ROOT / "fixtures" / "minimal_capture"
CLAIMS_PATH = PROMO_ROOT / "claims" / "claims.json"

if str(PROMO_ROOT) not in sys.path:
    sys.path.insert(0, str(PROMO_ROOT))


class VivhiteSemanticAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from vivhite_promo.capture_contract import load_capture_contract
        from vivhite_promo.claims import load_claims

        cls.claims = load_claims(CLAIMS_PATH)
        cls.contract = load_capture_contract(
            FIXTURE_ROOT / "contract.json", artifact_root=FIXTURE_ROOT
        )

    def test_pending_ledger_cannot_pass_without_explicit_validator_result(self) -> None:
        from vivhite_promo.semantic_audit import audit_claims

        report = audit_claims(
            self.claims,
            self.contract,
            project_root=ROOT,
            required_shot_ids=tuple(self.contract.shot_bindings),
        )
        self.assertFalse(report.passed)
        self.assertEqual(len(report.checked_claim_ids), len(self.claims))
        self.assertTrue(
            any("no explicit validator result" in item for item in report.blockers)
        )

    def test_injected_validator_closes_structural_and_semantic_gate(self) -> None:
        from vivhite_promo.semantic_audit import audit_claims

        calls: list[str] = []

        def validator(claim, contract):
            calls.append(claim.claim_id)
            self.assertIs(contract, self.contract)
            return {"claim_id": claim.claim_id, "validator_id": claim.validator_id, "result": "pass"}

        report = audit_claims(
            self.claims,
            self.contract,
            project_root=ROOT,
            validator=validator,
            required_shot_ids=tuple(self.contract.shot_bindings),
        )
        self.assertTrue(report.passed, report.blockers)
        self.assertEqual(tuple(calls), report.checked_claim_ids)
        self.assertTrue(all(item.validator_result is not None for item in report.claims))

    def test_pending_or_failed_callback_result_is_red(self) -> None:
        from vivhite_promo.semantic_audit import audit_claims

        def validator(claim):
            return "pending" if claim.claim_id == self.claims[0].claim_id else "pass"

        report = audit_claims(
            self.claims,
            self.contract,
            project_root=ROOT,
            validator=validator,
        )
        self.assertFalse(report.passed)
        self.assertTrue(any("validator result is 'pending'" in item for item in report.blockers))

    def test_source_ref_escape_and_missing_path_are_rejected(self) -> None:
        from vivhite_promo.semantic_audit import audit_claims

        escaped = replace(
            self.claims[0],
            source_refs=("../outside.cs",),
        )
        report = audit_claims(
            (escaped,),
            self.contract,
            project_root=ROOT,
            validator=lambda claim: True,
        )
        self.assertFalse(report.passed)
        self.assertTrue(any("relative project path" in item or "'..'" in item for item in report.blockers))

        missing = replace(self.claims[0], source_refs=("does/not/exist.cs",))
        report = audit_claims(
            (missing,),
            self.contract,
            project_root=ROOT,
            validator=lambda claim: True,
        )
        self.assertFalse(report.passed)
        self.assertTrue(any("does not exist" in item for item in report.blockers))

    def test_shot_and_evidence_roles_must_close_over_capture(self) -> None:
        from vivhite_promo.semantic_audit import audit_claims

        missing_shot = replace(self.claims[0], shot_ids=("S99-missing",))
        report = audit_claims(
            (missing_shot,),
            self.contract,
            project_root=ROOT,
            validator=lambda claim: True,
        )
        self.assertFalse(report.passed)
        self.assertTrue(any("missing shot" in item for item in report.blockers))

        missing_role = replace(self.claims[0], evidence_roles=("state.after",))
        # S01 intentionally has no state.after role in the fixture.
        report = audit_claims(
            (missing_role,),
            self.contract,
            project_root=ROOT,
            validator=lambda claim: True,
        )
        self.assertFalse(report.passed)
        self.assertTrue(any("lacks evidence roles" in item for item in report.blockers))

    def test_review_or_signoff_decision_is_not_a_semantic_result(self) -> None:
        from vivhite_promo.semantic_audit import audit_claims

        report = audit_claims(
            (self.claims[0],),
            self.contract,
            project_root=ROOT,
            validator=lambda claim: {"decision": "approved", "signoff": True},
        )
        self.assertFalse(report.passed)
        self.assertTrue(
            any("review/signoff" in item or "explicit result" in item for item in report.blockers)
        )

    def test_result_sidecar_is_explicit_and_declared_verified_is_opt_in(self) -> None:
        from vivhite_promo.semantic_audit import audit_claims

        result_map = {
            claim.claim_id: {
                "claim_id": claim.claim_id,
                "validator_id": claim.validator_id,
                "result": "pass",
                "details": "offline fixture validator",
            }
            for claim in self.claims
        }
        report = audit_claims(
            self.claims,
            self.contract,
            project_root=ROOT,
            validator_results=result_map,
        )
        self.assertTrue(report.passed, report.blockers)
        self.assertEqual("result-sidecar", report.claims[0].validator_result.source)

        verified = tuple(replace(claim, status="verified") for claim in self.claims)
        strict = audit_claims(verified, self.contract, project_root=ROOT)
        self.assertFalse(strict.passed)
        migrated = audit_claims(
            verified,
            self.contract,
            project_root=ROOT,
            allow_declared_verified=True,
        )
        self.assertTrue(migrated.passed, migrated.blockers)
        self.assertEqual(
            "declared-ledger-status", migrated.claims[0].validator_result.source
        )

    def test_adapter_exposes_explicit_semantic_gate(self) -> None:
        from vivhite_promo.adapter import VivhiteAdapter

        adapter = VivhiteAdapter(
            project_root=ROOT,
            storyboard_path=PROMO_ROOT / "storyboard.json",
            claims_path=CLAIMS_PATH,
        )
        # ``audit_semantics`` is explicit and read-only; loading a candidate
        # remains a separate structural operation.
        candidate = adapter.load_capture(
            FIXTURE_ROOT / "contract.json", artifact_root=FIXTURE_ROOT
        )
        report = adapter.audit_semantics(candidate, validator=lambda claim: True)
        self.assertTrue(report.passed, report.blockers)
        self.assertIs(
            getattr(adapter.semantic_audit, "__func__", None),
            getattr(adapter.audit_semantics, "__func__", None),
        )


if __name__ == "__main__":
    unittest.main()
