"""Character strategy parameters, catalog, and uncapped scoring regressions."""
from __future__ import annotations

from collections import Counter
from dataclasses import FrozenInstanceError
from math import isfinite
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

from character_strategy import (  # noqa: E402
    BUILD_TAGS,
    CONSERVATION_GEOMETRY,
    CRIMSON_INTEGRAL,
    HYBRID,
    IRONCLAD_CHARACTER_ID,
    IRONCLAD_PARAMETERS,
    IRONCLAD_STRATEGY,
    RECURSIVE_ASTRAL,
    SELECTION_COPY_FREE_BEST,
    SELECTION_DISCARD_WORST,
    SELECTION_RECOVER_COPY_BEST,
    SELECTION_RECOVER_FREE_BEST,
    SELECTION_TOPDECK_BEST,
    VIVHITE_CARD_CATALOG,
    VIVHITE_CARD_IDS,
    VIVHITE_CHARACTER_ID,
    VIVHITE_CRIMSON_RITUAL_POWER_ID,
    VIVHITE_CRIMSON_RITUAL_UPGRADED_POWER_ID,
    VIVHITE_PARAMETERS,
    VIVHITE_STARTING_RELIC_NAME_EN,
    VIVHITE_STARTING_RELIC_NAME_ZH,
    VIVHITE_STRATEGY,
    CardMechanics,
    card_dynamic_value,
    character_build_synergy,
    character_card_has_terminal_life_cost_lock,
    estimate_character_card,
    drain_healing_from_actual_damage,
    resolve_character_card_numbers,
    resolve_character_selection_mode,
    resolve_character_strategy,
    score_drain_healing,
    score_draw,
    score_growth,
    score_kill_healing,
    score_life_cost,
    score_margin,
    score_permanent_max_hp,
    score_realized_mechanics,
    solitary_crown_kill_heal,
    vivhite_crimson_ritual_totals,
)
from character_profiles import ProfileStore  # noqa: E402
from knowledge import Knowledge  # noqa: E402
from policy import Policy  # noqa: E402


APPROVED_IDS = {
    # Basics.
    "VIVHITE_CARD_LUMINOUS_PROJECTION",
    "VIVHITE_CARD_CLOSED_DOMAIN_MAPPING",
    "VIVHITE_CARD_VIVHITE_TRANSFORMATION",
    # Conservation Geometry.
    "VIVHITE_CARD_AXIOM_RING",
    "VIVHITE_CARD_CLOSED_PROJECTION",
    "VIVHITE_CARD_TANGENT_STARLIGHT",
    "VIVHITE_CARD_OPEN_SET_SHELTER",
    "VIVHITE_CARD_LOCAL_HOMEOMORPHISM",
    "VIVHITE_CARD_SCALE_TRANSFORMATION",
    "VIVHITE_CARD_ISOPERIMETRIC_WARD",
    "VIVHITE_CARD_TOPOLOGICAL_GROWTH",
    "VIVHITE_CARD_LAW_OF_CONSERVATION",
    "VIVHITE_CARD_LIFE_MANIFOLD",
    "VIVHITE_CARD_MOBIUS_LOOP",
    "VIVHITE_CARD_INVARIANT",
    "VIVHITE_CARD_GEODESIC_VEIL",
    "VIVHITE_CARD_CLOSED_MANIFOLD",
    "VIVHITE_CARD_AXIOM_OF_LIFE",
    "VIVHITE_CARD_INFINITE_EXTENSION",
    "VIVHITE_CARD_CONSERVATION_FIRMAMENT",
    # Recursive Astral.
    "VIVHITE_CARD_RECURRENT_STARLIGHT",
    "VIVHITE_CARD_TERMINATION_CONDITION",
    "VIVHITE_CARD_PARALLEL_STARFALL",
    "VIVHITE_CARD_ASTRAL_SEARCH",
    "VIVHITE_CARD_HEURISTIC_SHIELD",
    "VIVHITE_CARD_SUCCESSOR_FORMULA",
    "VIVHITE_CARD_BACKTRACKING_SPELL",
    "VIVHITE_CARD_CONVERGENCE_VERDICT",
    "VIVHITE_CARD_DIVIDE_AND_CONQUER_CIRCLE",
    "VIVHITE_CARD_ASTRAL_PURSUIT",
    "VIVHITE_CARD_PREFETCH_FUTURE",
    "VIVHITE_CARD_INDUCTIVE_CIRCLE",
    "VIVHITE_CARD_EVENT_LOOP",
    "VIVHITE_CARD_PROOF_OF_TERMINATION",
    "VIVHITE_CARD_DYNAMIC_PROGRAMMING",
    "VIVHITE_CARD_INFINITE_STAR_SEQUENCE",
    "VIVHITE_CARD_OPTIMAL_ALGORITHM",
    # Crimson Integral.
    "VIVHITE_CARD_CRIMSON_AREA",
    "VIVHITE_CARD_TRICHROMATIC_WALTZ",
    "VIVHITE_CARD_COMPOSITE_COLOR_WHEEL",
    "VIVHITE_CARD_DIFFERENTIAL_SAMPLING",
    "VIVHITE_CARD_CHIAROSCURO",
    "VIVHITE_CARD_NEGATIVE_SPACE",
    "VIVHITE_CARD_SPECTRAL_INTEGRAL",
    "VIVHITE_CARD_GOLDEN_COMPOSITION",
    "VIVHITE_CARD_RIEMANN_STAR_ARRAY",
    "VIVHITE_CARD_CHROMATIC_TRANSITION",
    "VIVHITE_CARD_COLOR_CONSERVATION",
    "VIVHITE_CARD_COMPOSITE_COLOR_FIELD",
    "VIVHITE_CARD_COMPLEMENTARY_AFTERIMAGE",
    "VIVHITE_CARD_DEFINITE_CRIMSON_INTEGRAL",
    "VIVHITE_CARD_CRIMSON_CONSERVATION_LAW",
    "VIVHITE_CARD_INFINITE_CANVAS",
    "VIVHITE_CARD_PERFECT_SYNTHESIS",
    # Cross-suit.
    "VIVHITE_CARD_GOLDEN_RATIO",
    "VIVHITE_CARD_ASTRAL_MEASURE",
    "VIVHITE_CARD_CHROMATIC_SEQUENCE",
    "VIVHITE_CARD_UNIFIED_FIELD_THEORY",
    "VIVHITE_CARD_CONSERVED_RECURRENCE",
    "VIVHITE_CARD_CHROMATIC_LIMIT",
    "VIVHITE_CARD_VIVHITES_CRIMSON_TRANSFORMATION_RITUAL",
}

CROSS_SUIT_IDS = {
    "VIVHITE_CARD_GOLDEN_RATIO",
    "VIVHITE_CARD_ASTRAL_MEASURE",
    "VIVHITE_CARD_CHROMATIC_SEQUENCE",
    "VIVHITE_CARD_UNIFIED_FIELD_THEORY",
    "VIVHITE_CARD_CONSERVED_RECURRENCE",
    "VIVHITE_CARD_CHROMATIC_LIMIT",
    "VIVHITE_CARD_VIVHITES_CRIMSON_TRANSFORMATION_RITUAL",
}


