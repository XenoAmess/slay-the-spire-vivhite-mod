using System.Collections;
using System.Reflection;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Localization.DynamicVars;
using MegaCrit.Sts2.Core.Models;
using STS2RitsuLib.Scaffolding.Characters;
using STS2RitsuLib.Scaffolding.Content;
using Vivhite.Cards.Common;
using Vivhite.Characters;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests;

internal static class SharedAssetsAcceptanceTests
{
    public static void VivhiteAndIroncladUseTheSameV3Skin(RepositorySnapshot repository)
    {
        var validatedGetter = RequireDeclaredMethod(
            typeof(IroncladReplacementAssets),
            "GetValidatedV3Profile");
        var cachedField = typeof(IroncladReplacementAssets).GetField(
            "ValidatedV3Profile",
            BindingFlags.Static | BindingFlags.NonPublic);
        AcceptanceAssert.True(
            cachedField?.FieldType == typeof(Lazy<CharacterAssetProfile>),
            "The shared Ironclad V3 profile must be backed by one Lazy<CharacterAssetProfile> cache.");
        AcceptanceAssert.Equal(
            1,
            IlInspection.CalledMethods(validatedGetter).Count(method =>
                method.DeclaringType == typeof(Lazy<CharacterAssetProfile>) &&
                method.Name == "get_Value"),
            "GetValidatedV3Profile must return the single cached Lazy value.");

        var ironcladRegistration = RequireDeclaredMethod(
            typeof(IroncladReplacementAssets),
            "TryRegister");
        var vivhiteFactory = RequireDeclaredMethod(
            typeof(VivhiteCharacter),
            "CreateSharedAssetProfile");
        foreach (var consumer in new[] { ironcladRegistration, vivhiteFactory })
        {
            var calls = IlInspection.CalledMethods(consumer);
            AcceptanceAssert.Equal(
                1,
                calls.Count(method =>
                    method.DeclaringType == typeof(IroncladReplacementAssets) &&
                    method.Name == "GetValidatedV3Profile"),
                $"{consumer.DeclaringType?.Name}.{consumer.Name} must use the shared validated V3 entry once.");
            AcceptanceAssert.Equal(
                0,
                calls.Count(method =>
                    method.DeclaringType == typeof(IroncladReplacementAssets) &&
                    method.Name == "CreateProfile"),
                $"{consumer.DeclaringType?.Name}.{consumer.Name} must never call the unvalidated profile factory.");
        }

        var validatedFactory = RequireDeclaredMethod(
            typeof(IroncladReplacementAssets),
            "CreateValidatedV3Profile");
        var factoryCalls = IlInspection.CalledMethods(validatedFactory).ToArray();
        var validationIndex = Array.FindIndex(factoryCalls, method =>
            method.DeclaringType == typeof(IroncladReplacementAssets) &&
            method.Name == "ValidateRequiredAssets");
        var profileIndex = Array.FindIndex(factoryCalls, method =>
            method.DeclaringType == typeof(IroncladReplacementAssets) &&
            method.Name == "CreateProfile");
        AcceptanceAssert.True(
            validationIndex >= 0 && profileIndex > validationIndex,
            "The cached V3 entry must validate every required asset before constructing its profile.");

        var vivhiteCharacter = new VivhiteCharacter();
        AcceptanceAssert.Equal(78, vivhiteCharacter.StartingHp, "Vivhite starting HP must be 78.");
        AcceptanceAssert.Equal(3, vivhiteCharacter.MaxEnergy, "Vivhite must start each turn with 3 energy.");
        AcceptanceAssert.Equal(99, vivhiteCharacter.StartingGold, "Vivhite starting gold must be 99.");

        string[] v3Pages =
        [
            "vivhite_combat.png",
            "vivhite_combat_death.png",
            "vivhite_combat_attack.png",
            "vivhite_combat_attack_heavy.png",
            "vivhite_combat_cast.png"
        ];
        var missingPages = v3Pages
            .Select(page => Path.Combine(
                repository.GodotProjectDirectory,
                "skins",
                "ironclad",
                "spine",
                "combat",
                page))
            .Where(path => !File.Exists(path))
            .ToArray();
        AcceptanceAssert.Empty(missingPages, "The shared V3 five-page combat skin must exist on disk:");
    }

