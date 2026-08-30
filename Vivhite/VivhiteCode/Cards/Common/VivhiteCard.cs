using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Models;
using STS2RitsuLib.Scaffolding.Content;

namespace Vivhite.Cards.Common;

public static class VivhitePlaceholderArt
{
    public static string AttackPortraitPath =>
        global::Vivhite.Entry.ResPath + "/images/cards/VivhiteStrike.png";

    public static string NonAttackPortraitPath =>
        global::Vivhite.Entry.ResPath + "/images/cards/VivhiteDefend.png";

    public static string For(CardType cardType)
    {
        return cardType == CardType.Attack ? AttackPortraitPath : NonAttackPortraitPath;
    }
}

/// <summary>
/// Lightweight base shared by all Vivhite cards. It deliberately reuses the two checked-in
/// placeholder PNGs and exposes one extension point for native and mod-owned keywords.
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

    public override CardAssetProfile AssetProfile => new(
        PortraitPath: VivhitePlaceholderArt.For(Type));

    protected virtual IEnumerable<CardKeyword> VivhiteCanonicalKeywords => [];

    public sealed override IEnumerable<CardKeyword> CanonicalKeywords =>
        VivhiteCanonicalKeywords;

    protected int IntVar(string name)
    {
        return DynamicVars[name].IntValue;
    }
}
