using MegaCrit.Sts2.Core.Entities.Cards;
using STS2RitsuLib.Content;
using STS2RitsuLib.Interop.AutoRegistration;
using STS2RitsuLib.Keywords;

namespace Vivhite.Cards.Common;

public static class VivhiteKeywordStems
{
    public const string LifeCalculation = "LIFE_CALCULATION";
    public const string Margin = "MARGIN";
    public const string DimensionUp = "DIMENSION_UP";
    public const string Drain = "DRAIN";
    public const string Lethal = "LETHAL";
}

/// <summary>
/// RitsuLib scans one marker type and registers each keyword exactly once. Card descriptions
/// provide their own numeric clauses; these registrations provide the canonical hover tips.
/// </summary>
[RegisterOwnedCardKeyword(VivhiteKeywordStems.LifeCalculation)]
[RegisterOwnedCardKeyword(VivhiteKeywordStems.Margin)]
[RegisterOwnedCardKeyword(VivhiteKeywordStems.DimensionUp)]
[RegisterOwnedCardKeyword(VivhiteKeywordStems.Drain)]
[RegisterOwnedCardKeyword(VivhiteKeywordStems.Lethal)]
internal sealed class VivhiteKeywordRegistration;

public static class VivhiteKeywords
{
    public static CardKeyword LifeCalculation => Resolve(VivhiteKeywordStems.LifeCalculation);
    public static CardKeyword Margin => Resolve(VivhiteKeywordStems.Margin);
    public static CardKeyword DimensionUp => Resolve(VivhiteKeywordStems.DimensionUp);
    public static CardKeyword Drain => Resolve(VivhiteKeywordStems.Drain);
    public static CardKeyword Lethal => Resolve(VivhiteKeywordStems.Lethal);

    private static CardKeyword Resolve(string localStem)
    {
        return ModContentRegistry
            .GetQualifiedKeywordId(global::Vivhite.Entry.ModId, localStem)
            .GetModCardKeyword();
    }
}
