namespace Vivhite.Tests;

/// <summary>
/// Independent golden catalog from docs/2026-08-30-白绮角色与轮换大脑实现.md.
/// Production registration and localization must both converge on this exact set.
/// </summary>
internal static class ApprovedCardCatalog
{
    public static IReadOnlyDictionary<string, string> RarityById { get; } =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["VIVHITE_CARD_LUMINOUS_PROJECTION"] = "Basic",
            ["VIVHITE_CARD_CLOSED_DOMAIN_MAPPING"] = "Basic",
            ["VIVHITE_CARD_VIVHITE_TRANSFORMATION"] = "Basic",

            ["VIVHITE_CARD_AXIOM_RING"] = "Common",
            ["VIVHITE_CARD_CLOSED_PROJECTION"] = "Common",
            ["VIVHITE_CARD_TANGENT_STARLIGHT"] = "Common",
            ["VIVHITE_CARD_OPEN_SET_SHELTER"] = "Common",
            ["VIVHITE_CARD_LOCAL_HOMEOMORPHISM"] = "Common",
            ["VIVHITE_CARD_SCALE_TRANSFORMATION"] = "Common",
            ["VIVHITE_CARD_RECURRENT_STARLIGHT"] = "Common",
            ["VIVHITE_CARD_TERMINATION_CONDITION"] = "Common",
            ["VIVHITE_CARD_PARALLEL_STARFALL"] = "Common",
            ["VIVHITE_CARD_ASTRAL_SEARCH"] = "Common",
            ["VIVHITE_CARD_HEURISTIC_SHIELD"] = "Common",
            ["VIVHITE_CARD_SUCCESSOR_FORMULA"] = "Common",
            ["VIVHITE_CARD_CRIMSON_AREA"] = "Common",
            ["VIVHITE_CARD_TRICHROMATIC_WALTZ"] = "Common",
            ["VIVHITE_CARD_COMPOSITE_COLOR_WHEEL"] = "Common",
            ["VIVHITE_CARD_DIFFERENTIAL_SAMPLING"] = "Common",
            ["VIVHITE_CARD_CHIAROSCURO"] = "Common",
            ["VIVHITE_CARD_NEGATIVE_SPACE"] = "Common",

            ["VIVHITE_CARD_ISOPERIMETRIC_WARD"] = "Uncommon",
            ["VIVHITE_CARD_TOPOLOGICAL_GROWTH"] = "Uncommon",
            ["VIVHITE_CARD_LAW_OF_CONSERVATION"] = "Uncommon",
            ["VIVHITE_CARD_LIFE_MANIFOLD"] = "Uncommon",
            ["VIVHITE_CARD_MOBIUS_LOOP"] = "Uncommon",
            ["VIVHITE_CARD_INVARIANT"] = "Uncommon",
            ["VIVHITE_CARD_GEODESIC_VEIL"] = "Uncommon",
            ["VIVHITE_CARD_BACKTRACKING_SPELL"] = "Uncommon",
            ["VIVHITE_CARD_CONVERGENCE_VERDICT"] = "Uncommon",
            ["VIVHITE_CARD_DIVIDE_AND_CONQUER_CIRCLE"] = "Uncommon",
            ["VIVHITE_CARD_ASTRAL_PURSUIT"] = "Uncommon",
            ["VIVHITE_CARD_PREFETCH_FUTURE"] = "Uncommon",
            ["VIVHITE_CARD_INDUCTIVE_CIRCLE"] = "Uncommon",
            ["VIVHITE_CARD_EVENT_LOOP"] = "Uncommon",
            ["VIVHITE_CARD_SPECTRAL_INTEGRAL"] = "Uncommon",
            ["VIVHITE_CARD_GOLDEN_COMPOSITION"] = "Uncommon",
            ["VIVHITE_CARD_RIEMANN_STAR_ARRAY"] = "Uncommon",
            ["VIVHITE_CARD_CHROMATIC_TRANSITION"] = "Uncommon",
            ["VIVHITE_CARD_COLOR_CONSERVATION"] = "Uncommon",
            ["VIVHITE_CARD_COMPOSITE_COLOR_FIELD"] = "Uncommon",
            ["VIVHITE_CARD_COMPLEMENTARY_AFTERIMAGE"] = "Uncommon",
            ["VIVHITE_CARD_GOLDEN_RATIO"] = "Uncommon",
            ["VIVHITE_CARD_ASTRAL_MEASURE"] = "Uncommon",
            ["VIVHITE_CARD_CHROMATIC_SEQUENCE"] = "Uncommon",

            ["VIVHITE_CARD_CLOSED_MANIFOLD"] = "Rare",
            ["VIVHITE_CARD_AXIOM_OF_LIFE"] = "Rare",
            ["VIVHITE_CARD_INFINITE_EXTENSION"] = "Rare",
            ["VIVHITE_CARD_CONSERVATION_FIRMAMENT"] = "Rare",
            ["VIVHITE_CARD_PROOF_OF_TERMINATION"] = "Rare",
            ["VIVHITE_CARD_DYNAMIC_PROGRAMMING"] = "Rare",
            ["VIVHITE_CARD_INFINITE_STAR_SEQUENCE"] = "Rare",
            ["VIVHITE_CARD_OPTIMAL_ALGORITHM"] = "Rare",
            ["VIVHITE_CARD_DEFINITE_CRIMSON_INTEGRAL"] = "Rare",
            ["VIVHITE_CARD_CRIMSON_CONSERVATION_LAW"] = "Rare",
            ["VIVHITE_CARD_INFINITE_CANVAS"] = "Rare",
            ["VIVHITE_CARD_PERFECT_SYNTHESIS"] = "Rare",
            ["VIVHITE_CARD_UNIFIED_FIELD_THEORY"] = "Rare",
            ["VIVHITE_CARD_CONSERVED_RECURRENCE"] = "Rare",
            ["VIVHITE_CARD_CHROMATIC_LIMIT"] = "Rare",
            ["VIVHITE_CARD_VIVHITES_CRIMSON_TRANSFORMATION_RITUAL"] = "Rare"
        };
}
