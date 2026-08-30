using MegaCrit.Sts2.Core.Entities.Cards;
using STS2RitsuLib.Scaffolding.Content;

namespace Vivhite.Cards.Common;

/// <summary>
/// Lightweight base shared by all Vivhite cards. The inherited empty asset profile deliberately
/// lets RitsuLib supply its embedded card-art placeholder, while this base exposes one extension
/// point for native and mod-owned keywords.
/// </summary>
public abstract class VivhiteCard : ModCardTemplate
{
    protected VivhiteCard(
        int baseEnergyCost,
        CardType cardType,
        CardRarity rarity,
        TargetType targetType,
        bool shouldShowInCardLibrary = true)
        : base(baseEnergyCost, cardType, rarity, targetType, shouldShowInCardLibrary)
    {
    }

    protected virtual IEnumerable<CardKeyword> VivhiteCanonicalKeywords => [];

    public sealed override IEnumerable<CardKeyword> CanonicalKeywords =>
        VivhiteCanonicalKeywords;

    protected int IntVar(string name)
    {
        return DynamicVars[name].IntValue;
    }
}
