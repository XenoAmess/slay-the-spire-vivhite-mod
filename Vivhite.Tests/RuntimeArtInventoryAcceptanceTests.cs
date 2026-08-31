using System.Buffers.Binary;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using STS2RitsuLib.Scaffolding.Characters;
using STS2RitsuLib.Scaffolding.Content;
using Vivhite.Characters;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests;

internal static class RuntimeArtInventoryAcceptanceTests
{
    private static readonly string[] CardNames =
    [
        "LuminousProjection", "ClosedDomainMapping", "VivhiteTransformation",
        "AxiomRing", "ClosedProjection", "TangentStarlight", "OpenSetShelter",
        "LocalHomeomorphism", "ScaleTransformation", "IsoperimetricWard",
        "TopologicalGrowth", "LawOfConservation", "LifeManifold", "MobiusLoop",
        "Invariant", "GeodesicVeil", "ClosedManifold", "AxiomOfLife",
        "InfiniteExtension", "ConservationFirmament", "RecurrentStarlight",
        "TerminationCondition", "ParallelStarfall", "AstralSearch",
        "HeuristicShield", "SuccessorFormula", "BacktrackingSpell",
        "ConvergenceVerdict", "DivideAndConquerCircle", "AstralPursuit",
        "PrefetchFuture", "InductiveCircle", "EventLoop", "ProofOfTermination",
        "DynamicProgramming", "InfiniteStarSequence", "OptimalAlgorithm",
        "CrimsonArea", "TrichromaticWaltz", "CompositeColorWheel",
        "DifferentialSampling", "Chiaroscuro", "NegativeSpace",
        "SpectralIntegral", "GoldenComposition", "RiemannStarArray",
        "ChromaticTransition", "ColorConservation", "CompositeColorField",
        "ComplementaryAfterimage", "DefiniteCrimsonIntegral",
        "CrimsonConservationLaw", "InfiniteCanvas", "PerfectSynthesis",
        "GoldenRatio", "AstralMeasure", "ChromaticSequence", "UnifiedFieldTheory",
        "ConservedRecurrence", "ChromaticLimit",
        "VivhitesCrimsonTransformationRitual"
    ];

    private static readonly string[] SemanticPowerNames =
    [
        "AstralPursuitMarginPower", "AstralPursuitPower", "ChiaroscuroPower",
        "ClosedManifoldPower", "ColorConservationPower",
        "CrimsonConservationLawPower", "DynamicProgrammingPower",
        "InductiveCirclePower", "InfiniteCanvasPower",
        "InfiniteDimensionalityPower", "InfiniteDrainPower",
        "InfiniteDrainThisTurnPower", "InfiniteExtensionPower",
        "InfiniteMarginPower", "LawOfConservationPower", "LifeManifoldPower",
        "OptimalAlgorithmPower", "UnifiedFieldTheoryPower",
        "VivhitesCrimsonTransformationRitualPower"
    ];

