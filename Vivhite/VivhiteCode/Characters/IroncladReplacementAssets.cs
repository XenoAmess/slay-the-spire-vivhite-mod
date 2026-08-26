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
    private const string CombatAtlasPath = $"{SkinRoot}/spine/combat/ironclad.spatlas";
    private const string CombatAtlasPage1Path = $"{SkinRoot}/spine/combat/ironclad.png";
    private const string CombatAtlasPage2Path = $"{SkinRoot}/spine/combat/ironclad_2.png";
    private const string CombatAtlasPage3Path = $"{SkinRoot}/spine/combat/ironclad_3.png";
    private const string CombatAtlasPage4Path = $"{SkinRoot}/spine/combat/ironclad_4.png";

    private const string MerchantSkeletonDataPath = $"{SkinRoot}/spine/merchant/merchant_skeleton_data.tres";
    private const string MerchantAtlasPath = $"{SkinRoot}/spine/merchant/ironclad_shop.spatlas";
    private const string MerchantAtlasPage1Path = $"{SkinRoot}/spine/merchant/ironclad_shop.png";
    private const string MerchantAtlasPage2Path = $"{SkinRoot}/spine/merchant/ironclad_shop_2.png";
    private const string MerchantAtlasPage3Path = $"{SkinRoot}/spine/merchant/ironclad_shop_3.png";
    private const string MerchantAtlasPage4Path = $"{SkinRoot}/spine/merchant/ironclad_shop_4.png";

    private const string RestSiteSkeletonDataPath = $"{SkinRoot}/spine/rest_site/rest_site_skeleton_data.tres";
    private const string RestSiteAtlasPath = $"{SkinRoot}/spine/rest_site/restsite_ironclad.spatlas";
    private const string RestSiteAtlasPagePath = $"{SkinRoot}/spine/rest_site/restsite_ironclad.png";

    private const string CharacterSelectSkeletonDataPath = $"{SkinRoot}/spine/character_select/character_select_skeleton_data.tres";
    private const string CharacterSelectAtlasPath = $"{SkinRoot}/spine/character_select/characterselect_ironclad.spatlas";
    private const string CharacterSelectAtlasPagePath = $"{SkinRoot}/spine/character_select/characterselect_ironclad.png";

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
        new("combat atlas", CombatAtlasPath, typeof(Resource), "SpineAtlasResource"),
        new("combat atlas page 1", CombatAtlasPage1Path, typeof(Texture2D)),
        new("combat atlas page 2", CombatAtlasPage2Path, typeof(Texture2D)),
        new("combat atlas page 3", CombatAtlasPage3Path, typeof(Texture2D)),
        new("combat atlas page 4", CombatAtlasPage4Path, typeof(Texture2D)),
        new(
            "merchant skeleton data",
            MerchantSkeletonDataPath,
            typeof(Resource),
            "SpineSkeletonDataResource"),
        new("merchant atlas", MerchantAtlasPath, typeof(Resource), "SpineAtlasResource"),
        new("merchant atlas page 1", MerchantAtlasPage1Path, typeof(Texture2D)),
        new("merchant atlas page 2", MerchantAtlasPage2Path, typeof(Texture2D)),
        new("merchant atlas page 3", MerchantAtlasPage3Path, typeof(Texture2D)),
        new("merchant atlas page 4", MerchantAtlasPage4Path, typeof(Texture2D)),
        new(
            "rest-site skeleton data",
            RestSiteSkeletonDataPath,
            typeof(Resource),
            "SpineSkeletonDataResource"),
        new("rest-site atlas", RestSiteAtlasPath, typeof(Resource), "SpineAtlasResource"),
        new("rest-site atlas page", RestSiteAtlasPagePath, typeof(Texture2D)),
        new(
            "character-select skeleton data",
            CharacterSelectSkeletonDataPath,
            typeof(Resource),
            "SpineSkeletonDataResource"),
        new("character-select atlas", CharacterSelectAtlasPath, typeof(Resource), "SpineAtlasResource"),
        new("character-select atlas page", CharacterSelectAtlasPagePath, typeof(Texture2D)),
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
