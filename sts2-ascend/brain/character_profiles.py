"""Character-scoped paths for learned Brain knowledge.

The historical ``knowledge/`` layout belongs to Ironclad and remains in place.
Additional characters use isolated roots below ``knowledge/profiles/``.  This
module only describes and resolves that layout; it never migrates existing data.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


IRONCLAD_PROFILE_ID = "ironclad"
VIVHITE_PROFILE_ID = "vivhite"
DEFAULT_PROFILE_ID = IRONCLAD_PROFILE_ID

IRONCLAD_CHARACTER_ID = "IRONCLAD"
VIVHITE_CHARACTER_ID = "VIVHITE_CHARACTER_VIVHITE_CHARACTER"

PROFILE_TAG = "character_profile"
CHARACTER_TAG = "character_id"

_ARTIFACT_PATHS = {
    "stats": "stats.json",
    "stats.json": "stats.json",
    "policy": "policy.json",
    "policy.json": "policy.json",
    "progression": "progression.json",
    "progression.json": "progression.json",
    "lessons": "lessons.md",
    "lessons.md": "lessons.md",
    "runs": "runs",
}


def _normalise(value: object) -> str:
    return str(value).strip().casefold()


@dataclass(frozen=True, slots=True)
class CharacterProfile:
    """One character's learned-memory root and its shared knowledge root."""

    profile_id: str
    character_id: str
    root: Path
    knowledge_root: Path
    aliases: tuple[str, ...] = ()
    legacy_root: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))
        object.__setattr__(self, "knowledge_root", Path(self.knowledge_root))

    @property
    def stats_path(self) -> Path:
        return self.root / "stats.json"

    @property
    def policy_path(self) -> Path:
        return self.root / "policy.json"

    @property
    def progression_path(self) -> Path:
        return self.root / "progression.json"

    @property
    def lessons_path(self) -> Path:
        return self.root / "lessons.md"

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def game_dir(self) -> Path:
        """Shared, versioned native-game facts (not character learning)."""
        return self.knowledge_root / "game"

    @property
    def strategy(self):
        """Immutable strategy inputs resolved for this exact profile.

        The import stays local so path/profile resolution remains independent
        from the decision engine and cannot introduce an import cycle.
        """
        from character_strategy import resolve_character_strategy

        return resolve_character_strategy(
            profile_id=self.profile_id,
            character_id=self.character_id,
        )

    @property
    def strategy_parameters(self):
        """This profile's character-specific scoring parameter instance."""
        return self.strategy.parameters

    @property
    def card_catalog(self):
        """This profile's immutable static card-mechanics catalog."""
        return self.strategy.card_catalog

    @property
    def mechanic_weights(self) -> Mapping[str, float]:
        """Read-only keyword/mechanic valuation inputs for shared algorithms."""
        from types import MappingProxyType

        parameters = self.strategy_parameters
        return MappingProxyType({
            "life_calculation": parameters.life_cost_weight,
            "low_hp_fraction": parameters.low_hp_fraction,
            "low_hp_life_cost_multiplier": (
                parameters.low_hp_life_cost_multiplier),
            "margin": parameters.margin_weight,
            "drain_healing": parameters.drain_healing_weight,
            "permanent_max_hp": parameters.permanent_max_hp_weight,
            "kill_healing": parameters.kill_healing_weight,
            "draw": parameters.draw_weight,
            "energy": parameters.energy_weight,
            "growth": parameters.growth_weight,
        })

    @property
    def keyword_values(self) -> Mapping[str, float]:
        """Alias for consumers that describe mechanics as card keywords."""
        return self.mechanic_weights

    def path_for(self, artifact: str | None = None) -> Path:
        """Return the root or one named learned-knowledge artifact path."""
        if artifact is None or not str(artifact).strip() or _normalise(artifact) == "root":
            return self.root
        key = _normalise(artifact)
        if key == "game":
            return self.game_dir
        try:
            relative = _ARTIFACT_PATHS[key]
        except KeyError as exc:
            raise KeyError(f"unknown profile artifact: {artifact!r}") from exc
        return self.root / relative

    def ensure(self) -> "CharacterProfile":
        """Create this profile's root and run directory, leaving files untouched."""
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        return self