    private static readonly IReadOnlyDictionary<string, string> PowerIconByRuntimeType =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["AstralPursuitMarginPower"] = "AstralPursuitMarginPower",
            ["AstralPursuitPower"] = "AstralPursuitPower",
            ["ChiaroscuroPower"] = "ChiaroscuroPower",
            ["ClosedManifoldPower"] = "ClosedManifoldPower",
            ["ColorConservationPower"] = "ColorConservationPower",
            ["CrimsonConservationLawPower"] = "CrimsonConservationLawPower",
            ["CrimsonConservationLawUpgradedPower"] = "CrimsonConservationLawPower",
            ["DynamicProgrammingPower"] = "DynamicProgrammingPower",
            ["InductiveCirclePower"] = "InductiveCirclePower",
            ["InfiniteCanvasPower"] = "InfiniteCanvasPower",
            ["InfiniteCanvasUpgradedPower"] = "InfiniteCanvasPower",
            ["InfiniteDimensionalityPower"] = "InfiniteDimensionalityPower",
            ["InfiniteDrainPower"] = "InfiniteDrainPower",
            ["InfiniteDrainThisTurnPower"] = "InfiniteDrainThisTurnPower",
            ["InfiniteExtensionPower"] = "InfiniteExtensionPower",
            ["InfiniteMarginPower"] = "InfiniteMarginPower",
            ["LawOfConservationPower"] = "LawOfConservationPower",
            ["LifeManifoldPower"] = "LifeManifoldPower",
            ["OptimalAlgorithmPower"] = "OptimalAlgorithmPower",
            ["UnifiedFieldTheoryPower"] = "UnifiedFieldTheoryPower",
            ["UnifiedFieldTheoryUpgradedPower"] = "UnifiedFieldTheoryPower",
            ["VivhitesCrimsonTransformationRitualPower"] =
                "VivhitesCrimsonTransformationRitualPower",
            ["VivhitesCrimsonTransformationRitualUpgradedPower"] =
                "VivhitesCrimsonTransformationRitualPower"
        };

    private static readonly string[] SolitaryCrownNames =
        ["SolitaryCrown", "SolitaryCrownOutline"];

    private static readonly EnergyAsset[] EnergyAssets =
    [
        new("Vivhite_energy_orb_layer_1", 256, 256),
        new("Vivhite_energy_orb_layer_2", 256, 256),
        new("Vivhite_energy_orb_layer_3", 256, 256),
        new("Vivhite_energy_orb_layer_4", 256, 256),
        new("Vivhite_energy_orb_layer_5", 256, 256),
        new("energy_big", 256, 256),
        new("energy_text", 24, 24)
    ];

    private static readonly EnergySceneLayer[] EnergySceneLayers =
    [
        new(
            "1_layer1",
            "res://Vivhite/images/characters/Vivhite_energy_orb_layer_1.png",
            "Layer1",
            "Layers"),
        new(
            "2_layer2",
            "res://Vivhite/images/characters/Vivhite_energy_orb_layer_2.png",
            "Layer2",
            "Layers/RotationLayers"),
        new(
            "3_layer3",
            "res://Vivhite/images/characters/Vivhite_energy_orb_layer_3.png",
            "Layer3",
            "Layers/RotationLayers"),
        new(
            "4_layer4",
            "res://Vivhite/images/characters/Vivhite_energy_orb_layer_4.png",
            "Layer4",
            "Layers"),
        new(
            "5_layer5",
            "res://Vivhite/images/characters/Vivhite_energy_orb_layer_5.png",
            "Layer5",
            "Layers")
    ];

    private static readonly string[] RetiredRuntimePlaceholderPaths =
    [
        "images/cards/VivhiteStrike.png",
        "images/cards/VivhiteDefend.png",
        "images/relics/VivhiteRelic.png",
        "images/characters/Vivhite_character_select.png",
        "images/characters/Vivhite_character_icon.png",
        "images/characters/Vivhite_character_icon_outline.png",
        "images/characters/Vivhite_character_select_locked.png",
        "images/characters/Vivhite_map_marker.png",
        "scenes/characters/Vivhite_character.tscn",
        "scenes/characters/Vivhite_merchant.tscn",
        "scenes/characters/Vivhite_rest_site.tscn",
        "scenes/characters/Vivhite_character_select_bg.tscn"
    ];

    private static readonly string[] ExpectedTwiceReferencedSkinPngs =
    [
        "spine/combat/vivhite_combat.png",
        "scenes/vfx/vivhite_eye_lens_glint.png",
        "transitions/vivhite_character_select_transition.png",
        "ui/icon.png",
        "ui/icon_outline.png",
        "ui/select.png",
        "ui/select_locked.png",
        "ui/map_marker.png",
        "multiplayer/point.png",
        "multiplayer/rock.png",
        "multiplayer/paper.png",
        "multiplayer/scissors.png"
    ];

    private const byte MeaningfulAlphaThreshold = 16;
    private const byte NearOpaqueAlphaThreshold = 224;
    private const byte StrongBoundaryAlphaThreshold = 64;

    // These are byte hashes of previously used runtime fallbacks/templates. Some of
    // them satisfy dimensions and Alpha checks, so structure alone cannot reject them.
    private static readonly IReadOnlyDictionary<string, string> KnownPlaceholderHashes =
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["64483bc9497fad10fdb1fbc89b8ae4e395412703c30cc0e71b84d0b48dd90490"] =
                "RitsuLib card_art_placeholder",
            ["5a0be66752f8d26bd857f11b4e78fb490ac47c93819c259cd8f363dfb73a11e7"] =
                "legacy red energy layer 1",
            ["ded01ebbdf6532f70c338ba3b573e235e26ea73e2fa0c50954c9818ebd6584f6"] =
                "legacy red energy layer 2",
            ["55d944fa7ca5c248bca7670625699368062b26972da9b3aea312022a98907496"] =
                "legacy red energy layer 3",
            ["e59534bb60b30ce517c5d16db715ae460a03330e20fde5ac3f31708eebc52b75"] =
                "legacy red energy layer 4",
            ["12b55e14a01ab7ba318b1a0d77615dfebb18e18aa00580d4ccbcf75eba478ea5"] =
                "legacy red energy layer 5",
            ["4cd2a3ae8fbc7b4369c495597a933ac2a5eaf28dceddb64bc30f2f5375491290"] =
                "legacy red energy_text",
            ["9071a1f2d4cfdc6e4b90c59d5b5cc65e2ca7e1b6da902d275804d5a31f188fc2"] =
                "legacy shared fire / red NOPE-style power-relic fallback",
            ["decdc1380438eb01fc8448e8e294699cc386b761137184e214af6cffd3039d8c"] =
                "retired Vivhite Strike card placeholder",
            ["4b5c76a2463a8db99e435c3817936b88738a8f571d3f85e7850fd2dfeb5eb225"] =
                "retired Vivhite Defend card placeholder"
        };

    public static void CoversExactNinetyTwoRuntimeAssets(RepositorySnapshot repository)
    {
        AcceptanceAssert.Equal(61, CardNames.Length, "The runtime-art card inventory must remain fixed at 61.");
        AcceptanceAssert.Equal(19, SemanticPowerNames.Length, "The semantic power-art inventory must remain fixed at 19.");
        AcceptanceAssert.Equal(2, SolitaryCrownNames.Length, "Solitary Crown must own exactly two runtime images.");
        AcceptanceAssert.Equal(7, EnergyAssets.Length, "Vivhite must own exactly seven runtime energy images.");

        var inventory = BuildInventory(repository);
        AcceptanceAssert.Equal(92, inventory.Count, "Runtime art must total 61 cards + 19 powers + 2 crown + 7 energy + 3 VFX images.");
        AssertCategoryCount(inventory, "card", 61);
        AssertCategoryCount(inventory, "power", 19);
        AssertCategoryCount(inventory, "relic", 2);
        AssertCategoryCount(inventory, "energy", 7);
        AssertCategoryCount(inventory, "vfx", 3);

        var duplicatePaths = inventory
            .GroupBy(asset => asset.Path, StringComparer.OrdinalIgnoreCase)
            .Where(group => group.Count() > 1)
            .Select(group => $"{group.Key}: {string.Join(", ", group.Select(asset => asset.Category))}")
            .ToArray();
        AcceptanceAssert.Empty(duplicatePaths, "Each of the 92 inventory entries must resolve to a distinct file:");

        VerifyRuntimeMappings(repository);

        var failures = new List<string>();
        var warnings = new List<string>();
        var firstPathByHash = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var asset in inventory)
        {
            ValidateAsset(asset, firstPathByHash, failures, warnings);
        }

        foreach (var warning in warnings)
        {
            Console.WriteLine($"[WARN] Runtime art Alpha boundary: {warning}");
        }

        AcceptanceAssert.Empty(
            failures,
            "All 92 Vivhite runtime images must satisfy their dedicated format, Alpha, uniqueness, and no-placeholder contracts:");
    }

    public static void EyeLensGlintKeepsTransparentAlphaClassesDistinct(RepositorySnapshot repository)
    {
        var path = Path.Combine(
            repository.GodotProjectDirectory,
            "skins",
            "ironclad",
            "scenes",
            "vfx",
            "vivhite_eye_lens_glint.png");
        var failures = new List<string>();
        var warnings = new List<string>();
        ValidateAsset(
            new RuntimeAsset("combat-vfx", "VivhiteEyeLensGlint", path, 512, 512, IsOpaque: false),
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase),
            failures,
            warnings);
        AcceptanceAssert.Empty(
            failures,
            "The eye-lens glint must remain a valid transparent RGBA8 VFX asset:");
        AcceptanceAssert.Empty(
            warnings,
            "The eye-lens glint must keep every non-zero Alpha component away from the canvas edge:");

        var png = ReadPng(path);
        var pixels = DecodePngPixels(png, bytesPerPixel: 4);
        var alphaValues = Enumerable.Range(0, checked(png.Width * png.Height))
            .Select(index => pixels[index * 4 + 3])
            .ToArray();
        var nearOpaqueCount = alphaValues.Count(alpha => alpha == 254);
        var fullyOpaqueSampleCount = alphaValues.Count(alpha => alpha == byte.MaxValue);
        AcceptanceAssert.Equal(
            22,
            nearOpaqueCount,
            "A=254 samples must be counted as near-opaque, never folded into the A=255 class.");
        AcceptanceAssert.Equal(
            27,
            fullyOpaqueSampleCount,
            "The accepted runtime PNG currently contains exactly 27 genuine A=255 samples.");
        AcceptanceAssert.True(
            alphaValues.Any(alpha => alpha == 0) && alphaValues.Any(alpha => alpha > 0),
            "Interior A=255 samples do not make the RGBA VFX fully opaque; its canvas must remain transparent.");
    }

    public static void HasNoRetiredRuntimePlaceholdersOrPngOrphans(RepositorySnapshot repository)
    {
        var retiredFilesStillPresent = RetiredRuntimePlaceholderPaths
            .Select(relativePath => Path.Combine(
                repository.GodotProjectDirectory,
                relativePath.Replace('/', Path.DirectorySeparatorChar)))
            .Where(File.Exists)
            .Select(path => Path.GetRelativePath(repository.RootDirectory, path).Replace('\\', '/'))
            .Order(StringComparer.Ordinal)
            .ToArray();
        AcceptanceAssert.Empty(
            retiredFilesStillPresent,
            "Retired Vivhite placeholders and their self-contained legacy scenes must stay out of the runtime project:");

        // Runtime semantics and the skin contract are intentionally constructed through
        // independent sources. Do not merge either list before validating its own shape.
        var runtimePngReferences = BuildInventory(repository)
            .Select(asset => NormalizeFilePath(asset.Path))
            .ToArray();
        AcceptanceAssert.Equal(
            92,
            runtimePngReferences.Length,
            "The independently constructed semantic runtime inventory must contain exactly 92 PNG references.");
        var duplicateRuntimePngReferences = runtimePngReferences
            .GroupBy(path => path, StringComparer.OrdinalIgnoreCase)
            .Where(group => group.Count() != 1)
            .Select(group => $"{group.Key}: {group.Count()} references")
            .Order(StringComparer.Ordinal)
            .ToArray();
        AcceptanceAssert.Empty(
            duplicateRuntimePngReferences,
            "The 92 semantic runtime PNG references must be path-unique before any skin-contract merge:");
        var runtimePngSet = runtimePngReferences.ToHashSet(StringComparer.OrdinalIgnoreCase);
        AcceptanceAssert.Equal(
            92,
            runtimePngSet.Count,
            "The semantic runtime PNG set must remain exactly 92 after duplicate rejection.");

        var contractPath = Path.Combine(
            repository.RootDirectory,
            "Vivhite",
            "tools",
            "ironclad-skin.contract.json");
        using var contract = JsonDocument.Parse(File.ReadAllBytes(contractPath));
        var contractRoot = contract.RootElement;
        var skinRoot = Path.Combine(repository.GodotProjectDirectory, "skins", "ironclad");
        var contractPngReferences = new List<string>(30);

        void AddSkinPngReference(string relativePath)
        {
            AcceptanceAssert.True(
                relativePath.EndsWith(".png", StringComparison.OrdinalIgnoreCase),
                $"Skin-contract PNG reference must end in .png: {relativePath}");
            contractPngReferences.Add(NormalizeFilePath(Path.Combine(
                skinRoot,
                relativePath.Replace('/', Path.DirectorySeparatorChar))));
        }

        var v3Layout = contractRoot.GetProperty("combatRuntimeLayouts")
            .EnumerateArray()
            .Single(layout => string.Equals(
                layout.GetProperty("name").GetString(),
                "v3-five-page",
                StringComparison.Ordinal));
        foreach (var page in v3Layout.GetProperty("pages").EnumerateArray())
        {
            AddSkinPngReference(page.GetProperty("path").GetString() ?? string.Empty);
        }
        foreach (var resource in contractRoot.GetProperty("requiredResources").EnumerateArray())
        {
            var relativePath = resource.GetString() ?? string.Empty;
            if (relativePath.EndsWith(".png", StringComparison.OrdinalIgnoreCase))
            {
                AddSkinPngReference(relativePath);
            }
        }
        foreach (var dimension in contractRoot.GetProperty("pngDimensions").EnumerateArray())
        {
            AddSkinPngReference(dimension.GetProperty("path").GetString() ?? string.Empty);
        }

        AcceptanceAssert.Equal(
            30,
            contractPngReferences.Count,
            "The real V3 skin contract must expose exactly 30 PNG references across pages, required resources, and dimension records.");
        var contractPngGroups = contractPngReferences
            .GroupBy(path => path, StringComparer.OrdinalIgnoreCase)
            .ToArray();
        AcceptanceAssert.Equal(
            18,
            contractPngGroups.Length,
            "The 30 real skin-contract PNG references must resolve to exactly 18 unique files.");
        AcceptanceAssert.Equal(
            6,
            contractPngGroups.Count(group => group.Count() == 1),
            "Exactly six skin PNGs must be referenced once by the contract.");
        AcceptanceAssert.Equal(
            12,
            contractPngGroups.Count(group => group.Count() == 2),
            "Exactly twelve skin PNGs must be referenced twice by the contract.");
        var unexpectedContractMultiplicities = contractPngGroups
            .Where(group => group.Count() is not (1 or 2))
            .Select(group => $"{group.Key}: {group.Count()} references")
            .Order(StringComparer.Ordinal)
            .ToArray();
        AcceptanceAssert.Empty(
            unexpectedContractMultiplicities,
            "No skin PNG may occur with a multiplicity outside the approved six-singleton/twelve-double structure:");
        var expectedTwiceReferencedSkinPngs = ExpectedTwiceReferencedSkinPngs
            .Select(relativePath => NormalizeFilePath(Path.Combine(
                skinRoot,
                relativePath.Replace('/', Path.DirectorySeparatorChar))))
            .Order(StringComparer.Ordinal)
            .ToArray();
        var actualTwiceReferencedSkinPngs = contractPngGroups
            .Where(group => group.Count() == 2)
            .Select(group => group.Key)
            .Order(StringComparer.Ordinal)
            .ToArray();
        AcceptanceAssert.SetEqual(
            expectedTwiceReferencedSkinPngs,
            actualTwiceReferencedSkinPngs,
            "The contract's twelve duplicated PNG references must be the approved page/resource/dimension overlaps.");

        var contractPngSet = contractPngGroups
            .Select(group => group.Key)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        var runtimeSkinIntersection = runtimePngSet
            .Intersect(contractPngSet, StringComparer.OrdinalIgnoreCase)
            .Order(StringComparer.Ordinal)
            .ToArray();
        var expectedRuntimeSkinIntersection = new[]
        {
            NormalizeFilePath(Path.Combine(
                skinRoot,
                "scenes", "vfx", "vivhite_eye_lens_glint.png")),
            NormalizeFilePath(Path.Combine(
                skinRoot,
                "transitions", "vivhite_character_select_transition.png"))
        }.Order(StringComparer.Ordinal).ToArray();
        AcceptanceAssert.Equal(
            2,
            runtimeSkinIntersection.Length,
            "The semantic runtime and skin-contract PNG sets must intersect in exactly two files.");
        AcceptanceAssert.SetEqual(
            expectedRuntimeSkinIntersection,
            runtimeSkinIntersection,
            "The only runtime/skin overlap must be the eye-lens glint and character-select transition.");

        var contractExclusivePngs = contractPngSet
            .Except(runtimePngSet, StringComparer.OrdinalIgnoreCase)
            .Order(StringComparer.Ordinal)
            .ToArray();
        AcceptanceAssert.Equal(
            16,
            contractExclusivePngs.Length,
            "After removing the exact two-file overlap, the real skin contract must own exactly 16 PNGs outside the semantic runtime inventory.");

        var expectedProjectPngSet = runtimePngSet
            .Union(contractPngSet, StringComparer.OrdinalIgnoreCase)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        AcceptanceAssert.Equal(
            108,
            expectedProjectPngSet.Count,
            "The independently validated 92 runtime and 18 skin PNG sets with a two-file overlap must union to exactly 108 files.");
        var actualProjectPngs = Directory
            .EnumerateFiles(repository.GodotProjectDirectory, "*.png", SearchOption.AllDirectories)
            .Select(NormalizeFilePath)
            .ToArray();
        var duplicateActualProjectPngs = actualProjectPngs
            .GroupBy(path => path, StringComparer.OrdinalIgnoreCase)
            .Where(group => group.Count() != 1)
            .Select(group => $"{group.Key}: {group.Count()} filesystem entries")
            .Order(StringComparer.Ordinal)
            .ToArray();
        AcceptanceAssert.Empty(
            duplicateActualProjectPngs,
            "The materialized project PNG scan must not contain path duplicates:");
        var actualProjectPngSet = actualProjectPngs.ToHashSet(StringComparer.OrdinalIgnoreCase);
        AcceptanceAssert.Equal(
            108,
            actualProjectPngSet.Count,
            "The cleaned Vivhite Godot project must contain exactly 108 unique PNG files.");
        var missingProjectPngs = expectedProjectPngSet
            .Except(actualProjectPngSet, StringComparer.OrdinalIgnoreCase)
            .Order(StringComparer.Ordinal)
            .ToArray();
        var extraProjectPngs = actualProjectPngSet
            .Except(expectedProjectPngSet, StringComparer.OrdinalIgnoreCase)
            .Order(StringComparer.Ordinal)
            .ToArray();
        AcceptanceAssert.Empty(
            missingProjectPngs,
            "Every independently derived runtime/skin PNG must exist in the project; missing files:");
        AcceptanceAssert.Empty(
            extraProjectPngs,
            "Every project PNG must belong to the independently derived runtime or skin set; orphan/extra files:");
    }

    private static IReadOnlyList<RuntimeAsset> BuildInventory(RepositorySnapshot repository)
    {
        var imagesRoot = Path.Combine(repository.GodotProjectDirectory, "images");
        var assets = new List<RuntimeAsset>(92);
        assets.AddRange(CardNames.Select(name => new RuntimeAsset(
            "card",
            name,
            Path.Combine(imagesRoot, "cards", $"{name}.png"),
            1000,
            760,
            IsOpaque: true)));
        assets.AddRange(SemanticPowerNames.Select(name => new RuntimeAsset(
            "power",
            name,
            Path.Combine(imagesRoot, "powers", $"{name}.png"),
            256,
            256,
            IsOpaque: false)));
        assets.AddRange(SolitaryCrownNames.Select(name => new RuntimeAsset(
            "relic",
            name,
            Path.Combine(imagesRoot, "relics", $"{name}.png"),
            256,
            256,
            IsOpaque: false)));
        assets.AddRange(EnergyAssets.Select(asset => new RuntimeAsset(
            "energy",
            asset.Name,
            Path.Combine(imagesRoot, "characters", $"{asset.Name}.png"),
            asset.Width,
            asset.Height,
            IsOpaque: false)));
        assets.Add(new RuntimeAsset(
            "vfx",
            "VivhiteEyeLensGlint",
            Path.Combine(
                repository.GodotProjectDirectory,
                "skins", "ironclad", "scenes", "vfx", "vivhite_eye_lens_glint.png"),
            512,
            512,
            IsOpaque: false));
        assets.Add(new RuntimeAsset(
            "vfx",
            "VivhiteCharacterSelectTransition",
            Path.Combine(
                repository.GodotProjectDirectory,
                "skins", "ironclad", "transitions", "vivhite_character_select_transition.png"),
            2560,
            1200,
            IsOpaque: true,
            RequiresStrictGrayscale: true));
        assets.Add(new RuntimeAsset(
            "vfx",
            "VivhiteCardTrailMathematicalStar",
            Path.Combine(imagesRoot, "vfx", "vivhite_card_trail_mathematical_star_0194.png"),
            256,
            256,
            IsOpaque: false));
        return assets;
    }

    private static string NormalizeFilePath(string path) =>
        Path.GetFullPath(path).Replace('\\', '/');

    private static void AssertCategoryCount(
        IReadOnlyCollection<RuntimeAsset> inventory,
        string category,
        int expected)
    {
        AcceptanceAssert.Equal(
            expected,
            inventory.Count(asset => asset.Category == category),
            $"Runtime-art category '{category}' has the wrong number of files.");
    }

    private static void VerifyRuntimeMappings(RepositorySnapshot repository)
    {
        AcceptanceAssert.Equal(61, repository.RegisteredCards.Count, "Runtime registration must expose exactly 61 Vivhite cards.");
        AcceptanceAssert.Equal(61, repository.VivhitePoolCards.Count, "All 61 registered cards must belong to the Vivhite card pool.");
        AcceptanceAssert.SetEqual(
            CardNames,
            repository.RegisteredCards.Select(type => type.Name).ToArray(),
            "The 61 card-art files must exactly match the registered card type names.");
        AcceptanceAssert.SetEqual(
            CardNames,
            repository.VivhitePoolCards.Select(type => type.Name).ToArray(),
            "No registered card may escape the 61-file Vivhite art inventory.");

        var cardMappingFailures = new List<string>();
        foreach (var cardType in repository.RegisteredCards)
        {
            try
            {
                if (Activator.CreateInstance(cardType) is not ModCardTemplate card)
                {
                    cardMappingFailures.Add($"{cardType.FullName}: is not a ModCardTemplate");
                    continue;
                }

                var expectedPath = $"res://Vivhite/images/cards/{cardType.Name}.png";
                if (!string.Equals(expectedPath, card.CustomPortraitPath, StringComparison.Ordinal))
                {
                    cardMappingFailures.Add(
                        $"{repository.CardId(cardType)}: expected {expectedPath}, actual {card.CustomPortraitPath ?? "<null>"}");
                }
            }
            catch (Exception exception)
            {
                cardMappingFailures.Add($"{cardType.FullName}: {exception.GetBaseException().Message}");
            }
        }
        AcceptanceAssert.Empty(cardMappingFailures, "Every registered card must consume its same-named inventory image:");

        AcceptanceAssert.Equal(23, repository.RegisteredPowers.Count, "Runtime registration must expose the audited 23 power types.");
        AcceptanceAssert.Equal(23, PowerIconByRuntimeType.Count, "The explicit power-art mapping must contain exactly 23 runtime types.");
        AcceptanceAssert.SetEqual(
            PowerIconByRuntimeType.Keys.ToArray(),
            repository.RegisteredPowers.Select(type => type.Name).ToArray(),
            "Every registered Power type must have one explicit semantic-icon mapping, with no inferred or orphan mapping.");
        var mappedSemanticPowerNames = PowerIconByRuntimeType.Values
            .Distinct(StringComparer.Ordinal)
            .Order(StringComparer.Ordinal)
            .ToArray();
        AcceptanceAssert.Equal(19, mappedSemanticPowerNames.Length, "The explicit 23-type mapping must target exactly 19 semantic icons.");
        AcceptanceAssert.SetEqual(
            SemanticPowerNames,
            mappedSemanticPowerNames,
            "The explicit Power mapping must cover all and only the 19 audited semantic icons.");

        var expectedPowerPaths = SemanticPowerNames
            .Select(name => $"res://Vivhite/images/powers/{name}.png")
            .Order(StringComparer.Ordinal)
            .ToArray();
        var smallPowerPaths = new HashSet<string>(StringComparer.Ordinal);
        var bigPowerPaths = new HashSet<string>(StringComparer.Ordinal);
        var powerMappingFailures = new List<string>();
        foreach (var powerType in repository.RegisteredPowers)
        {
            try
            {
                if (Activator.CreateInstance(powerType) is not ModPowerTemplate power)
                {
                    powerMappingFailures.Add($"{powerType.FullName}: is not a ModPowerTemplate");
                    continue;
                }

                if (!PowerIconByRuntimeType.TryGetValue(powerType.Name, out var semanticIcon))
                {
                    powerMappingFailures.Add($"{powerType.FullName}: has no explicit semantic-icon mapping");
                    continue;
                }

                var expectedPath = $"res://Vivhite/images/powers/{semanticIcon}.png";
                var profile = power.AssetProfile;
                if (!string.Equals(expectedPath, profile.IconPath, StringComparison.Ordinal))
                {
                    powerMappingFailures.Add(
                        $"{repository.PowerId(powerType)} small icon: expected {expectedPath}, actual {profile.IconPath ?? "<null>"}");
                }
                if (!string.Equals(expectedPath, profile.BigIconPath, StringComparison.Ordinal))
                {
                    powerMappingFailures.Add(
                        $"{repository.PowerId(powerType)} large icon: expected {expectedPath}, actual {profile.BigIconPath ?? "<null>"}");
                }
                if (profile.IconPath is not null)
                {
                    smallPowerPaths.Add(profile.IconPath);
                }
                if (profile.BigIconPath is not null)
                {
                    bigPowerPaths.Add(profile.BigIconPath);
                }
            }
            catch (Exception exception)
            {
                powerMappingFailures.Add($"{powerType.FullName}: {exception.GetBaseException().Message}");
            }
        }
        AcceptanceAssert.Empty(powerMappingFailures, "Every registered power type must resolve its folded semantic icon:");
        AcceptanceAssert.SetEqual(expectedPowerPaths, smallPowerPaths.ToArray(), "Small power icons must cover exactly 19 semantic files.");
        AcceptanceAssert.SetEqual(expectedPowerPaths, bigPowerPaths.ToArray(), "Large power icons must cover exactly 19 semantic files.");

        AcceptanceAssert.Equal(1, repository.RegisteredRelics.Count, "The runtime art gate expects one registered Vivhite starter relic.");
        var relic = Activator.CreateInstance(repository.RegisteredRelics.Single()) as ModRelicTemplate
            ?? throw new AcceptanceFailureException("The registered Solitary Crown relic is not a ModRelicTemplate.");
        var relicPaths = new[]
        {
            relic.AssetProfile.IconPath,
            relic.AssetProfile.IconOutlinePath,
            relic.AssetProfile.BigIconPath
        }
            .Where(path => path is not null)
            .Cast<string>()
            .Distinct(StringComparer.Ordinal)
            .ToArray();
        AcceptanceAssert.SetEqual(
            SolitaryCrownNames.Select(name => $"res://Vivhite/images/relics/{name}.png").ToArray(),
            relicPaths,
            "Solitary Crown must consume exactly its color and outline images.");

        VerifyEnergyMappings(repository);
    }

    private static void VerifyEnergyMappings(RepositorySnapshot repository)
    {
        var expectedBig = "res://Vivhite/images/characters/energy_big.png";
        var expectedText = "res://Vivhite/images/characters/energy_text.png";
        var pools = new (string Name, string? Big, string? Text)[]
        {
            (nameof(VivhiteCardPool), new VivhiteCardPool().BigEnergyIconPath, new VivhiteCardPool().TextEnergyIconPath),
            (nameof(VivhiteRelicPool), new VivhiteRelicPool().BigEnergyIconPath, new VivhiteRelicPool().TextEnergyIconPath),
            (nameof(VivhitePotionPool), new VivhitePotionPool().BigEnergyIconPath, new VivhitePotionPool().TextEnergyIconPath)
        };
        var poolFailures = pools
            .Where(pool => !string.Equals(pool.Big, expectedBig, StringComparison.Ordinal) ||
                !string.Equals(pool.Text, expectedText, StringComparison.Ordinal))
            .Select(pool => $"{pool.Name}: expected {expectedBig} / {expectedText}, actual {pool.Big ?? "<null>"} / {pool.Text ?? "<null>"}")
            .ToArray();
        AcceptanceAssert.Empty(poolFailures, "Every Vivhite content pool must consume the same two energy UI files:");

        const string expectedSceneResourcePath =
            "res://Vivhite/scenes/characters/Vivhite_energy_counter.tscn";
        var sceneResourcePath = ResolveCharacterEnergyCounterPath(repository);
        AcceptanceAssert.Equal(
            expectedSceneResourcePath,
            sceneResourcePath,
            "The inventory must audit the exact energy scene consumed by VivhiteCharacter.AssetProfile.");

        var scenePath = ResolveVivhiteResourcePath(repository, sceneResourcePath);
        AcceptanceAssert.True(File.Exists(scenePath), $"Vivhite energy-counter scene is missing: {scenePath}");
        var scene = File.ReadAllText(scenePath, Encoding.UTF8);
        VerifyEnergySceneTextureContract(sceneResourcePath, scene);
    }

    private static string ResolveCharacterEnergyCounterPath(RepositorySnapshot repository)
    {
        var source = repository.RequireSourceType(typeof(VivhiteCharacter).FullName!).Declaration;
        var assetProfileProperty = source.Members
            .OfType<PropertyDeclarationSyntax>()
            .Single(property => property.Identifier.ValueText == nameof(VivhiteCharacter.AssetProfile));
        var assetProfileIdentifiers = assetProfileProperty.DescendantNodes()
            .OfType<IdentifierNameSyntax>()
            .Select(identifier => identifier.Identifier.ValueText)
            .ToArray();
        AcceptanceAssert.True(
            assetProfileIdentifiers.Contains("_assetProfile", StringComparer.Ordinal) &&
            assetProfileIdentifiers.Contains("CreateSharedAssetProfile", StringComparer.Ordinal),
            "VivhiteCharacter.AssetProfile must expose its cached CreateSharedAssetProfile result.");

        var factory = source.Members
            .OfType<MethodDeclarationSyntax>()
            .Single(method => method.Identifier.ValueText == "CreateSharedAssetProfile");
        var energyAssignment = factory.DescendantNodes()
            .OfType<AssignmentExpressionSyntax>()
            .SingleOrDefault(assignment =>
                assignment.Left is IdentifierNameSyntax left &&
                left.Identifier.ValueText == "EnergyCounterPath" &&
                assignment.Right is IdentifierNameSyntax right &&
                right.Identifier.ValueText == "EnergyCounterScenePath" &&
                assignment.Ancestors().OfType<WithExpressionSyntax>().Any());
        AcceptanceAssert.True(
            energyAssignment is not null,
            "CreateSharedAssetProfile must assign EnergyCounterScenePath into Scenes.EnergyCounterPath.");
        AcceptanceAssert.True(
            factory.DescendantNodes()
                .OfType<InvocationExpressionSyntax>()
                .Any(invocation =>
                    invocation.Expression is MemberAccessExpressionSyntax access &&
                    access.Expression is IdentifierNameSyntax owner &&
                    owner.Identifier.ValueText == nameof(CharacterAssetProfiles) &&
                    access.Name.Identifier.ValueText == nameof(CharacterAssetProfiles.WithScenes)),
            "CreateSharedAssetProfile must publish the overridden scene set through CharacterAssetProfiles.WithScenes.");

        var scenePathField = typeof(VivhiteCharacter).GetField(
            "EnergyCounterScenePath",
            BindingFlags.Static | BindingFlags.NonPublic)
            ?? throw new AcceptanceFailureException(
                "VivhiteCharacter.EnergyCounterScenePath is missing from the compiled runtime type.");
        var compiledScenePath = scenePathField.GetRawConstantValue() as string
            ?? throw new AcceptanceFailureException(
                "VivhiteCharacter.EnergyCounterScenePath must remain a compiled string constant.");
        var cacheField = typeof(VivhiteCharacter).GetField(
            "_assetProfile",
            BindingFlags.Static | BindingFlags.NonPublic)
            ?? throw new AcceptanceFailureException(
                "VivhiteCharacter._assetProfile cache is missing from the compiled runtime type.");

        // The production factory first validates textures through Godot APIs. A plain .NET
        // acceptance process cannot call those native APIs, so seed the same structural base
        // profile into the production cache, then read the real public AssetProfile chain.
        var originalProfile = cacheField.GetValue(null);
        try
        {
            var baseProfile = IroncladReplacementAssets.CreateProfile();
            var baseScenes = baseProfile.Scenes
                ?? throw new AcceptanceFailureException(
                    "The structural Ironclad profile has no scene asset set.");
            var seededProfile = CharacterAssetProfiles.WithScenes(
                baseProfile,
                baseScenes with { EnergyCounterPath = compiledScenePath });
            cacheField.SetValue(null, seededProfile);
            return new VivhiteCharacter().AssetProfile.Scenes?.EnergyCounterPath
                ?? throw new AcceptanceFailureException(
                    "VivhiteCharacter.AssetProfile.Scenes.EnergyCounterPath is missing.");
        }
        finally
        {
            cacheField.SetValue(null, originalProfile);
        }
    }

    private static string ResolveVivhiteResourcePath(
        RepositorySnapshot repository,
        string resourcePath)
    {
        const string prefix = "res://Vivhite/";
        AcceptanceAssert.True(
            resourcePath.StartsWith(prefix, StringComparison.Ordinal),
            $"Runtime resource must stay inside the Vivhite pack: {resourcePath}");
        var relative = resourcePath[prefix.Length..].Replace('/', Path.DirectorySeparatorChar);
        var projectRoot = Path.GetFullPath(repository.GodotProjectDirectory)
            .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) +
            Path.DirectorySeparatorChar;
        var resolved = Path.GetFullPath(Path.Combine(projectRoot, relative));
        AcceptanceAssert.True(
            resolved.StartsWith(projectRoot, StringComparison.OrdinalIgnoreCase),
            $"Runtime resource escapes the Vivhite project directory: {resourcePath}");
        return resolved;
    }

    private static void VerifyEnergySceneTextureContract(
        string sceneResourcePath,
        string scene)
    {
        var failures = new List<string>();
        var resources = ParseSceneExternalResources(scene, failures);
        var duplicateResourceIds = resources
            .GroupBy(resource => resource.Id, StringComparer.Ordinal)
            .Where(group => group.Count() > 1)
            .Select(group => group.Key)
            .ToArray();
        foreach (var duplicateId in duplicateResourceIds)
        {
            failures.Add($"duplicate ext_resource id '{duplicateId}'");
        }

        var textureResources = resources
            .Where(resource => IsTextureResource(resource.Type, resource.Path))
            .ToArray();
        var declaredTextureIds = textureResources
            .Select(resource => resource.Id)
            .ToHashSet(StringComparer.Ordinal);
        var expectedIds = EnergySceneLayers.Select(layer => layer.ResourceId).ToArray();
        var actualIds = textureResources.Select(resource => resource.Id).ToArray();
        AddSetDifference(
            expectedIds,
            actualIds,
            "texture ext_resource declarations",
            failures);

        foreach (var layer in EnergySceneLayers)
        {
            var matches = textureResources
                .Where(resource => resource.Id == layer.ResourceId)
                .ToArray();
            if (matches.Length != 1)
            {
                failures.Add(
                    $"{layer.ResourceId}: expected one Texture2D declaration, actual {matches.Length}");
                continue;
            }

            var resource = matches[0];
            if (!string.Equals(resource.Type, "Texture2D", StringComparison.Ordinal))
            {
                failures.Add(
                    $"{layer.ResourceId}: expected type Texture2D, actual {resource.Type}");
            }
            if (!string.Equals(resource.Path, layer.ResourcePath, StringComparison.Ordinal))
            {
                failures.Add(
                    $"{layer.ResourceId}: expected path {layer.ResourcePath}, actual {resource.Path}");
            }
        }

        foreach (var subresource in ParseSceneSubresources(scene, failures)
                     .Where(subresource =>
                         subresource.Type.Contains("Texture", StringComparison.Ordinal)))
        {
            failures.Add(
                $"unexpected texture sub_resource '{subresource.Id}' of type {subresource.Type}");
        }

        var nodes = ParseSceneNodes(scene, failures)
            .Select(node => node with
            {
                TextureReferences = node.TextureReferences
                    .Where(reference =>
                        reference.ResourceKind == "ExtResource" &&
                        declaredTextureIds.Contains(reference.ResourceId) ||
                        IsTextureProperty(reference.Property))
                    .ToArray()
            })
            .ToArray();
        var textureNodes = nodes
            .Where(node => IsTextureNodeType(node.Type) || node.TextureReferences.Count > 0)
            .ToArray();
        var expectedNodeKeys = EnergySceneLayers.Select(layer => layer.NodeKey).ToArray();
        var actualNodeKeys = textureNodes.Select(node => node.NodeKey).ToArray();
        AddSetDifference(
            expectedNodeKeys,
            actualNodeKeys,
            "texture-consuming scene nodes",
            failures);

        foreach (var layer in EnergySceneLayers)
        {
            var matches = textureNodes
                .Where(node => node.NodeKey == layer.NodeKey)
                .ToArray();
            if (matches.Length != 1)
            {
                failures.Add(
                    $"{layer.NodeKey}: expected one TextureRect node, actual {matches.Length}");
                continue;
            }

            var node = matches[0];
            if (!string.Equals(node.Type, "TextureRect", StringComparison.Ordinal))
            {
                failures.Add($"{layer.NodeKey}: expected type TextureRect, actual {node.Type}");
            }
            if (node.TextureReferences.Count != 1 ||
                !string.Equals(node.TextureReferences[0].Property, "texture", StringComparison.Ordinal) ||
                !string.Equals(node.TextureReferences[0].ResourceKind, "ExtResource", StringComparison.Ordinal) ||
                !string.Equals(node.TextureReferences[0].ResourceId, layer.ResourceId, StringComparison.Ordinal))
            {
                failures.Add(
                    $"{layer.NodeKey}: expected texture = ExtResource(\"{layer.ResourceId}\"), actual " +
                    FormatTextureReferences(node.TextureReferences));
            }
        }

        var allTextureReferences = nodes
            .SelectMany(node => node.TextureReferences.Select(reference => (Node: node, Reference: reference)))
            .ToArray();
        foreach (var resource in textureResources)
        {
            var consumers = allTextureReferences
                .Where(item =>
                    item.Reference.ResourceKind == "ExtResource" &&
                    item.Reference.ResourceId == resource.Id)
                .ToArray();
            if (consumers.Length != 1)
            {
                failures.Add(
                    $"ext_resource '{resource.Id}' must be consumed exactly once, actual {consumers.Length}: " +
                    string.Join(", ", consumers.Select(item => item.Node.NodeKey)));
            }
        }

        foreach (var item in allTextureReferences)
        {
            if (item.Reference.ResourceKind != "ExtResource" ||
                !declaredTextureIds.Contains(item.Reference.ResourceId))
            {
                failures.Add(
                    $"{item.Node.NodeKey}.{item.Reference.Property} consumes undeclared/non-texture " +
                    $"{item.Reference.ResourceKind} '{item.Reference.ResourceId}'");
            }
        }

        AcceptanceAssert.Empty(
            failures,
            $"Energy scene {sceneResourcePath} must declare and consume all and only its five audited texture layers:");
    }

    private static SceneExternalResource[] ParseSceneExternalResources(
        string scene,
        ICollection<string> failures)
    {
        var resources = new List<SceneExternalResource>();
        foreach (Match match in Regex.Matches(
                     scene,
                     @"(?m)^\[ext_resource(?<attributes>[^\]]*)\]\s*$",
                     RegexOptions.CultureInvariant))
        {
            var attributes = ParseSceneAttributes(match.Groups["attributes"].Value);
            if (!attributes.TryGetValue("id", out var id) ||
                !attributes.TryGetValue("type", out var type) ||
                !attributes.TryGetValue("path", out var path))
            {
                failures.Add($"malformed ext_resource declaration: {match.Value}");
                continue;
            }
            resources.Add(new SceneExternalResource(id, type, path));
        }
        return resources.ToArray();
    }

    private static SceneSubresource[] ParseSceneSubresources(
        string scene,
        ICollection<string> failures)
    {
        var resources = new List<SceneSubresource>();
        foreach (Match match in Regex.Matches(
                     scene,
                     @"(?m)^\[sub_resource(?<attributes>[^\]]*)\]\s*$",
                     RegexOptions.CultureInvariant))
        {
            var attributes = ParseSceneAttributes(match.Groups["attributes"].Value);
            if (!attributes.TryGetValue("id", out var id) ||
                !attributes.TryGetValue("type", out var type))
            {
                failures.Add($"malformed sub_resource declaration: {match.Value}");
                continue;
            }
            resources.Add(new SceneSubresource(id, type));
        }
        return resources.ToArray();
    }

    private static SceneNode[] ParseSceneNodes(
        string scene,
        ICollection<string> failures)
    {
        var nodes = new List<SceneNode>();
        foreach (Match match in Regex.Matches(
                     scene,
                     @"(?ms)^\[node(?<attributes>[^\]]*)\]\s*\r?\n(?<body>.*?)(?=^\[(?:node|ext_resource|sub_resource|connection|editable)\b|\z)",
                     RegexOptions.CultureInvariant))
        {
            var attributes = ParseSceneAttributes(match.Groups["attributes"].Value);
            if (!attributes.TryGetValue("name", out var name))
            {
                failures.Add($"malformed node declaration without name: {match.Value.Split('\n')[0]}");
                continue;
            }
            attributes.TryGetValue("type", out var type);
            attributes.TryGetValue("parent", out var parent);
            type ??= string.Empty;
            parent ??= string.Empty;

            var references = Regex.Matches(
                    match.Groups["body"].Value,
                    "(?m)^(?<property>[A-Za-z_][A-Za-z0-9_]*)\\s*=\\s*" +
                    "(?<kind>ExtResource|SubResource)\\(\"(?<id>[^\"]+)\"\\)\\s*$",
                    RegexOptions.CultureInvariant)
                .Select(reference => new SceneTextureReference(
                    reference.Groups["property"].Value,
                    reference.Groups["kind"].Value,
                    reference.Groups["id"].Value))
                .ToArray();
            nodes.Add(new SceneNode(name, type, parent, references));
        }
        return nodes.ToArray();
    }

    private static Dictionary<string, string> ParseSceneAttributes(string attributes) =>
        Regex.Matches(
                attributes,
                "(?<key>[A-Za-z_][A-Za-z0-9_]*)=\"(?<value>[^\"]*)\"",
                RegexOptions.CultureInvariant)
            .ToDictionary(
                match => match.Groups["key"].Value,
                match => match.Groups["value"].Value,
                StringComparer.Ordinal);

    private static bool IsTextureResource(string type, string path) =>
        type.Contains("Texture", StringComparison.Ordinal) ||
        path.EndsWith(".png", StringComparison.OrdinalIgnoreCase) ||
        path.EndsWith(".jpg", StringComparison.OrdinalIgnoreCase) ||
        path.EndsWith(".jpeg", StringComparison.OrdinalIgnoreCase) ||
        path.EndsWith(".webp", StringComparison.OrdinalIgnoreCase) ||
        path.EndsWith(".svg", StringComparison.OrdinalIgnoreCase);

    private static bool IsTextureNodeType(string type) =>
        type.Contains("Texture", StringComparison.Ordinal) ||
        type is "Sprite2D" or "Sprite3D" or "NinePatchRect";

    private static bool IsTextureProperty(string property) =>
        property.Contains("texture", StringComparison.OrdinalIgnoreCase) ||
        property.Equals("icon", StringComparison.OrdinalIgnoreCase);

    private static void AddSetDifference(
        IReadOnlyCollection<string> expected,
        IReadOnlyCollection<string> actual,
        string label,
        ICollection<string> failures)
    {
        foreach (var missing in expected.Except(actual, StringComparer.Ordinal).Order(StringComparer.Ordinal))
        {
            failures.Add($"{label}: missing {missing}");
        }
        foreach (var unexpected in actual.Except(expected, StringComparer.Ordinal).Order(StringComparer.Ordinal))
        {
            failures.Add($"{label}: unexpected {unexpected}");
        }
    }

    private static string FormatTextureReferences(
        IReadOnlyCollection<SceneTextureReference> references) =>
        references.Count == 0
            ? "<none>"
            : string.Join(", ", references.Select(reference =>
                $"{reference.Property}={reference.ResourceKind}(\"{reference.ResourceId}\")"));

    private static void ValidateAsset(
        RuntimeAsset asset,
        IDictionary<string, string> firstPathByHash,
        ICollection<string> failures,
        ICollection<string> warnings)
    {
        if (!File.Exists(asset.Path))
        {
            failures.Add($"{asset.Category}/{asset.Name}: missing file {asset.Path}");
            return;
        }

        string hash;
        try
        {
            using var stream = File.OpenRead(asset.Path);
            hash = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
        }
        catch (Exception exception)
        {
            failures.Add($"{asset.Category}/{asset.Name}: could not hash {asset.Path}: {exception.Message}");
            return;
        }

        if (KnownPlaceholderHashes.TryGetValue(hash, out var placeholder))
        {
            failures.Add($"{asset.Category}/{asset.Name}: still uses {placeholder} ({hash})");
        }
        if (firstPathByHash.TryGetValue(hash, out var firstPath))
        {
            failures.Add($"{asset.Category}/{asset.Name}: duplicates SHA-256 {hash} from {firstPath}");
        }
        else
        {
            firstPathByHash.Add(hash, asset.Path);
        }

        try
        {
            var png = ReadPng(asset.Path);
            ValidatePngContract(asset, png, failures, warnings);
        }
        catch (Exception exception)
        {
            failures.Add($"{asset.Category}/{asset.Name}: PNG decode failed: {exception.GetBaseException().Message}");
        }
    }

    private static void ValidatePngContract(
        RuntimeAsset asset,
        PngInfo png,
        ICollection<string> failures,
        ICollection<string> warnings)
    {
        if (png.Width != asset.Width || png.Height != asset.Height)
        {
            failures.Add(
                $"{asset.Category}/{asset.Name}: expected {asset.Width}x{asset.Height}, actual {png.Width}x{png.Height}");
        }
        if (png.BitDepth != 8)
        {
            failures.Add($"{asset.Category}/{asset.Name}: expected 8-bit channels, actual bit depth {png.BitDepth}");
        }
        if (png.CompressionMethod != 0 || png.FilterMethod != 0 || png.InterlaceMethod != 0)
        {
            failures.Add(
                $"{asset.Category}/{asset.Name}: expected standard non-interlaced PNG methods 0/0/0, actual " +
                $"{png.CompressionMethod}/{png.FilterMethod}/{png.InterlaceMethod}");
        }

        if (asset.IsOpaque)
        {
            if (png.ColorType != 2 || png.HasTransparencyChunk)
            {
                failures.Add(
                    $"{asset.Category}/{asset.Name}: expected fully opaque RGB8 (color type 2 without tRNS), actual " +
                    $"color type {png.ColorType}, tRNS={png.HasTransparencyChunk}");
            }
            if (png.BitDepth == 8 &&
                png.ColorType == 2 &&
                png.CompressionMethod == 0 &&
                png.FilterMethod == 0 &&
                png.InterlaceMethod == 0)
            {
                var opaquePixels = DecodePngPixels(png, bytesPerPixel: 3);
                if (asset.RequiresStrictGrayscale)
                {
                    for (var offset = 0; offset < opaquePixels.Length; offset += 3)
                    {
                        if (opaquePixels[offset] != opaquePixels[offset + 1] ||
                            opaquePixels[offset + 1] != opaquePixels[offset + 2])
                        {
                            failures.Add(
                                $"{asset.Category}/{asset.Name}: expected strict grayscale RGB8, " +
                                $"first mismatch at pixel {offset / 3}");
                            break;
                        }
                    }
                }
            }
            return;
        }

        if (png.ColorType != 6)
        {
            failures.Add($"{asset.Category}/{asset.Name}: expected RGBA8 color type 6, actual {png.ColorType}");
            return;
        }

        if (png.BitDepth != 8 ||
            png.CompressionMethod != 0 ||
            png.FilterMethod != 0 ||
            png.InterlaceMethod != 0)
        {
            return;
        }

        var pixels = DecodePngPixels(png, bytesPerPixel: 4);
        var alpha = InspectRgbaAlpha(png, pixels);
        if (alpha.Corners.Any(value => value != 0))
        {
            failures.Add(
                $"{asset.Category}/{asset.Name}: corner Alpha must be 0, actual [{string.Join(", ", alpha.Corners)}]");
        }
        if (alpha.NonZeroPixels == 0 || alpha.MeaningfulPixels == 0 || alpha.Components.Count == 0)
        {
            failures.Add(
                $"{asset.Category}/{asset.Name}: transparent UI art has no connected subject at Alpha >= " +
                MeaningfulAlphaThreshold);
            return;
        }

        var main = alpha.Components[0];
        var requiredNearOpaqueInterior = Math.Max(
            1,
            (int)Math.Ceiling(main.PixelCount * 0.01m));
        if (main.NearOpaqueInteriorPixels < requiredNearOpaqueInterior)
        {
            failures.Add(
                $"{asset.Category}/{asset.Name}: main connected subject lacks a near-opaque interior core; " +
                $"expected at least {requiredNearOpaqueInterior} pixels with Alpha >= " +
                $"{NearOpaqueAlphaThreshold}, actual {main.NearOpaqueInteriorPixels}; " +
                FormatAlphaComponent(main));
        }

        if (main.StrongBoundaryPixels >= 2)
        {
            failures.Add(
                $"{asset.Category}/{asset.Name}: the main connected subject is materially clipped by the canvas; " +
                FormatAlphaComponent(main));
        }
        else if (main.BoundaryPixels > 0)
        {
            warnings.Add(
                $"{asset.Category}/{asset.Name}: main subject has only isolated/soft edge contact; " +
                FormatAlphaComponent(main));
        }

        var significantSecondarySize = Math.Max(8, main.PixelCount / 20);
        foreach (var component in alpha.Components.Skip(1).Where(component => component.BoundaryPixels > 0))
        {
            if (component.PixelCount >= significantSecondarySize && component.StrongBoundaryPixels >= 2)
            {
                failures.Add(
                    $"{asset.Category}/{asset.Name}: a significant secondary connected subject is clipped by the canvas; " +
                    FormatAlphaComponent(component));
            }
            else
            {
                warnings.Add(
                    $"{asset.Category}/{asset.Name}: isolated secondary Alpha component touches an edge; " +
                    FormatAlphaComponent(component));
            }
        }

        if (alpha.LowAlphaBoundaryPixels > 0)
        {
            warnings.Add(
                $"{asset.Category}/{asset.Name}: {alpha.LowAlphaBoundaryPixels} edge pixels have only low Alpha " +
                $"1-{MeaningfulAlphaThreshold - 1} (max {alpha.MaxLowAlphaBoundary}); warning only");
        }
    }

    private static PngInfo ReadPng(string path)
    {
        byte[] expectedSignature = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
        using var stream = File.OpenRead(path);
        Span<byte> signature = stackalloc byte[8];
        stream.ReadExactly(signature);
        if (!signature.SequenceEqual(expectedSignature))
        {
            throw new InvalidDataException("invalid PNG signature");
        }

        var seenHeader = false;
        var seenEnd = false;
        var seenImageData = false;
        var imageDataEnded = false;
        var hasTransparencyChunk = false;
        var width = 0;
        var height = 0;
        byte bitDepth = 0;
        byte colorType = 0;
        byte compressionMethod = 0;
        byte filterMethod = 0;
        byte interlaceMethod = 0;
        using var imageData = new MemoryStream();
        Span<byte> lengthBytes = stackalloc byte[4];
        Span<byte> typeBytes = stackalloc byte[4];
        Span<byte> crcBytes = stackalloc byte[4];

        while (!seenEnd)
        {
            stream.ReadExactly(lengthBytes);
            var length = BinaryPrimitives.ReadUInt32BigEndian(lengthBytes);
            if (length > int.MaxValue || length > stream.Length - stream.Position - 8)
            {
                throw new InvalidDataException($"invalid PNG chunk length {length}");
            }

            stream.ReadExactly(typeBytes);
            var data = new byte[(int)length];
            stream.ReadExactly(data);
            stream.ReadExactly(crcBytes);
            var expectedCrc = BinaryPrimitives.ReadUInt32BigEndian(crcBytes);
            var actualCrc = ComputePngCrc(typeBytes, data);
            if (actualCrc != expectedCrc)
            {
                throw new InvalidDataException(
                    $"PNG chunk {Encoding.ASCII.GetString(typeBytes)} has invalid CRC");
            }

            var chunkType = Encoding.ASCII.GetString(typeBytes);
            if (!seenHeader && chunkType != "IHDR")
            {
                throw new InvalidDataException("IHDR is not the first PNG chunk");
            }
            if (chunkType == "IDAT")
            {
                if (imageDataEnded)
                {
                    throw new InvalidDataException("IDAT chunks must be consecutive");
                }
                seenImageData = true;
            }
            else if (seenImageData)
            {
                imageDataEnded = true;
            }

            switch (chunkType)
            {
                case "IHDR":
                    if (seenHeader || data.Length != 13)
                    {
                        throw new InvalidDataException("PNG must contain exactly one 13-byte IHDR");
                    }
                    width = checked((int)BinaryPrimitives.ReadUInt32BigEndian(data.AsSpan(0, 4)));
                    height = checked((int)BinaryPrimitives.ReadUInt32BigEndian(data.AsSpan(4, 4)));
                    bitDepth = data[8];
                    colorType = data[9];
                    compressionMethod = data[10];
                    filterMethod = data[11];
                    interlaceMethod = data[12];
                    seenHeader = true;
                    break;
                case "IDAT":
                    imageData.Write(data);
                    break;
                case "tRNS":
                    hasTransparencyChunk = true;
                    break;
                case "IEND":
                    if (data.Length != 0)
                    {
                        throw new InvalidDataException("IEND must be empty");
                    }
                    if (!seenImageData)
                    {
                        throw new InvalidDataException("IEND appears before IDAT");
                    }
                    seenEnd = true;
                    break;
            }
        }

        if (stream.Position != stream.Length)
        {
            throw new InvalidDataException(
                $"PNG has {stream.Length - stream.Position} trailing bytes after IEND");
        }
        if (!seenHeader || width <= 0 || height <= 0 || imageData.Length == 0)
        {
            throw new InvalidDataException("PNG is missing valid IHDR or IDAT data");
        }

        return new PngInfo(
            width,
            height,
            bitDepth,
            colorType,
            compressionMethod,
            filterMethod,
            interlaceMethod,
            hasTransparencyChunk,
            imageData.ToArray());
    }

    private static byte[] DecodePngPixels(PngInfo png, int bytesPerPixel)
    {
        if (png.BitDepth != 8 || png.InterlaceMethod != 0)
        {
            throw new InvalidDataException("scanline decoding only supports non-interlaced 8-bit PNGs");
        }

        var rowBytes = checked(png.Width * bytesPerPixel);
        var expectedBytes = checked((rowBytes + 1) * png.Height);
        var filtered = new byte[expectedBytes];
        using (var compressed = new MemoryStream(png.CompressedImageData, writable: false))
        using (var zlib = new ZLibStream(compressed, CompressionMode.Decompress))
        {
            zlib.ReadExactly(filtered);
            if (zlib.ReadByte() != -1)
            {
                throw new InvalidDataException("decompressed IDAT payload exceeds the expected scanline length");
            }
            if (compressed.Position != compressed.Length)
            {
                throw new InvalidDataException(
                    $"compressed IDAT payload has {compressed.Length - compressed.Position} trailing bytes");
            }
        }

        var previous = new byte[rowBytes];
        var current = new byte[rowBytes];
        var pixels = new byte[checked(rowBytes * png.Height)];
        var sourceOffset = 0;

        for (var y = 0; y < png.Height; y++)
        {
            var filter = filtered[sourceOffset++];
            for (var index = 0; index < rowBytes; index++)
            {
                var raw = filtered[sourceOffset++];
                var left = index >= bytesPerPixel ? current[index - bytesPerPixel] : (byte)0;
                var up = previous[index];
                var upLeft = index >= bytesPerPixel ? previous[index - bytesPerPixel] : (byte)0;
                current[index] = filter switch
                {
                    0 => raw,
                    1 => unchecked((byte)(raw + left)),
                    2 => unchecked((byte)(raw + up)),
                    3 => unchecked((byte)(raw + ((left + up) >> 1))),
                    4 => unchecked((byte)(raw + Paeth(left, up, upLeft))),
                    _ => throw new InvalidDataException($"unsupported PNG row filter {filter}")
                };
            }
            Buffer.BlockCopy(current, 0, pixels, y * rowBytes, rowBytes);
            (previous, current) = (current, previous);
        }

        if (sourceOffset != filtered.Length)
        {
            throw new InvalidDataException(
                $"scanline decoder consumed {sourceOffset} bytes, expected {filtered.Length}");
        }
        return pixels;
    }

    private static AlphaInfo InspectRgbaAlpha(PngInfo png, byte[] pixels)
    {
        var pixelCount = checked(png.Width * png.Height);
        if (pixels.Length != checked(pixelCount * 4))
        {
            throw new InvalidDataException(
                $"RGBA payload length {pixels.Length} does not match {png.Width}x{png.Height}");
        }

        var alpha = new byte[pixelCount];
        var corners = new byte[4];
        var nonZeroPixels = 0;
        var meaningfulPixels = 0;
        var lowAlphaBoundaryPixels = 0;
        byte maxLowAlphaBoundary = 0;
        for (var y = 0; y < png.Height; y++)
        {
            for (var x = 0; x < png.Width; x++)
            {
                var pixelIndex = y * png.Width + x;
                var value = pixels[pixelIndex * 4 + 3];
                alpha[pixelIndex] = value;
                if (value > 0)
                {
                    nonZeroPixels++;
                }
                if (value >= MeaningfulAlphaThreshold)
                {
                    meaningfulPixels++;
                }
                else if (value > 0 && IsBoundary(x, y, png.Width, png.Height))
                {
                    lowAlphaBoundaryPixels++;
                    maxLowAlphaBoundary = Math.Max(maxLowAlphaBoundary, value);
                }
            }
        }

        corners[0] = alpha[0];
        corners[1] = alpha[png.Width - 1];
        corners[2] = alpha[(png.Height - 1) * png.Width];
        corners[3] = alpha[pixelCount - 1];
        var components = FindAlphaComponents(alpha, png.Width, png.Height);
        return new AlphaInfo(
            corners,
            nonZeroPixels,
            meaningfulPixels,
            lowAlphaBoundaryPixels,
            maxLowAlphaBoundary,
            components);
    }

    private static IReadOnlyList<AlphaComponent> FindAlphaComponents(
        byte[] alpha,
        int width,
        int height)
    {
        var visited = new bool[alpha.Length];
        var queue = new int[alpha.Length];
        var components = new List<AlphaComponent>();
        for (var start = 0; start < alpha.Length; start++)
        {
            if (visited[start] || alpha[start] < MeaningfulAlphaThreshold)
            {
                continue;
            }

            var head = 0;
            var tail = 0;
            queue[tail++] = start;
            visited[start] = true;
            var count = 0;
            var nearOpaqueInteriorPixels = 0;
            var boundaryPixels = 0;
            var strongBoundaryPixels = 0;
            byte maxAlpha = 0;
            byte maxBoundaryAlpha = 0;
            var minX = width;
            var minY = height;
            var maxX = -1;
            var maxY = -1;

            while (head < tail)
            {
                var index = queue[head++];
                var x = index % width;
                var y = index / width;
                var value = alpha[index];
                var boundary = IsBoundary(x, y, width, height);
                count++;
                maxAlpha = Math.Max(maxAlpha, value);
                minX = Math.Min(minX, x);
                minY = Math.Min(minY, y);
                maxX = Math.Max(maxX, x);
                maxY = Math.Max(maxY, y);
                if (boundary)
                {
                    boundaryPixels++;
                    maxBoundaryAlpha = Math.Max(maxBoundaryAlpha, value);
                    if (value >= StrongBoundaryAlphaThreshold)
                    {
                        strongBoundaryPixels++;
                    }
                }
                else if (value >= NearOpaqueAlphaThreshold)
                {
                    nearOpaqueInteriorPixels++;
                }

                for (var deltaY = -1; deltaY <= 1; deltaY++)
                {
                    for (var deltaX = -1; deltaX <= 1; deltaX++)
                    {
                        if (deltaX == 0 && deltaY == 0)
                        {
                            continue;
                        }
                        var neighborX = x + deltaX;
                        var neighborY = y + deltaY;
                        if (neighborX < 0 || neighborX >= width || neighborY < 0 || neighborY >= height)
                        {
                            continue;
                        }
                        var neighbor = neighborY * width + neighborX;
                        if (!visited[neighbor] && alpha[neighbor] >= MeaningfulAlphaThreshold)
                        {
                            visited[neighbor] = true;
                            queue[tail++] = neighbor;
                        }
                    }
                }
            }

            components.Add(new AlphaComponent(
                count,
                nearOpaqueInteriorPixels,
                boundaryPixels,
                strongBoundaryPixels,
                maxAlpha,
                maxBoundaryAlpha,
                minX,
                minY,
                maxX,
                maxY));
        }

        return components
            .OrderByDescending(component => component.PixelCount)
            .ThenByDescending(component => component.MaxAlpha)
            .ToArray();
    }

    private static bool IsBoundary(int x, int y, int width, int height) =>
        x == 0 || y == 0 || x == width - 1 || y == height - 1;

    private static string FormatAlphaComponent(AlphaComponent component) =>
        $"pixels={component.PixelCount}, nearOpaqueInterior={component.NearOpaqueInteriorPixels}, " +
        $"edge={component.BoundaryPixels}, strongEdge={component.StrongBoundaryPixels}, " +
        $"maxAlpha={component.MaxAlpha}, maxEdgeAlpha={component.MaxBoundaryAlpha}, " +
        $"bbox=({component.MinX},{component.MinY})-({component.MaxX},{component.MaxY})";

    private static byte Paeth(byte left, byte up, byte upLeft)
    {
        var estimate = left + up - upLeft;
        var leftDistance = Math.Abs(estimate - left);
        var upDistance = Math.Abs(estimate - up);
        var upLeftDistance = Math.Abs(estimate - upLeft);
        if (leftDistance <= upDistance && leftDistance <= upLeftDistance)
        {
            return left;
        }
        return upDistance <= upLeftDistance ? up : upLeft;
    }

    private static uint ComputePngCrc(ReadOnlySpan<byte> type, ReadOnlySpan<byte> data)
    {
        var crc = uint.MaxValue;
        foreach (var value in type)
        {
            crc = CrcTable[(crc ^ value) & 0xff] ^ (crc >> 8);
        }
        foreach (var value in data)
        {
            crc = CrcTable[(crc ^ value) & 0xff] ^ (crc >> 8);
        }
        return ~crc;
    }

    private static readonly uint[] CrcTable = BuildCrcTable();

    private static uint[] BuildCrcTable()
    {
        var table = new uint[256];
        for (uint index = 0; index < table.Length; index++)
        {
            var value = index;
            for (var bit = 0; bit < 8; bit++)
            {
                value = (value & 1) != 0 ? 0xedb88320U ^ (value >> 1) : value >> 1;
            }
            table[index] = value;
        }
        return table;
    }

    private sealed record RuntimeAsset(
        string Category,
        string Name,
        string Path,
        int Width,
        int Height,
        bool IsOpaque,
        bool RequiresStrictGrayscale = false);

    private sealed record EnergyAsset(string Name, int Width, int Height);

    private sealed record EnergySceneLayer(
        string ResourceId,
        string ResourcePath,
        string NodeName,
        string Parent)
    {
        public string NodeKey => $"{Parent}/{NodeName}";
    }

    private sealed record SceneExternalResource(string Id, string Type, string Path);

    private sealed record SceneSubresource(string Id, string Type);

    private sealed record SceneTextureReference(
        string Property,
        string ResourceKind,
        string ResourceId);

    private sealed record SceneNode(
        string Name,
        string Type,
        string Parent,
        IReadOnlyList<SceneTextureReference> TextureReferences)
    {
        public string NodeKey => string.IsNullOrEmpty(Parent) ? Name : $"{Parent}/{Name}";
    }

    private sealed record PngInfo(
        int Width,
        int Height,
        byte BitDepth,
        byte ColorType,
        byte CompressionMethod,
        byte FilterMethod,
        byte InterlaceMethod,
        bool HasTransparencyChunk,
        byte[] CompressedImageData);

    private sealed record AlphaInfo(
        byte[] Corners,
        int NonZeroPixels,
        int MeaningfulPixels,
        int LowAlphaBoundaryPixels,
        byte MaxLowAlphaBoundary,
        IReadOnlyList<AlphaComponent> Components);

    private sealed record AlphaComponent(
        int PixelCount,
        int NearOpaqueInteriorPixels,
        int BoundaryPixels,
        int StrongBoundaryPixels,
        byte MaxAlpha,
        byte MaxBoundaryAlpha,
        int MinX,
        int MinY,
        int MaxX,
        int MaxY);
}

#if VIVHITE_RUNTIME_ART_TARGET
internal static class RuntimeArtInventoryTarget
{
    private static int Main()
    {
        try
        {
            RuntimeArtInventoryAcceptanceTests.CoversExactNinetyTwoRuntimeAssets(
                RepositorySnapshot.Load());
            Console.WriteLine("[PASS] exact 92-file runtime art inventory");
            return 0;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine("[FAIL] exact 92-file runtime art inventory");
            Console.Error.WriteLine(exception.GetBaseException().Message);
            return 1;
        }
    }
}
#endif
