using Godot;
using System.Text.Json;
using STS2RitsuLib.Content;
using STS2RitsuLib.Scaffolding.Characters;

namespace Vivhite.Characters;

/// <summary>
/// Registers the optional, complete White Qi replacement for the Ironclad.
/// Partial bundles are deliberately ignored so a missing PCK resource cannot
/// leave the base-game character with a mixture of private and vanilla assets.
/// </summary>
internal static class IroncladReplacementAssets
{
    private const string SkinRoot = $"{Entry.ResPath}/skins/ironclad";

    private const string CombatSkeletonFilePath = $"{SkinRoot}/spine/combat/vivhite_combat.spjson";
    private const string CombatSkeletonDataPath = $"{SkinRoot}/spine/combat/vivhite_combat_skeleton_data.tres";
    private const string CombatAtlasPath = $"{SkinRoot}/spine/combat/vivhite_combat.spatlas";
    private const string CombatAtlasPagePath = $"{SkinRoot}/spine/combat/vivhite_combat.png";
    private const string CombatDeathAtlasPagePath = $"{SkinRoot}/spine/combat/vivhite_combat_death.png";
    private const string CombatAttackAtlasPagePath = $"{SkinRoot}/spine/combat/vivhite_combat_attack.png";
    private const string CombatHeavyAtlasPagePath = $"{SkinRoot}/spine/combat/vivhite_combat_attack_heavy.png";
    private const string CombatCastAtlasPagePath = $"{SkinRoot}/spine/combat/vivhite_combat_cast.png";

    private const string MerchantSkeletonDataPath = $"{SkinRoot}/spine/merchant/merchant_skeleton_data.tres";

    private const string RestSiteSkeletonDataPath = $"{SkinRoot}/spine/rest_site/rest_site_skeleton_data.tres";
    private const string RestSiteSkeletonFilePath = $"{SkinRoot}/spine/rest_site/vivhite_rest_site.spjson";
    private const string RestSiteAtlasPath = $"{SkinRoot}/spine/rest_site/restsite_ironclad.spatlas";
    private const string RestSiteAtlasPagePath = $"{SkinRoot}/spine/rest_site/restsite_ironclad.png";

    private const string CharacterSelectSkeletonDataPath = $"{SkinRoot}/spine/character_select/character_select_skeleton_data.tres";
    private const string CharacterSelectSkeletonFilePath = $"{SkinRoot}/spine/character_select/vivhite_character_select.spjson";
    private const string CharacterSelectAtlasPath = $"{SkinRoot}/spine/character_select/characterselect_ironclad.spatlas";
    private const string CharacterSelectAtlasPagePath = $"{SkinRoot}/spine/character_select/characterselect_ironclad.png";

    private const string CombatScenePath = $"{SkinRoot}/scenes/combat.tscn";
    private const string MerchantScenePath = $"{SkinRoot}/scenes/merchant.tscn";
    private const string RestSiteScenePath = $"{SkinRoot}/scenes/rest_site.tscn";
    private const string CharacterSelectScenePath = $"{SkinRoot}/scenes/character_select.tscn";

    private const string IconTexturePath = $"{SkinRoot}/ui/icon.png";
    private const string IconOutlineTexturePath = $"{SkinRoot}/ui/icon_outline.png";
    private const string CharacterSelectIconPath = $"{SkinRoot}/ui/select.png";
    private const string CharacterSelectLockedIconPath = $"{SkinRoot}/ui/select_locked.png";
    private const string MapMarkerPath = $"{SkinRoot}/ui/map_marker.png";

    private const string PointingHandTexturePath = $"{SkinRoot}/multiplayer/point.png";
    private const string RockHandTexturePath = $"{SkinRoot}/multiplayer/rock.png";
    private const string PaperHandTexturePath = $"{SkinRoot}/multiplayer/paper.png";
    private const string ScissorsHandTexturePath = $"{SkinRoot}/multiplayer/scissors.png";

    private static readonly AtlasPageContract[] LegacyCombatAtlasPages =
    [
        new(
            "vivhite_combat.png",
            3072,
            2304,
            [
                new("vivhite_combat_body", 16, 16, 1536, 2272),
                new("vivhite_combat_magic_arc", 1568, 16, 1488, 1104),
                new("vivhite_combat_magic_sigil", 1808, 1152, 1248, 1136)
            ])
    ];

