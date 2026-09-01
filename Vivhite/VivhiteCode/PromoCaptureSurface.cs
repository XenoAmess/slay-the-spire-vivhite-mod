using Godot;
using HarmonyLib;
using MegaCrit.Sts2.Core.Nodes.Debug;

namespace Vivhite;

/// <summary>
/// Keeps the game's diagnostic version/"MODDED" labels out of an explicitly
/// requested promo capture. This is deliberately opt-in: ordinary players
/// still see the native warning, and the capture run records the environment
/// switch in its runtime manifest.
/// </summary>
internal static class PromoCaptureSurface
{
    private const string EnableVariable = "VIVHITE_PROMO_CAPTURE";
    private const string HarmonyId = "Vivhite.PromoCaptureSurface";
    private static Harmony? _harmony;

    public static void InstallIfEnabled()
    {
        if (!IsEnabled() || _harmony is not null)
        {
            return;
        }

        try
        {
            var harmony = new Harmony(HarmonyId);
            Patch(harmony, "_Ready");
            // _Ready can schedule SetCommitIdInEditor(), which calls
            // UpdateText after an await.  UpdateText also re-enables the
            // MODDED label, so cover that path as well as scene creation.
            Patch(harmony, "UpdateText", new[] { typeof(string) });
            _harmony = harmony;
            Entry.Logger.Info(
                $"Promo capture surface enabled ({EnableVariable}=1); native debug labels will be hidden.");
        }
        catch (Exception exception)
        {
            // A capture-only cosmetic aid must never prevent the Mod from
            // loading. The capture preflight will still flag the labels if
            // this opt-in patch cannot be installed.
            Entry.Logger.Error(
                $"Promo capture surface could not be installed: {exception.GetType().Name}: {exception.Message}");
        }
    }

    private static void Patch(Harmony harmony, string methodName, Type[]? argumentTypes = null)
    {
        var target = argumentTypes is null
            ? AccessTools.Method(typeof(NDebugInfoLabelManager), methodName)
            : AccessTools.Method(typeof(NDebugInfoLabelManager), methodName, argumentTypes);
        if (target is null)
        {
            throw new MissingMethodException(typeof(NDebugInfoLabelManager).FullName, methodName);
        }

        harmony.Patch(
            target,
            postfix: new HarmonyMethod(
                typeof(PromoCaptureSurface),
                nameof(HideNativeDebugLabels)));
    }

    private static bool IsEnabled()
    {
        return string.Equals(
            System.Environment.GetEnvironmentVariable(EnableVariable),
            "1",
            StringComparison.Ordinal);
    }

    // Harmony identifies the patched receiver through the reserved
    // ``__instance`` parameter name.  A normal parameter name would be
    // interpreted as an original _Ready argument (of which there are none)
    // and the patch would fail to install at runtime.
    private static void HideNativeDebugLabels(NDebugInfoLabelManager __instance)
    {
        try
        {
            Hide(__instance, "%ReleaseInfo");
            Hide(__instance, "%ModdedWarning");
            Hide(__instance, "%DebugSeed");
            Hide(__instance, "%ModWarningContainer");
        }
        catch (Exception exception)
        {
            Entry.Logger.Warn(
                $"Promo capture surface could not hide native debug labels: {exception.GetType().Name}: {exception.Message}");
        }
    }

    private static void Hide(Node owner, string uniquePath)
    {
        if (owner.GetNodeOrNull<CanvasItem>(new NodePath(uniquePath)) is CanvasItem item)
        {
            item.Visible = false;
        }
    }
}
