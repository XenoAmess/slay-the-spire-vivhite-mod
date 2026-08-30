"""Character strategy parameters, catalog, and uncapped scoring regressions."""
from __future__ import annotations

from collections import Counter
from dataclasses import FrozenInstanceError
from pathlib import Path
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
    VIVHITE_CARD_CATALOG,
    VIVHITE_CARD_IDS,
    VIVHITE_CHARACTER_ID,
    VIVHITE_PARAMETERS,
    VIVHITE_STRATEGY,
    CardMechanics,
    drain_healing_from_actual_damage,
    resolve_character_strategy,
    score_drain_healing,
    score_draw,
    score_growth,
    score_kill_healing,
    score_life_cost,
    score_margin,
    score_permanent_max_hp,
    score_realized_mechanics,
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
}


class CharacterStrategyCatalogTests(unittest.TestCase):
    def test_catalog_is_exactly_the_approved_60_ids(self) -> None:
        self.assertEqual(len(APPROVED_IDS), 60)
        self.assertEqual(len(VIVHITE_CARD_CATALOG), 60)
        self.assertEqual(VIVHITE_CARD_IDS, APPROVED_IDS)
        self.assertEqual(
            len({entry.stable_id for entry in VIVHITE_CARD_CATALOG}), 60)

    def test_exact_rarity_distribution_and_required_fields(self) -> None:
        self.assertEqual(
            Counter(entry.rarity for entry in VIVHITE_CARD_CATALOG),
            {"basic": 3, "common": 18, "uncommon": 24, "rare": 15},
        )
        for entry in VIVHITE_CARD_CATALOG:
            self.assertIn(entry.card_type, {"attack", "skill", "ability"})
            self.assertTrue(entry.name_en)
            self.assertTrue(entry.name_zh)
            self.assertTrue(set(entry.build_tags) <= BUILD_TAGS)
            self.assertTrue(entry.card_id.endswith(entry.stable_id))
            self.assertIsInstance(entry.mechanics, CardMechanics)

    def test_catalog_captures_representative_base_mechanics(self) -> None:
        luminous = VIVHITE_STRATEGY.card(
            "VIVHITE_CARD_LUMINOUS_PROJECTION")
        self.assertIsNotNone(luminous)
        self.assertEqual(luminous.mechanics.energy, 1)
        self.assertEqual(luminous.mechanics.life_calculation_cost, 1)
        self.assertEqual(luminous.mechanics.base_damage, 10)
        self.assertEqual(luminous.build_tags, (HYBRID,))

        scale = VIVHITE_STRATEGY.card(
            "VIVHITE_CARD_SCALE_TRANSFORMATION")
        self.assertEqual(scale.mechanics.max_hp_growth, 1)
        self.assertTrue(scale.mechanics.lethal)
        self.assertTrue(scale.mechanics.exhaust)
        self.assertEqual(scale.build_tags, (CONSERVATION_GEOMETRY,))

        termination = VIVHITE_STRATEGY.card(
            "VIVHITE_CARD_TERMINATION_CONDITION")
        self.assertEqual(termination.mechanics.kill_heal, 5)
        self.assertEqual(termination.build_tags, (RECURSIVE_ASTRAL,))

        optimal = VIVHITE_STRATEGY.card(
            "VIVHITE_CARD_OPTIMAL_ALGORITHM")
        self.assertEqual(
            (optimal.mechanics.kill_heal,
             optimal.mechanics.kill_draw,
             optimal.mechanics.kill_energy),
            (3, 2, 1),
        )

        synthesis = VIVHITE_STRATEGY.card(
            "VIVHITE_CARD_PERFECT_SYNTHESIS")
        self.assertEqual(synthesis.mechanics.base_damage, 11)
        self.assertEqual(synthesis.mechanics.damage_hits, 5)
        self.assertTrue(synthesis.mechanics.all_enemies)
        self.assertEqual(synthesis.mechanics.drain_percent, 40)
        self.assertEqual(synthesis.build_tags, (CRIMSON_INTEGRAL,))

        limit_card = VIVHITE_STRATEGY.card("VIVHITE_CARD_CHROMATIC_LIMIT")
        self.assertEqual(limit_card.mechanics.energy, "X")
        self.assertEqual(limit_card.mechanics.life_calculation_cost, 4)
        self.assertEqual(limit_card.mechanics.drain_percent, 15)
        self.assertEqual(limit_card.mechanics.drain_percent_mode, "per_x")

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

    def test_static_estimate_marks_non_telemetry_and_uses_strict_low_hp(self) -> None:
        luminous = self._card(
            "VIVHITE_CARD_LUMINOUS_PROJECTION", "Attack", damage=10)
        at_boundary, boundary_note = (
            self.vivhite_policy._character_static_card_estimate(
                luminous, current_hp=35, max_hp=100))
        below_boundary, low_note = (
            self.vivhite_policy._character_static_card_estimate(
                luminous, current_hp=34, max_hp=100))

        self.assertEqual(at_boundary, -1.25)
        self.assertEqual(below_boundary, -2.5)
        self.assertIn("VIVHITE_STATIC_ESTIMATE", boundary_note)
        self.assertIn("not-realized-margin/drain/kill-telemetry", low_note)
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

        self.assertAlmostEqual(vivhite_value - ironclad_value, 2.5)
        self.assertTrue(any(
            "VIVHITE_STATIC_ESTIMATE=+2.50" in row for row in detail))

    def test_combat_ranking_consumes_profile_estimate(self) -> None:
        calls: list[str] = []

        def _base_score(*_args, **_kwargs):
            return 0.0, None, "shared-base"

        def _profile_estimate(card, **_kwargs):
            calls.append(card["card_id"])
            return 10.0, "VIVHITE_STATIC_ESTIMATE_TEST"

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
        self.assertIn("VIVHITE_STATIC_ESTIMATE_TEST", decision.reason)

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
