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
            23,
            repository.RegisteredPowers.Count,
            "The runtime RegisterPower inventory must contain exactly the 23 audited Vivhite powers.");

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
                .Where(type => type.Name != "ClosedManifoldPower" &&
                    !type.Name.StartsWith("VivhitesCrimsonTransformationRitual", StringComparison.Ordinal))
                .Select(repository.PowerId)
                .Where(id => !entries[$"{id}.smartDescription"].Contains("{Amount}", StringComparison.Ordinal))
                .ToArray();
            AcceptanceAssert.Empty(
                missingSmartAmount,
                $"Locale '{locale}' stack/counter power smartDescription entries must render their live Amount:");

            var ritualSmartDescriptions = repository.RegisteredPowers
                .Where(type => type.Name.StartsWith("VivhitesCrimsonTransformationRitual", StringComparison.Ordinal))
                .Select(repository.PowerId)
                .Select(id => entries[$"{id}.smartDescription"])
                .Where(text => !text.Contains("{Phase}", StringComparison.Ordinal) ||
                    !text.Contains("{DamagePercentPerPhase}", StringComparison.Ordinal))
                .ToArray();
            AcceptanceAssert.Empty(
                ritualSmartDescriptions,
                $"Locale '{locale}' ritual powers must render their independent live phase and per-phase damage rate:");
        }
    }

    public static void AllRegisteredPowersUseDedicatedExistingIcons(RepositorySnapshot repository)
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
        AcceptanceAssert.Equal(23, profiles.Count, "The icon audit must inspect all 23 registered powers.");

        var missingPaths = profiles
            .Where(item => string.IsNullOrWhiteSpace(item.Profile.IconPath) ||
                string.IsNullOrWhiteSpace(item.Profile.BigIconPath))
            .Select(item => item.Id)
            .ToArray();
        AcceptanceAssert.Empty(missingPaths, "Every registered power must provide both small and large dedicated icon paths:");
        var expectedSemanticIcons = repository.RegisteredPowers
            .Select(type => type.Name.Replace("UpgradedPower", "Power", StringComparison.Ordinal))
            .Distinct(StringComparer.Ordinal)
            .ToArray();
        var iconPaths = profiles.Select(item => item.Profile.IconPath!).Distinct(StringComparer.Ordinal).ToArray();
        var bigIconPaths = profiles.Select(item => item.Profile.BigIconPath!).Distinct(StringComparer.Ordinal).ToArray();
        AcceptanceAssert.Equal(
            expectedSemanticIcons.Length,
            iconPaths.Length,
            "Each semantic Vivhite power must own a small icon; upgraded variants may share only their base power's art.");
        AcceptanceAssert.Equal(
            expectedSemanticIcons.Length,
            bigIconPaths.Length,
            "Each semantic Vivhite power must own a large icon; upgraded variants may share only their base power's art.");

        const string projectPrefix = "res://Vivhite/";
        var assetFailures = new List<string>();
        foreach (var (id, profile) in profiles)
        {
            var powerType = repository.RegisteredPowers.Single(type => repository.PowerId(type) == id);
            var iconName = powerType.Name.Replace("UpgradedPower", "Power", StringComparison.Ordinal);
            var expectedPath = $"{projectPrefix}images/powers/{iconName}.png";
            foreach (var (size, iconPath) in new[]
                     {
                         ("small", profile.IconPath!),
                         ("large", profile.BigIconPath!)
                     })
            {
                if (!iconPath.StartsWith($"{projectPrefix}images/powers/", StringComparison.Ordinal) ||
                    iconPath.Contains("VivhiteRelic", StringComparison.OrdinalIgnoreCase) ||
                    iconPath.Contains("placeholder", StringComparison.OrdinalIgnoreCase) ||
                    iconPath.Contains("fallback", StringComparison.OrdinalIgnoreCase) ||
                    iconPath.Contains("missing_power", StringComparison.OrdinalIgnoreCase) ||
                    iconPath.Contains("power_atlas.sprites", StringComparison.OrdinalIgnoreCase))
                {
                    assetFailures.Add($"{id} {size}: non-dedicated/NOPE path {iconPath}");
                    continue;
                }

                if (!string.Equals(iconPath, expectedPath, StringComparison.Ordinal))
                {
                    assetFailures.Add(
                        $"{id} {size}: expected dedicated semantic icon {expectedPath}, actual {iconPath}");
                    continue;
                }

                var diskPath = Path.Combine(
                    repository.GodotProjectDirectory,
                    iconPath[projectPrefix.Length..].Replace('/', Path.DirectorySeparatorChar));
                if (!File.Exists(diskPath))
                {
                    assetFailures.Add($"{id} {size}: resource is missing: {diskPath}");
                }
            }

            if (id == "VIVHITE_POWER_INFINITE_MARGIN_POWER" &&
                (!profile.IconPath!.Contains("InfiniteMargin", StringComparison.OrdinalIgnoreCase) ||
                 !profile.BigIconPath!.Contains("InfiniteMargin", StringComparison.OrdinalIgnoreCase)))
            {
                assetFailures.Add(
                    $"{id}: Margin must use its own InfiniteMargin artwork, actual {profile.IconPath} / {profile.BigIconPath}");
            }
        }

        AcceptanceAssert.Empty(
            assetFailures,
            "Vivhite power icons must use existing dedicated pack resources rather than the generic relic fallback or red NOPE:");
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