    private static readonly AtlasPageContract[] V3CombatAtlasPages =
    [
        .. LegacyCombatAtlasPages,
        new(
            "vivhite_combat_death.png",
            2048,
            1536,
            [new("vivhite_combat_death_side", 16, 16, 2016, 1504)]),
        new(
            "vivhite_combat_attack.png",
            2048,
            2304,
            [new("vivhite_combat_attack_peak", 16, 16, 1536, 2272)]),
        new(
            "vivhite_combat_attack_heavy.png",
            2048,
            2304,
            [new("vivhite_combat_attack_heavy_peak", 16, 16, 1536, 2272)]),
        new(
            "vivhite_combat_cast.png",
            2048,
            2304,
            [new("vivhite_combat_cast_peak", 16, 16, 1536, 2272)])
    ];

    private static readonly RequiredAsset[] RequiredAssets =
    [
        new(
            "combat skeleton file",
            CombatSkeletonFilePath,
            typeof(Resource),
            "SpineSkeletonFileResource"),
        new(
            "combat skeleton data",
            CombatSkeletonDataPath,
            typeof(Resource),
            "SpineSkeletonDataResource"),
        new("combat atlas", CombatAtlasPath, typeof(Resource), "SpineAtlasResource"),
        new("combat atlas page", CombatAtlasPagePath, typeof(Texture2D), ExpectedWidth: 3072, ExpectedHeight: 2304),
        new(
            "V3 combat death atlas page",
            CombatDeathAtlasPagePath,
            typeof(Texture2D),
            RequiredLayout: CombatAtlasLayout.V3FivePage,
            ExpectedWidth: 2048,
            ExpectedHeight: 1536),
        new(
            "V3 combat attack atlas page",
            CombatAttackAtlasPagePath,
            typeof(Texture2D),
            RequiredLayout: CombatAtlasLayout.V3FivePage,
            ExpectedWidth: 2048,
            ExpectedHeight: 2304),
        new(
            "V3 combat heavy-attack atlas page",
            CombatHeavyAtlasPagePath,
            typeof(Texture2D),
            RequiredLayout: CombatAtlasLayout.V3FivePage,
            ExpectedWidth: 2048,
            ExpectedHeight: 2304),
        new(
            "V3 combat cast atlas page",
            CombatCastAtlasPagePath,
            typeof(Texture2D),
            RequiredLayout: CombatAtlasLayout.V3FivePage,
            ExpectedWidth: 2048,
            ExpectedHeight: 2304),
        new(
            "merchant skeleton data",
            MerchantSkeletonDataPath,
            typeof(Resource),
            "SpineSkeletonDataResource"),
        new(
            "rest-site skeleton data",
            RestSiteSkeletonDataPath,
            typeof(Resource),
            "SpineSkeletonDataResource"),
        new(
            "rest-site skeleton file",
            RestSiteSkeletonFilePath,
            typeof(Resource),
            "SpineSkeletonFileResource"),
        new("rest-site atlas", RestSiteAtlasPath, typeof(Resource), "SpineAtlasResource"),
        new("rest-site atlas page", RestSiteAtlasPagePath, typeof(Texture2D)),
        new(
            "character-select skeleton data",
            CharacterSelectSkeletonDataPath,
            typeof(Resource),
            "SpineSkeletonDataResource"),
        new(
            "character-select skeleton file",
            CharacterSelectSkeletonFilePath,
            typeof(Resource),
            "SpineSkeletonFileResource"),
        new("character-select atlas", CharacterSelectAtlasPath, typeof(Resource), "SpineAtlasResource"),
        new("character-select atlas page", CharacterSelectAtlasPagePath, typeof(Texture2D)),
        new("combat scene", CombatScenePath, typeof(PackedScene)),
        new("merchant scene", MerchantScenePath, typeof(PackedScene)),
        new("rest-site scene", RestSiteScenePath, typeof(PackedScene)),
        new("character-select scene", CharacterSelectScenePath, typeof(PackedScene)),
        new("character icon", IconTexturePath, typeof(Texture2D)),
        new("character icon outline", IconOutlineTexturePath, typeof(Texture2D)),
        new("character-select portrait", CharacterSelectIconPath, typeof(Texture2D)),
        new("locked character-select portrait", CharacterSelectLockedIconPath, typeof(Texture2D)),
        new("map marker", MapMarkerPath, typeof(Texture2D)),
        new("multiplayer pointing hand", PointingHandTexturePath, typeof(Texture2D)),
        new("multiplayer rock hand", RockHandTexturePath, typeof(Texture2D)),
        new("multiplayer paper hand", PaperHandTexturePath, typeof(Texture2D)),
        new("multiplayer scissors hand", ScissorsHandTexturePath, typeof(Texture2D))
    ];

