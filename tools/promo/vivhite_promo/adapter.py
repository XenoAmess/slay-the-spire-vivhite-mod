"""Vivhite-specific adapter for the generic xAR promotional pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .capture_contract import (
    CaptureContractError,
    VivhiteCaptureContract,
    load_capture_contract,
)
from .claims import ClaimValidationReport, load_claims, validate_claim_bindings
from .preset import (
    BGM_STEM_IDS,
    CAPTURE_CONTRACT_RELATIVE_PATH,
    CLAIMS_RELATIVE_PATH,
    GAME_VERSION,
    MOD_ID,
    MOD_VERSION,
    PCK_NAME,
    RITSULIB_ID,
    RITSULIB_VERSION,
    SHOT_IDS,
    STORYBOARD_RELATIVE_PATH,
    VivhitePolicy,
    VivhitePresetError,
    load_storyboard,
)


class VivhiteAdapterError(ValueError):
    """A project-specific capture or identity contract is not consumable."""


@dataclass(frozen=True, slots=True)
class ShotBinding:
    shot_id: str
    span_id: str
    provenance: str
    begin_seconds: float
    end_seconds: float


@dataclass(frozen=True, slots=True)
class VivhiteCaptureCandidate:
    contract: VivhiteCaptureContract
    shots: tuple[ShotBinding, ...]
    claims: ClaimValidationReport | None = None

    def shot(self, shot_id: str) -> ShotBinding:
        for item in self.shots:
            if item.shot_id == shot_id:
                return item
        raise KeyError(shot_id)

    @property
    def audio_stems(self) -> tuple[Any, ...]:
        """Return optional immutable stem bindings from the capture contract."""

        return self.contract.audio_stems


def _candidate_paths(root: Path, relative: str) -> tuple[Path, ...]:
    """Return deterministic project/run candidates without scanning broadly."""

    return (
        root / relative,
        root / "promo" / relative,
        root / "runs" / "current" / Path(relative).name,
    )


class VivhiteAdapter:
    """Read-only adapter; recorder and game automation remain external."""

    adapter_id = "vivhite"

    def __init__(
        self,
        *,
        policy: VivhitePolicy | None = None,
        project_root: str | Path | None = None,
        capture_contract_path: str | Path | None = None,
        storyboard_path: str | Path | None = None,
        claims_path: str | Path | None = None,
    ) -> None:
        self.policy = policy or VivhitePolicy()
        try:
            self.policy.validate()
        except VivhitePresetError as exc:
            raise VivhiteAdapterError(f"invalid Vivhite promo policy: {exc}") from exc
        self.project_root = None if project_root is None else Path(project_root).expanduser().resolve()
        self.capture_contract_path = None if capture_contract_path is None else Path(capture_contract_path)
        self.storyboard_path = None if storyboard_path is None else Path(storyboard_path)
        self.claims_path = None if claims_path is None else Path(claims_path)

    def _root(self, root: str | Path | None = None) -> Path:
        candidate = self.project_root if root is None else Path(root)
        if candidate is None:
            raise VivhiteAdapterError("project_root is required for this adapter operation")
        return candidate.expanduser().resolve()

    def validate_identity(self, context: Mapping[str, Any]) -> None:
        expected = {
            "game_version": self.policy.game_version,
            "mod_id": self.policy.mod_id,
            "mod_version": self.policy.mod_version,
            # The capture is only useful when the game window and the
            # deployed Mod/PCK/dependency came from one known runtime set.
            # These are project-side identity fields; xAR receives them only
            # as opaque metadata after this adapter has checked them.
            "pck_name": self.policy.pck_name,
            "pck_version": self.policy.pck_version,
            "ritsu_lib_id": self.policy.ritsu_lib_id,
            "ritsu_lib_version": self.policy.ritsu_lib_version,
        }
        for key, value in expected.items():
            observed = context.get(key)
            if observed != value:
                raise VivhiteAdapterError(
                    f"project context {key} must be {value!r}, got {observed!r}"
                )
        if self.policy.require_vulkan and str(context.get("renderer", "")).casefold() != "vulkan":
            raise VivhiteAdapterError("Vivhite capture must use the Vulkan renderer")
        for key in ("overlays_absent", "loading_absent", "console_absent"):
            if context.get(key) is not True:
                raise VivhiteAdapterError(f"capture context {key} must be true")
        resolution = context.get("resolution")
        if tuple(resolution or ()) != (self.policy.width, self.policy.height):
            raise VivhiteAdapterError(
                f"capture resolution must be {self.policy.width}x{self.policy.height}"
            )
        if context.get("fps") != self.policy.fps:
            raise VivhiteAdapterError(f"capture fps must be {self.policy.fps}")

    def storyboard(self, path: str | Path | None = None) -> Mapping[str, Any]:
        selected = Path(path) if path is not None else self.storyboard_path
        if selected is None:
            selected = self._root() / STORYBOARD_RELATIVE_PATH
        return load_storyboard(selected)

    def capture_path(self, path: str | Path | None = None) -> Path:
        selected = Path(path) if path is not None else self.capture_contract_path
        if selected is not None:
            return selected.expanduser().resolve()
        root = self._root()
        candidates = _candidate_paths(root, CAPTURE_CONTRACT_RELATIVE_PATH)
        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()
        # Return the canonical path for an actionable missing-file error.
        return (root / CAPTURE_CONTRACT_RELATIVE_PATH).resolve()

    def load_capture(
        self,
        path: str | Path | None = None,
        *,
        verify_files: bool = True,
        artifact_root: str | Path | None = None,
    ) -> VivhiteCaptureCandidate:
        contract_path = self.capture_path(path)
        # A production run normally stores ``capture/contract.json`` under a
        # run root, and serializes all artifact paths relative to that run
        # root.  The tiny checked-in fixture keeps its contract at the fixture
        # root, so retain the parent-directory default there.  Callers can
        # always pass an explicit root when using a different layout.
        if artifact_root is None:
            inferred_root = contract_path.parent
            if contract_path.parent.name.casefold() == "capture":
                inferred_root = contract_path.parent.parent
            artifact_root = inferred_root
        if self.project_root is None:
            # An explicit contract path is enough to locate the companion
            # storyboard/claims in a standalone fixture or run.  Registry
            # callers that provide a project root retain their configured
            # root; this fallback merely avoids an unnecessary second setup
            # step for offline validation.
            inferred_project_root = Path(artifact_root).expanduser().resolve()
            for candidate_root in (
                inferred_project_root,
                *inferred_project_root.parents,
            ):
                if (candidate_root / STORYBOARD_RELATIVE_PATH).is_file():
                    inferred_project_root = candidate_root
                    break
            self.project_root = inferred_project_root
        try:
            contract = load_capture_contract(
                contract_path,
                artifact_root=artifact_root,
                verify_files=verify_files,
            )
        except CaptureContractError as exc:
            raise VivhiteAdapterError(str(exc)) from exc
        if not self.policy.include_bgm:
            forbidden_bgm = sorted(
                stem.stem_id
                for stem in contract.audio_stems
                if stem.stem_id.casefold() in BGM_STEM_IDS
            )
            if forbidden_bgm:
                raise VivhiteAdapterError(
                    "capture declares BGM stems while this preset has "
                    "include_bgm=false: "
                    + ", ".join(forbidden_bgm)
                )
        self.validate_identity(contract.project_context)
        storyboard = self.storyboard()
        required_shots = tuple(item["shot_id"] for item in storyboard["shots"])
        if tuple(required_shots) != SHOT_IDS:
            raise VivhiteAdapterError("storyboard shot order is not the canonical Vivhite order")
        shots: list[ShotBinding] = []
        storyboard_rows = {
            str(item["shot_id"]): item
            for item in storyboard.get("shots", [])
            if isinstance(item, Mapping) and "shot_id" in item
        }
        for shot_id in required_shots:
            try:
                span = contract.span_for_shot(shot_id)
            except CaptureContractError as exc:
                raise VivhiteAdapterError(str(exc)) from exc
            row = storyboard_rows.get(shot_id, {})
            required_roles = row.get("required_evidence_roles", [])
            if not isinstance(required_roles, list):
                raise VivhiteAdapterError(
                    f"storyboard shot {shot_id!r} has malformed required_evidence_roles"
                )
            actual_roles = {item.role for item in span.evidence}
            missing_roles = sorted(set(map(str, required_roles)) - actual_roles)
            if missing_roles:
                raise VivhiteAdapterError(
                    f"capture shot {shot_id!r} lacks required evidence roles: "
                    + ", ".join(missing_roles)
                )
            expected_provenance = row.get("provenance")
            if expected_provenance is not None and str(expected_provenance) != span.provenance:
                raise VivhiteAdapterError(
                    f"capture shot {shot_id!r} provenance does not match storyboard"
                )
            expected_span = row.get("span_id")
            if expected_span is not None and str(expected_span) != span.span_id:
                raise VivhiteAdapterError(
                    f"capture shot {shot_id!r} span binding does not match storyboard"
                )
            shots.append(
                ShotBinding(
                    shot_id=shot_id,
                    span_id=span.span_id,
                    provenance=span.provenance,
                    begin_seconds=span.begin_seconds,
                    end_seconds=span.end_seconds,
                )
            )
        claims_report: ClaimValidationReport | None = None
        claims_path = self.claims_path
        if claims_path is None:
            candidate = self._root() / CLAIMS_RELATIVE_PATH
            if candidate.is_file():
                claims_path = candidate
        if claims_path is not None and Path(claims_path).is_file():
            claims_report = validate_claim_bindings(
                load_claims(claims_path),
                contract,
                required_shot_ids=required_shots,
            )
            if not claims_report.passed:
                raise VivhiteAdapterError(
                    "capture does not satisfy structural claim bindings: "
                    + "; ".join(claims_report.blockers)
                )
        return VivhiteCaptureCandidate(contract=contract, shots=tuple(shots), claims=claims_report)

    def to_xar_receipt(self, candidate: VivhiteCaptureCandidate) -> Any:
        """Project a verified sidecar into xAR's generic CaptureReceipt.

        This method is intentionally optional: the project-side parser remains
        usable when xAR is not installed, while an installed xAR release gets
        the exact canonical producer/timebase/evidence shape it validates.
        """

        if not isinstance(candidate, VivhiteCaptureCandidate):
            raise VivhiteAdapterError("candidate must be a VivhiteCaptureCandidate")
        try:
            from xar_promo.capture import load_capture_receipt  # type: ignore
        except ModuleNotFoundError as exc:
            raise VivhiteAdapterError("xAR capture module is unavailable") from exc
        return load_capture_receipt(
            candidate.contract.to_xar_mapping(),
            project_root=candidate.contract.artifact_root,
        )

    def planned_raw_path(self, workdir: str | Path) -> Path:
        """Path used by xAR validate-only plans; no file is created."""

        root = Path(workdir).expanduser().resolve()
        return root / "capture" / "raw" / "gameplay.mp4"

    def visual_path(
        self,
        shot_id: str,
        *,
        workdir: str | Path,
        candidate: VivhiteCaptureCandidate | None,
        validate_only: bool,
    ) -> tuple[Path, float]:
        if shot_id not in SHOT_IDS:
            raise VivhiteAdapterError(f"unknown Vivhite shot {shot_id!r}")
        if candidate is None:
            if not validate_only:
                raise VivhiteAdapterError("a verified capture contract is required for build")
            return self.planned_raw_path(workdir), 0.0
        binding = candidate.shot(shot_id)
        return candidate.contract.raw_capture.path, binding.begin_seconds

    def to_visual_source(
        self,
        shot_id: str,
        *,
        workdir: str | Path,
        candidate: VivhiteCaptureCandidate | None = None,
        validate_only: bool = True,
    ) -> tuple[Any, float]:
        """Project one shot to ``(xAR VisualSource, start_seconds)``.

        The adapter does not import xAR at module import time.  This keeps
        contract validation usable in a clean project checkout while giving a
        composer a single, explicit projection point when xAR is installed.
        """

        selected = candidate
        if selected is None and not validate_only:
            raise VivhiteAdapterError("a verified capture candidate is required")
        path, start_seconds = self.visual_path(
            shot_id,
            workdir=workdir,
            candidate=selected,
            validate_only=validate_only,
        )
        try:
            from xar_promo.sources import VIDEO, VisualSource  # type: ignore
        except ModuleNotFoundError as exc:
            raise VivhiteAdapterError("xAR visual-source module is unavailable") from exc
        return (
            VisualSource(
                source_id=shot_id,
                kind=VIDEO,
                path=path,
                origin="vivhite-capture-contract-v1",
                requires_resolution=selected is None and validate_only,
                metadata={"shot_id": shot_id, "adapter_id": self.adapter_id},
            ),
            start_seconds,
        )

    # A concise alias is useful to project composers and keeps the public
    # adapter vocabulary close to xAR's ``VisualSource`` type.
    visual_source = to_visual_source

    def __call__(self, *args: Any, **kwargs: Any) -> "VivhiteAdapter":
        return self


def create_adapter(*args: Any, **kwargs: Any) -> VivhiteAdapter:
    """Entry-point factory.  Registry resolution never starts production."""

    return VivhiteAdapter()


__all__ = [
    "VivhiteAdapterError",
    "ShotBinding",
    "VivhiteCaptureCandidate",
    "VivhiteAdapter",
    "create_adapter",
]
