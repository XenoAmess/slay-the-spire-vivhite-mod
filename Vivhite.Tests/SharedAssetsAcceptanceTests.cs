using System.Buffers.Binary;
using System.Collections;
using System.IO.Compression;
using System.Reflection;
using System.Text;
using System.Text.Json;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Localization.DynamicVars;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Characters;
using STS2RitsuLib.Scaffolding.Characters;
using STS2RitsuLib.Scaffolding.Content;
using Vivhite.Characters;
using Vivhite.Relics;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests;

internal static class SharedAssetsAcceptanceTests
{
    public static void VivhiteOwnsV3SkinAndIroncladHasNoReplacement(RepositorySnapshot repository)
    {
        var validatedGetter = RequireDeclaredMethod(
            typeof(VivhiteCharacterAssets),
            "GetValidatedV3Profile");
        var cachedField = typeof(VivhiteCharacterAssets).GetField(
            "ValidatedV3Profile",
            BindingFlags.Static | BindingFlags.NonPublic);
        AcceptanceAssert.True(
            cachedField?.FieldType == typeof(Lazy<CharacterAssetProfile>),
            "The Vivhite-owned V3 profile must be backed by one Lazy<CharacterAssetProfile> cache.");
        AcceptanceAssert.Equal(
            1,
            IlInspection.CalledMethods(validatedGetter).Count(method =>
                method.DeclaringType == typeof(Lazy<CharacterAssetProfile>) &&
                method.Name == "get_Value"),
            "GetValidatedV3Profile must return the single cached Lazy value.");

        var vivhiteFactory = RequireDeclaredMethod(
            typeof(VivhiteCharacter),
            "CreateVivhiteAssetProfile");
        var vivhiteCalls = IlInspection.CalledMethods(vivhiteFactory);
        AcceptanceAssert.Equal(
            1,
            vivhiteCalls.Count(method =>
                method.DeclaringType == typeof(VivhiteCharacterAssets) &&
                method.Name == "GetValidatedV3Profile"),
            "VivhiteCharacter must use the Vivhite-owned validated V3 entry exactly once.");
        AcceptanceAssert.Equal(
            0,
            vivhiteCalls.Count(method =>
                method.DeclaringType == typeof(VivhiteCharacterAssets) &&
                method.Name == "CreateProfile"),
            "VivhiteCharacter must never bypass validation by calling the structural profile factory.");

        var validatedFactory = RequireDeclaredMethod(
            typeof(VivhiteCharacterAssets),
            "CreateValidatedV3Profile");
        var factoryCalls = IlInspection.CalledMethods(validatedFactory).ToArray();
        var validationIndex = Array.FindIndex(factoryCalls, method =>
            method.DeclaringType == typeof(VivhiteCharacterAssets) &&
            method.Name == "ValidateRequiredAssets");
        var profileIndex = Array.FindIndex(factoryCalls, method =>
            method.DeclaringType == typeof(VivhiteCharacterAssets) &&
            method.Name == "CreateProfile");
        AcceptanceAssert.True(
            validationIndex >= 0 && profileIndex > validationIndex,
            "The cached V3 entry must validate every required asset before constructing its profile.");

        AcceptanceAssert.True(
            repository.SourceTypes.All(type =>
                type.FullName != "Vivhite.Characters.IroncladReplacementAssets"),
            "The retired IroncladReplacementAssets production type must remain deleted.");
        var productionSource = string.Join(
            "\n",
            repository.SourceDocuments.Select(document => document.Root.ToFullString()));
        string[] forbiddenIroncladReplacementSymbols =
        [
            "VanillaCharacterIds.Ironclad",
            "IroncladReplacementAssets",
            "PrefixIroncladCharacterSelectSfx",
            "PrefixIroncladCharacterTransitionSfx",
            "EnsureIroncladVirtualAudioOverrides",
            "_activeIroncladAudio"
        ];
        AcceptanceAssert.Empty(
            forbiddenIroncladReplacementSymbols
                .Where(symbol => productionSource.Contains(symbol, StringComparison.Ordinal))
                .ToArray(),
            "Vivhite production source must not register or patch a base-game Ironclad replacement:");

        AssertVivhiteOwnsCompleteAssetProfile(VivhiteCharacterAssets.CreateProfile());

        var vivhiteCharacter = new VivhiteCharacter();
        AcceptanceAssert.Equal(78, vivhiteCharacter.StartingHp, "Vivhite starting HP must be 78.");
        AcceptanceAssert.Equal(3, vivhiteCharacter.MaxEnergy, "Vivhite must start each turn with 3 energy.");
        AcceptanceAssert.Equal(99, vivhiteCharacter.StartingGold, "Vivhite starting gold must be 99.");
        AssertArchitectAttackVfxContract(repository, vivhiteCharacter);
        AssertCharacterSelectTransitionContract(repository);

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
        AcceptanceAssert.Empty(missingPages, "The Vivhite-owned V3 five-page combat skin must exist on disk:");
    }

