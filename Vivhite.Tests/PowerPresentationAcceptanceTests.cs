using System.Text.Json;
using STS2RitsuLib.Scaffolding.Content;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests;

internal static class PowerPresentationAcceptanceTests
{
    private static readonly string[] RequiredPowerSuffixes =
        ["title", "description", "smartDescription"];

    public static void AllRegisteredPowersHaveCompleteBilingualLocalization(RepositorySnapshot repository)
    {
        AcceptanceAssert.Equal(
            21,
            repository.RegisteredPowers.Count,
            "The runtime RegisterPower inventory must contain exactly the 21 audited Vivhite powers.");

        var expectedIds = repository.RegisteredPowers
            .Select(repository.PowerId)
            .Order(StringComparer.Ordinal)
            .ToArray();
        var expectedKeys = expectedIds
            .SelectMany(id => RequiredPowerSuffixes.Select(suffix => $"{id}.{suffix}"))
            .Order(StringComparer.Ordinal)
            .ToArray();

        foreach (var locale in new[] { "eng", "zhs" })
        {
            var entries = ReadObject(repository, locale, "powers.json");
            AcceptanceAssert.SetEqual(
                expectedKeys,
                entries.Keys.Order(StringComparer.Ordinal).ToArray(),
                $"Locale '{locale}' powers.json must exactly cover title/description/smartDescription for every registered power.");

            var rawOrEmpty = expectedKeys
                .Where(key => !entries.TryGetValue(key, out var value) ||
                    string.IsNullOrWhiteSpace(value) ||
                    string.Equals(value, key, StringComparison.Ordinal) ||
                    value.StartsWith("VIVHITE_POWER_", StringComparison.Ordinal))
                .ToArray();
            AcceptanceAssert.Empty(
                rawOrEmpty,
                $"Locale '{locale}' must never expose a raw power localization key:");

            var missingSmartAmount = repository.RegisteredPowers
                .Where(type => type.Name != "ClosedManifoldPower")
                .Select(repository.PowerId)
                .Where(id => !entries[$"{id}.smartDescription"].Contains("{Amount}", StringComparison.Ordinal))
                .ToArray();
            AcceptanceAssert.Empty(
                missingSmartAmount,
                $"Locale '{locale}' stack/counter power smartDescription entries must render their live Amount:");
        }
    }

    public static void AllRegisteredPowersUseOneExistingNonNopePlaceholder(RepositorySnapshot repository)
    {
        var failures = new List<string>();
        var profiles = new List<(string Id, PowerAssetProfile Profile)>();
        foreach (var powerType in repository.RegisteredPowers)
        {
            var powerId = repository.PowerId(powerType);
            try
            {
                var power = (ModPowerTemplate?)Activator.CreateInstance(powerType)
                    ?? throw new InvalidOperationException("constructor returned null");
                profiles.Add((powerId, power.AssetProfile));
            }
            catch (Exception exception)
            {
                failures.Add($"{powerId}: could not construct registered power: {exception.GetBaseException().Message}");
            }
        }

        AcceptanceAssert.Empty(failures, "Every registered power must expose its presentation profile:");
        AcceptanceAssert.Equal(21, profiles.Count, "The icon audit must inspect all 21 registered powers.");

        var missingPaths = profiles
            .Where(item => string.IsNullOrWhiteSpace(item.Profile.IconPath) ||
                string.IsNullOrWhiteSpace(item.Profile.BigIconPath))
            .Select(item => item.Id)
            .ToArray();
        AcceptanceAssert.Empty(missingPaths, "Every registered power must provide both small and large placeholder paths:");
        var iconPaths = profiles.Select(item => item.Profile.IconPath!).Distinct(StringComparer.Ordinal).ToArray();
        var bigIconPaths = profiles.Select(item => item.Profile.BigIconPath!).Distinct(StringComparer.Ordinal).ToArray();
        AcceptanceAssert.Equal(1, iconPaths.Length, "All Vivhite powers must share one intentional placeholder icon.");
        AcceptanceAssert.Equal(1, bigIconPaths.Length, "All Vivhite powers must share one intentional large placeholder icon.");
        AcceptanceAssert.Equal(iconPaths[0], bigIconPaths[0], "Small and large power placeholders must resolve to the same known-good texture.");

        var iconPath = iconPaths[0];
        AcceptanceAssert.True(
            !string.IsNullOrWhiteSpace(iconPath) &&
            !iconPath.Contains("missing_power", StringComparison.OrdinalIgnoreCase) &&
            !iconPath.Contains("power_atlas.sprites", StringComparison.OrdinalIgnoreCase),
            $"Power icon path must not fall through to the engine NOPE icon or a nonexistent atlas region: {iconPath}");
        const string projectPrefix = "res://Vivhite/";
        AcceptanceAssert.True(
            iconPath.StartsWith(projectPrefix, StringComparison.Ordinal),
            $"Power placeholder must be a Vivhite pack resource: {iconPath}");
        var diskPath = Path.Combine(
            repository.GodotProjectDirectory,
            iconPath[projectPrefix.Length..].Replace('/', Path.DirectorySeparatorChar));
        AcceptanceAssert.True(File.Exists(diskPath), $"Power placeholder resource is missing on disk: {diskPath}");
    }

    private static IReadOnlyDictionary<string, string> ReadObject(
        RepositorySnapshot repository,
        string locale,
        string fileName)
    {
        var path = Path.Combine(repository.LocalizationDirectory, locale, fileName);
        AcceptanceAssert.True(File.Exists(path), $"Localization file is missing: {path}");
        using var document = JsonDocument.Parse(File.ReadAllText(path));
        AcceptanceAssert.True(document.RootElement.ValueKind == JsonValueKind.Object, $"Localization file must be a JSON object: {path}");
        return document.RootElement.EnumerateObject().ToDictionary(
            property => property.Name,
            property => property.Value.GetString() ?? string.Empty,
            StringComparer.Ordinal);
    }
}