class CharacterStrategyCatalogTests(unittest.TestCase):
    def test_catalog_is_exactly_the_approved_61_ids(self) -> None:
        self.assertEqual(len(APPROVED_IDS), 61)
        self.assertEqual(len(VIVHITE_CARD_CATALOG), 61)
        self.assertEqual(VIVHITE_CARD_IDS, APPROVED_IDS)
        self.assertEqual(
            len({entry.stable_id for entry in VIVHITE_CARD_CATALOG}), 61)

    def test_exact_rarity_distribution_and_required_fields(self) -> None:
        self.assertEqual(
            Counter(entry.rarity for entry in VIVHITE_CARD_CATALOG),
            {"basic": 3, "common": 18, "uncommon": 24, "rare": 16},
        )
        for entry in VIVHITE_CARD_CATALOG:
            self.assertIn(entry.card_type, {"attack", "skill", "ability"})
            self.assertTrue(entry.name_en)
            self.assertTrue(entry.name_zh)
            self.assertTrue(set(entry.build_tags) <= BUILD_TAGS)
            self.assertTrue(entry.card_id.endswith(entry.stable_id))
            self.assertIsInstance(entry.mechanics, CardMechanics)

    def test_all_printed_life_costs_match_approved_balance_table(self) -> None:
        expected_nonzero = {
            "LUMINOUS_PROJECTION": 2,
            "CLOSED_DOMAIN_MAPPING": 2,
            "VIVHITE_TRANSFORMATION": 4,
            "CLOSED_PROJECTION": 4,
            "TANGENT_STARLIGHT": 2,
            "OPEN_SET_SHELTER": 2,
            "LOCAL_HOMEOMORPHISM": 2,
            "SCALE_TRANSFORMATION": 4,
            "ISOPERIMETRIC_WARD": 4,
            "TOPOLOGICAL_GROWTH": 8,
            "LAW_OF_CONSERVATION": 6,
            "LIFE_MANIFOLD": 8,
            "MOBIUS_LOOP": 4,
            "INVARIANT": 2,
            "GEODESIC_VEIL": 6,
            "CLOSED_MANIFOLD": 10,
            "AXIOM_OF_LIFE": 10,
            "INFINITE_EXTENSION": 12,
            "CONSERVATION_FIRMAMENT": 10,
            "RECURRENT_STARLIGHT": 4,
            "TERMINATION_CONDITION": 4,
            "PARALLEL_STARFALL": 6,
            "ASTRAL_SEARCH": 2,
            "HEURISTIC_SHIELD": 2,
            "SUCCESSOR_FORMULA": 2,
            "BACKTRACKING_SPELL": 6,
            "CONVERGENCE_VERDICT": 8,
            "DIVIDE_AND_CONQUER_CIRCLE": 4,
            "ASTRAL_PURSUIT": 4,
            "PREFETCH_FUTURE": 4,
            "INDUCTIVE_CIRCLE": 8,
            "EVENT_LOOP": 6,
            "PROOF_OF_TERMINATION": 10,
            "DYNAMIC_PROGRAMMING": 10,
            "INFINITE_STAR_SEQUENCE": 8,
            "OPTIMAL_ALGORITHM": 14,
            "CRIMSON_AREA": 4,
            "TRICHROMATIC_WALTZ": 6,
            "COMPOSITE_COLOR_WHEEL": 6,
            "DIFFERENTIAL_SAMPLING": 2,
            "CHIAROSCURO": 4,
            "NEGATIVE_SPACE": 2,
            "SPECTRAL_INTEGRAL": 6,
            "GOLDEN_COMPOSITION": 8,
            "RIEMANN_STAR_ARRAY": 6,
            "CHROMATIC_TRANSITION": 4,
            "COLOR_CONSERVATION": 4,
            "COMPOSITE_COLOR_FIELD": 8,
            "COMPLEMENTARY_AFTERIMAGE": 6,
            "DEFINITE_CRIMSON_INTEGRAL": 12,
            "CRIMSON_CONSERVATION_LAW": 10,
            "INFINITE_CANVAS": 16,
            "PERFECT_SYNTHESIS": 16,
            "GOLDEN_RATIO": 4,
            "CHROMATIC_SEQUENCE": 4,
            "UNIFIED_FIELD_THEORY": 14,
            "CONSERVED_RECURRENCE": 10,
            "CHROMATIC_LIMIT": 8,
        }
        actual_nonzero = {
            entry.stable_id: entry.mechanics.life_calculation_cost
            for entry in VIVHITE_CARD_CATALOG
            if entry.mechanics.life_calculation_cost
        }
        self.assertEqual(actual_nonzero, expected_nonzero)
        self.assertEqual(
            {
                entry.stable_id
                for entry in VIVHITE_CARD_CATALOG
                if entry.mechanics.life_calculation_cost == 0
            },
            {
                "AXIOM_RING",
                "ASTRAL_MEASURE",
                "VIVHITES_CRIMSON_TRANSFORMATION_RITUAL",
            },
        )

        # Explicit exception: ritual phases remain 0, 1, 2, 3... rather than
        # inheriting the printed-card x2 multiplier.
        self.assertEqual(
            vivhite_crimson_ritual_totals(
                VIVHITE_STRATEGY,
                [{"power_id": VIVHITE_CRIMSON_RITUAL_POWER_ID, "amount": 3}],
            )[0],
            3.0,
        )

    def test_all_card_drain_values_are_doubled_from_current_integers(self) -> None:
        expected_nonzero = {
            "CRIMSON_AREA": 16,
            "TRICHROMATIC_WALTZ": 12,
            "COMPOSITE_COLOR_WHEEL": 20,
            "DIFFERENTIAL_SAMPLING": 8,
            "CHIAROSCURO": 20,
            "SPECTRAL_INTEGRAL": 8,
            "GOLDEN_COMPOSITION": 20,
            "RIEMANN_STAR_ARRAY": 12,
            "CHROMATIC_TRANSITION": 8,
            "COMPOSITE_COLOR_FIELD": 8,
            "COMPLEMENTARY_AFTERIMAGE": 16,
            "DEFINITE_CRIMSON_INTEGRAL": 48,
            "INFINITE_CANVAS": 4,
            "PERFECT_SYNTHESIS": 32,
            "GOLDEN_RATIO": 12,
            "ASTRAL_MEASURE": 4,
            "CHROMATIC_SEQUENCE": 4,
            "UNIFIED_FIELD_THEORY": 4,
            "CHROMATIC_LIMIT": 12,
        }
        actual_nonzero = {
            entry.stable_id: entry.mechanics.drain_percent
            for entry in VIVHITE_CARD_CATALOG
            if entry.mechanics.drain_percent
        }
        self.assertEqual(actual_nonzero, expected_nonzero)
        self.assertTrue(all(
            isinstance(entry.mechanics.drain_percent, int)
            and not isinstance(entry.mechanics.drain_percent, bool)
            for entry in VIVHITE_CARD_CATALOG
        ))
        self.assertEqual(
            VIVHITE_STRATEGY.card(
                "VIVHITE_CARD_INFINITE_CANVAS").mechanics.growth,
            4,
        )
        sequence = VIVHITE_STRATEGY.card(
            "VIVHITE_CARD_CHROMATIC_SEQUENCE")
        self.assertEqual(
            sequence.mechanics.drain_percent_mode,
            "per_drawn_skill",
        )
        self.assertIn(
            "drawn_skill_grants_4_temporary_drain_percent",
            sequence.mechanics.effects,
        )
        with self.assertRaises(ValueError):
            CardMechanics(energy=1, drain_percent=1.2)

        # Upgraded values arrive from the live API already at the final doubled
        # values. Consume every runtime Drain-family integer unchanged instead
        # of applying a second scaling pass in Brain.
        upgraded_values = {
            ("CRIMSON_AREA", "Drain"): 20,
            ("TRICHROMATIC_WALTZ", "Drain"): 16,
            ("COMPOSITE_COLOR_WHEEL", "Drain"): 24,
            ("DIFFERENTIAL_SAMPLING", "Drain"): 12,
            ("CHIAROSCURO", "Drain"): 28,
            ("SPECTRAL_INTEGRAL", "Drain"): 12,
            ("GOLDEN_COMPOSITION", "Drain"): 24,
            ("RIEMANN_STAR_ARRAY", "Drain"): 16,
            ("CHROMATIC_TRANSITION", "Drain"): 12,
            ("COMPOSITE_COLOR_FIELD", "Drain"): 12,
            ("COMPLEMENTARY_AFTERIMAGE", "Drain"): 20,
            ("DEFINITE_CRIMSON_INTEGRAL", "Drain"): 60,
            ("INFINITE_CANVAS", "DrainGrowth"): 4,
            ("PERFECT_SYNTHESIS", "Drain"): 40,
            ("GOLDEN_RATIO", "Drain"): 16,
            ("ASTRAL_MEASURE", "DrainPerMargin"): 8,
            ("CHROMATIC_SEQUENCE", "DrainPerSkill"): 4,
            ("UNIFIED_FIELD_THEORY", "DrainPerMargin"): 4,
            ("CHROMATIC_LIMIT", "DrainPerX"): 16,
        }
        for (stable_id, name), expected in upgraded_values.items():
            with self.subTest(card=stable_id, name=name):
                self.assertEqual(
                    card_dynamic_value({
                        "card_id": f"VIVHITE_CARD_{stable_id}",
                        "dynamic_values": [{
                            "name": name,
                            "current_value": expected,
                        }],
                    }, name),
                    expected,
                )

    def test_final_draw_discard_inductive_and_zero_cost_catalog_contract(self) -> None:
        expected_draws = {
            "RECURRENT_STARLIGHT": (0, 4),
            "ASTRAL_SEARCH": (4, 0),
            "HEURISTIC_SHIELD": (2, 0),
            "CONVERGENCE_VERDICT": (0, 6),
            "DIVIDE_AND_CONQUER_CIRCLE": (4, 0),
            "ASTRAL_PURSUIT": (0, 2),
            "PREFETCH_FUTURE": (6, 0),
            "PROOF_OF_TERMINATION": (0, 4),
            "OPTIMAL_ALGORITHM": (0, 4),
            "CHROMATIC_TRANSITION": (2, 0),
            "GOLDEN_RATIO": (2, 0),
            "CHROMATIC_SEQUENCE": (4, 0),
        }
        actual_draws = {
            entry.stable_id: (entry.mechanics.draw, entry.mechanics.kill_draw)
            for entry in VIVHITE_CARD_CATALOG
            if entry.mechanics.draw or entry.mechanics.kill_draw
        }
        self.assertEqual(actual_draws, expected_draws)

        astral_search = VIVHITE_STRATEGY.card("VIVHITE_CARD_ASTRAL_SEARCH")
        self.assertIn("discard_2", astral_search.mechanics.effects)
        infinite_sequence = VIVHITE_STRATEGY.card(
            "VIVHITE_CARD_INFINITE_STAR_SEQUENCE")
        self.assertIn(
            "draw_2_cards_per_card_previously_played_this_turn",
            infinite_sequence.mechanics.effects,
        )

        inductive = VIVHITE_STRATEGY.card("VIVHITE_CARD_INDUCTIVE_CIRCLE")
        self.assertEqual(inductive.mechanics.energy, 1)
        self.assertEqual(inductive.mechanics.death_heal_percent, 50)
        self.assertEqual(
            card_dynamic_value({
                "dynamic_values": [{"name": "Heal", "current_value": 75}],
            }, "Heal"),
            75,
        )
        color_conservation = VIVHITE_STRATEGY.card(
            "VIVHITE_CARD_COLOR_CONSERVATION")
        self.assertEqual(color_conservation.mechanics.energy, 0)

    def test_catalog_captures_representative_base_mechanics(self) -> None:
        luminous = VIVHITE_STRATEGY.card(
            "VIVHITE_CARD_LUMINOUS_PROJECTION")
        self.assertIsNotNone(luminous)
        self.assertEqual(luminous.mechanics.energy, 1)
        self.assertEqual(luminous.mechanics.life_calculation_cost, 2)
        self.assertEqual(luminous.mechanics.base_damage, 10)
        self.assertEqual(luminous.build_tags, (HYBRID,))

        transformation = VIVHITE_STRATEGY.card(
            "VIVHITE_CARD_VIVHITE_TRANSFORMATION")
        self.assertEqual(transformation.name_zh, "白绮的变身式")

        scale = VIVHITE_STRATEGY.card(
            "VIVHITE_CARD_SCALE_TRANSFORMATION")
        self.assertEqual(scale.mechanics.energy, 1)
        self.assertEqual(scale.mechanics.life_calculation_cost, 4)
        self.assertEqual(scale.mechanics.max_hp_growth, 2)
        self.assertTrue(scale.mechanics.lethal)
        self.assertTrue(scale.mechanics.exhaust)
        self.assertEqual(scale.build_tags, (CONSERVATION_GEOMETRY,))

        termination = VIVHITE_STRATEGY.card(
            "VIVHITE_CARD_TERMINATION_CONDITION")
        self.assertEqual(termination.mechanics.base_damage, 16)
        self.assertEqual(termination.mechanics.kill_heal, 10)
        self.assertEqual(termination.build_tags, (RECURSIVE_ASTRAL,))

        optimal = VIVHITE_STRATEGY.card(
            "VIVHITE_CARD_OPTIMAL_ALGORITHM")
        self.assertEqual(
            (optimal.mechanics.kill_heal,
             optimal.mechanics.kill_draw,
             optimal.mechanics.kill_energy),
            (3, 4, 1),
        )

        synthesis = VIVHITE_STRATEGY.card(
            "VIVHITE_CARD_PERFECT_SYNTHESIS")
        self.assertEqual(synthesis.mechanics.base_damage, 11)
        self.assertEqual(synthesis.mechanics.damage_hits, 5)
        self.assertTrue(synthesis.mechanics.all_enemies)
        self.assertEqual(synthesis.mechanics.drain_percent, 32)
        self.assertEqual(synthesis.build_tags, (CRIMSON_INTEGRAL,))

        limit_card = VIVHITE_STRATEGY.card("VIVHITE_CARD_CHROMATIC_LIMIT")
        self.assertEqual(limit_card.mechanics.energy, "X")
        self.assertEqual(limit_card.mechanics.life_calculation_cost, 8)
        self.assertEqual(limit_card.mechanics.drain_percent, 12)
        self.assertEqual(limit_card.mechanics.drain_percent_mode, "per_x")

        ritual = VIVHITE_STRATEGY.card(
            "VIVHITE_CARD_VIVHITES_CRIMSON_TRANSFORMATION_RITUAL")
        self.assertEqual(ritual.card_type, "ability")
        self.assertEqual(ritual.rarity, "rare")
        self.assertEqual(ritual.mechanics.energy, 0)
        self.assertEqual(ritual.build_tags, (HYBRID,))
        self.assertEqual(ritual.name_zh, "白绮的猩红转化仪式")
        self.assertIn(
            "all_attacks_gain_life_cost_equal_total_ritual_phase",
            ritual.mechanics.effects,
        )
        self.assertEqual(VIVHITE_STARTING_RELIC_NAME_ZH, "孤高冠冕")
        self.assertEqual(VIVHITE_STARTING_RELIC_NAME_EN, "Solitary Crown")

    def test_priority_weak_card_and_dimension_buffs_are_in_catalog(self) -> None:
        expected = {
            "AXIOM_RING": {"energy": 0, "margin_gain": 3},
            "OPEN_SET_SHELTER": {
                "energy": 1, "life_calculation_cost": 2,
                "base_block": 14, "margin_gain": 2,
            },
            "SCALE_TRANSFORMATION": {
                "energy": 1, "life_calculation_cost": 4,
                "base_damage": 20, "max_hp_growth": 2,
            },
            "TOPOLOGICAL_GROWTH": {"max_hp_growth": 2},
            "AXIOM_OF_LIFE": {"max_hp_growth": 6},
            "INFINITE_EXTENSION": {"growth": 2},
            "TERMINATION_CONDITION": {
                "base_damage": 16, "kill_heal": 10,
            },
            "SUCCESSOR_FORMULA": {
                "energy": 0, "life_calculation_cost": 2,
                "base_damage": 10,
            },
            "ASTRAL_PURSUIT": {
                "energy": 0, "life_calculation_cost": 4,
                "kill_draw": 2,
            },
            "NEGATIVE_SPACE": {
                "energy": 0, "life_calculation_cost": 2, "margin_gain": 2,
            },
            "COLOR_CONSERVATION": {
                "energy": 0, "life_calculation_cost": 4,
            },
        }
        for stable_id, mechanics in expected.items():
            with self.subTest(card=stable_id):
                actual = VIVHITE_STRATEGY.card(
                    f"VIVHITE_CARD_{stable_id}").mechanics
                for field, value in mechanics.items():
                    self.assertEqual(getattr(actual, field), value)

        extension = VIVHITE_STRATEGY.card(
            "VIVHITE_CARD_INFINITE_EXTENSION")
        self.assertIn(
            "each_max_hp_growth_gains_2_more", extension.mechanics.effects)

    def test_cross_suit_contract_is_seven_cards(self) -> None:
        self.assertEqual(len(CROSS_SUIT_IDS), 7)
        for card_id in CROSS_SUIT_IDS:
            self.assertEqual(VIVHITE_STRATEGY.card(card_id).build_tags, (HYBRID,))

    def test_legacy_placeholder_ids_are_absent(self) -> None:
        legacy_ids = {
            "VIVHITE_CARD_VIVHITE_STRIKE",
            "VIVHITE_CARD_VIVHITE_DEFEND",
            "VIVHITE_CARD_VITAL_SPARK",
            "VIVHITE_CARD_AXIOM_GUARD",
            "VIVHITE_CARD_SCARLET_DIVISION",
            "VIVHITE_CARD_QED",
        }
        self.assertTrue(legacy_ids.isdisjoint(VIVHITE_CARD_IDS))

    def test_catalog_matches_every_production_registered_card_class(self) -> None:
        cards_root = (Path(__file__).resolve().parents[2]
                      / "Vivhite" / "VivhiteCode" / "Cards")
        registration = re.compile(
            r"\[RegisterCard\(typeof\(VivhiteCardPool\)\)\]\s*"
            r"(?:\[[^\]]+\]\s*)*public\s+sealed\s+class\s+(\w+)",
            re.S,
        )

        def stable_id(class_name: str) -> str:
            value = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", class_name)
            return re.sub(
                r"([a-z0-9])([A-Z])", r"\1_\2", value).upper()

        classes = []
        for source in cards_root.rglob("*.cs"):
            classes.extend(registration.findall(
                source.read_text(encoding="utf-8-sig")))
        production_ids = {
            f"VIVHITE_CARD_{stable_id(class_name)}"
            for class_name in classes
        }

        self.assertEqual(len(classes), 61)
        self.assertEqual(len(classes), len(production_ids))
        self.assertEqual(production_ids, VIVHITE_CARD_IDS)
        for card_id in production_ids:
            with self.subTest(card_id=card_id):
                self.assertIsNotNone(VIVHITE_STRATEGY.card(card_id))