    private static void AssertVivhiteOwnsCompleteAssetProfile(CharacterAssetProfile profile)
    {
        AcceptanceAssert.True(profile.Scenes is not null, "Vivhite's V3 profile must define scene assets.");
        AcceptanceAssert.Equal(
            "res://Vivhite/skins/ironclad/scenes/combat.tscn",
            profile.Scenes!.VisualsPath!,
            "Vivhite must own the V3 combat scene.");
        AcceptanceAssert.Equal(
            "res://Vivhite/skins/ironclad/scenes/merchant.tscn",
            profile.Scenes.MerchantAnimPath!,
            "Vivhite must own the V3 merchant scene.");
        AcceptanceAssert.Equal(
            "res://Vivhite/skins/ironclad/scenes/rest_site.tscn",
            profile.Scenes.RestSiteAnimPath!,
            "Vivhite must own the V3 rest-site scene.");

        AcceptanceAssert.True(profile.Ui is not null, "Vivhite's V3 profile must define UI assets.");
        AcceptanceAssert.Equal(
            "res://Vivhite/skins/ironclad/scenes/character_select.tscn",
            profile.Ui!.CharacterSelectBgPath!,
            "Vivhite must own the V3 character-select scene.");
        AcceptanceAssert.Equal(
            "res://Vivhite/skins/ironclad/ui/select.png",
            profile.Ui.CharacterSelectIconPath!,
            "Vivhite must own the unlocked character-select portrait.");
        AcceptanceAssert.Equal(
            "res://Vivhite/skins/ironclad/ui/select_locked.png",
            profile.Ui.CharacterSelectLockedIconPath!,
            "Vivhite must own the locked character-select portrait.");
        AcceptanceAssert.Equal(
            "res://Vivhite/skins/ironclad/ui/map_marker.png",
            profile.Ui.MapMarkerPath!,
            "Vivhite must own the map marker.");

        AcceptanceAssert.True(profile.Spine is not null, "Vivhite's V3 profile must define Spine assets.");
        AcceptanceAssert.Equal(
            "res://Vivhite/skins/ironclad/spine/combat/vivhite_combat_skeleton_data.tres",
            profile.Spine!.CombatSkeletonDataPath!,
            "Vivhite must own the V3 combat Spine resource.");

        AcceptanceAssert.True(
            profile.Multiplayer is not null,
            "Vivhite's V3 profile must define multiplayer hand assets.");
        string[] multiplayerPaths =
        [
            profile.Multiplayer!.ArmPointingTexturePath!,
            profile.Multiplayer.ArmRockTexturePath!,
            profile.Multiplayer.ArmPaperTexturePath!,
            profile.Multiplayer.ArmScissorsTexturePath!
        ];
        string[] expectedMultiplayerPaths =
        [
            "res://Vivhite/skins/ironclad/multiplayer/point.png",
            "res://Vivhite/skins/ironclad/multiplayer/rock.png",
            "res://Vivhite/skins/ironclad/multiplayer/paper.png",
            "res://Vivhite/skins/ironclad/multiplayer/scissors.png"
        ];
        AcceptanceAssert.True(
            multiplayerPaths.SequenceEqual(expectedMultiplayerPaths, StringComparer.Ordinal),
            $"Vivhite multiplayer resource ownership changed: [{string.Join(", ", multiplayerPaths)}]");
    }

