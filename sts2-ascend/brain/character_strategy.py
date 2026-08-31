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
from math import ceil, floor, isfinite
import re
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

SELECTION_DISCARD_WORST: Final = "discard_worst"
SELECTION_TOPDECK_BEST: Final = "topdeck_best"
SELECTION_RECOVER_FREE_BEST: Final = "recover_free_best"
SELECTION_COPY_FREE_BEST: Final = "copy_free_best"
SELECTION_RECOVER_COPY_BEST: Final = "recover_copy_best"

VIVHITE_MARGIN_POWER_ID: Final = "VIVHITE_POWER_INFINITE_MARGIN_POWER"
VIVHITE_DRAIN_POWER_ID: Final = "VIVHITE_POWER_INFINITE_DRAIN_POWER"
VIVHITE_TURN_DRAIN_POWER_ID: Final = (
    "VIVHITE_POWER_INFINITE_DRAIN_THIS_TURN_POWER")
VIVHITE_DIMENSIONALITY_POWER_ID: Final = (
    "VIVHITE_POWER_INFINITE_DIMENSIONALITY_POWER")
VIVHITE_EXTENSION_POWER_ID: Final = (
    "VIVHITE_POWER_INFINITE_EXTENSION_POWER")
VIVHITE_CRIMSON_RITUAL_POWER_ID: Final = (
    "VIVHITE_POWER_VIVHITES_CRIMSON_TRANSFORMATION_RITUAL_POWER")
VIVHITE_CRIMSON_RITUAL_UPGRADED_POWER_ID: Final = (
    "VIVHITE_POWER_VIVHITES_CRIMSON_TRANSFORMATION_RITUAL_UPGRADED_POWER")
