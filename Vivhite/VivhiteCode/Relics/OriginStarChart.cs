using MegaCrit.Sts2.Core.Entities.Relics;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Localization.DynamicVars;
using STS2RitsuLib.Interop.AutoRegistration;
using STS2RitsuLib.Scaffolding.Content;
using Vivhite.Characters;
using Vivhite.Core;

namespace Vivhite.Relics;

[RegisterRelic(typeof(VivhiteRelicPool))]
[RegisterCharacterStarterRelic(typeof(VivhiteCharacter))]
public sealed class OriginStarChart : AnyEnemyDeathRelic
{
    private const int HealingPercent = 5;

    public override RelicRarity Rarity => RelicRarity.Starter;

    protected override IEnumerable<DynamicVar> CanonicalVars =>
    [
        new HealVar(HealingPercent)
    ];

    // Keep the existing runtime icon until a dedicated Solitary Crown asset is supplied.
    public override RelicAssetProfile AssetProfile => new(
        IconPath: $"{Entry.ResPath}/images/relics/VivhiteRelic.png",
        IconOutlinePath: $"{Entry.ResPath}/images/relics/VivhiteRelic.png",
        BigIconPath: $"{Entry.ResPath}/images/relics/VivhiteRelic.png");

    protected override async Task OnAnyEnemyDeath(
        PlayerChoiceContext choiceContext,
        EnemyDeathEvent deathEvent)
    {
        await Overheal.HealAsync(
            Owner.Creature,
            CalculateHealingForMaxHp(Owner.Creature.MaxHp));
    }

    internal static int CalculateHealingForMaxHp(int maxHp)
    {
        ArgumentOutOfRangeException.ThrowIfNegative(maxHp);
        return checked((int)(((long)maxHp * HealingPercent + 99L) / 100L));
    }
}