    public static void VivhiteCombatSceneUsesEyeLensMagic(RepositorySnapshot repository)
    {
        var skinRoot = Path.Combine(repository.GodotProjectDirectory, "skins", "ironclad");
        var scenePath = Path.Combine(skinRoot, "scenes", "combat.tscn");
        var scriptPath = Path.Combine(skinRoot, "scenes", "vfx", "vivhite_combat_vfx.gd");
        var imagePath = Path.Combine(skinRoot, "scenes", "vfx", "vivhite_eye_lens_glint.png");
        var scene = File.ReadAllText(scenePath);
        var script = File.ReadAllText(scriptPath);

        string[] requiredSceneText =
        [
            "[ext_resource type=\"Script\" path=\"res://Vivhite/skins/ironclad/scenes/vfx/vivhite_combat_vfx.gd\" id=\"4_vfx\"]",
            "[ext_resource type=\"Texture2D\" path=\"res://Vivhite/skins/ironclad/scenes/vfx/vivhite_eye_lens_glint.png\" id=\"5_eye_magic\"]",
            "[node name=\"VivhiteCombatVfx\" type=\"Node\" parent=\"Visuals\"]",
            "[node name=\"EyeMagic\" type=\"TextureRect\" parent=\"Visuals/EyeSlot\"]",
            "texture = ExtResource(\"5_eye_magic\")"
        ];
        string[] retiredSceneText =
        [
            "res://src/Core/Nodes/Vfx/NIroncladVfx.cs",
            "[node name=\"NIroncladVfx\"",
            "[node name=\"EyeFire\"",
            "EyeFireMaterial",
            "vfx_stepped_shader_fire_flat.tres",
            "ironclad_eye_fire_base.png",
            "res://images/vfx/fire/",
            "res://images/vfx/environment/fire/"
        ];
        AcceptanceAssert.Empty(
            requiredSceneText.Where(fragment => !scene.Contains(fragment, StringComparison.Ordinal)).ToArray(),
            "The Vivhite-owned combat scene is missing lens-magic wiring:");
        AcceptanceAssert.Empty(
            retiredSceneText.Where(fragment => scene.Contains(fragment, StringComparison.Ordinal)).ToArray(),
            "The Vivhite-owned combat scene still contains retired Ironclad eye-fire wiring:");
        AcceptanceAssert.True(File.Exists(scriptPath), "The Vivhite combat VFX GDScript must exist.");
        AcceptanceAssert.True(File.Exists(imagePath), "The Vivhite eye-lens VFX texture must exist.");

        string[] requiredScriptText =
        [
            "extends Node",
            "_spine_sprite.get_node(\"SlashVfxSlot\")",
            "_spine_sprite.get_node(\"EyeSlot/EyeMagic\") as TextureRect",
            "_spine_sprite.connect(\"animation_event\", Callable(self, \"_on_animation_event\"))",
            "\"cast_eyes_start\":",
            "_eye_magic.visible = true",
            "\"clear_vfx\":",
            "_eye_magic.visible = false"
        ];
        AcceptanceAssert.Empty(
            requiredScriptText.Where(fragment => !script.Contains(fragment, StringComparison.Ordinal)).ToArray(),
            "The Vivhite combat VFX GDScript is missing its Spine-event bridge:");
        AcceptanceAssert.Empty(
            new[] { "NIroncladVfx", "EyeFire", "ironclad_eye_fire_base.png", "vfx_stepped_shader_fire_flat.tres" }
                .Where(fragment => script.Contains(fragment, StringComparison.Ordinal))
                .ToArray(),
            "The Vivhite combat VFX GDScript still depends on retired eye-fire code:");

        var contractPath = Path.Combine(repository.RootDirectory, "Vivhite", "tools", "ironclad-skin.contract.json");
        using var contract = JsonDocument.Parse(File.ReadAllText(contractPath));
        var contractRoot = contract.RootElement;
        var requiredResources = JsonStringSet(contractRoot.GetProperty("requiredResources"));
        AcceptanceAssert.Empty(
            new[]
            {
                "scenes/vfx/vivhite_combat_vfx.gd",
                "scenes/vfx/vivhite_eye_lens_glint.png"
            }.Where(path => !requiredResources.Contains(path)).ToArray(),
            "The private skin source allowlist is missing Vivhite eye-VFX resources:");

        var combatBinding = contractRoot.GetProperty("sceneBindings")
            .EnumerateArray()
            .Single(binding => binding.GetProperty("scene").GetString() == "scenes/combat.tscn");
        var sceneRequired = JsonStringSet(combatBinding.GetProperty("requiredText"));
        var sceneForbidden = JsonStringSet(combatBinding.GetProperty("forbiddenText"));
        AcceptanceAssert.Empty(
            requiredSceneText.Where(fragment => !sceneRequired.Contains(fragment)).ToArray(),
            "The combat scene contract is missing Vivhite eye-VFX requirements:");
        AcceptanceAssert.Empty(
            retiredSceneText.Where(fragment =>
                sceneRequired.Any(required => required.Contains(fragment, StringComparison.Ordinal))).ToArray(),
            "Retired Ironclad eye-fire text must never remain in combat requiredText:");
        AcceptanceAssert.Empty(
            new[]
            {
                "res://src/Core/Nodes/Vfx/NIroncladVfx.cs",
                "[node name=\"EyeFire\"",
                "res://shaders/vfx/vfx_stepped_shader_fire_flat.tres",
                "res://images/vfx/characters/ironclad_eye_fire_base.png"
            }.Where(fragment => !sceneForbidden.Contains(fragment)).ToArray(),
            "The combat scene contract must explicitly reject retired eye-fire dependencies:");

        var textBinding = contractRoot.GetProperty("textBindings")
            .EnumerateArray()
            .Single(binding => binding.GetProperty("path").GetString() == "scenes/vfx/vivhite_combat_vfx.gd");
        AcceptanceAssert.Equal(
            "gdscript",
            textBinding.GetProperty("kind").GetString()!,
            "The Vivhite VFX controller must use the GDScript syntax gate.");
        var contractScriptRequired = JsonStringSet(textBinding.GetProperty("requiredText"));
        AcceptanceAssert.Empty(
            requiredScriptText.Where(fragment => !contractScriptRequired.Contains(fragment)).ToArray(),
            "The GDScript source contract is missing required event semantics:");

        var combatSpine = contractRoot.GetProperty("spineSets")
            .EnumerateArray()
            .Single(set => set.GetProperty("name").GetString() == "combat");
        var spineSlots = JsonStringSet(combatSpine.GetProperty("slots"));
        var spineEvents = JsonStringSet(combatSpine.GetProperty("events"));
        AcceptanceAssert.Empty(
            new[] { "slash_mesh", "eye_attach_slot" }.Where(value => !spineSlots.Contains(value)).ToArray(),
            "The combat Spine contract lost a VFX attachment slot:");
        AcceptanceAssert.Empty(
            new[] { "attack_slash_start", "heavy_slash_start", "cast_eyes_start", "clear_vfx" }
                .Where(value => !spineEvents.Contains(value))
                .ToArray(),
            "The combat Spine contract lost a VFX event:");

        var validator = File.ReadAllText(Path.Combine(
            repository.RootDirectory,
            "Vivhite",
            "tools",
            "Validate-IroncladSkin.ps1"));
        AcceptanceAssert.Empty(
            new[]
            {
                "Test-TextBindingContract", "forbiddenText", "--check-only", "--script",
                "Invoke-GodotSpineContract", "Get-PckEntryPathsForLogicalAsset",
                "$logicalPath.remap", ".gdc"
            }
                .Where(fragment => !validator.Contains(fragment, StringComparison.Ordinal))
                .ToArray(),
            "The production validator must enforce Source text, GDScript syntax, and Spine contracts:");
    }

