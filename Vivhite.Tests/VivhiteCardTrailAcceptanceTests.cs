using System.Buffers.Binary;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.RegularExpressions;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using STS2RitsuLib.Scaffolding.Characters;
using Vivhite.Characters;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests;

internal static class VivhiteCardTrailAcceptanceTests
{
    private const string ExpectedTrailScenePath =
        "res://Vivhite/scenes/vfx/card_trail_vivhite.tscn";

    private const string ExpectedTrailTexturePath =
        "res://Vivhite/images/vfx/vivhite_card_trail_mathematical_star_0194.png";

    private const string ExpectedTrailTextureSha256 =
        "1595AC644C9384CDFB9C1DED4BD2546FFE328AA888654691280C1481518F3EEE";

    private const string ExpectedTrailSceneSha256 =
        "BA493F9C6C7665D80B1939CFA9A7C2D67D9CE9533EE910B250A57CF5D0647C6C";

    public static void IsOwnedOnlyByVivhiteCharacter(RepositorySnapshot repository)
    {
        AssertVivhiteBaseProfileExcludesTheCharacterTrail(repository);
        AssertVivhiteFactoryOwnsTheTrailOverride(repository);
        AssertVivhiteTrailResources(repository);
    }

    private static void AssertVivhiteBaseProfileExcludesTheCharacterTrail(RepositorySnapshot repository)
    {
        var baseProfile = VivhiteCharacterAssets.CreateProfile();
        AcceptanceAssert.True(
            baseProfile.Vfx is null,
            "The structural Vivhite V3 profile must leave the character-owned trail override unset.");

        var requiredAssetsField = typeof(VivhiteCharacterAssets).GetField(
            "RequiredAssets",
            BindingFlags.Static | BindingFlags.NonPublic)
            ?? throw new AcceptanceFailureException(
                "VivhiteCharacterAssets.RequiredAssets is missing.");
        var requiredAssets = (Array?)requiredAssetsField.GetValue(null)
            ?? throw new AcceptanceFailureException(
                "VivhiteCharacterAssets.RequiredAssets is null.");
        var requiredPaths = requiredAssets.Cast<object>()
            .Select(asset => asset.GetType().GetProperty(
                    "Path",
                    BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
                ?.GetValue(asset) as string)
            .Where(path => path is not null)
            .Cast<string>()
            .ToArray();
        AcceptanceAssert.Empty(
            requiredPaths.Where(IsVivhiteTrailResource).ToArray(),
            "The reusable Vivhite V3 RequiredAssets gate must not absorb the character-local trail resources:");

        var source = repository.RequireSourceType(typeof(VivhiteCharacterAssets).FullName!).Declaration;
        var sourceText = source.ToFullString();
        AcceptanceAssert.True(
            !sourceText.Contains("card_trail_vivhite", StringComparison.Ordinal) &&
            !sourceText.Contains("vivhite_card_trail_mathematical_star_0194", StringComparison.Ordinal),
            "VivhiteCharacterAssets must leave both character-local card-trail resources to VivhiteCharacter.");
    }

    private static void AssertVivhiteFactoryOwnsTheTrailOverride(RepositorySnapshot repository)
    {
        var trailPathField = typeof(VivhiteCharacter).GetField(
            "CardTrailScenePath",
            BindingFlags.Static | BindingFlags.NonPublic)
            ?? throw new AcceptanceFailureException(
                "VivhiteCharacter.CardTrailScenePath is missing.");
        AcceptanceAssert.Equal(
            ExpectedTrailScenePath,
            trailPathField.GetRawConstantValue() as string
                ?? throw new AcceptanceFailureException(
                    "VivhiteCharacter.CardTrailScenePath must remain a compiled string constant."),
            "VivhiteCharacter must compile the exact character-owned card-trail scene path.");

        var factory = typeof(VivhiteCharacter).GetMethod(
            "CreateVivhiteAssetProfile",
            BindingFlags.Static | BindingFlags.NonPublic)
            ?? throw new AcceptanceFailureException(
                "VivhiteCharacter.CreateVivhiteAssetProfile is missing.");
        var calls = IlInspection.CalledMethods(factory).ToArray();
        var withScenesIndex = Array.FindIndex(calls, method =>
            method.DeclaringType == typeof(CharacterAssetProfiles) &&
            method.Name == nameof(CharacterAssetProfiles.WithScenes));
        var withVfxIndex = Array.FindIndex(calls, method =>
            method.DeclaringType == typeof(CharacterAssetProfiles) &&
            method.Name == nameof(CharacterAssetProfiles.WithVfx));
        AcceptanceAssert.True(
            withScenesIndex >= 0 && withVfxIndex > withScenesIndex,
            "Vivhite must apply its scene override first and then its own VFX override through WithVfx.");
        AcceptanceAssert.Equal(
            1,
            calls.Count(method =>
                method.DeclaringType == typeof(CharacterAssetProfiles) &&
                method.Name == nameof(CharacterAssetProfiles.WithVfx)),
            "VivhiteCharacter must publish exactly one character-owned VFX override.");

        var source = repository.RequireSourceType(typeof(VivhiteCharacter).FullName!).Declaration;
        var factorySource = source.Members
            .OfType<MethodDeclarationSyntax>()
            .Single(method => method.Identifier.ValueText == "CreateVivhiteAssetProfile");
        var withVfxCall = factorySource.DescendantNodes()
            .OfType<InvocationExpressionSyntax>()
            .Single(invocation =>
                invocation.Expression is MemberAccessExpressionSyntax access &&
                access.Expression is IdentifierNameSyntax owner &&
                owner.Identifier.ValueText == nameof(CharacterAssetProfiles) &&
                access.Name.Identifier.ValueText == nameof(CharacterAssetProfiles.WithVfx));
        var vfxAsset = withVfxCall.ArgumentList.Arguments
            .Select(argument => argument.Expression)
            .OfType<ObjectCreationExpressionSyntax>()
            .SingleOrDefault(creation => creation.Type.ToString() == nameof(CharacterVfxAssetSet))
            ?? throw new AcceptanceFailureException(
                "Vivhite's WithVfx call must construct its own CharacterVfxAssetSet.");
        var trailArgument = vfxAsset.ArgumentList?.Arguments
            .SingleOrDefault(argument => argument.NameColon?.Name.Identifier.ValueText == "TrailPath");
        AcceptanceAssert.True(
            trailArgument?.Expression is IdentifierNameSyntax identifier &&
            identifier.Identifier.ValueText == "CardTrailScenePath",
            "Vivhite's CharacterVfxAssetSet must bind TrailPath to CardTrailScenePath.");
    }

    private static void AssertVivhiteTrailResources(RepositorySnapshot repository)
    {
        var scenePath = Path.Combine(
            repository.GodotProjectDirectory,
            "scenes",
            "vfx",
            "card_trail_vivhite.tscn");
        var texturePath = Path.Combine(
            repository.GodotProjectDirectory,
            "images",
            "vfx",
            "vivhite_card_trail_mathematical_star_0194.png");
        AcceptanceAssert.True(File.Exists(scenePath), $"Vivhite card-trail scene is missing: {scenePath}");
        AcceptanceAssert.True(File.Exists(texturePath), $"Vivhite card-trail texture is missing: {texturePath}");

        var scene = File.ReadAllText(scenePath);
        string[] requiredSceneFragments =
        [
            "[gd_scene load_steps=11 format=3]",
            $"path=\"{ExpectedTrailTexturePath}\"",
            "[node name=\"Trails\" type=\"Node2D\" parent=\".\"]",
            "[node name=\"OuterTrail\" type=\"Line2D\" parent=\"Trails\"]",
            "[node name=\"InnerTrail\" type=\"Line2D\" parent=\"Trails\"]",
            "[node name=\"Sprites\" type=\"Node2D\" parent=\".\"]",
            "[node name=\"BigSparks\" type=\"CPUParticles2D\" parent=\"Sprites\"]",
            "[node name=\"LittleSparks\" type=\"CPUParticles2D\" parent=\"Sprites\"]",
            "[node name=\"Sprite2D2\" type=\"Sprite2D\" parent=\"Sprites\"]",
            "[node name=\"Sprite2D3\" type=\"Sprite2D\" parent=\"Sprites\"]"
        ];
        AcceptanceAssert.Empty(
            requiredSceneFragments.Where(fragment => !scene.Contains(fragment, StringComparison.Ordinal)).ToArray(),
            "Vivhite's card-trail scene is missing required consumer-contract fragments:");

        string[] forbiddenBrushFragments =
        [
            "res://images/packed/vfx/",
            "res://images/vfx/",
            "res://images/packed/vfx/trail.png",
            "res://images/packed/vfx/trail2.png",
            "brush_particle_2",
            "brush_particle"
        ];
        AcceptanceAssert.Empty(
            forbiddenBrushFragments
                .Where(fragment => scene.Contains(fragment, StringComparison.OrdinalIgnoreCase))
                .ToArray(),
            "Vivhite's card-trail scene must not retain any original-game trail brush or particle texture:");

        var textureResources = Regex.Matches(
                scene,
                @"\[ext_resource type=""Texture2D"" path=""(?<path>[^""]+)""")
            .Select(match => match.Groups["path"].Value)
            .ToArray();
        AcceptanceAssert.Equal(
            1,
            textureResources.Length,
            "Vivhite's trail scene must declare exactly one Texture2D resource.");
        AcceptanceAssert.Equal(
            ExpectedTrailTexturePath,
            textureResources.Single(),
            "Every trail particle and sprite must use only Vivhite's approved 0194 texture.");

        var ribbonBlocks = Regex.Matches(
            scene,
            @"^\[node name=""(?<name>OuterTrail|InnerTrail)"" type=""Line2D"" parent=""Trails""\]\r?\n(?<body>.*?)(?=^\[node |\z)",
            RegexOptions.Multiline | RegexOptions.Singleline);
        AcceptanceAssert.Equal(2, ribbonBlocks.Count, "Both textureless ribbon nodes must remain present.");
        AcceptanceAssert.Empty(
            ribbonBlocks
                .Select(match => match.Groups["body"].Value)
                .Where(body => Regex.IsMatch(
                    body,
                    @"^\s*texture(?:_mode)?\s*=",
                    RegexOptions.Multiline))
                .ToArray(),
            "OuterTrail and InnerTrail must use only width/gradient ribbons without texture bindings:");

        var actualSceneSha256 = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(scenePath)));
        AcceptanceAssert.Equal(
            ExpectedTrailSceneSha256,
            actualSceneSha256,
            "Vivhite's approved textureless card-trail scene changed unexpectedly.");