    private static readonly RequiredTextBinding[] RequiredTextBindings =
    [
        new(
            "combat skeleton data",
            CombatSkeletonDataPath,
            [CombatSkeletonFilePath, CombatAtlasPath]),
        new(
            "merchant skeleton data",
            MerchantSkeletonDataPath,
            [CombatSkeletonFilePath, CombatAtlasPath]),
        new(
            "rest-site skeleton data",
            RestSiteSkeletonDataPath,
            [RestSiteSkeletonFilePath, RestSiteAtlasPath]),
        new(
            "character-select skeleton data",
            CharacterSelectSkeletonDataPath,
            [CharacterSelectSkeletonFilePath, CharacterSelectAtlasPath]),
        new("combat scene", CombatScenePath, [CombatSkeletonDataPath]),
        new("merchant scene", MerchantScenePath, [MerchantSkeletonDataPath]),
        new("rest-site scene", RestSiteScenePath, [RestSiteSkeletonDataPath]),
        new(
            "character-select scene",
            CharacterSelectScenePath,
            [CharacterSelectSkeletonDataPath])
    ];

    private static readonly string[] ForbiddenVanillaSkeletonReferences =
    [
        "res://animations/characters/ironclad/ironclad.skel",
        "res://animations/rest_site/ironclad/restsite_ironclad.skel",
        "res://animations/character_select/ironclad/characterselect_ironclad.skel"
    ];

    private const string ForbiddenSerializedSpineMeshNode = "type=\"SpineMesh2D\"";

    public static bool TryRegister()
    {
        // Authoring sources live outside the Godot project under the repository's
        // assets directory. The combat resource appears here only after a complete
        // private rig is published, so templates alone stay inactive.
        try
        {
            if (!ResourceLoader.Exists(CombatSkeletonDataPath))
            {
                Entry.Logger.Info($"Ironclad skin is not published at {SkinRoot}; keeping vanilla visuals.");
                return false;
            }
        }
        catch (Exception exception)
        {
            Entry.Logger.Warn(
                "Ironclad skin disabled: the replacement root could not be inspected; " +
                $"the base-game Ironclad assets remain active. {exception.GetType().Name}: {exception.Message}");
            return false;
        }

        var issues = ValidateRequiredAssets();
        if (issues.Count > 0)
        {
            Entry.Logger.Warn(
                "Ironclad skin disabled: the complete resource bundle is not ready, so no Ironclad " +
                $"asset replacement was registered. Required root: {SkinRoot}. Issues: {string.Join("; ", issues)}");
            return false;
        }

        try
        {
            ModContentRegistry.For(Entry.ModId).RegisterCharacterAssetReplacement(
                ModContentRegistry.VanillaCharacterIds.Ironclad,
                CreateProfile());

            Entry.Logger.Info($"Ironclad skin enabled from {SkinRoot}.");
            return true;
        }
        catch (Exception exception)
        {
            Entry.Logger.Error(
                "Ironclad skin disabled: RitsuLib rejected the complete replacement profile; " +
                $"the base-game Ironclad assets remain active. {exception.GetType().Name}: {exception.Message}");
            return false;
        }
    }

    private static CharacterAssetProfile CreateProfile()
    {
        return new CharacterAssetProfile(
            Scenes: new CharacterSceneAssetSet(
                VisualsPath: CombatScenePath,
                MerchantAnimPath: MerchantScenePath,
                RestSiteAnimPath: RestSiteScenePath),
            Ui: new CharacterUiAssetSet(
                IconTexturePath: IconTexturePath,
                IconOutlineTexturePath: IconOutlineTexturePath,
                IconPath: IconTexturePath,
                CharacterSelectBgPath: CharacterSelectScenePath,
                CharacterSelectIconPath: CharacterSelectIconPath,
                CharacterSelectLockedIconPath: CharacterSelectLockedIconPath,
                MapMarkerPath: MapMarkerPath),
            Spine: new CharacterSpineAssetSet(
                CombatSkeletonDataPath: CombatSkeletonDataPath),
            Multiplayer: new CharacterMultiplayerAssetSet(
                ArmPointingTexturePath: PointingHandTexturePath,
                ArmRockTexturePath: RockHandTexturePath,
                ArmPaperTexturePath: PaperHandTexturePath,
                ArmScissorsTexturePath: ScissorsHandTexturePath));
    }