    public static void VivhiteProfileUsesVerifiedNativeMagicAudio(RepositorySnapshot repository)
    {
        _ = repository;
        const string select = "event:/sfx/characters/defect/defect_select";
        const string transition = "event:/sfx/ui/wipe_ironclad";
        const string attack = "event:/sfx/characters/defect/defect_attack";
        const string cast = "event:/sfx/characters/defect/defect_cast";
        const string death = "event:/sfx/characters/defect/defect_die";

        // These are the exact native paths exposed by the compiled v0.111.0 character model.
        var defect = new Defect();
        AcceptanceAssert.Equal(select, defect.CharacterSelectSfx, "Defect select FMOD path changed.");
        AcceptanceAssert.Equal(transition, defect.CharacterTransitionSfx, "The native wipe path changed.");
        AcceptanceAssert.Equal(attack, defect.AttackSfx, "Defect attack FMOD path changed.");
        AcceptanceAssert.Equal(cast, defect.CastSfx, "Defect cast FMOD path changed.");
        AcceptanceAssert.Equal(death, defect.DeathSfx, "Defect death FMOD path changed.");

        var profile = VivhiteCharacterAssets.CreateProfile();
        AssertAudio(profile.Audio, select, transition, attack, cast, death, "Vivhite V3 profile");

        // RitsuLib merges CharacterAudioAssetSet field by field. Supplying every field must
        // prevent the Ironclad placeholder from leaking back into the independent character.
        var resolved = CharacterAssetProfiles.Resolve(profile, "ironclad");
        AssertAudio(resolved.Audio, select, transition, attack, cast, death, "resolved profile");
        var vivhiteCharacterProfile = profile.WithScenes(profile.Scenes!);
        AssertAudio(
            vivhiteCharacterProfile.Audio,
            select,
            transition,
            attack,
            cast,
            death,
            "Vivhite character profile");

        var ironclad = new Ironclad();
        AcceptanceAssert.True(
            !string.Equals(ironclad.CharacterSelectSfx, select, StringComparison.Ordinal) &&
            !string.Equals(ironclad.AttackSfx, attack, StringComparison.Ordinal) &&
            !string.Equals(ironclad.CastSfx, cast, StringComparison.Ordinal) &&
            !string.Equals(ironclad.DeathSfx, death, StringComparison.Ordinal),
            "The base-game Ironclad must keep native Ironclad identity audio rather than Vivhite's magic audio.");
    }