class CharacterStrategyResolutionTests(unittest.TestCase):
    def test_resolver_supports_profile_and_character_ids(self) -> None:
        self.assertIs(resolve_character_strategy(), IRONCLAD_STRATEGY)
        self.assertIs(resolve_character_strategy("IRONCLAD"), IRONCLAD_STRATEGY)
        self.assertIs(resolve_character_strategy("vivhite"), VIVHITE_STRATEGY)
        self.assertIs(
            resolve_character_strategy(character_id=VIVHITE_CHARACTER_ID.lower()),
            VIVHITE_STRATEGY,
        )
        self.assertIs(
            resolve_character_strategy("vivhite", VIVHITE_CHARACTER_ID),
            VIVHITE_STRATEGY,
        )
        with self.assertRaises(ValueError):
            resolve_character_strategy("ironclad", VIVHITE_CHARACTER_ID)
        with self.assertRaises(KeyError):
            resolve_character_strategy("unknown-character")

    def test_parameter_instances_and_catalogs_are_isolated(self) -> None:
        self.assertIsNot(IRONCLAD_PARAMETERS, VIVHITE_PARAMETERS)
        self.assertIs(IRONCLAD_STRATEGY.parameters, IRONCLAD_PARAMETERS)
        self.assertIs(VIVHITE_STRATEGY.parameters, VIVHITE_PARAMETERS)
        self.assertEqual(IRONCLAD_STRATEGY.card_catalog, ())
        self.assertIsNone(
            IRONCLAD_STRATEGY.card("VIVHITE_CARD_LUMINOUS_PROJECTION"))
        self.assertEqual(IRONCLAD_STRATEGY.character_id, IRONCLAD_CHARACTER_ID)

    def test_strategy_inputs_are_immutable(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            VIVHITE_PARAMETERS.margin_weight = 99.0
        with self.assertRaises(FrozenInstanceError):
            VIVHITE_CARD_CATALOG[0].rarity = "rare"


class CharacterStrategyScoringTests(unittest.TestCase):
    def test_vivhite_initial_weights_are_exact(self) -> None:
        self.assertEqual(VIVHITE_PARAMETERS.life_cost_weight, -1.25)
        self.assertEqual(VIVHITE_PARAMETERS.low_hp_fraction, 0.35)
        self.assertEqual(
            VIVHITE_PARAMETERS.low_hp_life_cost_multiplier, 2.0)
        self.assertEqual(VIVHITE_PARAMETERS.margin_weight, 1.25)
        self.assertEqual(VIVHITE_PARAMETERS.drain_healing_weight, 0.85)
        self.assertEqual(VIVHITE_PARAMETERS.permanent_max_hp_weight, 3.0)
        self.assertEqual(VIVHITE_PARAMETERS.kill_healing_weight, 1.0)

    def test_life_cost_risk_doubles_strictly_below_35_percent(self) -> None:
        self.assertEqual(
            score_life_cost(
                VIVHITE_PARAMETERS, 4, current_hp=35, max_hp=100),
            -5.0,
        )
        self.assertEqual(
            score_life_cost(
                VIVHITE_PARAMETERS, 4, current_hp=34, max_hp=100),
            -10.0,
        )
        self.assertEqual(
            score_life_cost(
                VIVHITE_PARAMETERS, 400, current_hp=1, max_hp=1000),
            -1000.0,
        )

    def test_large_realized_values_and_over_100_drain_remain_linear(self) -> None:
        self.assertEqual(drain_healing_from_actual_damage(1, 1), 1.0)
        self.assertEqual(drain_healing_from_actual_damage(10, 15), 2.0)
        self.assertEqual(drain_healing_from_actual_damage(80, 250), 200.0)
        self.assertEqual(
            score_drain_healing(
                VIVHITE_PARAMETERS, 200, drain_percent=250),
            170.0,
        )
        self.assertEqual(score_margin(VIVHITE_PARAMETERS, 10_000), 12_500.0)
        self.assertEqual(
            score_permanent_max_hp(VIVHITE_PARAMETERS, 1_000), 3_000.0)
        self.assertEqual(
            score_kill_healing(VIVHITE_PARAMETERS, 5_000), 5_000.0)
        self.assertEqual(score_draw(VIVHITE_PARAMETERS, 2_000), 2_000.0)
        self.assertEqual(score_growth(VIVHITE_PARAMETERS, 3_000), 3_000.0)

        overcap_mechanics = CardMechanics(energy=1, drain_percent=275)
        self.assertEqual(overcap_mechanics.drain_percent, 275)

    def test_aggregate_uses_actual_amounts_without_clipping(self) -> None:
        score = score_realized_mechanics(
            VIVHITE_PARAMETERS,
            current_hp=80,
            max_hp=100,
            life_cost_hp=100,
            margin_gained=1_000,
            drain_percent=425,
            drain_hp_restored=2_000,
            permanent_max_hp_gained=300,
            kill_hp_restored=4_000,
            cards_drawn=500,
            energy_gained=100,
            growth=700,
        )
        expected = (
            -125.0
            + 1_250.0
            + 1_700.0
            + 900.0
            + 4_000.0
            + 500.0
            + 100.0
            + 700.0
        )
        self.assertEqual(score, expected)

    def test_ironclad_neutral_overlay_preserves_existing_behavior(self) -> None:
        self.assertEqual(IRONCLAD_PARAMETERS.profile_id, "ironclad")
        score = score_realized_mechanics(
            IRONCLAD_PARAMETERS,
            current_hp=1,
            max_hp=100,
            life_cost_hp=500,
            margin_gained=500,
            drain_percent=500,
            drain_hp_restored=500,
            permanent_max_hp_gained=500,
            kill_hp_restored=500,
            cards_drawn=500,
            energy_gained=500,
            growth=500,
        )
        self.assertEqual(score, 0.0)

    def test_negative_or_nonfinite_observations_are_rejected_not_clipped(self) -> None:
        with self.assertRaises(ValueError):
            score_margin(VIVHITE_PARAMETERS, -1)
        with self.assertRaises(ValueError):
            score_drain_healing(
                VIVHITE_PARAMETERS, 10, drain_percent=float("inf"))
        with self.assertRaises(ValueError):
            score_life_cost(
                VIVHITE_PARAMETERS, 1, current_hp=1, max_hp=0)


class CharacterStrategyDynamicEstimateTests(unittest.TestCase):
    @staticmethod
    def _card(card_id: str, card_type: str, **values: int) -> dict:
        return {
            "card_id": card_id,
            "name": card_id,
            "card_type": card_type,
            "energy_cost": 1,
            "dynamic_values": [
                {"name": name, "current_value": value}
                for name, value in values.items()
            ],
        }

    @staticmethod
    def _enemy(hp: int, *, block: int = 0, index: int = 0) -> dict:
        return {
            "index": index,
            "current_hp": hp,
            "max_hp": hp,
            "block": block,
            "is_alive": True,
            "is_hittable": True,
        }

    def test_exact_dynamic_names_do_not_turn_coefficients_into_card_numbers(self) -> None:
        closed = self._card(
            "VIVHITE_CARD_CLOSED_PROJECTION", "Attack",
            LifeCost=4, Damage=18, BlockPerMargin=6)
        self.assertIsNone(card_dynamic_value(closed, "Block"))
        self.assertEqual(
            resolve_character_card_numbers(
                VIVHITE_STRATEGY, closed, 6, 6, 1,
                energy=1, margin=2, hand_count=5),
            (18, 12, 1),
        )

        divide = self._card(
            "VIVHITE_CARD_DIVIDE_AND_CONQUER_CIRCLE", "Skill",
            LifeCost=4, Cards=6, SpellDamage=5)
        self.assertEqual(
            resolve_character_card_numbers(
                VIVHITE_STRATEGY, divide, 5, 0, 1,
                energy=1, margin=0, hand_count=5)[0],
            0,
        )

    def test_state_dependent_hit_counts_use_hand_and_uncapped_x_energy(self) -> None:
        riemann = self._card(
            "VIVHITE_CARD_RIEMANN_STAR_ARRAY", "Attack",
            LifeCost=6, Damage=5, Drain=16)
        self.assertEqual(
            resolve_character_card_numbers(
                VIVHITE_STRATEGY, riemann, 5, 0, 1,
                energy=1, margin=0, hand_count=7)[2],
            6,
        )

        limit_card = self._card(
            "VIVHITE_CARD_CHROMATIC_LIMIT", "Attack",
            LifeCost=8, Damage=9, DrainPerX=12, HealingPerMargin=10)
        limit_card["costs_x"] = True
        self.assertEqual(
            resolve_character_card_numbers(
                VIVHITE_STRATEGY, limit_card, 9, 0, 1,
                energy=37, margin=0, hand_count=1),
            (9, 0, 37),
        )

    def test_crimson_ritual_phases_sum_and_modify_each_attack_hit_uncapped(self) -> None:
        attack = self._card(
            "VIVHITE_CARD_LUMINOUS_PROJECTION", "Attack",
            LifeCost=2, Damage=10)
        powers = [
            {"power_id": VIVHITE_CRIMSON_RITUAL_POWER_ID, "amount": 2},
            {"power_id": VIVHITE_CRIMSON_RITUAL_POWER_ID, "amount": 4},
            {"power_id": VIVHITE_CRIMSON_RITUAL_UPGRADED_POWER_ID,
             "amount": 3},
        ]

        self.assertEqual(
            vivhite_crimson_ritual_totals(VIVHITE_STRATEGY, powers),
            (9.0, 105.0),
        )
        self.assertEqual(
            resolve_character_card_numbers(
                VIVHITE_STRATEGY, attack, 10, 0, 1,
                energy=1, margin=0, hand_count=1, player_powers=powers),
            (20, 0, 1),
        )
        self.assertTrue(character_card_has_terminal_life_cost_lock(
            VIVHITE_STRATEGY, attack, current_hp=11,
            player_powers=powers))
        self.assertFalse(character_card_has_terminal_life_cost_lock(
            VIVHITE_STRATEGY, attack, current_hp=12,
            player_powers=powers))
        score, note = estimate_character_card(
            VIVHITE_STRATEGY, attack,
            current_hp=50, max_hp=100,
            enemies=[self._enemy(100)], target_index=0,
            player_powers=powers, energy=1)
        self.assertEqual(score, -13.75)
        self.assertIn("hp-cost=11", note)
        self.assertIn("ritual-phase=9/damage=105%", note)
        self.assertEqual(
            vivhite_crimson_ritual_totals(
                IRONCLAD_STRATEGY, powers),
            (0.0, 0.0),
        )

        unbounded = [{
            "power_id": VIVHITE_CRIMSON_RITUAL_POWER_ID,
            "amount": 1000,
        }]
        self.assertEqual(
            resolve_character_card_numbers(
                VIVHITE_STRATEGY, attack, 10, 0, 1,
                energy=1, margin=0, hand_count=1,
                player_powers=unbounded)[0],
            1010,
        )

    def test_crimson_ritual_reads_production_power_phase_fields(self) -> None:
        powers = [
            {
                "power_id": VIVHITE_CRIMSON_RITUAL_POWER_ID,
                "Phase": 2,
                "DamagePercentPerPhase": 11,
                "amount": 999,
            },
            {
                "power_id": VIVHITE_CRIMSON_RITUAL_UPGRADED_POWER_ID,
                "dynamic_values": [
                    {"name": "Phase", "current_value": 3},
                    {"name": "DamagePercentPerPhase", "current_value": 16},
                ],
                "amount": 999,
            },
        ]

        # Explicit Power fields win over the legacy amount projection:
        # life cost = 2+3, damage = 2*11% + 3*16%.
        self.assertEqual(
            vivhite_crimson_ritual_totals(VIVHITE_STRATEGY, powers),
            (5.0, 70.0),
        )

    def test_crimson_ritual_does_not_double_apply_modified_api_previews(self) -> None:
        attack = {
            "card_id": "VIVHITE_CARD_LUMINOUS_PROJECTION",
            "card_type": "Attack",
            "dynamic_values": [
                {"name": "LifeCost", "base_value": 2,
                 "current_value": 7, "is_modified": True},
                {"name": "Damage", "base_value": 10,
                 "current_value": 16, "is_modified": True},
            ],
        }
        powers = [
            {"power_id": VIVHITE_CRIMSON_RITUAL_POWER_ID, "amount": 2},
            {"power_id": VIVHITE_CRIMSON_RITUAL_UPGRADED_POWER_ID,
             "amount": 3},
        ]

        self.assertEqual(
            resolve_character_card_numbers(
                VIVHITE_STRATEGY, attack, 10, 0, 1,
                energy=1, margin=0, hand_count=1, player_powers=powers),
            (16, 0, 1),
        )
        score, note = estimate_character_card(
            VIVHITE_STRATEGY, attack,
            current_hp=50, max_hp=100,
            enemies=[self._enemy(100)], target_index=0,
            player_powers=powers, energy=1)
        self.assertEqual(score, -8.75)
        self.assertIn("hp-cost=7", note)
        self.assertIn("ritual-phase=5/damage=65%", note)

    def test_crimson_ritual_parent_has_deck_aware_uncapped_longline_value(self) -> None:
        ritual = self._card(
            "VIVHITE_CARD_VIVHITES_CRIMSON_TRANSFORMATION_RITUAL",
            "Power")
        no_attacks, _ = estimate_character_card(
            VIVHITE_STRATEGY, ritual,
            deck_cards=[self._card(
                "VIVHITE_CARD_CLOSED_DOMAIN_MAPPING", "Skill", Block=9)])
        strong_deck = [self._card(
            "VIVHITE_CARD_DEFINITE_CRIMSON_INTEGRAL", "Attack",
            LifeCost=12, Damage=100)]
        base, base_note = estimate_character_card(
            VIVHITE_STRATEGY, ritual, deck_cards=strong_deck)
        upgraded = dict(ritual, upgraded=True)
        upgraded_score, _ = estimate_character_card(
            VIVHITE_STRATEGY, upgraded, deck_cards=strong_deck)
        dynamic_rate = self._card(
            "VIVHITE_CARD_VIVHITES_CRIMSON_TRANSFORMATION_RITUAL",
            "Power", DamagePercentPerPhase=20)
        dynamic_score, dynamic_note = estimate_character_card(
            VIVHITE_STRATEGY, dynamic_rate, deck_cards=strong_deck)
        long_fight, long_note = estimate_character_card(
            VIVHITE_STRATEGY, ritual,
            deck_cards=strong_deck,
            enemies=[self._enemy(10_000)], target_index=0)

        self.assertEqual(no_attacks, 0.0)
        self.assertGreater(base, no_attacks)
        self.assertGreater(upgraded_score, base)
        self.assertGreater(dynamic_score, upgraded_score)
        self.assertGreater(long_fight, base)
        self.assertIn("ritual-longline=", base_note)
        self.assertIn("rate=20%", dynamic_note)
        self.assertIn("turns=20", long_note)

    def test_solitary_crown_uses_current_max_hp_after_dimension_growth(self) -> None:
        self.assertEqual(solitary_crown_kill_heal(), 16)
        self.assertEqual(solitary_crown_kill_heal(78), 16)
        self.assertEqual(solitary_crown_kill_heal(100), 20)
        self.assertEqual(solitary_crown_kill_heal(101), 21)
        self.assertEqual(solitary_crown_kill_heal(10_000), 2_000)

        lethal = self._card(
            "VIVHITE_CARD_LUMINOUS_PROJECTION", "Attack",
            LifeCost=2, Damage=10)
        before, before_note = estimate_character_card(
            VIVHITE_STRATEGY, lethal,
            current_hp=50, max_hp=100,
            enemies=[self._enemy(10)], target_index=0,
            player_powers=[], energy=1)
        after_dimension, after_note = estimate_character_card(
            VIVHITE_STRATEGY, lethal,
            current_hp=50, max_hp=101,
            enemies=[self._enemy(10)], target_index=0,
            player_powers=[], energy=1)

        self.assertEqual(after_dimension - before, 1.0)
        self.assertIn("crown=20/kill", before_note)
        self.assertIn("crown=21/kill", after_note)

    def test_terminal_life_lock_accounts_for_uncapped_margin_and_is_profile_only(self) -> None:
        card = self._card(
            "VIVHITE_CARD_LAW_OF_CONSERVATION", "Power", LifeCost=100)
        margin_99 = [{
            "power_id": "VIVHITE_POWER_INFINITE_MARGIN_POWER",
            "amount": 99,
        }]
        margin_1000 = [{
            "power_id": "VIVHITE_POWER_INFINITE_MARGIN_POWER",
            "amount": 1000,
        }]
        self.assertFalse(character_card_has_terminal_life_cost_lock(
            VIVHITE_STRATEGY, card, current_hp=2, player_powers=margin_99))
        self.assertTrue(character_card_has_terminal_life_cost_lock(
            VIVHITE_STRATEGY, card, current_hp=1, player_powers=margin_99))
        self.assertFalse(character_card_has_terminal_life_cost_lock(
            VIVHITE_STRATEGY, card, current_hp=1, player_powers=margin_1000))
        self.assertFalse(character_card_has_terminal_life_cost_lock(
            IRONCLAD_STRATEGY, card, current_hp=1, player_powers=[]))

    def test_kill_rewards_and_dimension_up_require_an_observed_lethal(self) -> None:
        termination = self._card(
            "VIVHITE_CARD_TERMINATION_CONDITION", "Attack",
            LifeCost=4, Damage=12, Heal=8)
        nonlethal, _ = estimate_character_card(
            VIVHITE_STRATEGY, termination,
            current_hp=50, max_hp=100,
            enemies=[self._enemy(20)], target_index=0,
            player_powers=[], energy=1)
        lethal, lethal_note = estimate_character_card(
            VIVHITE_STRATEGY, termination,
            current_hp=50, max_hp=100,
            enemies=[self._enemy(12)], target_index=0,
            player_powers=[], energy=1)
        self.assertEqual(nonlethal, -5.0)
        # Heal=8 plus Solitary Crown's ceil(100*20%)=20, only on lethal.
        self.assertEqual(lethal, 23.0)
        self.assertIn("kills=1/lethal=1", lethal_note)

        scale = self._card(
            "VIVHITE_CARD_SCALE_TRANSFORMATION", "Attack",
            LifeCost=6, Damage=20, DimensionUp=2)
        powers = [{
            "power_id": "VIVHITE_POWER_INFINITE_EXTENSION_POWER",
            "amount": 100,
        }]
        no_growth, _ = estimate_character_card(
            VIVHITE_STRATEGY, scale,
            current_hp=50, max_hp=100,
            enemies=[self._enemy(21)], target_index=0,
            player_powers=powers, energy=2)
        growth, growth_note = estimate_character_card(
            VIVHITE_STRATEGY, scale,
            current_hp=50, max_hp=100,
            enemies=[self._enemy(20)], target_index=0,
            player_powers=powers, energy=2)
        self.assertEqual(no_growth, -7.5)
        self.assertGreater(growth, 300.0)
        self.assertIn("dimension=102", growth_note)

    def test_inductive_percentage_and_death_power_draws_use_final_values(self) -> None:
        inductive = self._card(
            "VIVHITE_CARD_INDUCTIVE_CIRCLE", "Power",
            LifeCost=8, Heal=50)
        optimal = [{
            "power_id": "VIVHITE_POWER_OPTIMAL_ALGORITHM_POWER",
            "amount": 1,
        }]
        base_score, _ = estimate_character_card(
            VIVHITE_STRATEGY, inductive,
            current_hp=50, max_hp=78,
            enemies=[self._enemy(100)], target_index=0,
            player_powers=optimal, energy=1)
        upgraded_score, _ = estimate_character_card(
            VIVHITE_STRATEGY,
            self._card(
                "VIVHITE_CARD_INDUCTIVE_CIRCLE", "Power",
                LifeCost=8, Heal=75),
            current_hp=50, max_hp=78,
            enemies=[self._enemy(100)], target_index=0,
            player_powers=optimal, energy=1)
        # Crown=ceil(78*20%)=16 and Optimal Algorithm=3, so 50%/75%
        # add ceil(19*.50)=10 and ceil(19*.75)=15 respectively.
        self.assertEqual(base_score, 0.0)
        self.assertEqual(upgraded_score, 5.0)

        lethal = self._card(
            "VIVHITE_CARD_LUMINOUS_PROJECTION", "Attack",
            LifeCost=2, Damage=10)
        score, _ = estimate_character_card(
            VIVHITE_STRATEGY, lethal,
            current_hp=50, max_hp=100,
            enemies=[self._enemy(10)], target_index=0,
            player_powers=[
                {"power_id": "VIVHITE_POWER_ASTRAL_PURSUIT_POWER",
                 "amount": 1},
                {"power_id": "VIVHITE_POWER_OPTIMAL_ALGORITHM_POWER",
                 "amount": 1},
            ],
            energy=1)
        # -2.5 Cough + (20 Crown + 3 Optimal) healing + (2+4) draws
        # + 1 Energy from Optimal Algorithm.
        self.assertEqual(score, 27.5)

    def test_margin_payment_and_custom_power_conversions_are_live_state(self) -> None:
        growth_card = self._card(
            "VIVHITE_CARD_TOPOLOGICAL_GROWTH", "Skill",
            LifeCost=8, Margin=4, DimensionUp=2)
        score, note = estimate_character_card(
            VIVHITE_STRATEGY, growth_card,
            current_hp=100, max_hp=100,
            player_powers=[
                {"power_id": "VIVHITE_POWER_INFINITE_MARGIN_POWER",
                 "amount": 4},
                {"power_id": "VIVHITE_POWER_INFINITE_EXTENSION_POWER",
                 "amount": 100},
            ],
            energy=1,
        )
        # Four Margin are spent and four regained; the remaining four HP cost is
        # scored while 2 + 100 DimensionUp stays fully uncapped.
        self.assertEqual(score, 301.0)
        self.assertIn("margin=4/spent=4", note)

        attack = self._card(
            "VIVHITE_CARD_LUMINOUS_PROJECTION", "Attack",
            LifeCost=6, Damage=100)
        converted, converted_note = estimate_character_card(
            VIVHITE_STRATEGY, attack,
            current_hp=50, max_hp=200,
            enemies=[self._enemy(500)], target_index=0,
            player_powers=[
                {"power_id": "VIVHITE_POWER_INFINITE_MARGIN_POWER",
                 "amount": 3},
                {"power_id": "VIVHITE_POWER_LAW_OF_CONSERVATION_POWER",
                 "amount": 2},
                {"power_id":
                 "VIVHITE_POWER_UNIFIED_FIELD_THEORY_UPGRADED_POWER",
                 "amount": 1},
            ],
            energy=1,
        )
        self.assertGreater(converted, 9.6)
        self.assertIn("drain=12%/12hp", converted_note)

    def test_drain_uses_real_hp_loss_missing_hp_and_unbounded_percent(self) -> None:
        crimson = self._card(
            "VIVHITE_CARD_CRIMSON_AREA", "Attack",
            LifeCost=4, Damage=14, Drain=16)
        powers = [{
            "power_id": "VIVHITE_POWER_INFINITE_DRAIN_POWER",
            "amount": 80,
        }]
        overkill, overkill_note = estimate_character_card(
            VIVHITE_STRATEGY, crimson,
            current_hp=50, max_hp=100,
            enemies=[self._enemy(5)], target_index=0,
            player_powers=powers, energy=1)
        blocked, blocked_note = estimate_character_card(
            VIVHITE_STRATEGY, crimson,
            current_hp=50, max_hp=100,
            enemies=[self._enemy(5, block=10)], target_index=0,
            player_powers=powers, energy=1)
        # -5 Cough score + 20 Crown healing + ceil(5*96%)*0.85 Drain value.
        self.assertAlmostEqual(overkill, 19.25)
        self.assertIn("drain=96%/5hp", overkill_note)
        self.assertIn("drain=96%/4hp", blocked_note)

        limit_card = self._card(
            "VIVHITE_CARD_CHROMATIC_LIMIT", "Attack",
            LifeCost=8, Damage=9, DrainPerX=12, HealingPerMargin=10)
        limit_card["costs_x"] = True
        five, five_note = estimate_character_card(
            VIVHITE_STRATEGY, limit_card,
            current_hp=500, max_hp=1000,
            enemies=[self._enemy(1000)], target_index=0,
            player_powers=[], energy=5)
        ten, ten_note = estimate_character_card(
            VIVHITE_STRATEGY, limit_card,
            current_hp=500, max_hp=1000,
            enemies=[self._enemy(1000)], target_index=0,
            player_powers=[], energy=10)
        self.assertAlmostEqual(five, 15.45)
        self.assertAlmostEqual(ten, 94.3)
        self.assertIn("drain=60%/27hp", five_note)
        self.assertIn("drain=120%/108hp", ten_note)

    def test_aoe_multihit_drain_aggregates_once_before_ceiling(self) -> None:
        synthesis = self._card(
            "VIVHITE_CARD_PERFECT_SYNTHESIS", "Attack",
            LifeCost=16, Damage=1, Drain=32)
        score, note = estimate_character_card(
            VIVHITE_STRATEGY,
            synthesis,
            current_hp=50,
            max_hp=100,
            enemies=[
                self._enemy(100, index=0),
                self._enemy(100, index=1),
                self._enemy(100, index=2),
            ],
            target_index=0,
            player_powers=[],
            energy=3,
        )

        # Fifteen total HP loss (3 enemies x 5 hits) at 32% heals
        # ceil(15 * .32) = 5 once. Per-target or per-hit rounding would heal 6
        # or 15 respectively.
        self.assertAlmostEqual(score, -15.75)
        self.assertIn("drain=32%/5hp", note)

    def test_global_and_temporary_drain_engines_gain_observed_attack_value(self) -> None:
        spectral = self._card(
            "VIVHITE_CARD_SPECTRAL_INTEGRAL", "Power",
            LifeCost=6, Drain=8)
        deck = [
            self._card("VIVHITE_CARD_CRIMSON_AREA", "Attack", Damage=100),
            self._card(
                "VIVHITE_CARD_GOLDEN_COMPOSITION", "Attack", Damage=80),
        ]
        without_attacks, _ = estimate_character_card(
            VIVHITE_STRATEGY, spectral,
            current_hp=50, max_hp=100, player_powers=[], deck_cards=[])
        with_attacks, note = estimate_character_card(
            VIVHITE_STRATEGY, spectral,
            current_hp=50, max_hp=100, player_powers=[], deck_cards=deck)
        self.assertGreater(with_attacks, without_attacks)
        self.assertIn("drain-projected-from-observed-cards", note)

        golden_ratio = self._card(
            "VIVHITE_CARD_GOLDEN_RATIO", "Skill",
            LifeCost=4, Margin=3, Drain=12, Cards=2)
        no_temporary, _ = estimate_character_card(
            VIVHITE_STRATEGY, golden_ratio,
            current_hp=50, max_hp=100, player_powers=[], hand_cards=[],
            energy=2)
        temporary, temporary_note = estimate_character_card(
            VIVHITE_STRATEGY, golden_ratio,
            current_hp=50, max_hp=100, player_powers=[],
            hand_cards=[self._card(
                "VIVHITE_CARD_DEFINITE_CRIMSON_INTEGRAL", "Attack",
                Damage=100)],
            energy=2)
        self.assertGreater(temporary, no_temporary)
        self.assertIn("drain-projected-from-observed-cards", temporary_note)

    def test_recovery_and_copy_parents_value_their_observed_child_choice(self) -> None:
        strong_attack = self._card(
            "VIVHITE_CARD_DEFINITE_CRIMSON_INTEGRAL", "Attack",
            LifeCost=12, Damage=32)
        strong_skill = self._card(
            "VIVHITE_CARD_GEODESIC_VEIL", "Skill",
            LifeCost=6, Block=30)
        cases = (
            ("VIVHITE_CARD_MOBIUS_LOOP", "Skill", [strong_skill], None),
            ("VIVHITE_CARD_BACKTRACKING_SPELL", "Skill",
             [strong_attack], None),
            ("VIVHITE_CARD_EVENT_LOOP", "Skill", [strong_attack], 1),
            ("VIVHITE_CARD_CONSERVED_RECURRENCE", "Skill",
             [strong_attack], None),
        )
        for card_id, card_type, observed, played in cases:
            with self.subTest(card_id=card_id):
                parent = self._card(card_id, card_type)
                empty, _ = estimate_character_card(
                    VIVHITE_STRATEGY, parent,
                    current_hp=60, max_hp=100, player_powers=[],
                    deck_cards=[], cards_played_this_turn=played)
                projected, note = estimate_character_card(
                    VIVHITE_STRATEGY, parent,
                    current_hp=60, max_hp=100, player_powers=[],
                    deck_cards=observed, cards_played_this_turn=played)
                self.assertGreater(projected, empty)
                self.assertIn("recovery-copy=", note)

        event = self._card("VIVHITE_CARD_EVENT_LOOP", "Skill")
        no_play, no_play_note = estimate_character_card(
            VIVHITE_STRATEGY, event,
            current_hp=60, max_hp=100, player_powers=[],
            deck_cards=[strong_attack], cards_played_this_turn=0)
        self.assertNotIn("recovery-copy=", no_play_note)
        self.assertLess(no_play, 0.0)

    def test_vulnerable_effects_use_dynamic_amount_and_all_enemy_scope(self) -> None:
        negative = self._card(
            "VIVHITE_CARD_NEGATIVE_SPACE", "Skill",
            LifeCost=4, Margin=1, VulnerablePower=3)
        single, single_note = estimate_character_card(
            VIVHITE_STRATEGY, negative,
            current_hp=60, max_hp=100, player_powers=[])
        self.assertEqual(single, -0.75)
        self.assertIn("vulnerable=3", single_note)

        field = self._card(
            "VIVHITE_CARD_COMPOSITE_COLOR_FIELD", "Skill",
            LifeCost=8, Drain=8, VulnerablePower=3)
        single_field, _ = estimate_character_card(
            VIVHITE_STRATEGY, field,
            current_hp=60, max_hp=100, player_powers=[],
            enemies=[self._enemy(20)], observed_target_count=1)
        group, group_note = estimate_character_card(
            VIVHITE_STRATEGY, field,
            current_hp=60, max_hp=100, player_powers=[],
            enemies=[self._enemy(20, index=index) for index in range(3)],
            observed_target_count=3)
        self.assertIn("vulnerable=9", group_note)
        self.assertGreater(group, single_field)

    def test_nominal_label_and_unexposed_dynamic_programming_state_are_explicit(self) -> None:
        nominal, nominal_note = estimate_character_card(
            VIVHITE_STRATEGY,
            self._card("VIVHITE_CARD_AXIOM_RING", "Skill", Margin=2),
        )
        self.assertEqual(nominal, 2.5)
        self.assertIn("VIVHITE_NOMINAL_ESTIMATE", nominal_note)

        _score, dynamic_note = estimate_character_card(
            VIVHITE_STRATEGY,
            self._card(
                "VIVHITE_CARD_DYNAMIC_PROGRAMMING", "Power",
                LifeCost=10, Calculation=3),
            current_hp=60, max_hp=100, player_powers=[])
        self.assertIn(
            "calculation-internal-not-exposed-by-api", dynamic_note)


class CharacterStrategyBuildSynergyTests(unittest.TestCase):
    @staticmethod
    def _card(card_id: str) -> dict:
        return {"card_id": card_id}

    def test_each_suit_core_gains_value_from_its_engine_components(self) -> None:
        cases = (
            (
                "VIVHITE_CARD_INFINITE_EXTENSION",
                ("VIVHITE_CARD_TOPOLOGICAL_GROWTH",
                 "VIVHITE_CARD_AXIOM_OF_LIFE"),
                ("VIVHITE_CARD_CRIMSON_AREA",
                 "VIVHITE_CARD_SPECTRAL_INTEGRAL"),
            ),
            (
                "VIVHITE_CARD_OPTIMAL_ALGORITHM",
                ("VIVHITE_CARD_RECURRENT_STARLIGHT",
                 "VIVHITE_CARD_PROOF_OF_TERMINATION"),
                ("VIVHITE_CARD_AXIOM_RING",
                 "VIVHITE_CARD_LIFE_MANIFOLD"),
            ),
            (
                "VIVHITE_CARD_SPECTRAL_INTEGRAL",
                ("VIVHITE_CARD_CRIMSON_AREA",
                 "VIVHITE_CARD_GOLDEN_COMPOSITION"),
                ("VIVHITE_CARD_AXIOM_RING",
                 "VIVHITE_CARD_LIFE_MANIFOLD"),
            ),
        )
        for candidate_id, same_ids, off_ids in cases:
            with self.subTest(candidate=candidate_id):
                same, note = character_build_synergy(
                    VIVHITE_STRATEGY,
                    self._card(candidate_id),
                    [self._card(card_id) for card_id in same_ids],
                )
                off, _ = character_build_synergy(
                    VIVHITE_STRATEGY,
                    self._card(candidate_id),
                    [self._card(card_id) for card_id in off_ids],
                )
                self.assertGreater(same, off)
                self.assertIn("VIVHITE_BUILD_SYNERGY", note)

    def test_synergy_is_profile_only_and_has_no_custom_stack_cap(self) -> None:
        candidate = self._card("VIVHITE_CARD_SPECTRAL_INTEGRAL")
        attack = self._card("VIVHITE_CARD_CRIMSON_AREA")
        ten, _ = character_build_synergy(
            VIVHITE_STRATEGY, candidate, [attack] * 10)
        hundred, _ = character_build_synergy(
            VIVHITE_STRATEGY, candidate, [attack] * 100)
        ironclad, note = character_build_synergy(
            IRONCLAD_STRATEGY, candidate, [attack] * 100)
        self.assertGreater(hundred, ten * 9)
        self.assertEqual((ironclad, note), (0.0, ""))

    def test_chromatic_sequence_is_a_drain_engine_for_crimson_builds(self) -> None:
        candidate = self._card("VIVHITE_CARD_CRIMSON_AREA")
        sequence_score, note = character_build_synergy(
            VIVHITE_STRATEGY,
            candidate,
            [self._card("VIVHITE_CARD_CHROMATIC_SEQUENCE")],
        )
        plain_bridge_score, _ = character_build_synergy(
            VIVHITE_STRATEGY,
            candidate,
            [self._card("VIVHITE_CARD_CONSERVED_RECURRENCE")],
        )

        self.assertGreater(sequence_score, plain_bridge_score)
        self.assertIn("汲取引擎×1", note)


class CharacterStrategyPolicyIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="sts2-strategy-policy-")
        self.root = Path(self.temp.name) / "knowledge"
        self.store = ProfileStore(self.root)
        self.vivhite_knowledge = Knowledge(
            self.store.vivhite, repair_phantoms=False)
        self.ironclad_knowledge = Knowledge(
            self.store.ironclad, repair_phantoms=False)
        self.vivhite_policy = Policy(self.vivhite_knowledge)
        self.ironclad_policy = Policy(self.ironclad_knowledge)

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _card(card_id: str, card_type: str = "Skill",
              damage: int = 0) -> dict:
        dynamic_values = []
        if damage:
            dynamic_values.append({
                "name": "Damage",
                "current_value": damage,
            })
        return {
            "card_id": card_id,
            "name": card_id,
            "card_type": card_type,
            "rarity": "Common",
            "energy_cost": 1,
            "resolved_rules_text": "",
            "dynamic_values": dynamic_values,
        }

    @staticmethod
    def _selection_card(index: int, card_id: str, card_type: str,
                        *, damage: int = 0, block: int = 0,
                        energy_cost: int = 1) -> dict:
        values = []
        if damage:
            values.append({"name": "Damage", "current_value": damage})
        if block:
            values.append({"name": "Block", "current_value": block})
        return {
            "index": index,
            "card_id": card_id,
            "name": card_id,
            "card_type": card_type,
            "rarity": "Common",
            "energy_cost": energy_cost,
            "resolved_rules_text": "",
            "dynamic_values": values,
        }

    @staticmethod
    def _selection_state(kind: str, prompt: str, cards: list[dict],
                         *, selected_count: int = 0,
                         can_confirm: bool = False,
                         reward: dict | None = None,
                         actions: list[str] | None = None) -> dict:
        return {
            "screen": "CARD_SELECTION",
            "available_actions": actions or ["select_deck_card"],
            "selection": {
                "kind": kind,
                "prompt": prompt,
                "cards": cards,
                "min_select": 1,
                "max_select": 1,
                "selected_count": selected_count,
                "can_confirm": can_confirm,
            },
            "reward": reward or {},
            "run": {
                "floor": 5,
                "current_hp": 60,
                "max_hp": 78,
                "deck": [],
            },
        }

    def test_profile_exposes_isolated_strategy_catalog_and_weights(self) -> None:
        vivhite = self.store.vivhite
        ironclad = self.store.ironclad

        self.assertIs(vivhite.strategy, VIVHITE_STRATEGY)
        self.assertIs(vivhite.strategy_parameters, VIVHITE_PARAMETERS)
        self.assertEqual(vivhite.card_catalog, VIVHITE_CARD_CATALOG)
        self.assertEqual(vivhite.mechanic_weights["life_calculation"], -1.25)
        self.assertEqual(vivhite.keyword_values["margin"], 1.25)
        with self.assertRaises(TypeError):
            vivhite.mechanic_weights["margin"] = 99.0

        self.assertIs(ironclad.strategy, IRONCLAD_STRATEGY)
        self.assertIs(ironclad.strategy_parameters, IRONCLAD_PARAMETERS)
        self.assertEqual(ironclad.card_catalog, ())
        self.assertIsNot(
            ironclad.strategy_parameters, vivhite.strategy_parameters)

    def test_policy_resolves_knowledge_or_explicit_profile_without_mixing(self) -> None:
        self.assertIs(
            self.vivhite_policy.character_strategy, VIVHITE_STRATEGY)
        self.assertIs(
            self.vivhite_policy.strategy_parameters, VIVHITE_PARAMETERS)
        self.assertIs(
            self.ironclad_policy.character_strategy, IRONCLAD_STRATEGY)
        self.assertIs(
            self.ironclad_policy.strategy_parameters, IRONCLAD_PARAMETERS)

        class ProfilelessKnowledge:
            profile = None

        explicit = Policy(ProfilelessKnowledge(), profile=self.store.vivhite)
        self.assertIs(explicit.character_strategy, VIVHITE_STRATEGY)
        with self.assertRaises(ValueError):
            Policy(self.ironclad_knowledge, profile=self.store.vivhite)

    def test_every_production_card_has_a_finite_profile_reward_estimate(self) -> None:
        type_names = {
            "attack": "Attack",
            "skill": "Skill",
            "ability": "Power",
        }
        for entry in VIVHITE_CARD_CATALOG:
            with self.subTest(card_id=entry.card_id):
                card = {
                    "card_id": entry.card_id,
                    "name": entry.name_zh,
                    "card_type": type_names[entry.card_type],
                    "rarity": entry.rarity.title(),
                    "energy_cost": (
                        0 if entry.mechanics.energy == "X"
                        else entry.mechanics.energy),
                    "costs_x": entry.mechanics.energy == "X",
                    "target_type": (
                        "AllEnemies" if entry.mechanics.all_enemies
                        else "AnyEnemy" if entry.card_type == "attack"
                        else "Self"),
                }
                detail: list[str] = []
                value = self.vivhite_policy.eval_reward_card(
                    card, [], detail=detail)
                self.assertTrue(isfinite(value))
                self.assertTrue(any(
                    "VIVHITE_NOMINAL_ESTIMATE" in row for row in detail))

    def test_live_estimate_uses_strict_low_hp_and_identifies_context(self) -> None:
        luminous = self._card(
            "VIVHITE_CARD_LUMINOUS_PROJECTION", "Attack", damage=10)
        at_boundary, boundary_note = (
            self.vivhite_policy._character_static_card_estimate(
                luminous, current_hp=35, max_hp=100))
        below_boundary, low_note = (
            self.vivhite_policy._character_static_card_estimate(
                luminous, current_hp=34, max_hp=100))

        self.assertEqual(at_boundary, -2.5)
        self.assertEqual(below_boundary, -5.0)
        self.assertIn("VIVHITE_LIVE_ESTIMATE", boundary_note)
        self.assertIn("hp-cost=2", low_note)
        self.assertEqual(
            self.ironclad_policy._character_static_card_estimate(
                luminous, current_hp=1, max_hp=100),
            (0.0, ""),
        )

    def test_reward_scoring_consumes_profile_estimate(self) -> None:
        axiom = self._card("VIVHITE_CARD_AXIOM_RING")
        detail: list[str] = []
        vivhite_value = self.vivhite_policy.eval_reward_card(
            axiom, [], max_hp=100, current_hp=100, detail=detail)
        ironclad_value = self.ironclad_policy.eval_reward_card(
            axiom, [], max_hp=100, current_hp=100)

        self.assertAlmostEqual(vivhite_value - ironclad_value, 3.75)
        self.assertTrue(any(
            "VIVHITE_LIVE_ESTIMATE=+3.75" in row for row in detail))

    def test_combat_ranking_consumes_profile_estimate(self) -> None:
        calls: list[str] = []

        def _base_score(*_args, **_kwargs):
            return 0.0, None, "shared-base"

        def _profile_estimate(card, **_kwargs):
            calls.append(card["card_id"])
            return 10.0, "VIVHITE_LIVE_ESTIMATE_TEST"

        self.vivhite_policy._score_play = _base_score
        self.vivhite_policy._character_static_card_estimate = _profile_estimate
        combat_token = {}
        state = {
            "screen": "COMBAT",
            "available_actions": ["play_card", "end_turn"],
            "turn": 1,
            "combat": {
                "player": {
                    "current_hp": 78,
                    "max_hp": 78,
                    "block": 0,
                    "energy": 3,
                    "powers": [],
                },
                "hand": [{
                    "index": 0,
                    "card_id": "VIVHITE_CARD_AXIOM_RING",
                    "name": "Axiom Ring",
                    "playable": True,
                    "energy_cost": 0,
                    "requires_target": False,
                    "dynamic_values": [],
                }],
                "enemies": [{
                    "index": 0,
                    "enemy_id": "TEST_ENEMY",
                    "name": "Test Enemy",
                    "current_hp": 20,
                    "max_hp": 20,
                    "block": 0,
                    "is_alive": True,
                    "is_hittable": True,
                    "intents": [],
                }],
            },
            "run": {
                "current_hp": 78,
                "max_hp": 78,
                "floor": 1,
                "deck": [],
            },
        }
        ctx = SimpleNamespace(
            combat=combat_token,
            current_combat_is_hard=False,
            stall_analysis_asked=False,
            stall_analysis_needed=False,
            stall_giveup=False,
        )

        decision = self.vivhite_policy._combat(state, ctx)

        self.assertEqual(decision.action, "play_card")
        self.assertEqual(calls, ["VIVHITE_CARD_AXIOM_RING"])
        self.assertIn("VIVHITE_LIVE_ESTIMATE_TEST", decision.reason)

    def test_vivhite_child_selection_prompts_have_explicit_semantics(self) -> None:
        cases = (
            ("combat_hand_select", "选择一张牌弃掉。",
             SELECTION_DISCARD_WORST),
            ("combat_hand_select", "选择一张手牌放到抽牌堆顶。",
             SELECTION_TOPDECK_BEST),
            ("combat_pile_select", "选择弃牌堆中的一张攻击牌返回手牌。",
             SELECTION_RECOVER_FREE_BEST),
            ("simple_grid", "选择本回合打出过的一张非能力牌进行复制。",
             SELECTION_COPY_FREE_BEST),
            ("combat_pile_select", "选择消耗牌堆中的一张非能力牌返回并复制。",
             SELECTION_RECOVER_COPY_BEST),
        )
        for kind, prompt, expected in cases:
            with self.subTest(prompt=prompt):
                self.assertEqual(
                    resolve_character_selection_mode(
                        VIVHITE_STRATEGY, kind=kind, prompt=prompt),
                    expected,
                )
                self.assertIsNone(resolve_character_selection_mode(
                    IRONCLAD_STRATEGY, kind=kind, prompt=prompt))

    def test_prefetch_discard_recovery_and_copy_do_not_reverse_pick(self) -> None:
        strong_attack = self._selection_card(
            1, "VIVHITE_CARD_LUMINOUS_PROJECTION", "Attack", damage=30)
        weak_status = self._selection_card(
            0, "TEST_STATUS", "Status")
        strong_skill = self._selection_card(
            1, "VIVHITE_CARD_GEODESIC_VEIL", "Skill", block=30,
            energy_cost=2)
        weak_skill = self._selection_card(
            0, "VIVHITE_CARD_CLOSED_DOMAIN_MAPPING", "Skill", block=1)
        ctx = SimpleNamespace(credit_tags=[])
        cases = (
            ("combat_hand_select", "选择一张牌弃掉。",
             [weak_status, strong_attack], 0, "card_discard"),
            ("combat_hand_select", "选择一张手牌放到抽牌堆顶。",
             [weak_status, strong_attack], 1, "card_top_pick"),
            ("combat_pile_select", "选择弃牌堆中的一张技能牌返回手牌。",
             [weak_skill, strong_skill], 1, "card_recover"),
            ("simple_grid", "选择本回合打出过的一张非能力牌进行复制。",
             [weak_status, strong_attack], 1, "card_copy"),
            ("combat_pile_select", "选择消耗牌堆中的一张非能力牌返回并复制。",
             [weak_status, strong_attack], 1, "card_recover_copy"),
        )
        for kind, prompt, cards, expected_index, expected_tag in cases:
            with self.subTest(prompt=prompt):
                decision = self.vivhite_policy._card_selection(
                    self._selection_state(kind, prompt, cards), ctx)
                self.assertEqual(decision.action, "select_deck_card")
                self.assertEqual(
                    decision.params["option_index"], expected_index)
                self.assertIn(expected_tag, [tag[0] for tag in decision.tags])

    def test_structural_reward_is_not_misclassified_as_discard_or_tribute(self) -> None:
        weak = self._selection_card(0, "TEST_STATUS", "Status")
        strong = self._selection_card(
            1, "VIVHITE_CARD_LUMINOUS_PROJECTION", "Attack", damage=30)
        state = self._selection_state(
            "combat_hand_select",
            "Choose a reward card; its rules may mention the Discard Pile.",
            [weak, strong],
            reward={
                "pending_card_choice": True,
                "card_options": [weak, strong],
            },
        )
        decision = self.vivhite_policy._card_selection(
            state, SimpleNamespace(credit_tags=[]))

        self.assertEqual(decision.action, "select_deck_card")
        self.assertEqual(decision.params["option_index"], 1)
        tags = [tag[0] for tag in decision.tags]
        self.assertNotIn("card_sacrifice", tags)
        self.assertNotIn("card_discard", tags)

    def test_accepted_selection_waits_at_stale_zero_and_accepted_one(self) -> None:
        cards = [
            self._selection_card(0, "TEST_STATUS", "Status"),
            self._selection_card(
                1, "VIVHITE_CARD_LUMINOUS_PROJECTION", "Attack", damage=30),
        ]
        state = self._selection_state(
            "combat_hand_select",
            "选择一张手牌放到抽牌堆顶。",
            cards,
        )
        ctx = SimpleNamespace(credit_tags=[])
        first = self.vivhite_policy._card_selection(state, ctx)
        self.assertEqual(first.action, "select_deck_card")
        self.assertEqual(first.params["option_index"], 1)

        ctx.credit_tags = list(first.tags)
        stale_zero = self.vivhite_policy._card_selection(state, ctx)
        self.assertIsNone(stale_zero.action)
        self.assertIn("等待结果刷新", stale_zero.reason)

        state["selection"]["selected_count"] = 1
        state["selection"]["can_confirm"] = False
        accepted_one = self.vivhite_policy._card_selection(state, ctx)
        self.assertIsNone(accepted_one.action)
        self.assertIn("避免连续点选", accepted_one.reason)

    def test_unplayable_life_cost_card_never_enters_settle_latent_roll(self) -> None:
        combat_token = object()
        ctx = SimpleNamespace(
            combat=combat_token,
            current_combat_is_hard=False,
            stall_analysis_asked=False,
            stall_analysis_needed=False,
            stall_giveup=False,
        )
        self.vivhite_policy._turn_combat = combat_token
        self.vivhite_policy._cur_turn = 1
        self.vivhite_policy._saw_playable_this_turn = True
        state = {
            "screen": "COMBAT",
            "available_actions": ["end_turn"],
            "turn": 1,
            "combat": {
                "player": {
                    "current_hp": 2,
                    "max_hp": 78,
                    "block": 0,
                    "energy": 1,
                    "powers": [],
                },
                "hand": [{
                    "index": 0,
                    "card_id": "VIVHITE_CARD_LAW_OF_CONSERVATION",
                    "name": "守恒定律",
                    "playable": False,
                    "unplayable_reason": "咳血后生命不足",
                    "energy_cost": 1,
                    "requires_target": False,
                    "dynamic_values": [
                        {"name": "LifeCost", "current_value": 6},
                    ],
                }],
                "enemies": [{
                    "index": 0,
                    "enemy_id": "TEST_ENEMY",
                    "name": "Test Enemy",
                    "current_hp": 20,
                    "max_hp": 20,
                    "block": 0,
                    "is_alive": True,
                    "is_hittable": True,
                    "intents": [],
                }],
            },
            "run": {
                "current_hp": 2,
                "max_hp": 78,
                "floor": 17,
                "deck": [],
            },
        }

        first = self.vivhite_policy._combat(state, ctx)
        second = self.vivhite_policy._combat(state, ctx)
        self.assertIsNone(first.action)
        self.assertIn("确认结束", first.reason)
        self.assertEqual(second.action, "end_turn")
        self.assertNotIn("结算等待", first.reason + second.reason)

    def test_new_turn_all_non_curse_cards_life_locked_ends_after_two_ticks(self) -> None:
        combat_token = object()
        ctx = SimpleNamespace(
            combat=combat_token,
            current_combat_is_hard=False,
            stall_analysis_asked=False,
            stall_analysis_needed=False,
            stall_giveup=False,
        )
        state = {
            "screen": "COMBAT",
            "available_actions": ["end_turn"],
            "turn": 1,
            "combat": {
                "player": {
                    "current_hp": 1,
                    "max_hp": 78,
                    "block": 0,
                    "energy": 3,
                    "powers": [],
                },
                "hand": [
                    {
                        "index": 0,
                        "card_id": "GUILTY",
                        "name": "愧疚",
                        "card_type": "Curse",
                        "rarity": "Curse",
                        "playable": False,
                        "energy_cost": -1,
                        "requires_target": False,
                        "dynamic_values": [],
                    },
                    {
                        "index": 1,
                        "card_id": "VIVHITE_CARD_LUMINOUS_PROJECTION",
                        "name": "弦光投影",
                        "card_type": "Attack",
                        "playable": False,
                        "energy_cost": 1,
                        "requires_target": True,
                        "valid_target_indices": [0],
                        "dynamic_values": [
                            {"name": "LifeCost", "current_value": 2},
                        ],
                    },
                    {
                        "index": 2,
                        "card_id": "VIVHITE_CARD_GOLDEN_RATIO",
                        "name": "黄金分割",
                        "card_type": "Skill",
                        "playable": False,
                        "energy_cost": 1,
                        "requires_target": False,
                        "dynamic_values": [
                            {"name": "LifeCost", "current_value": 4},
                        ],
                    },
                ],
                "enemies": [{
                    "index": 0,
                    "enemy_id": "TEST_ENEMY",
                    "name": "Test Enemy",
                    "current_hp": 20,
                    "max_hp": 20,
                    "block": 0,
                    "is_alive": True,
                    "is_hittable": True,
                    "intents": [],
                }],
            },
            "run": {
                "current_hp": 1,
                "max_hp": 78,
                "floor": 17,
                "deck": [],
            },
        }

        first = self.vivhite_policy._combat(state, ctx)
        second = self.vivhite_policy._combat(state, ctx)

        self.assertIsNone(first.action)
        self.assertIn("謦欬不可支付", first.reason)
        self.assertIn("1/2", first.reason)
        self.assertEqual(second.action, "end_turn")
        self.assertIn("謦欬会令生命低于1", second.reason)
        self.assertNotIn("手牌未就绪", first.reason + second.reason)

    def test_new_turn_unknown_unplayable_card_keeps_fifteen_tick_guard(self) -> None:
        combat_token = object()
        ctx = SimpleNamespace(
            combat=combat_token,
            current_combat_is_hard=False,
            stall_analysis_asked=False,
            stall_analysis_needed=False,
            stall_giveup=False,
        )
        state = {
            "screen": "COMBAT",
            "available_actions": ["end_turn"],
            "turn": 1,
            "combat": {
                "player": {
                    "current_hp": 3,
                    "max_hp": 78,
                    "block": 0,
                    "energy": 3,
                    "powers": [],
                },
                "hand": [{
                    "index": 0,
                    "card_id": "VIVHITE_CARD_CLOSED_DOMAIN_MAPPING",
                    "name": "闭域映射",
                    "card_type": "Skill",
                    "playable": False,
                    "energy_cost": 1,
                    "requires_target": False,
                    "dynamic_values": [
                        {"name": "LifeCost", "current_value": 2},
                    ],
                }],
                "enemies": [{
                    "index": 0,
                    "enemy_id": "TEST_ENEMY",
                    "name": "Test Enemy",
                    "current_hp": 20,
                    "max_hp": 20,
                    "block": 0,
                    "is_alive": True,
                    "is_hittable": True,
                    "intents": [],
                }],
            },
            "run": {
                "current_hp": 3,
                "max_hp": 78,
                "floor": 17,
                "deck": [],
            },
        }

        waits = [self.vivhite_policy._combat(state, ctx) for _ in range(14)]
        timeout = self.vivhite_policy._combat(state, ctx)

        self.assertTrue(all(decision.action is None for decision in waits))
        self.assertIn("14/15", waits[-1].reason)
        self.assertEqual(timeout.action, "end_turn")
        self.assertIn("手牌长时间未就绪", timeout.reason)

    def test_f17_ringing_native_hook_rejection_skips_forty_tick_settle(self) -> None:
        combat_token = object()
        ctx = SimpleNamespace(
            combat=combat_token,
            current_combat_is_hard=False,
            stall_analysis_asked=False,
            stall_analysis_needed=False,
            stall_giveup=False,
        )
        self.vivhite_policy._turn_combat = combat_token
        self.vivhite_policy._cur_turn = 1
        self.vivhite_policy._saw_playable_this_turn = True

        cards = [
            ("VIVHITE_CARD_TANGENT_STARLIGHT", "切线星光", 1, True),
            ("VIVHITE_CARD_ASTRAL_SEARCH", "星图检索", 0, False),
            ("VIVHITE_CARD_LUMINOUS_PROJECTION", "弦光投影", 1, True),
            ("VIVHITE_CARD_CHIAROSCURO", "明暗对照+", 1, False),
        ]
        hand = []
        for index, (card_id, name, cost, requires_target) in enumerate(cards):
            hand.append({
                "index": index,
                "card_id": card_id,
                "name": name,
                "card_type": "Attack" if requires_target else "Skill",
                "playable": False,
                "energy_cost": cost,
                "requires_target": requires_target,
                "valid_target_indices": [0] if requires_target else [],
                "unplayable_reason": "blocked_by_hook",
                "unplayable_reason_raw": "BlockedByHook",
                "unplayable_preventer_id": "RINGING_POWER",
                "unplayable_preventer_type": "RingingPower",
                "dynamic_values": [
                    {"name": "LifeCost", "current_value": 2},
                ],
            })
        state = {
            "screen": "COMBAT",
            "available_actions": ["end_turn"],
            "turn": 1,
            "combat": {
                "action_readiness": {
                    "can_use_combat_actions": True,
                    "reason": "ready",
                    "actions_settled": True,
                    "modal_open": False,
                },
                "player": {
                    "current_hp": 50,
                    "max_hp": 78,
                    "block": 0,
                    "energy": 1,
                    "powers": [{"power_id": "RINGING_POWER", "amount": 1}],
                },
                "hand": hand,
                "enemies": [{
                    "index": 0,
                    "enemy_id": "CEREMONIAL_BEAST",
                    "name": "Ceremonial Beast",
                    "current_hp": 100,
                    "max_hp": 100,
                    "block": 0,
                    "is_alive": True,
                    "is_hittable": True,
                    "intents": [],
                }],
            },
            "run": {"current_hp": 50, "max_hp": 78, "floor": 17, "deck": []},
        }

        first = self.vivhite_policy._combat(state, ctx)
        second = self.vivhite_policy._combat(state, ctx)

        self.assertIsNone(first.action)
        self.assertIn("确认结束", first.reason)
        self.assertEqual(second.action, "end_turn")
        self.assertNotIn("结算等待", first.reason + second.reason)
        self.assertIn("blocked_by_hook", second.reason)

    def test_missing_can_play_reason_keeps_settle_and_reports_queue_state(self) -> None:
        combat_token = object()
        ctx = SimpleNamespace(
            combat=combat_token,
            current_combat_is_hard=False,
            stall_analysis_asked=False,
            stall_analysis_needed=False,
            stall_giveup=False,
        )
        self.vivhite_policy._turn_combat = combat_token
        self.vivhite_policy._cur_turn = 1
        self.vivhite_policy._saw_playable_this_turn = True
        state = {
            "screen": "COMBAT",
            "available_actions": ["end_turn"],
            "turn": 1,
            "combat": {
                "action_readiness": {
                    "can_use_combat_actions": False,
                    "reason": "game_action_running",
                    "actions_settled": False,
                    "running_action_type": "TestQueuedAction",
                    "modal_open": False,
                },
                "player": {
                    "current_hp": 50,
                    "max_hp": 78,
                    "block": 0,
                    "energy": 1,
                    "powers": [],
                },
                "hand": [{
                    "index": 0,
                    "card_id": "VIVHITE_CARD_ASTRAL_SEARCH",
                    "name": "星图检索",
                    "card_type": "Skill",
                    "playable": False,
                    "energy_cost": 0,
                    "requires_target": False,
                    "dynamic_values": [
                        {"name": "LifeCost", "current_value": 2},
                    ],
                }],
                "enemies": [{
                    "index": 0, "enemy_id": "CEREMONIAL_BEAST",
                    "name": "Ceremonial Beast", "current_hp": 100,
                    "max_hp": 100, "block": 0, "is_alive": True,
                    "is_hittable": True, "intents": [],
                }],
            },
            "run": {"current_hp": 50, "max_hp": 78, "floor": 17, "deck": []},
        }

        decision = self.vivhite_policy._combat(state, ctx)

        self.assertIsNone(decision.action)
        self.assertIn("结算等待", decision.reason)
        self.assertIn("unknown_can_play", decision.reason)
        self.assertIn("接口状态=game_action_running", decision.reason)
        self.assertIn("1/40", decision.reason)

    def test_combat_targeting_expands_chromatic_limit_with_current_energy(self) -> None:
        card = {
            "index": 0,
            "card_id": "VIVHITE_CARD_CHROMATIC_LIMIT",
            "name": "绯彩极限",
            "playable": True,
            "costs_x": True,
            "energy_cost": 0,
            "requires_target": True,
            "target_type": "AnyEnemy",
            "valid_target_indices": [0, 1],
            "resolved_rules_text": "造成 9 点伤害 X 次。",
            "dynamic_values": [
                {"name": "LifeCost", "current_value": 8},
                {"name": "Damage", "current_value": 9},
                {"name": "DrainPerX", "current_value": 12},
            ],
        }
        enemies = [
            {
                "index": 0, "name": "Low", "current_hp": 20,
                "max_hp": 20, "block": 0, "intents": [],
            },
            {
                "index": 1, "name": "Threat", "current_hp": 100,
                "max_hp": 100, "block": 0,
                "intents": [{"total_damage": 10}],
            },
        ]
        _score, target, reason = self.vivhite_policy._score_play(
            card, enemies, 10, 0, 1, self.vivhite_knowledge.policy,
            my_hp=78, my_max_hp=78, stance={}, cur_energy=3,
            player_powers=[], observed_hand_count=1)
        self.assertEqual(target, 0)
        self.assertIn("可击杀Low", reason)

    def test_combat_scoring_passes_active_crimson_ritual_phases(self) -> None:
        card = {
            "index": 0,
            "card_id": "VIVHITE_CARD_LUMINOUS_PROJECTION",
            "name": "弦光投影",
            "playable": True,
            "energy_cost": 1,
            "requires_target": True,
            "target_type": "AnyEnemy",
            "valid_target_indices": [0],
            "dynamic_values": [
                {"name": "LifeCost", "current_value": 2},
                {"name": "Damage", "current_value": 10},
            ],
        }
        enemies = [{
            "index": 0, "name": "Ritual lethal", "current_hp": 12,
            "max_hp": 12, "block": 0, "intents": [],
        }]
        powers = [{
            "power_id": VIVHITE_CRIMSON_RITUAL_POWER_ID,
            "amount": 2,
        }]

        _score, target, reason = self.vivhite_policy._score_play(
            card, enemies, 0, 0, 1, self.vivhite_knowledge.policy,
            my_hp=78, my_max_hp=78, stance={}, cur_energy=3,
            player_powers=powers, observed_hand_count=1)

        self.assertEqual(target, 0)
        self.assertIn("可击杀Ritual lethal", reason)

    def test_policy_realized_scoring_is_linear_and_uncapped(self) -> None:
        actual = dict(
            current_hp=34,
            max_hp=100,
            life_cost_hp=10,
            margin_gained=100,
            drain_percent=250,
            drain_hp_restored=200,
            permanent_max_hp_gained=50,
            kill_hp_restored=300,
            cards_drawn=40,
            energy_gained=20,
            growth=10,
        )
        self.assertEqual(
            self.vivhite_policy.score_character_realized_mechanics(**actual),
            790.0,
        )
        self.assertEqual(
            self.ironclad_policy.score_character_realized_mechanics(**actual),
            0.0,
        )


if __name__ == "__main__":
    unittest.main()