VIVHITE_BASE_MAX_HP: Final = 78
VIVHITE_STARTING_RELIC_NAME_ZH: Final = "孤高冠冕"
VIVHITE_STARTING_RELIC_NAME_EN: Final = "Solitary Crown"


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
    stores the final integer printed value or coefficient after the complete
    balance sequence (``ceil(old / 5)`` followed by the approved doublings);
    ``drain_percent_mode`` explains whether it is flat, temporary, global,
    per-drawn-card type, per-Margin, or per-X.  No percentage field has an
    upper bound.
    """

    energy: int | str
    life_calculation_cost: int = 0
    base_damage: int = 0
    damage_hits: int = 0
    all_enemies: bool = False
    base_block: int = 0
    margin_gain: int = 0
    max_hp_growth: int = 0
    drain_percent: int = 0
    drain_percent_mode: str = "flat"
    kill_heal: int = 0
    death_heal_percent: int = 0
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
            "death_heal_percent",
            "kill_draw",
            "kill_energy",
            "draw",
            "energy_gain",
            "growth",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if (isinstance(self.drain_percent, bool)
                or not isinstance(self.drain_percent, int)
                or self.drain_percent < 0):
            raise ValueError("drain_percent must be a non-negative integer")
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
        drain: int = 0,
        drain_mode: str = "flat",
        kill_heal: int = 0,
        death_heal_percent: int = 0,
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
            death_heal_percent=death_heal_percent,
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
          "attack", "basic", HYBRID, energy=1, life=2, damage=10, hits=1),
    _card("CLOSED_DOMAIN_MAPPING", "Closed-Domain Mapping", "闭域映射",
          "skill", "basic", HYBRID, energy=1, life=2, block=9),
    _card("VIVHITE_TRANSFORMATION", "Vivhite's Transformation Formula",
          "白绮的变身式", "ability", "basic", HYBRID, energy=1, life=4,
          growth=2, effects=("gain_1_strength", "gain_1_dexterity")),
)


# A suit: Conservation Geometry.
_CONSERVATION_CARDS = (
    _card("AXIOM_RING", "Axiom Ring", "公理护环", "skill", "common",
          CONSERVATION_GEOMETRY, energy=0, margin=2),
    _card("CLOSED_PROJECTION", "Closed Projection", "闭域投影", "attack",
          "common", CONSERVATION_GEOMETRY, energy=1, life=4, damage=14,
          hits=1, effects=("block_5_per_margin_spent_on_life_cost",)),
    _card("TANGENT_STARLIGHT", "Tangent Starlight", "切线星光", "attack",
          "common", CONSERVATION_GEOMETRY, energy=1, life=2, damage=11,
          hits=1, margin=1),
    _card("OPEN_SET_SHELTER", "Open-Set Shelter", "开集庇护", "skill",
          "common", CONSERVATION_GEOMETRY, energy=1, life=4, block=14,
          margin=1),
    _card("LOCAL_HOMEOMORPHISM", "Local Homeomorphism", "局部同胚", "skill",
          "common", CONSERVATION_GEOMETRY, energy=1, life=2, block=8,
          margin=2),
    _card("SCALE_TRANSFORMATION", "Scale Transformation", "尺度变换", "attack",
          "common", CONSERVATION_GEOMETRY, energy=2, life=6, damage=20,
          hits=1, max_hp=1, lethal=True, exhaust=True,
          effects=("max_hp_growth_on_lethal",)),
    _card("ISOPERIMETRIC_WARD", "Isoperimetric Ward", "等周壁垒", "skill",
          "uncommon", CONSERVATION_GEOMETRY, energy=1, life=4, block=12,
          effects=("block_2_per_current_margin",)),
    _card("TOPOLOGICAL_GROWTH", "Topological Growth", "拓扑增生", "skill",
          "uncommon", CONSERVATION_GEOMETRY, energy=1, life=8, margin=3,
          max_hp=1, exhaust=True),
    _card("LAW_OF_CONSERVATION", "Law of Conservation", "守恒定律", "ability",
          "uncommon", CONSERVATION_GEOMETRY, energy=1, life=6,
          effects=("block_1_per_life_cost_prevented_by_margin",)),
    _card("LIFE_MANIFOLD", "Life Manifold", "生命流形", "ability", "uncommon",
          CONSERVATION_GEOMETRY, energy=2, life=8,
          effects=("gain_2_margin_each_turn",)),
    _card("MOBIUS_LOOP", "Möbius Loop", "莫比乌斯回路", "skill", "uncommon",
          CONSERVATION_GEOMETRY, energy=1, life=4, exhaust=True,
          effects=("return_skill_from_discard", "returned_card_free_this_turn")),
    _card("INVARIANT", "Invariant", "不变量", "skill", "uncommon",
          CONSERVATION_GEOMETRY, energy=1, life=2, block=10, margin=3,
          effects=("margin_if_max_hp_grew_this_combat",)),
    _card("GEODESIC_VEIL", "Geodesic Veil", "测地护幕", "skill", "uncommon",
          CONSERVATION_GEOMETRY, energy=2, life=6, block=24,
          effects=("retain",)),
    _card("CLOSED_MANIFOLD", "Closed Manifold", "闭合流形", "ability", "rare",
          CONSERVATION_GEOMETRY, energy=2, life=10,
          effects=("overheal_becomes_equal_margin",)),
    _card("AXIOM_OF_LIFE", "Axiom of Life", "生命公理", "attack", "rare",
          CONSERVATION_GEOMETRY, energy=2, life=10, damage=24, hits=1,
          max_hp=4, lethal=True, exhaust=True,
          effects=("max_hp_growth_on_lethal",)),
    _card("INFINITE_EXTENSION", "Infinite Extension", "无限延拓", "ability",
          "rare", CONSERVATION_GEOMETRY, energy=3, life=12, growth=1,
          effects=("each_max_hp_growth_gains_1_more", "bonus_does_not_recurse")),
    _card("CONSERVATION_FIRMAMENT", "Conservation Firmament", "守恒穹顶",
          "skill", "rare", CONSERVATION_GEOMETRY, energy=2, life=10,
          exhaust=True, effects=("double_current_margin", "block_2_per_resulting_margin")),
)


# B suit: Recursive Astral.
_RECURSIVE_CARDS = (
    _card("RECURRENT_STARLIGHT", "Recurrent Starlight", "递推星芒", "attack",
          "common", RECURSIVE_ASTRAL, energy=1, life=4, damage=13, hits=1,
          kill_draw=4, lethal=True),
    _card("TERMINATION_CONDITION", "Termination Condition", "终止条件", "attack",
          "common", RECURSIVE_ASTRAL, energy=1, life=4, damage=12, hits=1,
          kill_heal=5, lethal=True),
    _card("PARALLEL_STARFALL", "Parallel Starfall", "并行星雨", "attack",
          "common", RECURSIVE_ASTRAL, energy=1, life=6, damage=6, hits=2,
          all_enemies=True),
    _card("ASTRAL_SEARCH", "Astral Search", "星图检索", "skill", "common",
          RECURSIVE_ASTRAL, energy=0, life=2, draw=4,
          effects=("discard_2",)),
    _card("HEURISTIC_SHIELD", "Heuristic Shield", "启发式护盾", "skill",
          "common", RECURSIVE_ASTRAL, energy=1, life=2, block=8, draw=2),
    _card("SUCCESSOR_FORMULA", "Successor Formula", "后继式", "attack", "common",
          RECURSIVE_ASTRAL, energy=0, life=4, damage=7, hits=1,
          kill_energy=1, lethal=True),
    _card("BACKTRACKING_SPELL", "Backtracking Spell", "回溯咒文", "skill",
          "uncommon", RECURSIVE_ASTRAL, energy=1, life=6, exhaust=True,
          effects=("return_attack_from_discard", "returned_card_free_this_turn")),
    _card("CONVERGENCE_VERDICT", "Convergence Verdict", "收敛判决", "attack",
          "uncommon", RECURSIVE_ASTRAL, energy=2, life=8, damage=27, hits=1,
          kill_draw=6, kill_energy=1, lethal=True),
    _card("DIVIDE_AND_CONQUER_CIRCLE", "Divide-and-Conquer Circle", "分治法阵",
          "skill", "uncommon", RECURSIVE_ASTRAL, energy=1, life=4, draw=4,
          effects=("4_spell_damage_per_attack_drawn_to_random_enemy",)),
    _card("ASTRAL_PURSUIT", "Astral Pursuit", "星算追猎", "ability", "uncommon",
          RECURSIVE_ASTRAL, energy=1, life=6, kill_draw=2,
          effects=("triggers_on_any_enemy_death",)),
    _card("PREFETCH_FUTURE", "Prefetch Future", "预取未来", "skill", "uncommon",
          RECURSIVE_ASTRAL, energy=1, life=4, draw=6,
          effects=("put_1_hand_card_on_draw_pile_top",)),
    _card("INDUCTIVE_CIRCLE", "Inductive Circle", "归纳法阵", "ability",
          "uncommon", RECURSIVE_ASTRAL, energy=1, life=8,
          death_heal_percent=50,
          effects=("increase_immediate_enemy_death_heal_percent",)),
    _card("EVENT_LOOP", "Event Loop", "事件循环", "skill", "uncommon",
          RECURSIVE_ASTRAL, energy=1, life=6, exhaust=True,
          effects=("copy_non_ability_played_this_turn", "copy_free_this_turn")),
    _card("PROOF_OF_TERMINATION", "Proof of Termination", "终止证明", "attack",
          "rare", RECURSIVE_ASTRAL, energy=2, life=10, damage=20, hits=1,
          all_enemies=True, kill_draw=4, kill_energy=1, lethal=True,
          exhaust=True),
    _card("DYNAMIC_PROGRAMMING", "Dynamic Programming", "动态规划", "ability",
          "rare", RECURSIVE_ASTRAL, energy=2, life=10, growth=2,
          effects=("gain_2_calculation_per_extra_card_drawn",
                   "next_attack_each_hit_gains_all_calculation_then_reset")),
    _card("INFINITE_STAR_SEQUENCE", "Infinite Star Sequence", "无穷星序", "skill",
          "rare", RECURSIVE_ASTRAL, energy=1, life=8, exhaust=True,
          effects=("draw_2_cards_per_card_previously_played_this_turn",
                   "gain_1_margin_per_card_actually_drawn")),
    _card("OPTIMAL_ALGORITHM", "Optimal Algorithm", "最优算法", "ability", "rare",
          RECURSIVE_ASTRAL, energy=3, life=14, kill_heal=3, kill_draw=4,
          kill_energy=1, effects=("triggers_on_any_enemy_death",)),
)


# C suit: Crimson Integral.
_CRIMSON_CARDS = (
    _card("CRIMSON_AREA", "Crimson Area", "绯色面积", "attack", "common",
          CRIMSON_INTEGRAL, energy=1, life=4, damage=14, hits=1, drain=16),
    _card("TRICHROMATIC_WALTZ", "Trichromatic Waltz", "三色轮舞", "attack",
          "common", CRIMSON_INTEGRAL, energy=1, life=6, damage=4, hits=3,
          drain=12),
    _card("COMPOSITE_COLOR_WHEEL", "Composite Color Wheel", "综合色轮", "attack",
          "common", CRIMSON_INTEGRAL, energy=2, life=6, damage=10, hits=1,
          all_enemies=True, drain=20),
    _card("DIFFERENTIAL_SAMPLING", "Differential Sampling", "微分取样", "attack",
          "common", CRIMSON_INTEGRAL, energy=0, life=2, damage=3, hits=2,
          drain=8),
    _card("CHIAROSCURO", "Chiaroscuro", "明暗对照", "skill", "common",
          CRIMSON_INTEGRAL, energy=1, life=4, block=10, drain=20,
          drain_mode="next_attack_bonus",
          effects=("next_attack_gains_drain_percent",)),
    _card("NEGATIVE_SPACE", "Negative Space", "负空间", "skill", "common",
          CRIMSON_INTEGRAL, energy=0, life=4, margin=1,
          effects=("apply_2_vulnerable",)),
    _card("SPECTRAL_INTEGRAL", "Spectral Integral", "光谱积分", "ability",
          "uncommon", CRIMSON_INTEGRAL, energy=1, life=6, drain=8,
          drain_mode="global_combat"),
    _card("GOLDEN_COMPOSITION", "Golden Composition", "黄金构图", "attack",
          "uncommon", CRIMSON_INTEGRAL, energy=2, life=8, damage=8, hits=3,
          drain=20),
    _card("RIEMANN_STAR_ARRAY", "Riemann Star Array", "黎曼星阵", "attack",
          "uncommon", CRIMSON_INTEGRAL, energy=1, life=6, damage=4,
          drain=12, drain_mode="flat",
          effects=("one_hit_per_current_hand_card",)),
    _card("CHROMATIC_TRANSITION", "Chromatic Transition", "色阶过渡", "skill",
          "uncommon", CRIMSON_INTEGRAL, energy=1, life=4, drain=8,
          drain_mode="global_combat", draw=2, exhaust=True),
    _card("COLOR_CONSERVATION", "Color Conservation", "色彩守恒", "ability",
          "uncommon", CRIMSON_INTEGRAL, energy=0, life=8,
          effects=("gain_block_equal_actual_drain_healing",)),
    _card("COMPOSITE_COLOR_FIELD", "Composite Color Field", "综合色域", "skill",
          "uncommon", CRIMSON_INTEGRAL, energy=2, life=8, drain=8,
          drain_mode="global_combat", exhaust=True,
          effects=("apply_2_vulnerable_to_all_enemies",)),
    _card("COMPLEMENTARY_AFTERIMAGE", "Complementary Afterimage", "补色残像",
          "attack", "uncommon", CRIMSON_INTEGRAL, energy=1, life=6,
          damage=12, hits=1, drain=16,
          effects=("repeat_if_current_hp_increased_this_turn",)),
    _card("DEFINITE_CRIMSON_INTEGRAL", "Definite Crimson Integral", "绯红定积分",
          "attack", "rare", CRIMSON_INTEGRAL, energy=2, life=12, damage=32,
          hits=1, drain=48),
    _card("CRIMSON_CONSERVATION_LAW", "Crimson Conservation Law", "血色守恒律",
          "ability", "rare", CRIMSON_INTEGRAL, energy=2, life=10, growth=1,
          effects=("gain_1_strength_per_5_actual_drain_healing",)),
    _card("INFINITE_CANVAS", "Infinite Canvas", "无限画布", "ability", "rare",
          CRIMSON_INTEGRAL, energy=3, life=16, drain=4,
          drain_mode="global_growth_per_attack_that_drain_heals", growth=4),
    _card("PERFECT_SYNTHESIS", "Perfect Synthesis", "完美综合色", "attack",
          "rare", CRIMSON_INTEGRAL, energy=3, life=16, damage=11, hits=5,
          all_enemies=True, drain=32, exhaust=True),
)


# Cross-suit cards deliberately carry only the hybrid tag.
_HYBRID_CARDS = (
    _card("GOLDEN_RATIO", "Golden Ratio", "黄金分割", "skill", "uncommon",
          HYBRID, energy=1, life=4, margin=3, drain=12,
          drain_mode="temporary_this_turn", draw=2),
    _card("ASTRAL_MEASURE", "Astral Measure", "星体测度", "attack", "uncommon",
          HYBRID, energy=1, damage=10, hits=1, drain=4,
          drain_mode="per_margin_before_life_payment",
          effects=("damage_plus_margin_before_life_payment",)),
    _card("CHROMATIC_SEQUENCE", "Chromatic Sequence", "综合色序", "skill",
          "uncommon", HYBRID, energy=1, life=4, draw=4, drain=4,
          drain_mode="per_drawn_skill",
          effects=("drawn_attack_grants_1_margin",
                   "drawn_skill_grants_4_temporary_drain_percent",
                   "drawn_ability_grants_both")),
    _card("UNIFIED_FIELD_THEORY", "Unified Field Theory", "统一场论", "ability",
          "rare", HYBRID, energy=3, life=14, drain=4,
          drain_mode="per_life_cost_prevented_by_margin",
          effects=("gain_floor_actual_drain_healing_div_3_margin",)),
    _card("CONSERVED_RECURRENCE", "Conserved Recurrence", "守恒递归", "skill",
          "rare", HYBRID, energy=2, life=10, exhaust=True,
          effects=("return_non_ability_from_exhaust",
                   "create_free_this_turn_copy")),
    _card("CHROMATIC_LIMIT", "Chromatic Limit", "绯彩极限", "attack", "rare",
          HYBRID, energy="X", life=8, damage=9, drain=12,
          drain_mode="per_x", effects=("damage_hits_equal_x",
                                        "gain_1_margin_per_10_actual_drain_healing")),
    _card(
        "VIVHITES_CRIMSON_TRANSFORMATION_RITUAL",
        "Vivhite's Crimson Transformation Ritual",
        "白绮的猩红转化仪式",
        "ability",
        "rare",
        HYBRID,
        energy=0,
        effects=(
            "ritual_phase_starts_at_0_and_increments_each_player_turn",
            "all_attacks_gain_life_cost_equal_total_ritual_phase",
            "all_attack_hits_gain_10_percent_damage_per_ritual_phase",
        ),
    ),
)


VIVHITE_CARD_CATALOG: Final = (
    _BASIC_CARDS
    + _CONSERVATION_CARDS
    + _RECURSIVE_CARDS
    + _CRIMSON_CARDS
    + _HYBRID_CARDS
)
VIVHITE_CARD_IDS: Final = frozenset(card.card_id for card in VIVHITE_CARD_CATALOG)

if len(VIVHITE_CARD_CATALOG) != 61 or len(VIVHITE_CARD_IDS) != 61:
    raise RuntimeError("the approved Vivhite catalog must contain 61 unique cards")


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


def _dynamic_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def _card_dynamic_record(card: dict, name: str) -> dict | None:
    wanted = _dynamic_name(name)
    for collection_name in ("dynamic_values", "vars"):
        for item in card.get(collection_name) or ():
            if (isinstance(item, dict)
                    and _dynamic_name(item.get("name")) == wanted):
                return item
    return None


def card_dynamic_value(
        card: dict,
        name: str,
        default: int | float | None = None,
) -> float | None:
    """Read one current API dynamic value by exact variable name.

    Combat/selection payloads expose ``dynamic_values`` while ``/data/cards``
    exposes the same records as ``vars``. Exact-name matching is intentional:
    ``BlockPerMargin`` and ``SpellDamage`` are coefficients, not the card's
    immediate Block or Damage.
    """

    item = _card_dynamic_record(card, name)
    if item is not None:
        value = item.get("current_value", item.get("base_value"))
        if value is not None:
            try:
                return _finite_number(name, value)
            except (TypeError, ValueError):
                pass
    return None if default is None else _finite_number(name, default)


def _card_dynamic_preview_includes_modifier(card: dict, name: str) -> bool:
    """Whether the API preview already folded a combat modifier into a var."""

    item = _card_dynamic_record(card, name)
    if item is None:
        return False
    if bool(item.get("is_modified")):
        return True
    current = item.get("current_value")
    base = item.get("base_value")
    if current is None or base is None:
        return False
    try:
        return _finite_number(name, current) != _finite_number(name, base)
    except (TypeError, ValueError):
        return False


def character_power_amount(
        powers: list[dict] | tuple[dict, ...] | None,
        power_id: str,
) -> float:
    """Return the uncapped amount of one exposed custom Power.

    Single powers may have a null amount in an API payload; their presence is
    represented as one. Counter powers retain their full amount.
    """

    total = 0.0
    wanted = str(power_id).strip().upper()
    for power in powers or ():
        if not isinstance(power, dict):
            continue
        observed = str(power.get("power_id") or power.get("id") or "").upper()
        if observed != wanted:
            continue
        amount = power.get("amount")
        if amount is None:
            total += 1.0
            continue
        try:
            total += max(0.0, _finite_number("power amount", amount))
        except (TypeError, ValueError):
            continue
    return total


def vivhite_crimson_ritual_totals(
        strategy: CharacterStrategy,
        powers: list[dict] | tuple[dict, ...] | None,
) -> tuple[float, float]:
    """Return uncapped (total extra LifeCost, additive damage percent).

    Every ritual instance advances independently, but summing the exposed
    phase values is algebraically identical for this turn's Attack modifiers.
    Base and upgraded powers stay separate because they contribute 10% and 15%
    per stage respectively.  The ritual's 0, 1, 2, 3... extra-LifeCost sequence
    is an explicit balance exception and is therefore not doubled with printed
    card costs.
    """

    if strategy.profile_id != VIVHITE_PROFILE_ID:
        return 0.0, 0.0
    extra_life_cost = 0.0
    damage_percent = 0.0
    ritual_ids = {
        VIVHITE_CRIMSON_RITUAL_POWER_ID: 10.0,
        VIVHITE_CRIMSON_RITUAL_UPGRADED_POWER_ID: 15.0,
    }
    for power in powers or ():
        if not isinstance(power, dict):
            continue
        power_id = str(
            power.get("power_id") or power.get("id") or "").strip().upper()
        canonical_percent = ritual_ids.get(power_id)
        if canonical_percent is None:
            continue

        def power_field(name: str) -> float | None:
            normalized = _dynamic_name(name)
            for key, raw_value in power.items():
                if _dynamic_name(key) != normalized or raw_value is None:
                    continue
                try:
                    return max(0.0, _finite_number(name, raw_value))
                except (TypeError, ValueError):
                    continue
            value = card_dynamic_value(power, name)
            return None if value is None else max(0.0, value)

        # The production Power exposes Phase and DamagePercentPerPhase.  The
        # current Agent payload still commonly projects DisplayAmount as amount,
        # so retain that exact fallback without treating a phase-0 instance as 1.
        phase = power_field("Phase")
        if phase is None:
            raw_amount = power.get("amount")
            try:
                phase = (0.0 if raw_amount is None else
                         max(0.0, _finite_number("ritual phase", raw_amount)))
            except (TypeError, ValueError):
                phase = 0.0
        percent_per_phase = power_field("DamagePercentPerPhase")
        if percent_per_phase is None:
            percent_per_phase = canonical_percent
        extra_life_cost += phase
        damage_percent += phase * percent_per_phase
    return extra_life_cost, damage_percent


def solitary_crown_kill_heal(max_hp: int | float | None = None) -> int:
    """Solitary Crown healing for one death, with no custom ceiling."""

    observed_max_hp = (VIVHITE_BASE_MAX_HP if max_hp is None
                       else _finite_number("max hp", max_hp))
    if observed_max_hp <= 0:
        raise ValueError("max hp must be positive")
    return int(ceil(observed_max_hp * 0.20))


def character_card_has_terminal_life_cost_lock(
        strategy: CharacterStrategy,
        card: dict,
        *,
        current_hp: int | float,
        player_powers: list[dict] | tuple[dict, ...] | None = None,
) -> bool:
    """Whether Vivhite's observed cough-blood cost makes the card illegal.

    A transient combat payload may report every card as ``playable=false``
    while an animation closes the play endpoint.  That signal therefore cannot
    disable the existing bounded settle wait by itself.  Vivhite's life rule is
    different: after Margin pays one-for-one, a card that would leave less than
    one HP is deterministically illegal and must never be treated as latent.
    """

    if strategy.profile_id != VIVHITE_PROFILE_ID:
        return False
    life_cost = card_dynamic_value(card, "LifeCost", 0) or 0
    entry = strategy.card(
        str(card.get("card_id") or "").strip().upper().rstrip("+"))
    ritual_phase, _ritual_percent = vivhite_crimson_ritual_totals(
        strategy, player_powers)
    if (entry is not None and entry.card_type == "attack"
            and not _card_dynamic_preview_includes_modifier(card, "LifeCost")):
        life_cost += ritual_phase
    if life_cost <= 0:
        return False
    margin = character_power_amount(player_powers, VIVHITE_MARGIN_POWER_ID)
    effective_cost = max(0.0, life_cost - margin)
    return _finite_number("current hp", current_hp) - effective_cost < 1


def resolve_character_selection_mode(
        strategy: CharacterStrategy,
        *,
        kind: str,
        prompt: str,
        reward_pending: bool = False,
) -> str | None:
    """Resolve Vivhite's child-selection semantics from production prompts.

    The API does not expose the source card ID for a child selection, but it does
    preserve each card's localized ``selectionScreenPrompt``. Reward structure
    wins before prompt matching because an offered card's rules text may itself
    mention a discard pile.
    """

    if strategy.profile_id != VIVHITE_PROFILE_ID or reward_pending:
        return None
    blob = f"{kind} {prompt}".casefold()

    if (("消耗牌堆" in blob and "复制" in blob)
            or ("exhaust pile" in blob and "copy" in blob)):
        return SELECTION_RECOVER_COPY_BEST
    if (("本回合打出过" in blob and "复制" in blob)
            or ("played this turn" in blob and "copy" in blob)):
        return SELECTION_COPY_FREE_BEST
    if (("弃牌堆" in blob and "返回" in blob)
            or ("discard pile" in blob and "return" in blob)):
        return SELECTION_RECOVER_FREE_BEST
    if (("放到抽牌堆顶" in blob or "置于抽牌堆顶" in blob)
            or ("top of" in blob and "draw pile" in blob)):
        return SELECTION_TOPDECK_BEST
    if ("combat_hand" in blob
            and "弃牌堆" not in blob
            and "discard pile" not in blob
            and ("弃" in blob or "discard" in blob)):
        return SELECTION_DISCARD_WORST
    return None


def character_selection_value(
        strategy: CharacterStrategy,
        mode: str | None,
        card: dict,
        base_value: int | float,
) -> float:
    """Value a child-selection candidate without contaminating shared policy."""

    value = _finite_number("base selection value", base_value)
    if strategy.profile_id != VIVHITE_PROFILE_ID:
        return value
    try:
        energy = max(0.0, _finite_number(
            "selection energy cost", card.get("energy_cost", 0) or 0))
    except (TypeError, ValueError):
        energy = 0.0
    energy_value = energy * strategy.parameters.energy_weight
    if mode in (SELECTION_RECOVER_FREE_BEST, SELECTION_COPY_FREE_BEST):
        return value + energy_value
    if mode == SELECTION_RECOVER_COPY_BEST:
        return (2.0 * value) + energy_value
    return value


def resolve_character_card_numbers(
        strategy: CharacterStrategy,
        card: dict,
        fallback_damage: int | float,
        fallback_block: int | float,
        fallback_hits: int | float,
        *,
        energy: int | float | None = None,
        margin: int | float = 0,
        hand_count: int | None = None,
        player_powers: list[dict] | tuple[dict, ...] | None = None,
) -> tuple[int, int, int]:
    """Resolve actual pre-play numbers for a catalogued Vivhite card.

    This corrects coefficient vars that the shared substring parser cannot
    distinguish and expands state-dependent attacks/blocks from API-visible
    energy, hand size, and Margin. Non-Vivhite cards return the shared values
    byte-for-byte.
    """

    entry = strategy.card(str(card.get("card_id") or "").upper().rstrip("+"))
    if entry is None:
        return (int(fallback_damage), int(fallback_block),
                max(0, int(fallback_hits)))

    mechanics = entry.mechanics
    current_margin = max(0, int(_finite_number("margin", margin)))
    life_cost = max(0, int(card_dynamic_value(
        card, "LifeCost", mechanics.life_calculation_cost) or 0))

    if mechanics.base_damage > 0:
        damage = max(0, int(card_dynamic_value(
            card, "Damage", mechanics.base_damage) or 0))
    else:
        # SpellDamage and similar vars are delayed effects, not this card's hit.
        damage = 0

    if mechanics.base_block > 0:
        block = max(0, int(card_dynamic_value(
            card, "Block", mechanics.base_block) or 0))
    else:
        block = 0

    repeat = card_dynamic_value(card, "Repeat")
    if mechanics.energy == "X" or card.get("costs_x"):
        hits = max(0, int(_finite_number("X energy", energy or 0)))
    elif repeat is not None:
        hits = max(0, int(repeat))
    elif entry.stable_id == "RIEMANN_STAR_ARRAY" and hand_count is not None:
        # The played card leaves Hand before its OnPlay body counts the pile.
        hits = max(0, int(hand_count) - 1)
    elif mechanics.damage_hits > 0:
        hits = mechanics.damage_hits
    else:
        hits = max(0, int(fallback_hits))

    if entry.stable_id == "ASTRAL_MEASURE":
        damage += current_margin
    elif entry.stable_id == "CLOSED_PROJECTION":
        consumed = min(life_cost, current_margin)
        coefficient = max(0, int(card_dynamic_value(
            card, "BlockPerMargin", 5) or 0))
        block = consumed * coefficient
    elif entry.stable_id == "ISOPERIMETRIC_WARD":
        remaining = max(0, current_margin - life_cost)
        multiplier = max(0, int(card_dynamic_value(
            card, "Multiplier", 2) or 0))
        block += remaining * multiplier
    elif entry.stable_id == "CONSERVATION_FIRMAMENT":
        remaining = max(0, current_margin - life_cost)
        multiplier = max(0, int(card_dynamic_value(
            card, "Multiplier", 2) or 0))
        block = (remaining * 2) * multiplier

    _ritual_phase, ritual_damage_percent = vivhite_crimson_ritual_totals(
        strategy, player_powers)
    if (entry.card_type == "attack" and ritual_damage_percent > 0
            and not _card_dynamic_preview_includes_modifier(card, "Damage")):
        damage = floor(damage * (100.0 + ritual_damage_percent) / 100.0)

    return damage, block, hits


def character_build_synergy(
        strategy: CharacterStrategy,
        card: dict,
        deck: list[dict] | tuple[dict, ...] | None,
) -> tuple[float, str]:
    """Return profile-only draft synergy from immutable build tags."""

    candidate = strategy.card(
        str(card.get("card_id") or "").strip().upper().rstrip("+"))
    if candidate is None or strategy.profile_id != VIVHITE_PROFILE_ID:
        return 0.0, ""

    entries = []
    for owned in deck or ():
        entry = strategy.card(
            str(owned.get("card_id") or "").strip().upper().rstrip("+"))
        if entry is not None:
            entries.append(entry)

    tags = [entry.build_tags[0] for entry in entries]
    candidate_tag = candidate.build_tags[0]
    same_suit = tags.count(candidate_tag) if candidate_tag != HYBRID else 0
    score = 0.25 * same_suit
    reasons = [f"同系×{same_suit}"] if same_suit else []

    def has_effect(entry: CardCatalogEntry, fragment: str) -> bool:
        return any(fragment in effect for effect in entry.mechanics.effects)

    margin_sources = sum(
        1 for entry in entries if entry.mechanics.margin_gain > 0
        or has_effect(entry, "gain_2_margin_each_turn"))
    margin_payoffs = sum(
        1 for entry in entries if any(
            token in " ".join(entry.mechanics.effects)
            for token in ("per_margin", "current_margin", "double_current_margin")))
    dimension_cards = sum(
        1 for entry in entries if entry.mechanics.max_hp_growth > 0)
    extension_cards = sum(
        1 for entry in entries if entry.stable_id == "INFINITE_EXTENSION")

    death_engines = sum(
        1 for entry in entries if any(
            token in entry.mechanics.effects
            for token in ("triggers_on_any_enemy_death",
                          "increase_immediate_enemy_death_heal_percent")))
    lethal_attacks = sum(
        1 for entry in entries if entry.mechanics.lethal
        or (entry.mechanics.all_enemies and entry.mechanics.base_damage > 0))
    draw_sources = sum(
        1 for entry in entries if entry.mechanics.draw > 0
        or entry.mechanics.kill_draw > 0
        or any("draw" in effect for effect in entry.mechanics.effects))
    draw_engines = sum(
        1 for entry in entries if entry.stable_id in (
            "DYNAMIC_PROGRAMMING", "INFINITE_STAR_SEQUENCE"))

    drain_attacks = sum(
        1 for entry in entries
        if entry.card_type == "attack" and (
            entry.mechanics.drain_percent > 0
            or entry.mechanics.drain_percent_mode
            in ("per_margin_before_life_payment", "per_x")))
    drain_engines = sum(
        1 for entry in entries if (
            entry.mechanics.drain_percent_mode in (
                "global_combat", "temporary_this_turn", "next_attack_bonus",
                "global_growth_per_attack_that_drain_heals",
                "per_life_cost_prevented_by_margin", "per_drawn_skill")
            or entry.stable_id in (
                "COLOR_CONSERVATION", "CRIMSON_CONSERVATION_LAW",
                "INFINITE_CANVAS")))

    mechanics = candidate.mechanics
    if candidate_tag == CONSERVATION_GEOMETRY:
        if mechanics.margin_gain > 0 or has_effect(
                candidate, "gain_2_margin_each_turn"):
            score += 0.45 * margin_payoffs
            if margin_payoffs:
                reasons.append(f"余裕供给→兑现×{margin_payoffs}")
        if (mechanics.max_hp_growth > 0
                or has_effect(candidate, "current_margin")
                or has_effect(candidate, "double_current_margin")):
            score += 0.45 * margin_sources
            if margin_sources:
                reasons.append(f"余裕兑现←供给×{margin_sources}")
        if candidate.stable_id == "INFINITE_EXTENSION":
            score += 0.75 * dimension_cards
            if dimension_cards:
                reasons.append(f"增维牌×{dimension_cards}")
        elif mechanics.max_hp_growth > 0:
            score += 0.75 * extension_cards
            if extension_cards:
                reasons.append(f"无限延拓×{extension_cards}")
    elif candidate_tag == RECURSIVE_ASTRAL:
        candidate_is_death_engine = any(
            token in mechanics.effects
            for token in ("triggers_on_any_enemy_death",
                          "increase_immediate_enemy_death_heal_percent"))
        if candidate_is_death_engine:
            score += 0.55 * lethal_attacks
            if lethal_attacks:
                reasons.append(f"击杀源×{lethal_attacks}")
        if mechanics.lethal or (mechanics.all_enemies and mechanics.base_damage > 0):
            score += 0.55 * death_engines
            if death_engines:
                reasons.append(f"死亡引擎×{death_engines}")
        if mechanics.draw > 0 or mechanics.kill_draw > 0:
            score += 0.35 * draw_engines
            if draw_engines:
                reasons.append(f"过牌引擎×{draw_engines}")
        if candidate.stable_id in ("DYNAMIC_PROGRAMMING",
                                   "INFINITE_STAR_SEQUENCE"):
            score += 0.35 * draw_sources
            if draw_sources:
                reasons.append(f"过牌源×{draw_sources}")
    elif candidate_tag == CRIMSON_INTEGRAL:
        if candidate.card_type == "attack" and mechanics.drain_percent > 0:
            score += 0.55 * drain_engines
            if drain_engines:
                reasons.append(f"汲取引擎×{drain_engines}")
        if (mechanics.drain_percent_mode in (
                "global_combat", "temporary_this_turn", "next_attack_bonus",
                "global_growth_per_attack_that_drain_heals")
                or candidate.stable_id in (
                    "COLOR_CONSERVATION", "CRIMSON_CONSERVATION_LAW",
                    "INFINITE_CANVAS")):
            score += 0.55 * drain_attacks
            if drain_attacks:
                reasons.append(f"汲取攻击×{drain_attacks}")

    hybrid_count = tags.count(HYBRID)
    if candidate_tag == HYBRID:
        distinct_suits = len(set(tags) & {
            CONSERVATION_GEOMETRY, RECURSIVE_ASTRAL, CRIMSON_INTEGRAL})
        score += 0.5 * distinct_suits
        if distinct_suits:
            reasons.append(f"跨系桥接×{distinct_suits}")
    elif hybrid_count:
        score += 0.2 * hybrid_count
        reasons.append(f"混合桥×{hybrid_count}")

    if score == 0.0:
        return 0.0, ""
    return score, (
        f"VIVHITE_BUILD_SYNERGY={score:+.2f}[{candidate.stable_id};"
        f"{'/'.join(reasons)}]")


def drain_healing_from_actual_damage(
        actual_enemy_hp_damage: int | float,
        drain_percent: int | float,
) -> float:
    """Return one card-level Drain aggregate, rounded up once and uncapped."""

    damage = _actual_amount("actual_enemy_hp_damage", actual_enemy_hp_damage)
    percent = _actual_amount("drain_percent", drain_percent)
    return float(ceil(damage * percent / 100.0))


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


def _enemy_attack_outcome(
        damage: int,
        hits: int,
        enemy: dict,
) -> tuple[int, bool]:
    """Estimate enemy HP loss after its current Block, with overkill removed."""

    try:
        hp = max(0, int(enemy.get("current_hp") or 0))
        block = max(0, int(enemy.get("block") or 0))
    except (TypeError, ValueError):
        return 0, False
    remaining = hp
    for _ in range(max(0, hits)):
        segment = max(0, damage)
        absorbed = min(block, segment)
        block -= absorbed
        segment -= absorbed
        lost = min(remaining, segment)
        remaining -= lost
        if remaining <= 0:
            break
    return hp - remaining, hp > 0 and remaining <= 0


def _future_attack_damage(
        strategy: CharacterStrategy,
        cards: list[dict] | tuple[dict, ...] | None,
        *,
        energy: int,
        margin: int,
        target_count: int,
        exclude_card: dict | None = None,
        player_powers: list[dict] | tuple[dict, ...] | None = None,
) -> list[int]:
    """Nominal HP-damage opportunities used by persistent/turn Drain cards."""

    values = []
    excluded_index = (exclude_card or {}).get("index")
    excluded_instance = ((exclude_card or {}).get("instance_id")
                         or (exclude_card or {}).get("uuid"))
    for observed in cards or ():
        if not isinstance(observed, dict):
            continue
        if excluded_instance and excluded_instance in (
                observed.get("instance_id"), observed.get("uuid")):
            continue
        if (excluded_instance is None and excluded_index is not None
                and observed.get("index") == excluded_index
                and observed.get("card_id") == (exclude_card or {}).get("card_id")):
            continue
        entry = strategy.card(
            str(observed.get("card_id") or "").upper().rstrip("+"))
        if entry is None or entry.card_type != "attack":
            continue
        fallback_hits = max(1, entry.mechanics.damage_hits)
        damage, _block, hits = resolve_character_card_numbers(
            strategy,
            observed,
            entry.mechanics.base_damage,
            entry.mechanics.base_block,
            fallback_hits,
            energy=energy,
            margin=margin,
            hand_count=len(cards or ()),
            player_powers=player_powers,
        )
        multiplier = target_count if entry.mechanics.all_enemies else 1
        values.append(max(0, damage * hits * multiplier))
    return values


def _catalog_tactical_value(
        strategy: CharacterStrategy,
        card: dict,
        *,
        energy: int,
        margin: int,
        hand_count: int,
        target_count: int,
        player_powers: list[dict] | tuple[dict, ...] | None = None,
) -> tuple[float, float]:
    """Return a conservative immediate value and printed energy for one card.

    Recovery/copy parents must be worth reaching their child-selection screen.
    This intentionally counts only API/catalog-visible immediate damage, Block,
    draw, Margin, and energy; it does not recursively estimate another recovery
    engine or invent unavailable discard/exhaust pile contents.
    """

    entry = strategy.card(
        str(card.get("card_id") or "").strip().upper().rstrip("+"))
    if entry is None or entry.card_type == "ability":
        return 0.0, 0.0
    # A recovered X card made free has engine-specific X semantics that are not
    # exposed by this API. Exclude it instead of pretending it receives energy.
    if entry.mechanics.energy == "X" or card.get("costs_x"):
        return 0.0, 0.0

    mechanics = entry.mechanics
    damage, block, hits = resolve_character_card_numbers(
        strategy,
        card,
        mechanics.base_damage,
        mechanics.base_block,
        max(1, mechanics.damage_hits),
        energy=energy,
        margin=margin,
        hand_count=hand_count,
        player_powers=player_powers,
    )
    targets = max(1, target_count) if mechanics.all_enemies else 1
    value = float(damage * hits * targets) + (0.8 * block)
    value += score_draw(strategy.parameters, mechanics.draw)
    value += score_margin(strategy.parameters, mechanics.margin_gain)
    value += score_energy(strategy.parameters, mechanics.energy_gain)
    try:
        printed_energy = max(0.0, _finite_number(
            "recovered card energy",
            card.get("energy_cost", mechanics.energy) or 0))
    except (TypeError, ValueError):
        printed_energy = max(0.0, float(mechanics.energy))
    return max(0.0, value), printed_energy


def _recovery_copy_projection(
        strategy: CharacterStrategy,
        entry: CardCatalogEntry,
        card: dict,
        cards: list[dict] | tuple[dict, ...] | None,
        *,
        energy: int,
        margin: int,
        target_count: int,
        cards_played_this_turn: int | None,
        player_powers: list[dict] | tuple[dict, ...] | None = None,
) -> float:
    """Project the best eligible child choice for Vivhite recursion cards."""

    rules = {
        "MOBIUS_LOOP": ({"skill"}, 1, 1),
        "BACKTRACKING_SPELL": ({"attack"}, 1, 1),
        "EVENT_LOOP": ({"attack", "skill"}, 1, 1),
        "CONSERVED_RECURRENCE": (
            {"attack", "skill"}, 2, 2 if card.get("upgraded") else 1),
    }
    rule = rules.get(entry.stable_id)
    if rule is None:
        return 0.0
    if entry.stable_id == "EVENT_LOOP" \
            and cards_played_this_turn is not None \
            and cards_played_this_turn <= 0:
        return 0.0

    allowed_types, realized_copies, free_copies = rule
    choices = []
    for candidate in cards or ():
        if not isinstance(candidate, dict):
            continue
        candidate_entry = strategy.card(
            str(candidate.get("card_id") or "").strip().upper().rstrip("+"))
        if candidate_entry is None or candidate_entry.card_type not in allowed_types:
            continue
        if candidate_entry.stable_id in rules:
            continue
        immediate, printed_energy = _catalog_tactical_value(
            strategy,
            candidate,
            energy=energy,
            margin=margin,
            hand_count=len(cards or ()),
            target_count=target_count,
            player_powers=player_powers,
        )
        choices.append(
            (realized_copies * immediate)
            + (free_copies * printed_energy
               * strategy.parameters.energy_weight))
    return max(choices, default=0.0)


def _ritual_longline_projection(
        strategy: CharacterStrategy,
        entry: CardCatalogEntry,
        card: dict,
        cards: list[dict] | tuple[dict, ...] | None,
        *,
        energy: int,
        margin: int,
        target_count: int,
        enemies: list[dict] | tuple[dict, ...] | None,
        current_hp: int | float | None,
        max_hp: int | float | None,
) -> tuple[float, str]:
    """Uncapped long-fight projection for one newly played ritual instance."""

    if entry.stable_id != "VIVHITES_CRIMSON_TRANSFORMATION_RITUAL":
        return 0.0, ""

    attack_damage = 0.0
    attack_count = 0
    deck_size = 0
    for candidate in cards or ():
        if not isinstance(candidate, dict):
            continue
        deck_size += 1
        candidate_entry = strategy.card(
            str(candidate.get("card_id") or "").strip().upper().rstrip("+"))
        if candidate_entry is None or candidate_entry.card_type != "attack":
            continue
        mechanics = candidate_entry.mechanics
        damage, _block, hits = resolve_character_card_numbers(
            strategy,
            candidate,
            mechanics.base_damage,
            mechanics.base_block,
            max(1, mechanics.damage_hits),
            energy=energy,
            margin=margin,
            hand_count=len(cards or ()),
            player_powers=None,
        )
        multiplier = max(1, target_count) if mechanics.all_enemies else 1
        attack_damage += max(0.0, float(damage * hits * multiplier))
        attack_count += 1

    if deck_size > 0 and attack_count > 0:
        # Five draws is the native turn baseline, not a gameplay growth cap.
        expected_damage_per_turn = attack_damage * 5.0 / deck_size
        expected_attacks_per_turn = attack_count * 5.0 / deck_size
    elif deck_size > 0:
        expected_damage_per_turn = 0.0
        expected_attacks_per_turn = 0.0
    else:
        # No live deck context (for example /data/cards): use the 78-HP starter's
        # conservative two basic attacks per turn as the nominal baseline.
        expected_damage_per_turn = 20.0
        expected_attacks_per_turn = 2.0

    alive = [enemy for enemy in (enemies or ())
             if enemy.get("is_alive", True) and enemy.get("is_hittable", True)]
    if alive and expected_damage_per_turn > 0:
        hp_pool = sum(max(0.0, float(enemy.get("current_hp") or 0))
                      + max(0.0, float(enemy.get("block") or 0))
                      for enemy in alive)
        future_turns = max(1, int(ceil(hp_pool / expected_damage_per_turn)))
    else:
        future_turns = 3
    phase_sum = future_turns * (future_turns + 1) / 2.0

    default_percent = 15.0 if card.get("upgraded") else 10.0
    percent_per_phase = default_percent
    observed_percent = card_dynamic_value(card, "DamagePercentPerPhase")
    if observed_percent is not None:
        percent_per_phase = max(0.0, observed_percent)

    extra_damage = (expected_damage_per_turn
                    * percent_per_phase / 100.0 * phase_sum)
    future_life_cost = expected_attacks_per_turn * phase_sum
    if current_hp is not None and max_hp is not None:
        future_life_score = score_life_cost(
            strategy.parameters,
            future_life_cost,
            current_hp=current_hp,
            max_hp=max_hp,
        )
    else:
        future_life_score = (
            future_life_cost * strategy.parameters.life_cost_weight)
    value = extra_damage + future_life_score
    return value, (
        f"ritual-longline={value:g}/turns={future_turns}/"
        f"phase-sum={phase_sum:g}/rate={percent_per_phase:g}%")


def estimate_character_card(
        strategy: CharacterStrategy,
        card: dict,
        *,
        current_hp: int | float | None = None,
        max_hp: int | float | None = None,
        observed_target_count: int | None = None,
        enemies: list[dict] | tuple[dict, ...] | None = None,
        target_index: int | None = None,
        player_powers: list[dict] | tuple[dict, ...] | None = None,
        energy: int | float | None = None,
        hand_cards: list[dict] | tuple[dict, ...] | None = None,
        deck_cards: list[dict] | tuple[dict, ...] | None = None,
        cards_played_this_turn: int | None = None,
        reward_x_energy: int = 3,
) -> tuple[float, str]:
    """State-aware nominal estimate for one catalogued Vivhite card.

    API dynamic values override catalog bases. Observable Margin and Drain Powers,
    target HP/Block, current missing HP, lethal conditions, X energy, hand size,
    and persistent child effects all participate. Natural engine constraints such
    as current missing HP and remaining enemy HP are respected; no custom gameplay
    ceiling is introduced for Margin, Drain rate, healing, growth, draw, or energy.
    """

    entry = strategy.card(
        str(card.get("card_id") or "").strip().upper().rstrip("+"))
    if entry is None:
        return 0.0, ""

    mechanics = entry.mechanics
    parameters = strategy.parameters
    powers_observed = player_powers is not None
    margin_before = int(character_power_amount(
        player_powers, VIVHITE_MARGIN_POWER_ID)) if powers_observed else 0
    x_energy = max(0, int(_finite_number(
        "energy", reward_x_energy if energy is None else energy)))
    life_cost = max(0, int(card_dynamic_value(
        card, "LifeCost", mechanics.life_calculation_cost) or 0))
    ritual_life_cost, ritual_damage_percent = vivhite_crimson_ritual_totals(
        strategy, player_powers)
    if (entry.card_type == "attack" and ritual_life_cost > 0
            and not _card_dynamic_preview_includes_modifier(card, "LifeCost")):
        life_cost += int(ritual_life_cost)
    margin_consumed = min(life_cost, margin_before)
    hp_cost = life_cost - margin_consumed
    margin_spend_score = -score_margin(parameters, margin_consumed)

    hp_observed = current_hp is not None and max_hp is not None
    if hp_observed:
        hp_value = _finite_number("current_hp", current_hp)
        max_hp_value = _finite_number("max_hp", max_hp)
        if max_hp_value <= 0:
            raise ValueError("max_hp must be positive")
        life_score = score_life_cost(
            parameters,
            hp_cost,
            current_hp=hp_value,
            max_hp=max_hp_value,
        )
        hp_after_payment = max(0.0, hp_value - hp_cost)
        missing_after_payment = max(0.0, max_hp_value - hp_after_payment)
    else:
        hp_value = max_hp_value = None
        life_score = hp_cost * parameters.life_cost_weight
        missing_after_payment = None

    fallback_hits = max(1, mechanics.damage_hits)
    damage, _block, hits = resolve_character_card_numbers(
        strategy,
        card,
        mechanics.base_damage,
        mechanics.base_block,
        fallback_hits,
        energy=x_energy,
        margin=margin_before,
        hand_count=len(hand_cards or ()) if hand_cards is not None else None,
        player_powers=player_powers,
    )

    alive_enemies = [enemy for enemy in (enemies or ())
                     if enemy.get("is_alive", True)
                     and enemy.get("is_hittable", True)]
    target_count = 1
    if mechanics.all_enemies:
        if alive_enemies:
            target_count = len(alive_enemies)
        elif observed_target_count is not None:
            if observed_target_count < 0:
                raise ValueError("observed_target_count cannot be negative")
            target_count = observed_target_count

    actual_enemy_hp_damage = 0
    kill_count = 0
    if damage > 0 and hits > 0 and alive_enemies:
        if mechanics.all_enemies:
            attack_targets = alive_enemies
        else:
            selected = next((enemy for enemy in alive_enemies
                             if enemy.get("index") == target_index), None)
            attack_targets = [selected] if selected is not None else []
        for enemy in attack_targets:
            hp_loss, killed = _enemy_attack_outcome(damage, hits, enemy)
            actual_enemy_hp_damage += hp_loss
            kill_count += int(killed)
    elif damage > 0 and hits > 0:
        actual_enemy_hp_damage = damage * hits * target_count

    immediate_margin = float(mechanics.margin_gain)
    if mechanics.margin_gain > 0:
        immediate_margin = float(card_dynamic_value(
            card, "Margin", mechanics.margin_gain) or 0)
    if entry.stable_id == "INVARIANT" and character_power_amount(
            player_powers, VIVHITE_DIMENSIONALITY_POWER_ID) <= 0:
        immediate_margin = 0.0
    if entry.stable_id == "CONSERVATION_FIRMAMENT":
        immediate_margin += max(0, margin_before - life_cost)
    if entry.stable_id == "LIFE_MANIFOLD":
        immediate_margin += max(0.0, card_dynamic_value(card, "Margin", 2) or 0)

    base_draw = float(mechanics.draw)
    base_growth = float(mechanics.growth)
    extra_damage_value = 0.0
    if mechanics.draw > 0:
        base_draw = max(0.0, card_dynamic_value(
            card, "Cards", mechanics.draw) or 0)
    if "discard_2" in mechanics.effects:
        base_draw = max(0.0, base_draw - 2.0)
    elif "discard_1" in mechanics.effects:
        base_draw = max(0.0, base_draw - 1.0)
    if entry.stable_id == "VIVHITE_TRANSFORMATION":
        def transformation_power(*names: str) -> float:
            for name in names:
                value = card_dynamic_value(card, name)
                if value is not None:
                    return max(0.0, value)
            return 1.0

        # ModCardVars.Power names have appeared in both short and model-name
        # forms across API builds; exact matching within each known spelling still
        # prevents unrelated coefficient vars from leaking into the estimate.
        base_growth = (
            transformation_power("Strength", "StrengthPower")
            + transformation_power("Dexterity", "DexterityPower"))
    elif entry.stable_id == "DYNAMIC_PROGRAMMING":
        base_growth = max(0.0, card_dynamic_value(card, "Calculation", 2) or 0)
    elif entry.stable_id == "INFINITE_CANVAS":
        base_growth = max(0.0, card_dynamic_value(
            card, "DrainGrowth", mechanics.growth) or 0)
    elif entry.stable_id == "LAW_OF_CONSERVATION":
        base_growth = max(0.0, card_dynamic_value(card, "Power", 1) or 0)
    elif entry.stable_id == "UNIFIED_FIELD_THEORY":
        base_growth = max(0.0, card_dynamic_value(
            card, "DrainPerMargin", mechanics.drain_percent) or 0)

    observed_cards = deck_cards if deck_cards is not None else hand_cards
    attack_entries = []
    for observed in observed_cards or ():
        owned_entry = strategy.card(
            str(observed.get("card_id") or "").upper().rstrip("+"))
        if owned_entry is not None:
            attack_entries.append(owned_entry)
    sequence_drain_rate = 0.0
    if entry.stable_id == "CHROMATIC_SEQUENCE":
        draw_count = max(0.0, card_dynamic_value(
            card, "Cards", mechanics.draw) or 0)
        if attack_entries:
            attacks = sum(1 for owned in attack_entries
                          if owned.card_type == "attack")
            skills = sum(1 for owned in attack_entries
                         if owned.card_type == "skill")
            powers = sum(1 for owned in attack_entries
                         if owned.card_type == "ability")
            denominator = len(attack_entries)
            immediate_margin += (draw_count * (attacks + powers) / denominator
                                 * max(0.0, card_dynamic_value(
                                     card, "MarginPerAttack", 1) or 0))
            sequence_drain_rate = (
                draw_count * (skills + powers) / denominator
                * max(0.0, card_dynamic_value(
                    card, "DrainPerSkill", mechanics.drain_percent) or 0))
    if entry.stable_id == "DIVIDE_AND_CONQUER_CIRCLE" and attack_entries:
        draw_count = max(0.0, card_dynamic_value(
            card, "Cards", mechanics.draw) or 0)
        attack_ratio = (sum(1 for owned in attack_entries
                            if owned.card_type == "attack")
                        / len(attack_entries))
        extra_damage_value = (draw_count * attack_ratio
                              * max(0.0, card_dynamic_value(
                                  card, "SpellDamage", 4) or 0))
    if entry.stable_id == "INFINITE_STAR_SEQUENCE" \
            and cards_played_this_turn is not None:
        sequence_draw = 2 * max(0, int(cards_played_this_turn))
        if card.get("upgraded"):
            sequence_draw += 2
        base_draw += sequence_draw
        immediate_margin += sequence_draw

    recovery_projection = _recovery_copy_projection(
        strategy,
        entry,
        card,
        observed_cards,
        energy=x_energy,
        margin=margin_before,
        target_count=target_count,
        cards_played_this_turn=cards_played_this_turn,
        player_powers=player_powers,
    )
    vulnerable_projection = 0.0
    if any(effect in mechanics.effects for effect in (
            "apply_2_vulnerable", "apply_2_vulnerable_to_all_enemies")):
        vulnerable = max(0.0, card_dynamic_value(
            card, "VulnerablePower", 2) or 0)
        applies_to_all = (
            "apply_2_vulnerable_to_all_enemies" in mechanics.effects)
        if applies_to_all:
            if alive_enemies:
                vulnerable_targets = len(alive_enemies)
            elif observed_target_count is not None:
                vulnerable_targets = max(0, observed_target_count)
            else:
                vulnerable_targets = 1
        else:
            vulnerable_targets = 1
        vulnerable_projection = score_growth(
            parameters, vulnerable * vulnerable_targets)

    ritual_projection, ritual_note = _ritual_longline_projection(
        strategy,
        entry,
        card,
        observed_cards,
        energy=x_energy,
        margin=margin_before,
        target_count=target_count,
        enemies=alive_enemies,
        current_hp=current_hp,
        max_hp=max_hp,
    )

    global_drain = character_power_amount(
        player_powers, VIVHITE_DRAIN_POWER_ID)
    turn_drain = character_power_amount(
        player_powers, VIVHITE_TURN_DRAIN_POWER_ID)
    prevented_drain = margin_consumed * (
        4.0 * character_power_amount(
            player_powers, "VIVHITE_POWER_UNIFIED_FIELD_THEORY_POWER")
        + 4.0 * character_power_amount(
            player_powers,
            "VIVHITE_POWER_UNIFIED_FIELD_THEORY_UPGRADED_POWER"))
    card_drain = 0.0
    if entry.card_type == "attack":
        if mechanics.drain_percent_mode == "per_x":
            card_drain = max(0.0, card_dynamic_value(
                card, "DrainPerX", mechanics.drain_percent) or 0) * x_energy
        elif mechanics.drain_percent_mode == "per_margin_before_life_payment":
            card_drain = max(0.0, card_dynamic_value(
                card, "DrainPerMargin", mechanics.drain_percent) or 0) * margin_before
        elif mechanics.drain_percent_mode == "flat":
            card_drain = max(0.0, card_dynamic_value(
                card, "Drain", mechanics.drain_percent) or 0)

    total_drain = card_drain + global_drain + turn_drain + prevented_drain
    drain_requested = ceil(actual_enemy_hp_damage * total_drain / 100.0)
    drain_projection = False
    if (entry.card_type != "attack"
            and (mechanics.drain_percent_mode in (
                "global_combat", "temporary_this_turn", "next_attack_bonus")
                 or sequence_drain_rate > 0)):
        engine_rate = (sequence_drain_rate if sequence_drain_rate > 0 else
                       max(0.0, card_dynamic_value(
                           card, "Drain", mechanics.drain_percent) or 0))
        future_cards = (deck_cards if mechanics.drain_percent_mode == "global_combat"
                        and deck_cards is not None else hand_cards or deck_cards)
        opportunities = _future_attack_damage(
            strategy,
            future_cards,
            energy=x_energy,
            margin=max(0, margin_before - life_cost),
            target_count=max(1, target_count),
            exclude_card=card,
            player_powers=player_powers,
        )
        future_damage = (max(opportunities, default=0)
                         if mechanics.drain_percent_mode == "next_attack_bonus"
                         else sum(opportunities))
        drain_requested = ceil(future_damage * engine_rate / 100.0)
        total_drain = engine_rate
        drain_projection = True

    if missing_after_payment is None:
        drain_healed = float(drain_requested)
        drain_excess = 0.0
    else:
        drain_healed = min(float(drain_requested), missing_after_payment)
        drain_excess = max(0.0, float(drain_requested) - drain_healed)
    closed_manifold = character_power_amount(
        player_powers, "VIVHITE_POWER_CLOSED_MANIFOLD_POWER") > 0
    if closed_manifold:
        immediate_margin += drain_excess

    if entry.stable_id == "CHROMATIC_LIMIT" and drain_healed > 0:
        healing_per_margin = max(1.0, card_dynamic_value(
            card, "HealingPerMargin", 10) or 10)
        immediate_margin += floor(drain_healed / healing_per_margin)

    conversion_block = margin_consumed * character_power_amount(
        player_powers, "VIVHITE_POWER_LAW_OF_CONSERVATION_POWER")
    conversion_growth = prevented_drain
    if drain_healed > 0:
        conversion_block += drain_healed * character_power_amount(
            player_powers, "VIVHITE_POWER_COLOR_CONSERVATION_POWER")
        normal_law = character_power_amount(
            player_powers, "VIVHITE_POWER_CRIMSON_CONSERVATION_LAW_POWER")
        upgraded_law = character_power_amount(
            player_powers,
            "VIVHITE_POWER_CRIMSON_CONSERVATION_LAW_UPGRADED_POWER")
        conversion_growth += ((floor(drain_healed / 5.0) * normal_law)
                              + (floor(drain_healed / 4.0) * upgraded_law))
        conversion_growth += (
            4.0 * character_power_amount(
                player_powers, "VIVHITE_POWER_INFINITE_CANVAS_POWER")
            + 4.0 * character_power_amount(
                player_powers, "VIVHITE_POWER_INFINITE_CANVAS_UPGRADED_POWER"))
        immediate_margin += (
            floor(drain_healed / 3.0) * character_power_amount(
                player_powers, "VIVHITE_POWER_UNIFIED_FIELD_THEORY_POWER")
            + floor(drain_healed / 2.0) * character_power_amount(
                player_powers,
                "VIVHITE_POWER_UNIFIED_FIELD_THEORY_UPGRADED_POWER"))

    lethal_kills = kill_count if mechanics.lethal else 0
    future_deaths = 0
    if any(effect in mechanics.effects for effect in (
            "triggers_on_any_enemy_death",
            "increase_immediate_enemy_death_heal_percent")):
        if alive_enemies:
            future_deaths = len(alive_enemies)
        elif observed_target_count is not None:
            future_deaths = max(0, observed_target_count)
        else:
            future_deaths = 1

    card_kill_heal = float(mechanics.kill_heal)
    if mechanics.kill_heal > 0:
        card_kill_heal = max(0.0, card_dynamic_value(
            card, "Heal", mechanics.kill_heal) or 0)
    card_death_heal_percent = float(mechanics.death_heal_percent)
    if mechanics.death_heal_percent > 0:
        card_death_heal_percent = max(0.0, card_dynamic_value(
            card, "Heal", mechanics.death_heal_percent) or 0)
    card_kill_draw = float(mechanics.kill_draw)
    if mechanics.kill_draw > 0:
        card_kill_draw = max(0.0, card_dynamic_value(
            card, "Cards", mechanics.kill_draw) or 0)

    crown_heal_per_kill = solitary_crown_kill_heal(
        max_hp_value if hp_observed else None)
    optimal_algorithm_stacks = character_power_amount(
        player_powers, "VIVHITE_POWER_OPTIMAL_ALGORITHM_POWER")
    base_death_heal_per_kill = (
        crown_heal_per_kill + 3.0 * optimal_algorithm_stacks)
    active_death_heal_percent = character_power_amount(
        player_powers, "VIVHITE_POWER_INDUCTIVE_CIRCLE_POWER")
    active_death_heal_bonus = ceil(
        base_death_heal_per_kill * active_death_heal_percent / 100.0)
    projected_base_death_heal_per_kill = (
        base_death_heal_per_kill
        + (card_kill_heal
           if entry.stable_id == "OPTIMAL_ALGORITHM" else 0.0))
    card_death_heal_bonus = (
        ceil(projected_base_death_heal_per_kill
             * (active_death_heal_percent + card_death_heal_percent) / 100.0)
        - active_death_heal_bonus)
    kill_heal_requested = (
        card_kill_heal * lethal_kills
        + (card_kill_heal + card_death_heal_bonus) * future_deaths
        + (base_death_heal_per_kill + active_death_heal_bonus) * kill_count)
    kill_draw = (card_kill_draw * lethal_kills
                 + card_kill_draw * future_deaths)
    kill_energy = (mechanics.kill_energy * lethal_kills
                   + mechanics.kill_energy * future_deaths)

    if kill_count > 0:
        kill_draw += kill_count * (
            2.0 * character_power_amount(
                player_powers, "VIVHITE_POWER_ASTRAL_PURSUIT_POWER")
            + 4.0 * character_power_amount(
                player_powers, "VIVHITE_POWER_OPTIMAL_ALGORITHM_POWER"))
        kill_energy += kill_count * character_power_amount(
            player_powers, "VIVHITE_POWER_OPTIMAL_ALGORITHM_POWER")
        immediate_margin += kill_count * character_power_amount(
            player_powers, "VIVHITE_POWER_ASTRAL_PURSUIT_MARGIN_POWER")
    if entry.stable_id == "ASTRAL_PURSUIT" and card.get("upgraded"):
        immediate_margin += future_deaths

    missing_after_drain = (None if missing_after_payment is None
                           else max(0.0, missing_after_payment - drain_healed))
    if missing_after_drain is None:
        kill_healed = float(kill_heal_requested)
        kill_excess = 0.0
    else:
        kill_healed = min(float(kill_heal_requested), missing_after_drain)
        kill_excess = max(0.0, float(kill_heal_requested) - kill_healed)
    if closed_manifold:
        immediate_margin += kill_excess

    dimension = float(mechanics.max_hp_growth)
    if mechanics.max_hp_growth > 0:
        dimension = max(0.0, card_dynamic_value(
            card, "DimensionUp", mechanics.max_hp_growth) or 0)
    applications = lethal_kills if mechanics.lethal else int(dimension > 0)
    extension = character_power_amount(
        player_powers, VIVHITE_EXTENSION_POWER_ID)
    permanent_growth = applications * (dimension + (extension if dimension > 0 else 0))

    estimate = sum((
        life_score,
        margin_spend_score,
        score_margin(parameters, immediate_margin),
        score_drain_healing(
            parameters, drain_healed, drain_percent=total_drain),
        score_permanent_max_hp(parameters, permanent_growth),
        score_kill_healing(parameters, kill_healed),
        score_draw(parameters, base_draw + kill_draw),
        score_energy(parameters, mechanics.energy_gain + kill_energy),
        score_growth(parameters, base_growth + conversion_growth),
        conversion_block,
        extra_damage_value,
        recovery_projection,
        vulnerable_projection,
        ritual_projection,
    ))

    context = "live" if (hp_observed or powers_observed or alive_enemies) else "nominal"
    notes = [
        f"dynamic={'yes' if card.get('dynamic_values') or card.get('vars') else 'no'}",
        f"hp-cost={hp_cost}",
        f"margin={margin_before}/spent={margin_consumed}",
        f"drain={total_drain:g}%/{drain_healed:g}hp",
        f"kills={kill_count}/lethal={lethal_kills}",
        f"crown={crown_heal_per_kill}/kill",
        f"dimension={permanent_growth:g}",
    ]
    if ritual_life_cost or ritual_damage_percent:
        notes.append(
            f"ritual-phase={ritual_life_cost:g}/damage={ritual_damage_percent:g}%")
    if ritual_note:
        notes.append(ritual_note)
    if drain_projection:
        notes.append("drain-projected-from-observed-cards")
    if recovery_projection:
        notes.append(f"recovery-copy={recovery_projection:g}")
    if vulnerable_projection:
        notes.append(f"vulnerable={vulnerable_projection:g}")
    if entry.stable_id == "DYNAMIC_PROGRAMMING" and powers_observed:
        notes.append("calculation-internal-not-exposed-by-api")
    return estimate, (
        f"VIVHITE_{context.upper()}_ESTIMATE={estimate:+.2f}"
        f"[{entry.stable_id};{';'.join(notes)}]")


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
    "SELECTION_COPY_FREE_BEST",
    "SELECTION_DISCARD_WORST",
    "SELECTION_RECOVER_COPY_BEST",
    "SELECTION_RECOVER_FREE_BEST",
    "SELECTION_TOPDECK_BEST",
    "VIVHITE_CARD_CATALOG",
    "VIVHITE_CARD_IDS",
    "VIVHITE_BASE_MAX_HP",
    "VIVHITE_CHARACTER_ID",
    "VIVHITE_CRIMSON_RITUAL_POWER_ID",
    "VIVHITE_CRIMSON_RITUAL_UPGRADED_POWER_ID",
    "VIVHITE_PARAMETERS",
    "VIVHITE_PROFILE_ID",
    "VIVHITE_STARTING_RELIC_NAME_EN",
    "VIVHITE_STARTING_RELIC_NAME_ZH",
    "VIVHITE_STRATEGY",
    "CardCatalogEntry",
    "CardMechanics",
    "CharacterStrategy",
    "CharacterStrategyParameters",
    "card_dynamic_value",
    "character_build_synergy",
    "character_card_has_terminal_life_cost_lock",
    "character_power_amount",
    "character_selection_value",
    "drain_healing_from_actual_damage",
    "estimate_character_card",
    "resolve_character_card_numbers",
    "resolve_character_selection_mode",
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
    "solitary_crown_kill_heal",
    "vivhite_crimson_ritual_totals",
]