    private static void AssertAudio(
        CharacterAudioAssetSet? audio,
        string select,
        string transition,
        string attack,
        string cast,
        string death,
        string label)
    {
        AcceptanceAssert.True(audio is not null, $"{label} must define all character audio fields.");
        AcceptanceAssert.Equal(select, audio!.CharacterSelectSfx!, $"{label} select sound mismatch.");
        AcceptanceAssert.Equal(transition, audio.CharacterTransitionSfx!, $"{label} transition sound mismatch.");
        AcceptanceAssert.Equal(attack, audio.AttackSfx!, $"{label} attack sound mismatch.");
        AcceptanceAssert.Equal(cast, audio.CastSfx!, $"{label} cast sound mismatch.");
        AcceptanceAssert.Equal(death, audio.DeathSfx!, $"{label} death sound mismatch.");

        var identityPaths = new[] { audio.CharacterSelectSfx, audio.AttackSfx, audio.CastSfx, audio.DeathSfx };
        AcceptanceAssert.Empty(
            identityPaths.Where(path =>
                path is null ||
                path.Contains("ironclad", StringComparison.OrdinalIgnoreCase) ||
                path.Contains("blood", StringComparison.OrdinalIgnoreCase) ||
                path.Contains("slash", StringComparison.OrdinalIgnoreCase) ||
                path.Contains("blade", StringComparison.OrdinalIgnoreCase)).ToArray(),
            $"{label} must not contain weapon, blood, or Ironclad identity events:");
    }