        using var stream = File.OpenRead(texturePath);
        Span<byte> header = stackalloc byte[26];
        AcceptanceAssert.Equal(
            header.Length,
            stream.Read(header),
            "Vivhite's card-trail PNG header is truncated.");
        byte[] pngSignature = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
        AcceptanceAssert.True(
            header[..8].SequenceEqual(pngSignature) && header[12..16].SequenceEqual("IHDR"u8),
            "Vivhite's card-trail texture must be a PNG with IHDR as its first chunk.");
        AcceptanceAssert.Equal(
            256u,
            BinaryPrimitives.ReadUInt32BigEndian(header[16..20]),
            "Vivhite's card-trail texture width must remain 256 pixels.");
        AcceptanceAssert.Equal(
            256u,
            BinaryPrimitives.ReadUInt32BigEndian(header[20..24]),
            "Vivhite's card-trail texture height must remain 256 pixels.");
        AcceptanceAssert.Equal((byte)8, header[24], "Vivhite's card-trail PNG must remain 8-bit.");
        AcceptanceAssert.Equal((byte)6, header[25], "Vivhite's card-trail PNG must remain RGBA.");

        stream.Position = 0;
        var actualSha256 = Convert.ToHexString(SHA256.HashData(stream));
        AcceptanceAssert.Equal(
            ExpectedTrailTextureSha256,
            actualSha256,
            "Vivhite's approved transparent card-trail texture changed unexpectedly.");
    }

    private static bool IsVivhiteTrailResource(string path) =>
        string.Equals(path, ExpectedTrailScenePath, StringComparison.Ordinal) ||
        string.Equals(path, ExpectedTrailTexturePath, StringComparison.Ordinal) ||
        path.Contains("card_trail_vivhite", StringComparison.Ordinal) ||
        path.Contains("vivhite_card_trail_mathematical_star_0194", StringComparison.Ordinal);
}
