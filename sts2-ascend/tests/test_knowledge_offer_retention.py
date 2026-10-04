"""Exposure facts survive learning decay without inventing lost old history."""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import tempfile
import unittest

BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))
import knowledge


class KnowledgeOfferRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ascend-offer-retention-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = knowledge.Knowledge(self.root, repair_phantoms=False)

    def _card(self, **values):
        entry = self.store._empty_card_stats()
        entry.update(values)
        self.store.stats["cards"]["CARD"] = entry
        return entry

    def test_unpicked_offer_survives_multiple_run_ends_and_matches_audit_total(self):
        self.assertEqual(self.store.commit_card_offer(["CARD", "card", "CARD+"]), 1)
        for _ in range(10):
            self.store.commit_run_end(10, False, [], [], [], None, None)
        entry = self.store.stats["cards"]["CARD"]
        self.assertEqual((entry["seen"], entry["offered"], entry["picked"]), (1, 1, 0))
        tracking = self.store.stats["card_offer_tracking"]
        self.assertEqual((tracking["offers"], tracking["candidate_observations"]), (1, 1))
        self.store.save()
        loaded = knowledge.Knowledge(self.root, repair_phantoms=False)
        self.assertEqual(loaded.stats["cards"]["CARD"]["offered"], 1)

    def test_new_offer_keeps_synchronous_counts_while_samples_decay_proportionally(self):
        entry = self._card(seen=10, offered=10, picked=10, plays=10,
                           outcome_sum=100, bias=2)
        self.store._decay_stats()
        self.store.commit_card_offer(["CARD"])
        self.assertEqual((entry["seen"], entry["offered"]), (11, 11))
        self.assertAlmostEqual(entry["picked"], 10 * knowledge.STAT_DECAY_PER_RUN)
        self.assertAlmostEqual(entry["plays"], 10 * knowledge.STAT_DECAY_PER_RUN)
        self.assertAlmostEqual(entry["outcome_sum"] / entry["picked"], 10)
        self.assertEqual(entry["bias"], 2)

    def test_legacy_fractional_counts_are_retained_without_truncation_or_backfill(self):
        entry = self._card(seen=10.4, offered=12.7, picked=2, plays=2, outcome_sum=20)
        self.store._decay_stats()
        self.assertEqual((entry["seen"], entry["offered"]), (10.4, 12.7))
        self.store.commit_card_seen("CARD")
        self.assertAlmostEqual(entry["seen"], 11.4)
        self.assertAlmostEqual(entry["offered"], 13.7)

    def test_old_outcome_noise_is_removed_without_deleting_bias_or_exposure(self):
        entry = self._card(seen=3, offered=3, picked=0.49, plays=0.49,
                           outcome_sum=100, bias=-1.5)
        self.store._decay_stats()
        self.assertIs(self.store.stats["cards"]["CARD"], entry)
        self.assertEqual((entry["picked"], entry["outcome_sum"], entry["plays"]), (0, 0, 0))
        self.assertEqual((entry["seen"], entry["offered"], entry["bias"]), (3, 3, -1.5))

    def test_pure_low_mass_sample_still_gets_pruned(self):
        self._card(picked=0.49, plays=0.49, outcome_sum=10)
        self.store._decay_stats()
        self.assertNotIn("CARD", self.store.stats["cards"])

    def test_successful_plays_without_pick_or_offer_remain_significant_evidence(self):
        entry = self._card(plays=3)
        self.store._decay_stats()
        self.assertIs(self.store.stats["cards"]["CARD"], entry)
        self.assertAlmostEqual(entry["plays"], 3 * knowledge.STAT_DECAY_PER_RUN)

    def test_retention_cutover_does_not_rewrite_legacy_counting_baseline(self):
        stats = copy.deepcopy(knowledge.DEFAULT_STATS)
        stats["global"]["runs"] = 10
        stats["card_offer_tracking"] = {
            "version": 2, "baseline_runs": 3, "offers": 20, "candidate_observations": 50}
        stats["cards"]["CARD"] = {**self.store._empty_card_stats(), "offered": 5.5}
        knowledge._save_json(self.root / "stats.json", stats)
        store = knowledge.Knowledge(self.root, repair_phantoms=False)
        self.assertEqual(store.stats["card_offer_tracking"]["baseline_runs"], 3)
        self.assertEqual(store.stats["card_offer_tracking"]["retention_baseline_runs"], 10)
        self.assertEqual(store.stats["cards"]["CARD"]["offered"], 5.5)
        store.save()
        loaded = knowledge.Knowledge(self.root, repair_phantoms=False)
        self.assertEqual(loaded.stats["card_offer_tracking"]["retention_baseline_runs"], 10)

    def test_legacy_baseline_recreates_retention_marker_before_new_run_decay(self):
        del self.store.stats["card_offer_tracking"]["retention_baseline_runs"]
        self.store.commit_run_end(10, False, [], [], [], None, None)
        self.assertEqual(self.store.stats["card_offer_tracking"]["retention_baseline_runs"], 0)

    def test_human_exclusion_restores_and_freezes_exposure_facts(self):
        self.store.begin_run_learning("mixed")
        self.store.commit_card_offer(["CARD"])
        self.store.exclude_run_learning("mixed")
        self.assertNotIn("CARD", self.store.stats["cards"])
        self.assertEqual(self.store.commit_card_offer(["CARD"]), 0)
        self.assertEqual(self.store.stats["card_offer_tracking"]["offers"], 0)


if __name__ == "__main__":
    unittest.main()