    private static HashSet<string> JsonStringSet(JsonElement array) =>
        array.EnumerateArray()
            .Select(value => value.GetString() ?? string.Empty)
            .ToHashSet(StringComparer.Ordinal);

    private static void AssertArchitectAttackVfxContract(
        RepositorySnapshot repository,
        VivhiteCharacter character)
    {
        string[] expected =
        [
            "vfx/vfx_attack_lightning",
            "vfx/vfx_starry_impact",
            "vfx/vfx_attack_lightning",
            "vfx/vfx_starry_impact",
            "vfx/vfx_attack_lightning"
        ];
        string[] forbiddenFragments =
        [
            "blood",
            "slash",
            "rock",
            "blade",
            "dagger",
            "stab",
            "sword",
            "thrash"
        ];

        var runtimePaths = character.GetArchitectAttackVfx();
        AcceptanceAssert.True(
            runtimePaths.SequenceEqual(expected, StringComparer.Ordinal),
            $"Vivhite's Architect VFX must preserve five magical hits. Actual: [{string.Join(", ", runtimePaths)}]");
        var independentlyMutablePaths = character.GetArchitectAttackVfx();
        AcceptanceAssert.True(
            !ReferenceEquals(runtimePaths, independentlyMutablePaths),
            "Each Architect VFX request must return a fresh list because The Architect shuffles it in place.");
        runtimePaths.Clear();
        AcceptanceAssert.True(
            independentlyMutablePaths.SequenceEqual(expected, StringComparer.Ordinal),
            "Mutating one Architect VFX list must not affect a later request.");

        var source = repository.RequireSourceType(typeof(VivhiteCharacter).FullName!).Declaration;
        var method = source.Members
            .OfType<MethodDeclarationSyntax>()
            .Single(member => member.Identifier.ValueText == nameof(VivhiteCharacter.GetArchitectAttackVfx));
        var sourcePaths = method.DescendantNodes()
            .OfType<LiteralExpressionSyntax>()
            .Select(literal => literal.Token.ValueText)
            .Where(value => value.StartsWith("vfx/", StringComparison.Ordinal))
            .ToArray();
        AcceptanceAssert.True(
            sourcePaths.SequenceEqual(expected, StringComparer.Ordinal),
            "The production Architect VFX source must contain only the approved native lightning and starry paths.");
        AcceptanceAssert.Empty(
            sourcePaths.Where(path => forbiddenFragments.Any(fragment =>
                path.Contains(fragment, StringComparison.OrdinalIgnoreCase))).ToArray(),
            "Vivhite's Architect VFX must not reintroduce weapon, blood, or rock-impact semantics:");
    }

