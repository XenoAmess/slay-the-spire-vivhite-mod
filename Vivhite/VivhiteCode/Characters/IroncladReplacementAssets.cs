using Godot;
using STS2RitsuLib.Content;
using STS2RitsuLib.Scaffolding.Characters;

namespace Vivhite.Characters;

/// <summary>
/// Registers the optional, complete Ironclad skin bundle. Partial bundles are
/// deliberately ignored so a missing PCK resource cannot leave the base-game
/// character with a mixture of replacement and vanilla assets.
/// </summary>
internal static class IroncladReplacementAssets
{
    private const string SkinRoot = $"{Entry.ResPath}/skins/ironclad";

    private const string CombatSkeletonDataPath = $"{SkinRoot}/spine/combat/combat_skeleton_data.tres";

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

    private static readonly RequiredAsset[] RequiredAssets =
    [
        new(
            "combat skeleton data",
            CombatSkeletonDataPath,
            typeof(Resource),
            "SpineSkeletonDataResource"),
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

    public static bool TryRegister()
    {
        // Extracted authoring templates live outside the Godot project under the
        // repository's assets directory. The combat resource appears here only after
        // an author publishes a complete edited bundle, so templates alone stay inactive.
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
                MerchantAnimPath: MerchantScenePath,
                RestSiteAnimPath: RestSiteScenePath),
            Ui: new CharacterUiAssetSet(
                IconTexturePath: IconTexturePath,
                IconOutlineTexturePath: IconOutlineTexturePath,
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

        foreach (var asset in RequiredAssets)
        {
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
            }
            catch (Exception exception)
            {
                issues.Add(
                    $"error loading {asset.Description} ({asset.Path}): " +
                    $"{exception.GetType().Name}: {exception.Message}");
            }
        }

        return issues;
    }

    private sealed record RequiredAsset(
        string Description,
        string Path,
        Type ExpectedType,
        string? ExpectedGodotClass = null);
}