class ProfileStore:
    """Resolve character IDs and run metadata to stable profile paths."""

    def __init__(self, knowledge_root: str | Path):
        self.knowledge_root = Path(knowledge_root)
        self.profiles_root = self.knowledge_root / "profiles"
        self._profiles = {
            IRONCLAD_PROFILE_ID: CharacterProfile(
                profile_id=IRONCLAD_PROFILE_ID,
                character_id=IRONCLAD_CHARACTER_ID,
                root=self.knowledge_root,
                knowledge_root=self.knowledge_root,
                aliases=("character_ironclad", "ironclad_character"),
                legacy_root=True,
            ),
            VIVHITE_PROFILE_ID: CharacterProfile(
                profile_id=VIVHITE_PROFILE_ID,
                character_id=VIVHITE_CHARACTER_ID,
                root=self.profiles_root / VIVHITE_PROFILE_ID,
                knowledge_root=self.knowledge_root,
                aliases=(
                    "vivhite_character_vivhite",
                    "vivhite_character",
                ),
            ),
        }
        self._by_label: dict[str, CharacterProfile] = {}
        for profile in self._profiles.values():
            for label in (
                    profile.profile_id, profile.character_id, *profile.aliases):
                self._by_label[_normalise(label)] = profile

    @property
    def default(self) -> CharacterProfile:
        return self._profiles[DEFAULT_PROFILE_ID]

    @property
    def ironclad(self) -> CharacterProfile:
        return self._profiles[IRONCLAD_PROFILE_ID]

    @property
    def vivhite(self) -> CharacterProfile:
        return self._profiles[VIVHITE_PROFILE_ID]

    @property
    def profiles(self) -> tuple[CharacterProfile, ...]:
        return tuple(self._profiles.values())

    def resolve(self, label: str | CharacterProfile | None = None) -> CharacterProfile:
        """Resolve a profile id, character id, alias, or the legacy default."""
        if isinstance(label, CharacterProfile):
            return label
        if label is None or not str(label).strip():
            return self.default
        try:
            return self._by_label[_normalise(label)]
        except KeyError as exc:
            raise KeyError(f"unknown character profile: {label!r}") from exc

    def for_character(self, character_id: str | None) -> CharacterProfile:
        return self.resolve(character_id)

    def for_run(self, run_log: Mapping[str, object]) -> CharacterProfile:
        """Resolve persisted run metadata; legacy untagged logs are Ironclad."""
        for key in (PROFILE_TAG, "profile_id", "profile"):
            value = run_log.get(key)
            if value is not None and str(value).strip():
                return self.resolve(str(value))
        for key in (CHARACTER_TAG, "character"):
            value = run_log.get(key)
            if value is not None and str(value).strip():
                return self.for_character(str(value))
        return self.ironclad

    # Explicit alias keeps call sites readable when they operate on archived logs.
    profile_for_run = for_run

    def path_for(
            self, label: str | CharacterProfile | None = None,
            artifact: str | None = None) -> Path:
        return self.resolve(label).path_for(artifact)

    def ensure(self, label: str | CharacterProfile | None = None) -> CharacterProfile:
        return self.resolve(label).ensure()


def profile_root(
        knowledge_root: str | Path,
        label: str | CharacterProfile | None = None) -> Path:
    """Compatibility helper for callers that only need the learned-data root."""
    return ProfileStore(knowledge_root).path_for(label)


__all__ = [
    "CHARACTER_TAG",
    "DEFAULT_PROFILE_ID",
    "IRONCLAD_CHARACTER_ID",
    "IRONCLAD_PROFILE_ID",
    "PROFILE_TAG",
    "VIVHITE_CHARACTER_ID",
    "VIVHITE_PROFILE_ID",
    "CharacterProfile",
    "ProfileStore",
    "profile_root",
]
