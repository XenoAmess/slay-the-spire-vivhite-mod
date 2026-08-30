using System.Reflection;
using MegaCrit.Sts2.Core.Combat;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Vivhite.Cards.Chromatic;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests.Mechanics;

internal static class ChromaticTurnHealingAcceptanceTests
{
    public static void TracksOnlyActualHpIncreaseAndResetsEachTurn(RepositorySnapshot repository)
    {
        var hook = repository.RequireSourceType(typeof(ChromaticCard).FullName!)
            .Declaration.Members
            .OfType<MethodDeclarationSyntax>()
            .Single(method => method.Identifier.ValueText == "AfterCurrentHpChanged");
        AcceptanceAssert.True(
            !hook.Body!.DescendantNodes().OfType<IdentifierNameSyntax>()
                .Any(identifier => identifier.Identifier.ValueText == "delta"),
            "Chromatic healing tracking must ignore the requested heal delta and observe actual CurrentHp instead.");

        var combatState = DispatchProxy.Create<ICombatState, EmptyCombatStateProxy>();
        var creature = EngineTestObjects.CreateCreature(currentHp: 30, maxHp: 30, enemy: false);
        EngineTestObjects.SetAutoProperty(creature, "CombatState", combatState);

        ChromaticTurnHealing.BeginTurn(combatState, creature, turnNumber: 1);
        ChromaticTurnHealing.ObserveCurrentHp(creature);
        AcceptanceAssert.True(
            !ChromaticTurnHealing.HasIncreased(creature),
            "A positive heal request at full HP with zero actual HP gain must not mark this turn as healed.");

        EngineTestObjects.SetCurrentHp(creature, 18);
        ChromaticTurnHealing.ObserveCurrentHp(creature);
        AcceptanceAssert.True(
            !ChromaticTurnHealing.HasIncreased(creature),
            "Losing HP must not mark this turn as healed.");

        EngineTestObjects.SetCurrentHp(creature, 25);
        ChromaticTurnHealing.ObserveCurrentHp(creature);
        AcceptanceAssert.True(
            ChromaticTurnHealing.HasIncreased(creature),
            "A real CurrentHp increase after taking damage must mark this turn as healed.");

        ChromaticTurnHealing.BeginTurn(combatState, creature, turnNumber: 2);
        AcceptanceAssert.True(
            !ChromaticTurnHealing.HasIncreased(creature),
            "The actual-healing marker must reset at the next turn boundary.");
    }

    private class EmptyCombatStateProxy : DispatchProxy
    {
        protected override object? Invoke(MethodInfo? targetMethod, object?[]? args)
        {
            var returnType = targetMethod?.ReturnType;
            return returnType is null || returnType == typeof(void)
                ? null
                : returnType.IsValueType
                    ? Activator.CreateInstance(returnType)
                    : null;
        }
    }
}
