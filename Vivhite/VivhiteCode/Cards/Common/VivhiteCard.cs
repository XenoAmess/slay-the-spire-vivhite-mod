using MegaCrit.Sts2.Core.Entities.Cards;
using STS2RitsuLib.Scaffolding.Content;

namespace Vivhite.Cards.Common;

/// <summary>
/// Lightweight base shared by all Vivhite cards. Every registered card resolves to a dedicated,
/// mod-owned opaque portrait whose file name matches the compiled card type. Missing artwork is
/// therefore a packaging error instead of a silent RitsuLib-placeholder fallback.
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

    public sealed override string CustomPortraitPath =>
        $"{Entry.ResPath}/images/cards/{GetType().Name}.png";

    protected virtual IEnumerable<CardKeyword> VivhiteCanonicalKeywords => [];

    public sealed override IEnumerable<CardKeyword> CanonicalKeywords =>
        VivhiteCanonicalKeywords;

    protected int IntVar(string name)
    {
        return DynamicVars[name].IntValue;
    }
}