    private static void AssertCharacterSelectTransitionContract(RepositorySnapshot repository)
    {
        const string textureResource =
            "res://Vivhite/skins/ironclad/transitions/vivhite_character_select_transition.png";
        const string materialResource =
            "res://Vivhite/skins/ironclad/transitions/vivhite_character_select_transition_mat.tres";

        var vivhiteProfile = VivhiteCharacterAssets.CreateProfile();
        AcceptanceAssert.True(vivhiteProfile.Ui is not null, "The Vivhite V3 profile must define UI assets.");
        AcceptanceAssert.Equal(
            materialResource,
            vivhiteProfile.Ui!.CharacterSelectTransitionPath!,
            "Vivhite must consume its private transition material.");

        var characterVivhiteProfile = CharacterAssetProfiles.WithScenes(
            vivhiteProfile,
            vivhiteProfile.Scenes
            ?? throw new AcceptanceFailureException("The Vivhite V3 profile has no scene set."));
        AcceptanceAssert.Equal(
            materialResource,
            characterVivhiteProfile.Ui!.CharacterSelectTransitionPath!,
            "Vivhite must retain its transition while overriding character-local scene fields.");

        var vivhiteFactory = RequireDeclaredMethod(typeof(VivhiteCharacter), "CreateVivhiteAssetProfile");
        var factoryCalls = IlInspection.CalledMethods(vivhiteFactory).ToArray();
        AcceptanceAssert.Equal(
            1,
            factoryCalls.Count(method =>
                method.DeclaringType == typeof(CharacterAssetProfiles) &&
                method.Name == nameof(CharacterAssetProfiles.WithScenes)),
            "Vivhite must derive its character profile through the scene override operation.");
        AcceptanceAssert.Equal(
            0,
            factoryCalls.Count(method =>
                method.DeclaringType == typeof(CharacterAssetProfiles) &&
                method.Name.Contains("Ui", StringComparison.Ordinal)),
            "Vivhite must not replace or clear its V3 transition UI field.");

        var ironcladTransition = new Ironclad().CharacterSelectTransitionPath;
        AcceptanceAssert.True(
            !string.Equals(materialResource, ironcladTransition, StringComparison.Ordinal),
            "The base-game Ironclad must not consume Vivhite's private transition material.");

        var transitionDirectory = Path.Combine(
            repository.GodotProjectDirectory,
            "skins",
            "ironclad",
            "transitions");
        var texturePath = Path.Combine(
            transitionDirectory,
            "vivhite_character_select_transition.png");
        var materialPath = Path.Combine(
            transitionDirectory,
            "vivhite_character_select_transition_mat.tres");
        AcceptanceAssert.True(File.Exists(texturePath), $"Transition texture is missing: {texturePath}");
        AcceptanceAssert.True(File.Exists(materialPath), $"Transition material is missing: {materialPath}");

        var pixels = DecodeRgb8Png(texturePath, out var width, out var height);
        AcceptanceAssert.Equal(2560, width, "Transition texture width changed.");
        AcceptanceAssert.Equal(1200, height, "Transition texture height changed.");
        AcceptanceAssert.Empty(
            Enumerable.Range(0, pixels.Length / 3)
                .Where(index =>
                {
                    var offset = index * 3;
                    return pixels[offset] != pixels[offset + 1] ||
                        pixels[offset + 1] != pixels[offset + 2];
                })
                .Take(1)
                .Select(index => $"pixel {index % width},{index / width}")
                .ToArray(),
            "Transition texture must remain strict grayscale RGB8:");

        var materialText = File.ReadAllText(materialPath);
        string[] requiredMaterialText =
        [
            textureResource,
            "shader_type canvas_item;",
            "uniform sampler2D transitionTex;",
            "uniform float threshold : hint_range(0,1);",
            "float falloff = 1.0 - texture(transitionTex, UV).r;",
            "float remap  = mix(-0.1, 1.1, threshold);",
            "falloff = step(falloff, remap);",
            "COLOR.a = falloff;",
            "shader_parameter/threshold = 0.332"
        ];
        AcceptanceAssert.Empty(
            requiredMaterialText.Where(text =>
                materialText.IndexOf(text, StringComparison.Ordinal) < 0).ToArray(),
            "Transition material must preserve the native red-channel threshold shader:");
    }

