"""Audit 09 composed-power contracts, using native damage-stage evidence.

Versioned source: knowledge/game/v0.111.0/mechanics/rules_commands.jsonl:12,
CreatureCmd.Damage(IEnumerable<Creature>, decimal, ...): Hook.ModifyDamage,
DamageBlockInternal, ModifyHpLost(BeforeOsty), ModifyHpLost(AfterOsty),
LoseHpInternal, then Hook.AfterDamageReceived. The power hooks are in
mechanics/powers.jsonl:115 (HardenedShellPower), :138 (IntangiblePower), and
:254 (SlipperyPower). Intangible.ModifyDamageCap returns 1 before block;
HardenedShell.ModifyHpLostBeforeOstyLate clamps HP loss to remaining allowance;
Slippery.ModifyHpLostAfterOsty clamps positive HP loss to 1 and its receipt hook
decrements a layer only when DamageResult.UnblockedDamage >= 1.

These are offline behavioral tests; native fact files remain read-only. Helpers
are from the original frozen audit module, not from model-added fixtures.
"""
from __future__ import annotations

import unittest

import test_policy_audit_contracts as audit


class NativeDamageOrderContracts(unittest.TestCase):
    def test_intangible_caps_damage_before_block_even_while_slippery_is_present(self) -> None:
        helper = audit.CombatAuditContracts()
        p = helper.make_policy()
        target = audit.enemy(hp=2, block=3, powers=[
            {"id": "SLIPPERY_POWER", "amount": 1},
            {"id": "INTANGIBLE_POWER", "amount": 1}])
        c = audit.card(0, "COMPOSED_NATIVE_AUDIT", damage=6, hits=3, targets=[0])
        result = helper.score(p, c, [target])
        score, _, why = result
        # Three one-damage hits remove exactly three block, zero HP, and no
        # Slippery layer. They cannot kill the target at two HP.
        self.assertEqual((score, why.startswith("可击杀")), (3.0, False), repr(result))
        self.assertIn("预计破0层", why, repr(result))

    def test_exhausted_hardened_shell_does_not_break_a_slippery_layer(self) -> None:
        helper = audit.CombatAuditContracts()
        p = helper.make_policy()
        target = audit.enemy(hp=10, powers=[
            {"id": "SLIPPERY_POWER", "amount": 1},
            {"id": "HARDENED_SHELL_POWER", "amount": 20, "display_amount": 0}])
        c = audit.card(0, "COMPOSED_NATIVE_AUDIT", damage=6, targets=[0])
        result = helper.score(p, c, [target])
        score, _, why = result
        self.assertEqual(score, 0.0, repr(result))
        # BeforeOsty has already reduced loss to zero. AfterDamageReceived sees
        # UnblockedDamage=0, so a proposed hit cannot claim any break credit.
        self.assertIn("预计破0层", why, repr(result))


if __name__ == "__main__":
    unittest.main()
