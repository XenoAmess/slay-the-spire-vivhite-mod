using System.Reflection;
using System.Runtime.CompilerServices;
using MegaCrit.Sts2.Core.Entities.Creatures;

namespace Vivhite.Tests.Acceptance;

internal static class EngineTestObjects
{
    public static Creature CreateCreature(int currentHp, int maxHp, bool enemy)
    {
        var creature = (Creature)RuntimeHelpers.GetUninitializedObject(typeof(Creature));
        SetAutoProperty(creature, "MaxHp", maxHp);
        SetAutoProperty(creature, "CurrentHp", currentHp);

        var sideProperty = typeof(Creature).GetProperty("Side", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new AcceptanceFailureException("Creature.Side was not found in the referenced game assembly.");
        var matchingSide = Enum.GetValues(sideProperty.PropertyType)
            .Cast<object>()
            .FirstOrDefault(value =>
            {
                SetAutoProperty(creature, "Side", value);
                return !string.Equals(value.ToString(), "None", StringComparison.OrdinalIgnoreCase) &&
                    creature.IsEnemy == enemy;
            });
        if (matchingSide is null)
        {
            throw new AcceptanceFailureException($"Could not configure a Creature with IsEnemy={enemy}.");
        }
        SetAutoProperty(creature, "Side", matchingSide);
        return creature;
    }

    public static void SetCurrentHp(Creature creature, int currentHp) =>
        SetAutoProperty(creature, "CurrentHp", currentHp);

    public static void SetAutoProperty(object target, string propertyName, object value)
    {
        var targetType = target.GetType();
        var backingField = targetType.GetField(
            $"<{propertyName}>k__BackingField",
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
        if (backingField is not null)
        {
            backingField.SetValue(target, value);
            return;
        }

        var property = targetType.GetProperty(
            propertyName,
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
        var setter = property?.GetSetMethod(nonPublic: true);
        if (setter is null)
        {
            throw new AcceptanceFailureException($"Could not set {targetType.FullName}.{propertyName} for an engine contract test.");
        }
        setter.Invoke(target, [value]);
    }
}