    public static void V3SkinRequiresExactFivePageLayout(RepositorySnapshot repository)
    {
        var skinType = typeof(IroncladReplacementAssets);
        var source = repository.RequireSourceType(skinType.FullName!).Declaration;
        AcceptanceAssert.True(
            source.DescendantTokens().All(token => token.ValueText != "LegacySinglePage"),
            "The production skin validator must not contain or accept a LegacySinglePage branch.");

        var expectedField = skinType.GetField(
            "V3CombatAtlasPages",
            BindingFlags.Static | BindingFlags.NonPublic)
            ?? throw new AcceptanceFailureException("V3CombatAtlasPages is missing.");
        var expectedPages = (Array?)expectedField.GetValue(null)
            ?? throw new AcceptanceFailureException("V3CombatAtlasPages is null.");
        string[] expectedNames =
        [
            "vivhite_combat.png",
            "vivhite_combat_death.png",
            "vivhite_combat_attack.png",
            "vivhite_combat_attack_heavy.png",
            "vivhite_combat_cast.png"
        ];
        var actualNames = expectedPages.Cast<object>()
            .Select(page => (string)GetRequiredProperty(page, "Name"))
            .ToArray();
        AcceptanceAssert.Equal(5, expectedPages.Length, "The only accepted combat atlas contract must have five pages.");
        AcceptanceAssert.True(
            actualNames.SequenceEqual(expectedNames, StringComparer.Ordinal),
            $"The V3 page order must be exact. Actual: [{string.Join(", ", actualNames)}]");

        var matcher = RequireDeclaredMethod(skinType, "MatchesAtlasContract");
        var complete = CreateParsedAtlasPages(skinType, expectedPages, expectedPages.Length);
        var missingOne = CreateParsedAtlasPages(skinType, expectedPages, expectedPages.Length - 1);
        AcceptanceAssert.True(
            (bool)matcher.Invoke(null, [complete, expectedPages])!,
            "The exact five-page V3 contract must match itself.");
        AcceptanceAssert.True(
            !(bool)matcher.Invoke(null, [missingOne, expectedPages])!,
            "A V3 atlas missing even one of its five pages must fail the production matcher.");

        var validator = RequireDeclaredMethod(skinType, "ValidateCombatAtlasContract");
        AcceptanceAssert.Equal(
            1,
            IlInspection.CalledMethods(validator).Count(method =>
                method.DeclaringType == skinType &&
                method.Name == "MatchesAtlasContract"),
            "The runtime atlas validator must gate acceptance through the strict V3 matcher.");

        var validatorSource = source.Members
            .OfType<MethodDeclarationSyntax>()
            .Single(method => method.Identifier.ValueText == "ValidateCombatAtlasContract");
        var matchingBranch = validatorSource.DescendantNodes()
            .OfType<IfStatementSyntax>()
            .Single(statement => statement.Condition.DescendantNodesAndSelf()
                .OfType<InvocationExpressionSyntax>()
                .Any(invocation => InvocationName(invocation) == "MatchesAtlasContract"));
        var rejectsMismatch = matchingBranch.Statement.DescendantNodesAndSelf()
                .OfType<ReturnStatementSyntax>()
                .Any() &&
            validatorSource.DescendantNodes()
                .OfType<InvocationExpressionSyntax>()
                .Any(invocation =>
                    invocation.SpanStart > matchingBranch.Span.End &&
                    InvocationName(invocation) == "Add");
        AcceptanceAssert.True(
            rejectsMismatch,
            "Only an exact five-page match may return success; every mismatch must add a validation issue.");
    }