    private static List<string> ValidateRequiredAssets()
    {
        var issues = new List<string>();
        var combatAtlasLayout = ValidateCombatAtlasContract(issues);

        foreach (var asset in RequiredAssets)
        {
            if (asset.RequiredLayout is not null && asset.RequiredLayout != combatAtlasLayout)
            {
                continue;
            }

            try
            {
                if (!ResourceLoader.Exists(asset.Path))
                {
                    issues.Add($"missing {asset.Description} ({asset.Path})");
                    continue;
                }

                var resource = ResourceLoader.Load(asset.Path);
                if (resource is null)
                {
                    issues.Add($"could not load {asset.Description} ({asset.Path})");
                    continue;
                }

                if (!asset.ExpectedType.IsInstanceOfType(resource))
                {
                    issues.Add(
                        $"wrong type for {asset.Description} ({asset.Path}): " +
                        $"expected {asset.ExpectedType.Name}, got {resource.GetType().Name}");
                    continue;
                }

                if (asset.ExpectedGodotClass is not null && !resource.IsClass(asset.ExpectedGodotClass))
                {
                    issues.Add(
                        $"wrong Godot class for {asset.Description} ({asset.Path}): " +
                        $"expected {asset.ExpectedGodotClass}, got {resource.GetClass()}");
                }

                if (resource is Texture2D texture &&
                    asset.ExpectedWidth is not null &&
                    asset.ExpectedHeight is not null &&
                    (texture.GetWidth() != asset.ExpectedWidth || texture.GetHeight() != asset.ExpectedHeight))
                {
                    issues.Add(
                        $"wrong dimensions for {asset.Description} ({asset.Path}): " +
                        $"expected {asset.ExpectedWidth}x{asset.ExpectedHeight}, " +
                        $"got {texture.GetWidth()}x{texture.GetHeight()}");
                }
            }
            catch (Exception exception)
            {
                issues.Add(
                    $"error loading {asset.Description} ({asset.Path}): " +
                    $"{exception.GetType().Name}: {exception.Message}");
            }
        }

        foreach (var binding in RequiredTextBindings)
        {
            try
            {
                var text = Godot.FileAccess.GetFileAsString(binding.Path);
                if (string.IsNullOrWhiteSpace(text))
                {
                    issues.Add($"could not inspect {binding.Description} ({binding.Path}) as text");
                    continue;
                }

                foreach (var requiredReference in binding.RequiredReferences)
                {
                    if (!text.Contains(requiredReference, StringComparison.Ordinal))
                    {
                        issues.Add(
                            $"{binding.Description} ({binding.Path}) does not reference " +
                            $"required private resource {requiredReference}");
                    }
                }

                foreach (var forbiddenReference in ForbiddenVanillaSkeletonReferences)
                {
                    if (text.Contains(forbiddenReference, StringComparison.OrdinalIgnoreCase))
                    {
                        issues.Add(
                            $"{binding.Description} ({binding.Path}) still references " +
                            $"original Ironclad skeleton {forbiddenReference}");
                    }
                }

                if (binding.Path.EndsWith(".tscn", StringComparison.OrdinalIgnoreCase) &&
                    text.Contains(ForbiddenSerializedSpineMeshNode, StringComparison.Ordinal))
                {
                    issues.Add(
                        $"{binding.Description} ({binding.Path}) contains serialized SpineMesh2D " +
                        "preview geometry; the private Spine JSON must own every mesh");
                }
            }
            catch (Exception exception)
            {
                issues.Add(
                    $"error inspecting {binding.Description} ({binding.Path}): " +
                    $"{exception.GetType().Name}: {exception.Message}");
            }
        }

        return issues;
    }

    private static CombatAtlasLayout? ValidateCombatAtlasContract(List<string> issues)
    {
        try
        {
            var wrapperText = Godot.FileAccess.GetFileAsString(CombatAtlasPath);
            if (string.IsNullOrWhiteSpace(wrapperText))
            {
                issues.Add($"could not inspect combat atlas ({CombatAtlasPath}) as text");
                return null;
            }

            using var wrapper = JsonDocument.Parse(wrapperText);
            if (!wrapper.RootElement.TryGetProperty("atlas_data", out var atlasDataElement) ||
                atlasDataElement.ValueKind != JsonValueKind.String)
            {
                issues.Add($"combat atlas ({CombatAtlasPath}) has no atlas_data string");
                return null;
            }

            var pages = ParseAtlasPages(atlasDataElement.GetString() ?? string.Empty);
            if (MatchesAtlasContract(pages, LegacyCombatAtlasPages))
            {
                return CombatAtlasLayout.LegacySinglePage;
            }
            if (MatchesAtlasContract(pages, V3CombatAtlasPages))
            {
                return CombatAtlasLayout.V3FivePage;
            }

            issues.Add(
                $"combat atlas ({CombatAtlasPath}) must match either the exact legacy page or " +
                "the exact V3 five-page order neutral/death/attack/attack_heavy/cast; got " +
                $"[{string.Join(", ", pages.Select(page => page.Name))}]");
            return null;
        }
        catch (Exception exception)
        {
            issues.Add(
                $"error inspecting combat atlas layout ({CombatAtlasPath}): " +
                $"{exception.GetType().Name}: {exception.Message}");
            return null;
        }
    }

