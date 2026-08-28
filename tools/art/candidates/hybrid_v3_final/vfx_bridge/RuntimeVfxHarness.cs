using System.Reflection;
using System.Security.Cryptography;
using Godot;
using Godot.Collections;
using MegaCrit.Sts2.Core.Bindings.MegaSpine;
using MegaCrit.Sts2.Core.Nodes.Vfx;

/// <summary>
/// Acceptance-only bridge into the exact NIroncladVfx type shipped by the
/// installed game. This file belongs to a throwaway Mono project and must
/// never be linked into the Vivhite mod assembly.
/// </summary>
public partial class RuntimeVfxHarness : RefCounted
{
    private static readonly FieldInfo? TweenField = typeof(NIroncladVfx).GetField(
        "_tween",
        BindingFlags.Instance | BindingFlags.NonPublic);

    private readonly Array<Dictionary> _signalLog = [];
    private double _probeTime;

    public Node CreateRuntimeVfx()
    {
        return new NIroncladVfx();
    }

    public void AttachSignalProbe(Node spineSprite)
    {
        var sprite = new MegaSprite(spineSprite);
        sprite.ConnectAnimationStarted(
            Callable.From<GodotObject, GodotObject, GodotObject>(OnAnimationStarted));
        sprite.ConnectAnimationEvent(
            Callable.From<GodotObject, GodotObject, GodotObject, GodotObject>(OnAnimationEvent));
    }

    public void SetProbeTime(double seconds)
    {
        _probeTime = seconds;
    }

    public void ClearSignalLog()
    {
        _signalLog.Clear();
    }

    public Array<Dictionary> GetSignalLog()
    {
        return _signalLog;
    }

    public Dictionary GetRuntimeTweenSnapshot(Node runtimeVfx)
    {
        var result = new Dictionary
        {
            ["exists"] = false,
            ["valid"] = false,
            ["running"] = false,
            ["instance_id"] = 0UL,
            ["elapsed"] = 0.0,
        };
        if (runtimeVfx is not NIroncladVfx || TweenField?.GetValue(runtimeVfx) is not Tween tween)
        {
            return result;
        }

        result["exists"] = true;
        result["instance_id"] = tween.GetInstanceId();
        try
        {
            result["valid"] = tween.IsValid();
            result["running"] = tween.IsRunning();
            result["elapsed"] = tween.GetTotalElapsedTime();
        }
        catch (ObjectDisposedException)
        {
            // Preserve exists=true while making a killed/disposed Tween explicit.
        }
        return result;
    }

    public bool CustomStepRuntimeVfx(Node runtimeVfx, double delta)
    {
        if (runtimeVfx is not NIroncladVfx || TweenField?.GetValue(runtimeVfx) is not Tween tween)
        {
            return false;
        }
        if (!tween.IsValid())
        {
            return false;
        }
        return tween.CustomStep(delta);
    }

    public string GetConsumerTypeName()
    {
        return typeof(NIroncladVfx).FullName ?? string.Empty;
    }

    public string GetConsumerAssemblyPath()
    {
        return typeof(NIroncladVfx).Assembly.Location ?? string.Empty;
    }

    public string GetConsumerAssemblySha256()
    {
        var path = GetConsumerAssemblyPath();
        if (string.IsNullOrEmpty(path) || !File.Exists(path))
        {
            // Godot's collectible AssemblyLoadContext commonly loads dependency
            // bytes without a Location. The runner independently hashes the
            // exact sts2.dll passed to the bridge build.
            return string.Empty;
        }
        return Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path)));
    }

    public string GetConsumerAssemblyIdentity()
    {
        return typeof(NIroncladVfx).Assembly.FullName ?? string.Empty;
    }

    public string GetConsumerModuleVersionId()
    {
        return typeof(NIroncladVfx).Module.ModuleVersionId.ToString("D");
    }

    private void OnAnimationStarted(
        GodotObject _,
        GodotObject animationState,
        GodotObject __)
    {
        var animationName = new MegaAnimationState(animationState).GetCurrentAnimationName() ?? string.Empty;
        _signalLog.Add(new Dictionary
        {
            ["kind"] = "animation_started",
            ["name"] = animationName,
            ["time"] = _probeTime,
        });
    }

    private void OnAnimationEvent(
        GodotObject _,
        GodotObject __,
        GodotObject ___,
        GodotObject spineEvent)
    {
        var eventName = new MegaEvent(spineEvent).GetData().GetEventName();
        _signalLog.Add(new Dictionary
        {
            ["kind"] = "animation_event",
            ["name"] = eventName,
            ["time"] = _probeTime,
        });
    }
}