    public static void CardPortraitsUseRitsuLibEmbeddedFallback(RepositorySnapshot repository)
    {
        const BindingFlags declaredInstance =
            BindingFlags.Instance |
            BindingFlags.Public |
            BindingFlags.NonPublic |
            BindingFlags.DeclaredOnly;
        AcceptanceAssert.True(
            typeof(VivhiteCard).GetProperty("AssetProfile", declaredInstance) is null &&
            typeof(VivhiteCard).GetProperty("CustomPortraitPath", declaredInstance) is null,
            "VivhiteCard must leave AssetProfile and CustomPortraitPath to ModCardTemplate's built-in fallback.");

        string fallbackPath = new RitsuLibFallbackProbe().CustomPortraitPath ??
            throw new AcceptanceFailureException("RitsuLib's ModCardTemplate fallback returned null CustomPortraitPath.");
        AcceptanceAssert.True(
            !string.IsNullOrWhiteSpace(fallbackPath),
            "RitsuLib's ModCardTemplate fallback must resolve to a non-empty CustomPortraitPath.");
        AcceptanceAssert.True(
            fallbackPath.Contains("card_art_placeholder", StringComparison.OrdinalIgnoreCase),
            $"RitsuLib's fallback path must identify its embedded card-art placeholder; actual: {fallbackPath}");

        var ritsuAssembly = typeof(ModCardTemplate).Assembly;
        var placeholderResources = ritsuAssembly.GetManifestResourceNames()
            .Where(name => name.EndsWith(".Assets.card_art_placeholder.png", StringComparison.OrdinalIgnoreCase))
            .ToArray();
        AcceptanceAssert.Equal(
            1,
            placeholderResources.Length,
            "The referenced RitsuLib assembly must contain exactly one embedded card-art placeholder PNG.");
        using (var stream = ritsuAssembly.GetManifestResourceStream(placeholderResources[0]))
        {
            AcceptanceAssert.True(stream is not null, "RitsuLib's embedded card-art placeholder stream must be readable.");
            Span<byte> signature = stackalloc byte[8];
            var bytesRead = stream!.Read(signature);
            byte[] pngSignature = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
            AcceptanceAssert.True(
                bytesRead == pngSignature.Length && signature.SequenceEqual(pngSignature),
                "RitsuLib's embedded card-art placeholder must be a readable PNG resource.");
        }

        var failures = new List<string>();
        foreach (var cardType in repository.VivhitePoolCards)
        {
            try
            {
                var card = (CardModel?)Activator.CreateInstance(cardType);
                if (card is null)
                {
                    failures.Add($"{cardType.FullName}: could not construct CardModel");
                    continue;
                }

                if (card is not ModCardTemplate modCard)
                {
                    failures.Add($"{repository.CardId(cardType)}: does not derive from ModCardTemplate");
                    continue;
                }

                if (!string.Equals(fallbackPath, modCard.CustomPortraitPath, StringComparison.Ordinal))
                {
                    failures.Add(
                        $"{repository.CardId(cardType)}: expected RitsuLib fallback {fallbackPath}, " +
                        $"actual {modCard.CustomPortraitPath ?? "<null>"}");
                }
            }
            catch (Exception exception)
            {
                failures.Add($"{cardType.FullName}: {exception.GetBaseException().Message}");
            }
        }
        AcceptanceAssert.Empty(
            failures,
            "Every Vivhite card must resolve CustomPortraitPath to RitsuLib's embedded placeholder exactly once:");
    }

    private static MethodInfo RequireDeclaredMethod(Type type, string name)
    {
        var methods = type.GetMethods(
                BindingFlags.Instance |
                BindingFlags.Static |
                BindingFlags.Public |
                BindingFlags.NonPublic |
                BindingFlags.DeclaredOnly)
            .Where(method => method.Name == name)
            .ToArray();
        if (methods.Length != 1)
        {
            throw new AcceptanceFailureException(
                $"{type.FullName}.{name} must resolve once; actual {methods.Length}.");
        }
        return methods[0];
    }

    private static object GetRequiredProperty(object target, string name) =>
        target.GetType().GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            ?.GetValue(target)
        ?? throw new AcceptanceFailureException($"{target.GetType().FullName}.{name} is unavailable.");

    private static IList CreateParsedAtlasPages(Type skinType, Array expectedPages, int count)
    {
        var parsedPageType = skinType.GetNestedType("ParsedAtlasPage", BindingFlags.NonPublic)
            ?? throw new AcceptanceFailureException("ParsedAtlasPage is missing.");
        var regionType = skinType.GetNestedType("AtlasRegionContract", BindingFlags.NonPublic)
            ?? throw new AcceptanceFailureException("AtlasRegionContract is missing.");
        var pages = (IList)(Activator.CreateInstance(typeof(List<>).MakeGenericType(parsedPageType))
            ?? throw new AcceptanceFailureException("Could not construct parsed-page list."));

        foreach (var expected in expectedPages.Cast<object>().Take(count))
        {
            var regions = (IList)(Activator.CreateInstance(typeof(List<>).MakeGenericType(regionType))
                ?? throw new AcceptanceFailureException("Could not construct parsed-region list."));
            foreach (var region in (Array)GetRequiredProperty(expected, "Regions"))
            {
                regions.Add(region);
            }

            var parsed = Activator.CreateInstance(
                parsedPageType,
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
                binder: null,
                args:
                [
                    GetRequiredProperty(expected, "Name"),
                    GetRequiredProperty(expected, "Width"),
                    GetRequiredProperty(expected, "Height"),
                    regions
                ],
                culture: null)
                ?? throw new AcceptanceFailureException("Could not construct ParsedAtlasPage.");
            pages.Add(parsed);
        }
        return pages;
    }

    private static string? InvocationName(InvocationExpressionSyntax invocation) =>
        invocation.Expression switch
        {
            SimpleNameSyntax name => name.Identifier.ValueText,
            MemberAccessExpressionSyntax access => access.Name.Identifier.ValueText,
            _ => null
        };

    private sealed class RitsuLibFallbackProbe()
        : ModCardTemplate(0, CardType.Skill, CardRarity.Basic, TargetType.Self, false)
    {
        protected override IEnumerable<DynamicVar> CanonicalVars => [];

        protected override Task OnPlay(PlayerChoiceContext choiceContext, CardPlay cardPlay) =>
            Task.CompletedTask;

        protected override void OnUpgrade()
        {
        }
    }
}
