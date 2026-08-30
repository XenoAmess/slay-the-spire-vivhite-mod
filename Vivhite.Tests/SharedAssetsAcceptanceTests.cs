using System.Collections;
using System.Reflection;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Localization.DynamicVars;
using MegaCrit.Sts2.Core.Models;
using STS2RitsuLib.Scaffolding.Characters;
using STS2RitsuLib.Scaffolding.Content;
using Vivhite.Characters;
using Vivhite.Relics;
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

    public static void EveryVivhiteCardUsesDedicatedOpaquePortraitArt(RepositorySnapshot repository)
    {
        string fallbackPath = new RitsuLibFallbackProbe().CustomPortraitPath ??
            throw new AcceptanceFailureException("RitsuLib's ModCardTemplate fallback returned null CustomPortraitPath.");
        var failures = new List<string>();
        var portraitPaths = new List<string>();
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

                var portraitFileName = $"{cardType.Name}.png";
                var expectedResourcePath = $"res://Vivhite/images/cards/{portraitFileName}";
                if (string.Equals(fallbackPath, modCard.CustomPortraitPath, StringComparison.Ordinal) ||
                    modCard.CustomPortraitPath?.Contains("placeholder", StringComparison.OrdinalIgnoreCase) == true ||
                    modCard.CustomPortraitPath?.Contains("fallback", StringComparison.OrdinalIgnoreCase) == true)
                {
                    failures.Add($"{repository.CardId(cardType)}: still resolves to fallback art {modCard.CustomPortraitPath}.");
                    continue;
                }

                if (!string.Equals(expectedResourcePath, modCard.CustomPortraitPath, StringComparison.Ordinal))
                {
                    failures.Add(
                        $"{repository.CardId(cardType)}: expected dedicated portrait {expectedResourcePath}, " +
                        $"actual {modCard.CustomPortraitPath ?? "<null>"}");
                    continue;
                }

                portraitPaths.Add(expectedResourcePath);
                var diskPath = Path.Combine(
                    repository.GodotProjectDirectory,
                    "images",
                    "cards",
                    portraitFileName);
                ValidateOpaqueCardPng(diskPath, repository.CardId(cardType), failures);
            }
            catch (Exception exception)
            {
                failures.Add($"{cardType.FullName}: {exception.GetBaseException().Message}");
            }
        }
        AcceptanceAssert.Equal(61, portraitPaths.Count, "All 61 Vivhite cards must resolve dedicated portraits.");
        AcceptanceAssert.Equal(
            61,
            portraitPaths.Distinct(StringComparer.Ordinal).Count(),
            "Every Vivhite card must own a distinct portrait resource path.");
        AcceptanceAssert.Empty(
            failures,
            "Vivhite card portraits must never fall back and must match the dedicated opaque-art contract:");
    }

    public static void SolitaryCrownUsesDedicatedRelicArt(RepositorySnapshot repository)
    {
        var profile = new OriginStarChart().AssetProfile;
        var paths = new[] { profile.IconPath, profile.IconOutlinePath, profile.BigIconPath };
        var failures = new List<string>();
        foreach (var path in paths)
        {
            if (string.IsNullOrWhiteSpace(path) ||
                !path.Contains("/images/relics/", StringComparison.Ordinal) ||
                !path.Contains("SolitaryCrown", StringComparison.Ordinal) ||
                path.Contains("VivhiteRelic", StringComparison.OrdinalIgnoreCase) ||
                path.Contains("placeholder", StringComparison.OrdinalIgnoreCase) ||
                path.Contains("fallback", StringComparison.OrdinalIgnoreCase))
            {
                failures.Add($"Solitary Crown uses a non-dedicated relic path: {path ?? "<null>"}");
                continue;
            }

            ValidatePackedPng(repository, path, "Solitary Crown", failures);
        }

        AcceptanceAssert.Empty(failures, "Solitary Crown must use existing dedicated relic art for every runtime icon size:");
    }

    private static void ValidateOpaqueCardPng(string path, string cardId, ICollection<string> failures)
    {
        if (!File.Exists(path))
        {
            failures.Add($"{cardId}: runtime portrait is missing: {path}");
            return;
        }

        using var stream = File.OpenRead(path);
        Span<byte> header = stackalloc byte[26];
        if (stream.Read(header) != header.Length)
        {
            failures.Add($"{cardId}: PNG header is truncated: {path}");
            return;
        }

        byte[] pngSignature = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
        if (!header[..8].SequenceEqual(pngSignature) ||
            !header[12..16].SequenceEqual("IHDR"u8))
        {
            failures.Add($"{cardId}: runtime portrait is not a PNG with an IHDR first chunk: {path}");
            return;
        }

        var width = ReadBigEndianUInt32(header[16..20]);
        var height = ReadBigEndianUInt32(header[20..24]);
        var bitDepth = header[24];
        var colorType = header[25];
        if (width != 1000 || height != 760 || bitDepth != 8 || colorType != 2)
        {
            failures.Add(
                $"{cardId}: expected opaque RGB8 PNG 1000x760, actual " +
                $"{width}x{height}, bit depth {bitDepth}, color type {colorType}: {path}");
        }
    }

    private static uint ReadBigEndianUInt32(ReadOnlySpan<byte> bytes) =>
        ((uint)bytes[0] << 24) |
        ((uint)bytes[1] << 16) |
        ((uint)bytes[2] << 8) |
        bytes[3];

    private static void ValidatePackedPng(
        RepositorySnapshot repository,
        string resourcePath,
        string label,
        ICollection<string> failures)
    {
        const string prefix = "res://Vivhite/";
        if (!resourcePath.StartsWith(prefix, StringComparison.Ordinal))
        {
            failures.Add($"{label}: resource is outside the Vivhite pack: {resourcePath}");
            return;
        }

        var diskPath = Path.Combine(
            repository.GodotProjectDirectory,
            resourcePath[prefix.Length..].Replace('/', Path.DirectorySeparatorChar));
        if (!File.Exists(diskPath))
        {
            failures.Add($"{label}: PNG resource is missing: {diskPath}");
            return;
        }

        using var stream = File.OpenRead(diskPath);
        Span<byte> signature = stackalloc byte[8];
        byte[] expected = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
        if (stream.Read(signature) != signature.Length || !signature.SequenceEqual(expected))
        {
            failures.Add($"{label}: resource is not a readable PNG: {diskPath}");
        }
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