    public static void V3SkinRequiresExactFivePageLayout(RepositorySnapshot repository)
    {
        var skinType = typeof(VivhiteCharacterAssets);
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
        var profile = new SolitaryCrown().AssetProfile;
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

    private static byte[] DecodeRgb8Png(string path, out int width, out int height)
    {
        using var stream = File.OpenRead(path);
        Span<byte> signature = stackalloc byte[8];
        stream.ReadExactly(signature);
        byte[] expectedSignature = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
        if (!signature.SequenceEqual(expectedSignature))
        {
            throw new AcceptanceFailureException($"Transition texture is not a PNG: {path}");
        }

        width = 0;
        height = 0;
        var sawHeader = false;
        var sawImageData = false;
        var sawEnd = false;
        using var compressed = new MemoryStream();
        Span<byte> lengthBytes = stackalloc byte[4];
        Span<byte> typeBytes = stackalloc byte[4];
        Span<byte> crcBytes = stackalloc byte[4];
        while (!sawEnd)
        {
            stream.ReadExactly(lengthBytes);
            var length = BinaryPrimitives.ReadUInt32BigEndian(lengthBytes);
            if (length > int.MaxValue || length > stream.Length - stream.Position - 8)
            {
                throw new AcceptanceFailureException($"Transition PNG has an invalid chunk length: {length}");
            }
            stream.ReadExactly(typeBytes);
            var data = new byte[(int)length];
            stream.ReadExactly(data);
            stream.ReadExactly(crcBytes);
            var chunkType = Encoding.ASCII.GetString(typeBytes);

            switch (chunkType)
            {
                case "IHDR":
                    if (sawHeader || data.Length != 13)
                    {
                        throw new AcceptanceFailureException("Transition PNG has an invalid IHDR chunk.");
                    }
                    width = checked((int)BinaryPrimitives.ReadUInt32BigEndian(data.AsSpan(0, 4)));
                    height = checked((int)BinaryPrimitives.ReadUInt32BigEndian(data.AsSpan(4, 4)));
                    if (width <= 0 || height <= 0 ||
                        data[8] != 8 || data[9] != 2 ||
                        data[10] != 0 || data[11] != 0 || data[12] != 0)
                    {
                        throw new AcceptanceFailureException(
                            "Transition PNG must be non-interlaced opaque RGB8 (bit depth 8, color type 2)."
                        );
                    }
                    sawHeader = true;
                    break;
                case "IDAT":
                    if (!sawHeader)
                    {
                        throw new AcceptanceFailureException("Transition PNG has IDAT before IHDR.");
                    }
                    compressed.Write(data);
                    sawImageData = true;
                    break;
                case "tRNS":
                    throw new AcceptanceFailureException("Transition PNG must not contain transparency.");
                case "IEND":
                    if (data.Length != 0 || !sawImageData)
                    {
                        throw new AcceptanceFailureException("Transition PNG has an invalid IEND chunk.");
                    }
                    sawEnd = true;
                    break;
            }
        }
        if (!sawHeader || !sawImageData || stream.Position != stream.Length)
        {
            throw new AcceptanceFailureException("Transition PNG structure is incomplete or has trailing bytes.");
        }

        var rowBytes = checked(width * 3);
        var filtered = new byte[checked((rowBytes + 1) * height)];
        compressed.Position = 0;
        using (var zlib = new ZLibStream(compressed, CompressionMode.Decompress, leaveOpen: true))
        {
            zlib.ReadExactly(filtered);
            if (zlib.ReadByte() != -1)
            {
                throw new AcceptanceFailureException("Transition PNG expands beyond its declared dimensions.");
            }
        }

        var pixels = new byte[checked(rowBytes * height)];
        var previous = new byte[rowBytes];
        var current = new byte[rowBytes];
        var sourceOffset = 0;
        for (var y = 0; y < height; y++)
        {
            var filter = filtered[sourceOffset++];
            if (filter > 4)
            {
                throw new AcceptanceFailureException($"Transition PNG uses invalid row filter {filter}.");
            }
            for (var index = 0; index < rowBytes; index++)
            {
                var raw = filtered[sourceOffset++];
                var left = index >= 3 ? current[index - 3] : 0;
                var above = previous[index];
                var upperLeft = index >= 3 ? previous[index - 3] : 0;
                var predictor = filter switch
                {
                    0 => 0,
                    1 => left,
                    2 => above,
                    3 => (left + above) / 2,
                    4 => Paeth(left, above, upperLeft),
                    _ => 0
                };
                current[index] = (byte)((raw + predictor) & 0xff);
            }
            Buffer.BlockCopy(current, 0, pixels, y * rowBytes, rowBytes);
            (previous, current) = (current, previous);
        }
        return pixels;
    }

    private static int Paeth(int left, int above, int upperLeft)
    {
        var estimate = left + above - upperLeft;
        var leftDistance = Math.Abs(estimate - left);
        var aboveDistance = Math.Abs(estimate - above);
        var upperLeftDistance = Math.Abs(estimate - upperLeft);
        if (leftDistance <= aboveDistance && leftDistance <= upperLeftDistance)
        {
            return left;
        }
        return aboveDistance <= upperLeftDistance ? above : upperLeft;
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
