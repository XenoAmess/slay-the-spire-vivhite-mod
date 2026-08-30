using System.Reflection;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Models;
using Vivhite.Cards.Common;
using Vivhite.Characters;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests;

internal static class SharedAssetsAcceptanceTests
{
    public static void VivhiteAndIroncladUseTheSameV3Skin(RepositorySnapshot repository)
    {
        var ironclad = IroncladReplacementAssets.CreateProfile();
        var vivhiteCharacter = new VivhiteCharacter();
        var vivhite = vivhiteCharacter.AssetProfile;

        AssertStringPropertiesEqual(ironclad.Scenes, vivhite.Scenes, excludedProperty: "EnergyCounterPath");
        AssertStringPropertiesEqual(ironclad.Ui, vivhite.Ui);
        AssertStringPropertiesEqual(ironclad.Spine, vivhite.Spine);
        AssertStringPropertiesEqual(ironclad.Multiplayer, vivhite.Multiplayer);

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

    public static void CardPortraitsResolveToRealTypeAppropriatePlaceholders(RepositorySnapshot repository)
    {
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

                var assetProfile = cardType.GetProperty(
                    "AssetProfile",
                    BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)?.GetValue(card);
                var portraitPath = assetProfile?.GetType().GetProperty("PortraitPath")?.GetValue(assetProfile) as string;
                if (portraitPath is null)
                {
                    failures.Add($"{repository.CardId(cardType)}: AssetProfile.PortraitPath is null");
                    continue;
                }
                var expected = card.Type == CardType.Attack
                    ? VivhitePlaceholderArt.AttackPortraitPath
                    : VivhitePlaceholderArt.NonAttackPortraitPath;
                if (!string.Equals(expected, portraitPath, StringComparison.Ordinal))
                {
                    failures.Add($"{repository.CardId(cardType)}: expected {expected}, actual {portraitPath ?? "<null>"}");
                    continue;
                }

                var onDisk = ResourcePathToDisk(repository, portraitPath);
                if (!File.Exists(onDisk))
                {
                    failures.Add($"{repository.CardId(cardType)}: missing placeholder file {onDisk}");
                }
            }
            catch (Exception exception)
            {
                failures.Add($"{cardType.FullName}: {exception.GetBaseException().Message}");
            }
        }
        AcceptanceAssert.Empty(failures, "Every card must resolve at runtime to an existing attack or non-attack placeholder:");
    }

    private static void AssertStringPropertiesEqual(object? expected, object? actual, string? excludedProperty = null)
    {
        AcceptanceAssert.True(expected is not null && actual is not null, "Shared skin profile sections must be present for both characters.");
        var expectedType = expected!.GetType();
        var actualType = actual!.GetType();
        var differences = expectedType.GetProperties(BindingFlags.Instance | BindingFlags.Public)
            .Where(property => property.PropertyType == typeof(string) && property.Name != excludedProperty)
            .Select(property =>
            {
                var expectedValue = property.GetValue(expected) as string;
                var actualProperty = actualType.GetProperty(property.Name, BindingFlags.Instance | BindingFlags.Public);
                var actualValue = actualProperty?.GetValue(actual) as string;
                return (property.Name, Expected: expectedValue, Actual: actualValue);
            })
            .Where(item => !string.Equals(item.Expected, item.Actual, StringComparison.Ordinal))
            .Select(item => $"{expectedType.Name}.{item.Name}: Ironclad={item.Expected ?? "<null>"}, Vivhite={item.Actual ?? "<null>"}")
            .ToArray();
        AcceptanceAssert.Empty(differences, "Vivhite and the Ironclad replacement must share the same skin resource paths:");
    }

    private static string ResourcePathToDisk(RepositorySnapshot repository, string resourcePath)
    {
        const string prefix = "res://Vivhite/";
        AcceptanceAssert.True(resourcePath.StartsWith(prefix, StringComparison.Ordinal), $"Unexpected resource root: {resourcePath}");
        return Path.Combine(
            repository.GodotProjectDirectory,
            resourcePath[prefix.Length..].Replace('/', Path.DirectorySeparatorChar));
    }
}
