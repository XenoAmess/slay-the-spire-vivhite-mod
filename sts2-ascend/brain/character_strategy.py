"""Immutable character strategy inputs and the approved Vivhite card catalog.

This module is deliberately independent from ``policy`` and persistent knowledge.
It describes character-specific facts that a shared decision algorithm can consume
later without importing Vivhite mechanics into Ironclad's existing behaviour.

All scoring helpers use realized amounts.  They validate malformed negative input,
but never impose a gameplay ceiling: drain rates above 100%, large healing, Margin,
permanent max-HP growth, draw, energy, and other growth remain linear.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Final


IRONCLAD_PROFILE_ID: Final = "ironclad"
VIVHITE_PROFILE_ID: Final = "vivhite"
IRONCLAD_CHARACTER_ID: Final = "IRONCLAD"
VIVHITE_CHARACTER_ID: Final = "VIVHITE_CHARACTER_VIVHITE_CHARACTER"

CONSERVATION_GEOMETRY: Final = "conservation_geometry"
RECURSIVE_ASTRAL: Final = "recursive_astral"
CRIMSON_INTEGRAL: Final = "crimson_integral"
HYBRID: Final = "hybrid"
BUILD_TAGS: Final = frozenset({
    CONSERVATION_GEOMETRY,
    RECURSIVE_ASTRAL,
    CRIMSON_INTEGRAL,
    HYBRID,
})

CARD_ID_PREFIX: Final = "VIVHITE_CARD_"
CARD_TYPES: Final = frozenset({"attack", "skill", "ability"})
CARD_RARITIES: Final = frozenset({"basic", "common", "uncommon", "rare"})


def _finite_number(name: str, value: int | float) -> float:
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _actual_amount(name: str, value: int | float) -> float:
    result = _finite_number(name, value)
    if result < 0:
        raise ValueError(f"{name} must be an actual non-negative amount")
    return result


@dataclass(frozen=True, slots=True)
class CharacterStrategyParameters:
    """Character-specific weights consumed by the shared scoring algorithm.

    Ironclad uses a neutral overlay so adding this module cannot alter its current
    policy.  Vivhite has a distinct instance with the approved initial weights.
    Unspecified common-policy values remain outside this layer.
    """

    profile_id: str
    character_id: str
    life_cost_weight: float = 0.0
    low_hp_fraction: float = 0.0
    low_hp_life_cost_multiplier: float = 1.0
    margin_weight: float = 0.0
    drain_healing_weight: float = 0.0
    permanent_max_hp_weight: float = 0.0
    kill_healing_weight: float = 0.0
    draw_weight: float = 0.0
    energy_weight: float = 0.0
    growth_weight: float = 0.0

    def __post_init__(self) -> None:
        if not self.profile_id.strip() or not self.character_id.strip():
            raise ValueError("profile_id and character_id are required")
        for field_name in (
            "life_cost_weight",
            "low_hp_fraction",
            "low_hp_life_cost_multiplier",
            "margin_weight",
            "drain_healing_weight",
            "permanent_max_hp_weight",
            "kill_healing_weight",
            "draw_weight",
            "energy_weight",
            "growth_weight",
        ):
            _finite_number(field_name, getattr(self, field_name))
        if not 0.0 <= self.low_hp_fraction <= 1.0:
            raise ValueError("low_hp_fraction must be between zero and one")
        if self.low_hp_life_cost_multiplier < 0.0:
            raise ValueError("low_hp_life_cost_multiplier cannot be negative")


@dataclass(frozen=True, slots=True)
class CardMechanics:
    """Machine-readable base mechanics for one card.

    ``energy`` is either a non-negative integer or ``"X"``.  ``drain_percent``
    stores the printed value or coefficient; ``drain_percent_mode`` explains
    whether it is flat, temporary, global, per-Margin, or per-X.  No percentage
    field has an upper bound.
    """

    energy: int | str
    life_calculation_cost: int = 0
    base_damage: int = 0
    damage_hits: int = 0
    all_enemies: bool = False
    base_block: int = 0
    margin_gain: int = 0
    max_hp_growth: int = 0
    drain_percent: float = 0.0
    drain_percent_mode: str = "flat"
    kill_heal: int = 0
    kill_draw: int = 0
    kill_energy: int = 0
    draw: int = 0
    energy_gain: int = 0
    growth: int = 0
    lethal: bool = False
    exhaust: bool = False
    effects: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not (self.energy == "X" or (
                isinstance(self.energy, int) and not isinstance(self.energy, bool)
                and self.energy >= 0)):
            raise ValueError("energy must be a non-negative integer or 'X'")
        for field_name in (
            "life_calculation_cost",
            "base_damage",
            "damage_hits",
            "base_block",
            "margin_gain",
            "max_hp_growth",
            "kill_heal",
            "kill_draw",
            "kill_energy",
            "draw",
            "energy_gain",
            "growth",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if _finite_number("drain_percent", self.drain_percent) < 0.0:
            raise ValueError("drain_percent cannot be negative")
        if not self.drain_percent_mode.strip():
            raise ValueError("drain_percent_mode is required")
        object.__setattr__(self, "effects", tuple(self.effects))


@dataclass(frozen=True, slots=True)
class CardCatalogEntry:
    """One stable card identity, its presentation names, and base mechanics."""

    card_id: str
    stable_id: str
    name_en: str
    name_zh: str
    card_type: str
    rarity: str
    mechanics: CardMechanics
    build_tags: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.card_id != CARD_ID_PREFIX + self.stable_id:
            raise ValueError("card_id must be VIVHITE_CARD_<stable_id>")
        if self.card_type not in CARD_TYPES:
            raise ValueError(f"unsupported card type: {self.card_type!r}")
        if self.rarity not in CARD_RARITIES:
            raise ValueError(f"unsupported rarity: {self.rarity!r}")
        tags = tuple(self.build_tags)
        if not tags or any(tag not in BUILD_TAGS for tag in tags):
            raise ValueError(f"unsupported build tags: {tags!r}")
        object.__setattr__(self, "build_tags", tags)


@dataclass(frozen=True, slots=True)
class CharacterStrategy:
    """Resolved immutable strategy inputs for one character profile."""

    profile_id: str
    character_id: str
    parameters: CharacterStrategyParameters
    card_catalog: tuple[CardCatalogEntry, ...] = ()

    def card(self, card_id: str) -> CardCatalogEntry | None:
        normalized = str(card_id).strip().upper()
        for entry in self.card_catalog:
            if entry.card_id == normalized:
                return entry
        return None


def _card(
        stable_id: str,
        name_en: str,
        name_zh: str,
        card_type: str,
        rarity: str,
        build_tag: str,
        *,
        energy: int | str,
        life: int = 0,
        damage: int = 0,
        hits: int = 0,
        all_enemies: bool = False,
        block: int = 0,
        margin: int = 0,
        max_hp: int = 0,
        drain: float = 0.0,
        drain_mode: str = "flat",
        kill_heal: int = 0,
        kill_draw: int = 0,
        kill_energy: int = 0,
        draw: int = 0,
        energy_gain: int = 0,
        growth: int = 0,
        lethal: bool = False,
        exhaust: bool = False,
        effects: tuple[str, ...] = (),
) -> CardCatalogEntry:
    return CardCatalogEntry(
        card_id=CARD_ID_PREFIX + stable_id,
        stable_id=stable_id,
        name_en=name_en,
        name_zh=name_zh,
        card_type=card_type,
        rarity=rarity,
        mechanics=CardMechanics(
            energy=energy,
            life_calculation_cost=life,
            base_damage=damage,
            damage_hits=hits,
            all_enemies=all_enemies,
            base_block=block,
            margin_gain=margin,
            max_hp_growth=max_hp,
            drain_percent=drain,
            drain_percent_mode=drain_mode,
            kill_heal=kill_heal,
            kill_draw=kill_draw,
            kill_energy=kill_energy,
            draw=draw,
            energy_gain=energy_gain,
            growth=growth,
            lethal=lethal,
            exhaust=exhaust,
            effects=effects,
        ),
        build_tags=(build_tag,),
    )


# Basics: shared foundations rather than members of one exclusive build.
_BASIC_CARDS = (
    _card("LUMINOUS_PROJECTION", "Luminous Projection", "弦光投影",
          "attack", "basic", HYBRID, energy=1, life=1, damage=10, hits=1),
    _card("CLOSED_DOMAIN_MAPPING", "Closed-Domain Mapping", "闭域映射",
          "skill", "basic", HYBRID, energy=1, life=1, block=9),
    _card("VIVHITE_TRANSFORMATION", "Transformation Formula: Vivhite",
          "变身式·白绮", "ability", "basic", HYBRID, energy=1, life=2,
          growth=2, effects=("gain_1_strength", "gain_1_dexterity")),
)


# A suit: Conservation Geometry.
_CONSERVATION_CARDS = (
    _card("AXIOM_RING", "Axiom Ring", "公理护环", "skill", "common",
          CONSERVATION_GEOMETRY, energy=0, margin=2),
    _card("CLOSED_PROJECTION", "Closed Projection", "闭域投影", "attack",
          "common", CONSERVATION_GEOMETRY, energy=1, life=2, damage=14,
          hits=1, effects=("block_5_per_margin_spent_on_life_cost",)),
    _card("TANGENT_STARLIGHT", "Tangent Starlight", "切线星光", "attack",
          "common", CONSERVATION_GEOMETRY, energy=1, life=1, damage=11,
          hits=1, margin=1),
    _card("OPEN_SET_SHELTER", "Open-Set Shelter", "开集庇护", "skill",
          "common", CONSERVATION_GEOMETRY, energy=1, life=2, block=14,
          margin=1),
    _card("LOCAL_HOMEOMORPHISM", "Local Homeomorphism", "局部同胚", "skill",
          "common", CONSERVATION_GEOMETRY, energy=1, life=1, block=8,
          margin=2),
    _card("SCALE_TRANSFORMATION", "Scale Transformation", "尺度变换", "attack",
          "common", CONSERVATION_GEOMETRY, energy=2, life=3, damage=20,
          hits=1, max_hp=1, lethal=True, exhaust=True,
          effects=("max_hp_growth_on_lethal",)),
    _card("ISOPERIMETRIC_WARD", "Isoperimetric Ward", "等周壁垒", "skill",
          "uncommon", CONSERVATION_GEOMETRY, energy=1, life=2, block=12,
          effects=("block_2_per_current_margin",)),
    _card("TOPOLOGICAL_GROWTH", "Topological Growth", "拓扑增生", "skill",
          "uncommon", CONSERVATION_GEOMETRY, energy=1, life=4, margin=3,
          max_hp=1, exhaust=True),
    _card("LAW_OF_CONSERVATION", "Law of Conservation", "守恒定律", "ability",
          "uncommon", CONSERVATION_GEOMETRY, energy=1, life=3,
          effects=("block_1_per_life_cost_prevented_by_margin",)),
    _card("LIFE_MANIFOLD", "Life Manifold", "生命流形", "ability", "uncommon",
          CONSERVATION_GEOMETRY, energy=2, life=4,
          effects=("gain_2_margin_each_turn",)),
    _card("MOBIUS_LOOP", "Möbius Loop", "莫比乌斯回路", "skill", "uncommon",
          CONSERVATION_GEOMETRY, energy=1, life=2, exhaust=True,
          effects=("return_skill_from_discard", "returned_card_free_this_turn")),
    _card("INVARIANT", "Invariant", "不变量", "skill", "uncommon",
          CONSERVATION_GEOMETRY, energy=1, life=1, block=10, margin=3,
          effects=("margin_if_max_hp_grew_this_combat",)),
    _card("GEODESIC_VEIL", "Geodesic Veil", "测地护幕", "skill", "uncommon",
          CONSERVATION_GEOMETRY, energy=2, life=3, block=24,
          effects=("retain",)),
    _card("CLOSED_MANIFOLD", "Closed Manifold", "闭合流形", "ability", "rare",
          CONSERVATION_GEOMETRY, energy=2, life=5,
          effects=("overheal_becomes_equal_margin",)),
    _card("AXIOM_OF_LIFE", "Axiom of Life", "生命公理", "attack", "rare",
          CONSERVATION_GEOMETRY, energy=2, life=5, damage=24, hits=1,
          max_hp=4, lethal=True, exhaust=True,
          effects=("max_hp_growth_on_lethal",)),
    _card("INFINITE_EXTENSION", "Infinite Extension", "无限延拓", "ability",
          "rare", CONSERVATION_GEOMETRY, energy=3, life=6, growth=1,
          effects=("each_max_hp_growth_gains_1_more", "bonus_does_not_recurse")),
    _card("CONSERVATION_FIRMAMENT", "Conservation Firmament", "守恒穹顶",
          "skill", "rare", CONSERVATION_GEOMETRY, energy=2, life=5,
          exhaust=True, effects=("double_current_margin", "block_2_per_resulting_margin")),
)


# B suit: Recursive Astral.
_RECURSIVE_CARDS = (
    _card("RECURRENT_STARLIGHT", "Recurrent Starlight", "递推星芒", "attack",
          "common", RECURSIVE_ASTRAL, energy=1, life=2, damage=13, hits=1,
          kill_draw=2, lethal=True),
    _card("TERMINATION_CONDITION", "Termination Condition", "终止条件", "attack",
          "common", RECURSIVE_ASTRAL, energy=1, life=2, damage=12, hits=1,
          kill_heal=5, lethal=True),
    _card("PARALLEL_STARFALL", "Parallel Starfall", "并行星雨", "attack",
          "common", RECURSIVE_ASTRAL, energy=1, life=3, damage=6, hits=2,
          all_enemies=True),
    _card("ASTRAL_SEARCH", "Astral Search", "星图检索", "skill", "common",
          RECURSIVE_ASTRAL, energy=0, life=1, draw=2,
          effects=("discard_1",)),
    _card("HEURISTIC_SHIELD", "Heuristic Shield", "启发式护盾", "skill",
          "common", RECURSIVE_ASTRAL, energy=1, life=1, block=8, draw=1),
    _card("SUCCESSOR_FORMULA", "Successor Formula", "后继式", "attack", "common",
          RECURSIVE_ASTRAL, energy=0, life=2, damage=7, hits=1,
          kill_energy=1, lethal=True),
    _card("BACKTRACKING_SPELL", "Backtracking Spell", "回溯咒文", "skill",
          "uncommon", RECURSIVE_ASTRAL, energy=1, life=3, exhaust=True,
          effects=("return_attack_from_discard", "returned_card_free_this_turn")),
    _card("CONVERGENCE_VERDICT", "Convergence Verdict", "收敛判决", "attack",
          "uncommon", RECURSIVE_ASTRAL, energy=2, life=4, damage=27, hits=1,
          kill_draw=3, kill_energy=1, lethal=True),
    _card("DIVIDE_AND_CONQUER_CIRCLE", "Divide-and-Conquer Circle", "分治法阵",
          "skill", "uncommon", RECURSIVE_ASTRAL, energy=1, life=2, draw=2,
          effects=("4_spell_damage_per_attack_drawn_to_random_enemy",)),
    _card("ASTRAL_PURSUIT", "Astral Pursuit", "星算追猎", "ability", "uncommon",
          RECURSIVE_ASTRAL, energy=1, life=3, kill_draw=1,
          effects=("triggers_on_any_enemy_death",)),
    _card("PREFETCH_FUTURE", "Prefetch Future", "预取未来", "skill", "uncommon",
          RECURSIVE_ASTRAL, energy=1, life=2, draw=3,
          effects=("put_1_hand_card_on_draw_pile_top",)),
    _card("INDUCTIVE_CIRCLE", "Inductive Circle", "归纳法阵", "ability",
          "uncommon", RECURSIVE_ASTRAL, energy=2, life=4, kill_heal=2,
          effects=("increase_immediate_enemy_death_heal",)),
    _card("EVENT_LOOP", "Event Loop", "事件循环", "skill", "uncommon",
          RECURSIVE_ASTRAL, energy=1, life=3, exhaust=True,
          effects=("copy_non_ability_played_this_turn", "copy_free_this_turn")),
    _card("PROOF_OF_TERMINATION", "Proof of Termination", "终止证明", "attack",
          "rare", RECURSIVE_ASTRAL, energy=2, life=5, damage=20, hits=1,
          all_enemies=True, kill_draw=2, kill_energy=1, lethal=True,
          exhaust=True),
    _card("DYNAMIC_PROGRAMMING", "Dynamic Programming", "动态规划", "ability",
          "rare", RECURSIVE_ASTRAL, energy=2, life=5, growth=2,
          effects=("gain_2_calculation_per_extra_card_drawn",
                   "next_attack_each_hit_gains_all_calculation_then_reset")),
    _card("INFINITE_STAR_SEQUENCE", "Infinite Star Sequence", "无穷星序", "skill",
          "rare", RECURSIVE_ASTRAL, energy=1, life=4, exhaust=True,
          effects=("draw_cards_equal_cards_previously_played_this_turn",
                   "gain_1_margin_per_card_actually_drawn")),
    _card("OPTIMAL_ALGORITHM", "Optimal Algorithm", "最优算法", "ability", "rare",
          RECURSIVE_ASTRAL, energy=3, life=7, kill_heal=3, kill_draw=2,
          kill_energy=1, effects=("triggers_on_any_enemy_death",)),
)


# C suit: Crimson Integral.
_CRIMSON_CARDS = (
    _card("CRIMSON_AREA", "Crimson Area", "绯色面积", "attack", "common",
          CRIMSON_INTEGRAL, energy=1, life=2, damage=14, hits=1, drain=20),
    _card("TRICHROMATIC_WALTZ", "Trichromatic Waltz", "三色轮舞", "attack",
          "common", CRIMSON_INTEGRAL, energy=1, life=3, damage=4, hits=3,
          drain=15),
    _card("COMPOSITE_COLOR_WHEEL", "Composite Color Wheel", "综合色轮", "attack",
          "common", CRIMSON_INTEGRAL, energy=2, life=3, damage=10, hits=1,
          all_enemies=True, drain=25),
    _card("DIFFERENTIAL_SAMPLING", "Differential Sampling", "微分取样", "attack",
          "common", CRIMSON_INTEGRAL, energy=0, life=1, damage=3, hits=2,
          drain=10),
    _card("CHIAROSCURO", "Chiaroscuro", "明暗对照", "skill", "common",
          CRIMSON_INTEGRAL, energy=1, life=2, block=10, drain=25,
          drain_mode="next_attack_bonus",
          effects=("next_attack_gains_drain_percent",)),
    _card("NEGATIVE_SPACE", "Negative Space", "负空间", "skill", "common",
          CRIMSON_INTEGRAL, energy=0, life=2, margin=1,
          effects=("apply_2_vulnerable",)),
    _card("SPECTRAL_INTEGRAL", "Spectral Integral", "光谱积分", "ability",
          "uncommon", CRIMSON_INTEGRAL, energy=1, life=3, drain=8,
          drain_mode="global_combat"),
    _card("GOLDEN_COMPOSITION", "Golden Composition", "黄金构图", "attack",
          "uncommon", CRIMSON_INTEGRAL, energy=2, life=4, damage=8, hits=3,
          drain=25),
    _card("RIEMANN_STAR_ARRAY", "Riemann Star Array", "黎曼星阵", "attack",
          "uncommon", CRIMSON_INTEGRAL, energy=1, life=3, damage=4,
          drain=15, drain_mode="flat",
          effects=("one_hit_per_current_hand_card",)),
    _card("CHROMATIC_TRANSITION", "Chromatic Transition", "色阶过渡", "skill",
          "uncommon", CRIMSON_INTEGRAL, energy=1, life=2, drain=10,
          drain_mode="global_combat", draw=1, exhaust=True),
    _card("COLOR_CONSERVATION", "Color Conservation", "色彩守恒", "ability",
          "uncommon", CRIMSON_INTEGRAL, energy=2, life=4,
          effects=("gain_block_equal_actual_drain_healing",)),
    _card("COMPOSITE_COLOR_FIELD", "Composite Color Field", "综合色域", "skill",
          "uncommon", CRIMSON_INTEGRAL, energy=2, life=4, drain=10,
          drain_mode="global_combat", exhaust=True,
          effects=("apply_2_vulnerable_to_all_enemies",)),
    _card("COMPLEMENTARY_AFTERIMAGE", "Complementary Afterimage", "补色残像",
          "attack", "uncommon", CRIMSON_INTEGRAL, energy=1, life=3,
          damage=12, hits=1, drain=20,
          effects=("repeat_if_current_hp_increased_this_turn",)),
    _card("DEFINITE_CRIMSON_INTEGRAL", "Definite Crimson Integral", "绯红定积分",
          "attack", "rare", CRIMSON_INTEGRAL, energy=2, life=6, damage=32,
          hits=1, drain=60),
    _card("CRIMSON_CONSERVATION_LAW", "Crimson Conservation Law", "血色守恒律",
          "ability", "rare", CRIMSON_INTEGRAL, energy=2, life=5, growth=1,
          effects=("gain_1_strength_per_5_actual_drain_healing",)),
    _card("INFINITE_CANVAS", "Infinite Canvas", "无限画布", "ability", "rare",
          CRIMSON_INTEGRAL, energy=3, life=8, drain=2,
          drain_mode="global_growth_per_attack_that_drain_heals", growth=2),
    _card("PERFECT_SYNTHESIS", "Perfect Synthesis", "完美综合色", "attack",
          "rare", CRIMSON_INTEGRAL, energy=3, life=8, damage=11, hits=5,
          all_enemies=True, drain=40, exhaust=True),
)


# Cross-suit cards deliberately carry only the hybrid tag.
_HYBRID_CARDS = (
    _card("GOLDEN_RATIO", "Golden Ratio", "黄金分割", "skill", "uncommon",
          HYBRID, energy=1, life=2, margin=3, drain=15,
          drain_mode="temporary_this_turn", draw=1),
    _card("ASTRAL_MEASURE", "Astral Measure", "星体测度", "attack", "uncommon",
          HYBRID, energy=1, damage=10, hits=1, drain=5,
          drain_mode="per_margin_before_life_payment",
          effects=("damage_plus_margin_before_life_payment",)),
    _card("CHROMATIC_SEQUENCE", "Chromatic Sequence", "综合色序", "skill",
          "uncommon", HYBRID, energy=1, life=2, draw=2,
          effects=("drawn_attack_grants_1_margin",
                   "drawn_skill_grants_5_temporary_drain_percent",
                   "drawn_ability_grants_both")),
    _card("UNIFIED_FIELD_THEORY", "Unified Field Theory", "统一场论", "ability",
          "rare", HYBRID, energy=3, life=7, drain=2,
          drain_mode="per_life_cost_prevented_by_margin",
          effects=("gain_floor_actual_drain_healing_div_3_margin",)),
    _card("CONSERVED_RECURRENCE", "Conserved Recurrence", "守恒递归", "skill",
          "rare", HYBRID, energy=2, life=5, exhaust=True,
          effects=("return_non_ability_from_exhaust",
                   "create_free_this_turn_copy")),
    _card("CHROMATIC_LIMIT", "Chromatic Limit", "绯彩极限", "attack", "rare",
          HYBRID, energy="X", life=4, damage=9, drain=15,
          drain_mode="per_x", effects=("damage_hits_equal_x",
                                        "gain_1_margin_per_10_actual_drain_healing")),
)


VIVHITE_CARD_CATALOG: Final = (
    _BASIC_CARDS
    + _CONSERVATION_CARDS
    + _RECURSIVE_CARDS
    + _CRIMSON_CARDS
    + _HYBRID_CARDS
)
VIVHITE_CARD_IDS: Final = frozenset(card.card_id for card in VIVHITE_CARD_CATALOG)

if len(VIVHITE_CARD_CATALOG) != 60 or len(VIVHITE_CARD_IDS) != 60:
    raise RuntimeError("the approved Vivhite catalog must contain 60 unique cards")


IRONCLAD_PARAMETERS: Final = CharacterStrategyParameters(
    profile_id=IRONCLAD_PROFILE_ID,
    character_id=IRONCLAD_CHARACTER_ID,
)
VIVHITE_PARAMETERS: Final = CharacterStrategyParameters(
    profile_id=VIVHITE_PROFILE_ID,
    character_id=VIVHITE_CHARACTER_ID,
    life_cost_weight=-1.25,
    low_hp_fraction=0.35,
    low_hp_life_cost_multiplier=2.0,
    margin_weight=1.25,
    drain_healing_weight=0.85,
    permanent_max_hp_weight=3.0,
    kill_healing_weight=1.0,
    draw_weight=1.0,
    energy_weight=1.0,
    growth_weight=1.0,
)

IRONCLAD_STRATEGY: Final = CharacterStrategy(
    profile_id=IRONCLAD_PROFILE_ID,
    character_id=IRONCLAD_CHARACTER_ID,
    parameters=IRONCLAD_PARAMETERS,
    card_catalog=(),
)
VIVHITE_STRATEGY: Final = CharacterStrategy(
    profile_id=VIVHITE_PROFILE_ID,
    character_id=VIVHITE_CHARACTER_ID,
    parameters=VIVHITE_PARAMETERS,
    card_catalog=VIVHITE_CARD_CATALOG,
)

_STRATEGY_LABELS: Final = {
    IRONCLAD_PROFILE_ID.casefold(): IRONCLAD_STRATEGY,
    IRONCLAD_CHARACTER_ID.casefold(): IRONCLAD_STRATEGY,
    "character_ironclad": IRONCLAD_STRATEGY,
    VIVHITE_PROFILE_ID.casefold(): VIVHITE_STRATEGY,
    VIVHITE_CHARACTER_ID.casefold(): VIVHITE_STRATEGY,
    "vivhite_character": VIVHITE_STRATEGY,
    "vivhite_character_vivhite": VIVHITE_STRATEGY,
}


def _resolve_label(label: str) -> CharacterStrategy:
    normalized = str(label).strip().casefold()
    if not normalized:
        raise KeyError("empty character strategy label")
    try:
        return _STRATEGY_LABELS[normalized]
    except KeyError as exc:
        raise KeyError(f"unknown character strategy: {label!r}") from exc


def resolve_character_strategy(
        profile_id: str | None = None,
        character_id: str | None = None,
) -> CharacterStrategy:
    """Resolve by profile ID, character ID, or both.

    Supplying both is useful when binding an API run to persisted profile data;
    disagreement fails closed instead of silently crossing character strategy.
    With no label, the historical Ironclad behaviour remains the default.
    """

    if profile_id is None and character_id is None:
        return IRONCLAD_STRATEGY
    by_profile = _resolve_label(profile_id) if profile_id is not None else None
    by_character = _resolve_label(character_id) if character_id is not None else None
    if by_profile is not None and by_character is not None:
        if by_profile is not by_character:
            raise ValueError(
                f"profile {profile_id!r} and character {character_id!r} disagree")
        return by_profile
    return by_profile or by_character  # type: ignore[return-value]


resolve_strategy = resolve_character_strategy


def drain_healing_from_actual_damage(
        actual_enemy_hp_damage: int | float,
        drain_percent: int | float,
) -> float:
    """Return the uncapped drain amount implied by realized enemy HP damage."""

    damage = _actual_amount("actual_enemy_hp_damage", actual_enemy_hp_damage)
    percent = _actual_amount("drain_percent", drain_percent)
    return damage * percent / 100.0


def score_life_cost(
        parameters: CharacterStrategyParameters,
        actual_hp_lost: int | float,
        *,
        current_hp: int | float,
        max_hp: int | float,
) -> float:
    """Score actual life paid; Vivhite doubles risk strictly below 35% HP."""

    amount = _actual_amount("actual_hp_lost", actual_hp_lost)
    hp = _finite_number("current_hp", current_hp)
    maximum = _finite_number("max_hp", max_hp)
    if maximum <= 0.0:
        raise ValueError("max_hp must be positive")
    multiplier = (
        parameters.low_hp_life_cost_multiplier
        if hp / maximum < parameters.low_hp_fraction
        else 1.0
    )
    return amount * parameters.life_cost_weight * multiplier


def score_margin(
        parameters: CharacterStrategyParameters,
        actual_margin_gained: int | float,
) -> float:
    return (_actual_amount("actual_margin_gained", actual_margin_gained)
            * parameters.margin_weight)


def score_drain_healing(
        parameters: CharacterStrategyParameters,
        actual_hp_restored: int | float,
        *,
        drain_percent: int | float | None = None,
) -> float:
    """Score actual drain healing without an HP or percentage ceiling."""

    if drain_percent is not None:
        _actual_amount("drain_percent", drain_percent)  # deliberately no 100% cap
    return (_actual_amount("actual_hp_restored", actual_hp_restored)
            * parameters.drain_healing_weight)


def score_permanent_max_hp(
        parameters: CharacterStrategyParameters,
        actual_max_hp_gained: int | float,
) -> float:
    return (_actual_amount("actual_max_hp_gained", actual_max_hp_gained)
            * parameters.permanent_max_hp_weight)


def score_kill_healing(
        parameters: CharacterStrategyParameters,
        actual_hp_restored: int | float,
) -> float:
    return (_actual_amount("actual_hp_restored", actual_hp_restored)
            * parameters.kill_healing_weight)


def score_draw(
        parameters: CharacterStrategyParameters,
        actual_cards_drawn: int | float,
) -> float:
    return (_actual_amount("actual_cards_drawn", actual_cards_drawn)
            * parameters.draw_weight)


def score_energy(
        parameters: CharacterStrategyParameters,
        actual_energy_gained: int | float,
) -> float:
    return (_actual_amount("actual_energy_gained", actual_energy_gained)
            * parameters.energy_weight)


def score_growth(
        parameters: CharacterStrategyParameters,
        actual_growth: int | float,
) -> float:
    return (_actual_amount("actual_growth", actual_growth)
            * parameters.growth_weight)


def score_realized_mechanics(
        parameters: CharacterStrategyParameters,
        *,
        current_hp: int | float,
        max_hp: int | float,
        life_cost_hp: int | float = 0,
        margin_gained: int | float = 0,
        drain_percent: int | float = 0,
        drain_hp_restored: int | float = 0,
        permanent_max_hp_gained: int | float = 0,
        kill_hp_restored: int | float = 0,
        cards_drawn: int | float = 0,
        energy_gained: int | float = 0,
        growth: int | float = 0,
) -> float:
    """Score one realized mechanics observation as an uncapped linear sum."""

    return sum((
        score_life_cost(
            parameters, life_cost_hp, current_hp=current_hp, max_hp=max_hp),
        score_margin(parameters, margin_gained),
        score_drain_healing(
            parameters, drain_hp_restored, drain_percent=drain_percent),
        score_permanent_max_hp(parameters, permanent_max_hp_gained),
        score_kill_healing(parameters, kill_hp_restored),
        score_draw(parameters, cards_drawn),
        score_energy(parameters, energy_gained),
        score_growth(parameters, growth),
    ))


__all__ = [
    "BUILD_TAGS",
    "CONSERVATION_GEOMETRY",
    "CRIMSON_INTEGRAL",
    "HYBRID",
    "IRONCLAD_CHARACTER_ID",
    "IRONCLAD_PARAMETERS",
    "IRONCLAD_PROFILE_ID",
    "IRONCLAD_STRATEGY",
    "RECURSIVE_ASTRAL",
    "VIVHITE_CARD_CATALOG",
    "VIVHITE_CARD_IDS",
    "VIVHITE_CHARACTER_ID",
    "VIVHITE_PARAMETERS",
    "VIVHITE_PROFILE_ID",
    "VIVHITE_STRATEGY",
    "CardCatalogEntry",
    "CardMechanics",
    "CharacterStrategy",
    "CharacterStrategyParameters",
    "drain_healing_from_actual_damage",
    "resolve_character_strategy",
    "resolve_strategy",
    "score_drain_healing",
    "score_draw",
    "score_energy",
    "score_growth",
    "score_kill_healing",
    "score_life_cost",
    "score_margin",
    "score_permanent_max_hp",
    "score_realized_mechanics",
]