    private static List<ParsedAtlasPage> ParseAtlasPages(string atlasData)
    {
        var blocks = new List<List<string>>();
        var currentBlock = new List<string>();
        foreach (var rawLine in atlasData.Replace("\r", string.Empty, StringComparison.Ordinal).Split('\n'))
        {
            var line = rawLine.Trim();
            if (line.Length == 0)
            {
                if (currentBlock.Count > 0)
                {
                    blocks.Add(currentBlock);
                    currentBlock = [];
                }
                continue;
            }
            currentBlock.Add(line);
        }
        if (currentBlock.Count > 0)
        {
            blocks.Add(currentBlock);
        }

        var pages = new List<ParsedAtlasPage>();
        foreach (var block in blocks)
        {
            if (block.Count < 2 || !block[1].StartsWith("size:", StringComparison.Ordinal))
            {
                throw new InvalidDataException("atlas page has no leading size directive");
            }
            var size = ParseAtlasIntegers(block[1], "size", 2);
            var regions = new List<AtlasRegionContract>();
            string? currentRegion = null;
            foreach (var line in block.Skip(2))
            {
                if (!line.Contains(':'))
                {
                    currentRegion = line;
                    continue;
                }
                if (!line.StartsWith("bounds:", StringComparison.Ordinal))
                {
                    continue;
                }
                if (currentRegion is null)
                {
                    throw new InvalidDataException($"atlas page {block[0]} has bounds before a region");
                }
                var bounds = ParseAtlasIntegers(line, "bounds", 4);
                regions.Add(new AtlasRegionContract(
                    currentRegion,
                    bounds[0],
                    bounds[1],
                    bounds[2],
                    bounds[3]));
                currentRegion = null;
            }
            if (currentRegion is not null)
            {
                throw new InvalidDataException(
                    $"atlas page {block[0]} region {currentRegion} has no bounds");
            }
            pages.Add(new ParsedAtlasPage(block[0], size[0], size[1], regions));
        }
        return pages;
    }

    private static int[] ParseAtlasIntegers(string line, string directive, int count)
    {
        var parts = line[(directive.Length + 1)..]
            .Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length != count || parts.Any(value => !int.TryParse(value, out _)))
        {
            throw new InvalidDataException($"invalid atlas {directive} directive: {line}");
        }
        return parts.Select(value => int.Parse(value)).ToArray();
    }

    private static bool MatchesAtlasContract(
        IReadOnlyList<ParsedAtlasPage> actual,
        IReadOnlyList<AtlasPageContract> expected)
    {
        if (actual.Count != expected.Count)
        {
            return false;
        }
        for (var pageIndex = 0; pageIndex < expected.Count; pageIndex++)
        {
            var actualPage = actual[pageIndex];
            var expectedPage = expected[pageIndex];
            if (!string.Equals(actualPage.Name, expectedPage.Name, StringComparison.Ordinal) ||
                actualPage.Width != expectedPage.Width ||
                actualPage.Height != expectedPage.Height ||
                actualPage.Regions.Count != expectedPage.Regions.Length)
            {
                return false;
            }
            for (var regionIndex = 0; regionIndex < expectedPage.Regions.Length; regionIndex++)
            {
                if (actualPage.Regions[regionIndex] != expectedPage.Regions[regionIndex])
                {
                    return false;
                }
            }
        }
        return true;
    }

    private enum CombatAtlasLayout
    {
        LegacySinglePage,
        V3FivePage
    }

    private sealed record AtlasRegionContract(
        string Name,
        int X,
        int Y,
        int Width,
        int Height);

    private sealed record AtlasPageContract(
        string Name,
        int Width,
        int Height,
        AtlasRegionContract[] Regions);

    private sealed record ParsedAtlasPage(
        string Name,
        int Width,
        int Height,
        List<AtlasRegionContract> Regions);

    private sealed record RequiredAsset(
        string Description,
        string Path,
        Type ExpectedType,
        string? ExpectedGodotClass = null,
        CombatAtlasLayout? RequiredLayout = null,
        int? ExpectedWidth = null,
        int? ExpectedHeight = null);

    private sealed record RequiredTextBinding(
        string Description,
        string Path,
        string[] RequiredReferences);
}
