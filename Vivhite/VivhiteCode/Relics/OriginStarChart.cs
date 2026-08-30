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
    public override RelicRarity Rarity => RelicRarity.Starter;

    protected override IEnumerable<DynamicVar> CanonicalVars =>
    [
        new HealVar(4)
    ];

    // Keep the existing runtime icon until a dedicated OriginStarChart asset is supplied.
    public override RelicAssetProfile AssetProfile => new(
        IconPath: $"{Entry.ResPath}/images/relics/VivhiteRelic.png",
        IconOutlinePath: $"{Entry.ResPath}/images/relics/VivhiteRelic.png",
        BigIconPath: $"{Entry.ResPath}/images/relics/VivhiteRelic.png");

    protected override async Task OnAnyEnemyDeath(
        PlayerChoiceContext choiceContext,
        EnemyDeathEvent deathEvent)
    {
        await Overheal.HealAsync(Owner.Creature, DynamicVars.Heal.IntValue);
    }
}
