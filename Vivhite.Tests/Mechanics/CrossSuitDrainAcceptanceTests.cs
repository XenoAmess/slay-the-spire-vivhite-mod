using System.Globalization;
using System.Reflection;
using System.Reflection.Emit;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.ValueProps;
using Vivhite.Cards.Chromatic;
using Vivhite.Cards.Common;
using Vivhite.Cards.Conservation;
using Vivhite.Cards.Recursion;
using Vivhite.Core;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests.Mechanics;

internal static class CrossSuitDrainAcceptanceTests
{
    private static readonly string[] ExpectedGlobalOnlyAttackIds =
    [
        "VIVHITE_CARD_LUMINOUS_PROJECTION",
        "VIVHITE_CARD_CLOSED_PROJECTION",
        "VIVHITE_CARD_TANGENT_STARLIGHT",
        "VIVHITE_CARD_SCALE_TRANSFORMATION",
        "VIVHITE_CARD_AXIOM_OF_LIFE",
        "VIVHITE_CARD_RECURRENT_STARLIGHT",
        "VIVHITE_CARD_TERMINATION_CONDITION",
        "VIVHITE_CARD_PARALLEL_STARFALL",
        "VIVHITE_CARD_SUCCESSOR_FORMULA",
        "VIVHITE_CARD_CONVERGENCE_VERDICT",
        "VIVHITE_CARD_PROOF_OF_TERMINATION"
    ];

    private static readonly string[] ExpectedPrintedDrainAttackIds =
    [
        "VIVHITE_CARD_TRICHROMATIC_WALTZ",
        "VIVHITE_CARD_COMPOSITE_COLOR_WHEEL",
        "VIVHITE_CARD_CRIMSON_AREA",
        "VIVHITE_CARD_DIFFERENTIAL_SAMPLING",
        "VIVHITE_CARD_COMPLEMENTARY_AFTERIMAGE",
        "VIVHITE_CARD_GOLDEN_COMPOSITION",
        "VIVHITE_CARD_RIEMANN_STAR_ARRAY",
        "VIVHITE_CARD_DEFINITE_CRIMSON_INTEGRAL",
        "VIVHITE_CARD_PERFECT_SYNTHESIS",
        "VIVHITE_CARD_ASTRAL_MEASURE",
        "VIVHITE_CARD_CHROMATIC_LIMIT"
    ];

    public static void BasicAndABAttacksUseZeroPercentCommonDrain(RepositorySnapshot repository)
    {
        string[] namespaces =
        [
            "Vivhite.Cards.Basics",
            "Vivhite.Cards.Conservation",
            "Vivhite.Cards.Recursion"
        ];
        var attacks = RegisteredAttacksInNamespaces(repository, namespaces);
        AcceptanceAssert.SetEqual(
            ExpectedGlobalOnlyAttackIds,
            attacks.Select(repository.CardId).ToArray(),
            "The complete Basic/A/B Attack set guarded by global Drain must remain exact.");

        var failures = new List<string>();
        foreach (var cardType in attacks)
        {
            var calls = IlInspection.CalledMethods(RequirePlayMethod(cardType));
            var routeCount = cardType.Namespace switch
            {
                "Vivhite.Cards.Basics" => CountCalls(
                    calls,
                    typeof(VivhiteCardRules),
                    nameof(VivhiteCardRules.ExecuteAttackWithGlobalDrainAsync)),
                "Vivhite.Cards.Conservation" => CountCalls(calls, typeof(ConservationCard), "AttackAsync"),
                "Vivhite.Cards.Recursion" => CountCalls(calls, typeof(RecursionCard), "AttackTargetAsync", "AttackAllAsync"),
                _ => 0
            };
            if (routeCount != 1)
            {
                failures.Add($"{repository.CardId(cardType)}: expected one Common Drain route, actual {routeCount}");
            }
            if (calls.Any(method =>
                    method.DeclaringType == typeof(InfiniteDrain) ||
                    method.DeclaringType == typeof(ChromaticDrainMechanics)))
            {
                failures.Add($"{repository.CardId(cardType)}: bypasses its approved Common zero-percent helper");
            }
        }
        AcceptanceAssert.Empty(
            failures,
            "Every compiled Basic/A/B Attack must enter Common Drain once, even with no printed Drain:");

        AssertZeroPercentCommonHelper(
            repository,
            typeof(VivhiteCardRules),
            nameof(VivhiteCardRules.ExecuteAttackWithGlobalDrainAsync));
        AssertZeroPercentCommonHelper(repository, typeof(ConservationCard), "AttackAsync");
        AssertZeroPercentCommonHelper(repository, typeof(RecursionCard), "AttackTargetAsync");
        AssertZeroPercentCommonHelper(repository, typeof(RecursionCard), "AttackAllAsync");
    }

    public static void CommonDrainDefaultsToChromaticRecoveryConversions(RepositorySnapshot repository)
    {
        var common = RequireDeclaredMethod(
            typeof(VivhiteCardRules),
            nameof(VivhiteCardRules.ExecuteDrainAttackAsync));
        var recoveryParameter = common.GetParameters().Single(parameter => parameter.Name == "recoveryHandler");
        AcceptanceAssert.True(
            recoveryParameter.HasDefaultValue && recoveryParameter.DefaultValue is null,
            "Common Drain must expose a null default handler before selecting Chromatic recovery.");

        var commonCalls = IlInspection.CalledMethods(common);
        AcceptanceAssert.Equal(
            1,
            CountCalls(commonCalls, typeof(InfiniteDrain), nameof(InfiniteDrain.ExecuteAttackAsync)),
            "Common Drain must execute and aggregate one native AttackCommand.");
        AcceptanceAssert.Equal(
            1,
            CountCalls(
                commonCalls,
                typeof(ChromaticDrainMechanics),
                nameof(ChromaticDrainMechanics.RecoverAndConvertAsync)),
            "Common Drain's compiled default must bind Chromatic RecoverAndConvertAsync once.");

        var commonSource = RequireSourceMethod(
            repository,
            typeof(VivhiteCardRules),
            nameof(VivhiteCardRules.ExecuteDrainAttackAsync));
        AcceptanceAssert.True(
            commonSource.DescendantNodes()
                .OfType<BinaryExpressionSyntax>()
                .Any(expression =>
                    expression.IsKind(SyntaxKind.CoalesceExpression) &&
                    expression.Right.DescendantNodesAndSelf()
                        .OfType<SimpleNameSyntax>()
                        .Any(name => name.Identifier.ValueText == nameof(ChromaticDrainMechanics.RecoverAndConvertAsync))),
            "Common Drain must select Chromatic recovery only when no custom handler is supplied.");

        var recovery = RequireDeclaredMethod(
            typeof(ChromaticDrainMechanics),
            nameof(ChromaticDrainMechanics.RecoverAndConvertAsync));
        var recoveryCalls = IlInspection.CalledMethods(recovery);
        string[] requiredStages =
        [
            nameof(DrainRecovery.HealAsync),
            "GainConservationBlockAsync",
            "GainConservationStrengthAsync",
            "GrowCanvasDrainAsync"
        ];
        AcceptanceAssert.Empty(
            requiredStages.Where(stage => !recoveryCalls.Any(method => method.Name == stage)).ToArray(),
            "Default Chromatic recovery must heal and evaluate Color/Crimson/Canvas conversions:");

        AcceptanceAssert.True(
            ReferencesType(
                RequireDeclaredMethod(typeof(ChromaticDrainMechanics), "GainConservationBlockAsync"),
                typeof(ColorConservationPower)),
            "Color Conservation recovery must read ColorConservationPower.");
        var strength = RequireDeclaredMethod(typeof(ChromaticDrainMechanics), "GainConservationStrengthAsync");
        AcceptanceAssert.True(
            ReferencesType(strength, typeof(CrimsonConservationLawPower)) &&
            ReferencesType(strength, typeof(CrimsonConservationLawUpgradedPower)),
            "Crimson Conservation recovery must read both normal and upgraded stacks.");
        var canvas = RequireDeclaredMethod(typeof(ChromaticDrainMechanics), "GrowCanvasDrainAsync");
        AcceptanceAssert.True(
            ReferencesType(canvas, typeof(InfiniteCanvasPower)) &&
            ReferencesType(canvas, typeof(InfiniteCanvasUpgradedPower)),
            "Infinite Canvas recovery must read both normal and upgraded stacks.");
        AcceptanceAssert.Equal(
            1,
            CountCalls(
                IlInspection.CalledMethods(canvas),
                typeof(InfiniteDrain),
                nameof(InfiniteDrain.GainGlobalPercentAsync)),
            "Infinite Canvas must grow global Drain once per completed recovery.");
    }

    public static void ChromaticAndHybridPrintedDrainIsNotDuplicated(RepositorySnapshot repository)
    {
        string[] namespaces = ["Vivhite.Cards.Chromatic", "Vivhite.Cards.Hybrid"];
        var attacks = RegisteredAttacksInNamespaces(repository, namespaces);
        AcceptanceAssert.SetEqual(
            ExpectedPrintedDrainAttackIds,
            attacks.Select(repository.CardId).ToArray(),
            "The complete C/Hybrid printed-Drain Attack set must remain exact.");

        var failures = new List<string>();
        foreach (var cardType in attacks)
        {
            var calls = IlInspection.CalledMethods(RequirePlayMethod(cardType));
            var routeCount = cardType.Namespace == "Vivhite.Cards.Chromatic"
                ? CountCalls(calls, typeof(ChromaticCard), "DrainTargetAsync", "DrainAllAsync")
                : CountCalls(calls, typeof(VivhiteCardRules), nameof(VivhiteCardRules.ExecuteDrainAttackAsync));
            if (routeCount != 1)
            {
                failures.Add($"{repository.CardId(cardType)}: expected one printed-Drain route, actual {routeCount}");
            }
            if (CountCalls(
                    calls,
                    typeof(VivhiteCardRules),
                    nameof(VivhiteCardRules.ExecuteAttackWithGlobalDrainAsync)) != 0)
            {
                failures.Add($"{repository.CardId(cardType)}: also entered the zero-percent global wrapper");
            }
        }
        AcceptanceAssert.Empty(
            failures,
            "C/Hybrid printed Drain must not cause a second aggregation or recovery:");

        foreach (var helperName in new[] { "DrainTargetAsync", "DrainAllAsync" })
        {
            AcceptanceAssert.Equal(
                1,
                CountCalls(
                    IlInspection.CalledMethods(RequireDeclaredMethod(typeof(ChromaticCard), helperName)),
                    typeof(ChromaticDrainMechanics),
                    nameof(ChromaticDrainMechanics.ExecuteDrainAttackAsync)),
                $"ChromaticCard.{helperName} must forward its card percentage once.");
        }
        AcceptanceAssert.Equal(
            1,
            CountCalls(
                IlInspection.CalledMethods(RequireDeclaredMethod(
                    typeof(ChromaticDrainMechanics),
                    nameof(ChromaticDrainMechanics.ExecuteDrainAttackAsync))),
                typeof(VivhiteCardRules),
                nameof(VivhiteCardRules.ExecuteDrainAttackAsync)),
            "The Chromatic wrapper must forward to Common exactly once.");

        var rate = new DrainRate(CardPercent: 35m, GlobalPercent: 40m, ThisTurnPercent: 25m);
        AcceptanceAssert.Equal(
            100m,
            rate.TotalPercent,
            "Printed, global, and turn-scoped percentages must each enter the final rate once.");
    }

    public static void DynamicProgrammingOnlyBuffsPoweredOpponentAttackDamage(RepositorySnapshot repository)
    {
        var modifier = RequireDeclaredMethod(
            typeof(DynamicProgrammingPower),
            nameof(DynamicProgrammingPower.ModifyDamageAdditive));
        var parameters = modifier.GetParameters();
        var amountParameter = Array.FindIndex(parameters, parameter => parameter.Name == "amount");
        AcceptanceAssert.True(amountParameter >= 0, "DynamicProgramming must retain the native amount parameter.");

        var amountLoads = IlInspection.Read(modifier)
            .Where(instruction => LoadsArgument(instruction, amountParameter + 1))
            .Select(instruction => $"IL_{instruction.Offset:x4}: {instruction.OpCode.Name}")
            .ToArray();
        AcceptanceAssert.Empty(
            amountLoads,
            "An additive modifier must return only ArmedValue and never read/add the incoming amount:");

        var calls = IlInspection.CalledMethods(modifier);
        AcceptanceAssert.True(
            calls.Any(method =>
                method.DeclaringType == typeof(DynamicProgrammingState) &&
                method.Name == "get_ArmedValue"),
            "DynamicProgramming must return its ArmedValue.");
        AcceptanceAssert.True(
            calls.Any(method => method.Name == "IsPoweredAttack") &&
            calls.Any(method => method.DeclaringType == typeof(Creature) && method.Name == "get_IsEnemy"),
            "DynamicProgramming's compiled guard must require powered Attack damage against an enemy.");
        AcceptanceAssert.True(
            !calls.Any(method => method.DeclaringType == typeof(decimal) && method.Name == "op_Addition"),
            "DynamicProgramming must never return amount + ArmedValue.");

        AcceptanceAssert.True(
            !LifeCalculation.PaymentProps.IsPoweredAttack(),
            "Life Calculation's Unpowered self-damage must fail DynamicProgramming's powered-Attack gate.");

        var source = RequireSourceMethod(
            repository,
            typeof(DynamicProgrammingPower),
            nameof(DynamicProgrammingPower.ModifyDamageAdditive));
        var guard = source.DescendantNodes().OfType<IfStatementSyntax>().Single();
        AcceptanceAssert.True(
            HasNegatedCall(guard.Condition, "IsPoweredAttack") &&
            HasNegatedMember(guard.Condition, "IsEnemy") &&
            HasCallWithArguments(guard.Condition, "ReferenceEquals", "target", "Owner") &&
            ReturnsZero(guard.Statement),
            "The compiled-source guard must return zero for Unpowered damage, self-targets, and non-opponents.");
    }

    private static Type[] RegisteredAttacksInNamespaces(
        RepositorySnapshot repository,
        IReadOnlyCollection<string> namespaces)
    {
        var failures = new List<string>();
        var result = new List<Type>();
        foreach (var cardType in repository.VivhitePoolCards.Where(type => namespaces.Contains(type.Namespace ?? string.Empty)))
        {
            try
            {
                if (Activator.CreateInstance(cardType) is not CardModel card)
                {
                    failures.Add($"{cardType.FullName}: could not construct CardModel");
                }
                else if (card.Type == CardType.Attack)
                {
                    result.Add(cardType);
                }
            }
            catch (Exception exception)
            {
                failures.Add($"{cardType.FullName}: {exception.GetBaseException().Message}");
            }
        }
        AcceptanceAssert.Empty(failures, "Attack discovery must construct every in-scope registered card:");
        return result.OrderBy(type => type.FullName, StringComparer.Ordinal).ToArray();
    }

    private static MethodInfo RequirePlayMethod(Type cardType)
    {
        var methods = cardType.GetMethods(
                BindingFlags.Instance |
                BindingFlags.Public |
                BindingFlags.NonPublic |
                BindingFlags.DeclaredOnly)
            .Where(method => method.Name is "OnPlay" or "OnPlayAfterLifePayment")
            .ToArray();
        if (methods.Length != 1)
        {
            throw new AcceptanceFailureException(
                $"{cardType.FullName} must declare one play-effect method; actual {methods.Length}.");
        }
        return methods[0];
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

    private static MethodDeclarationSyntax RequireSourceMethod(
        RepositorySnapshot repository,
        Type type,
        string name)
    {
        var methods = repository.RequireSourceType(type.FullName!)
            .Declaration.Members
            .OfType<MethodDeclarationSyntax>()
            .Where(method => method.Identifier.ValueText == name)
            .ToArray();
        if (methods.Length != 1)
        {
            throw new AcceptanceFailureException(
                $"{type.FullName}.{name} source must resolve once; actual {methods.Length}.");
        }
        return methods[0];
    }

    private static void AssertZeroPercentCommonHelper(
        RepositorySnapshot repository,
        Type helperType,
        string helperName)
    {
        AcceptanceAssert.Equal(
            1,
            CountCalls(
                IlInspection.CalledMethods(RequireDeclaredMethod(helperType, helperName)),
                typeof(VivhiteCardRules),
                nameof(VivhiteCardRules.ExecuteDrainAttackAsync)),
            $"{helperType.Name}.{helperName} must call compiled Common Drain once.");

        var invocations = RequireSourceMethod(repository, helperType, helperName)
            .DescendantNodes()
            .OfType<InvocationExpressionSyntax>()
            .Where(invocation => InvokedName(invocation) == nameof(VivhiteCardRules.ExecuteDrainAttackAsync))
            .ToArray();
        AcceptanceAssert.Equal(1, invocations.Length, $"{helperType.Name}.{helperName} must invoke Common Drain once.");

        var arguments = invocations[0].ArgumentList.Arguments;
        var cardPercent = arguments.SingleOrDefault(argument =>
            argument.NameColon?.Name.Identifier.ValueText == "cardPercent");
        if (cardPercent is null && arguments.Count >= 5)
        {
            cardPercent = arguments[4];
        }
        AcceptanceAssert.True(
            cardPercent is not null && IsZeroNumericLiteral(cardPercent.Expression),
            $"{helperType.Name}.{helperName} must pass literal cardPercent 0.");
    }

    private static int CountCalls(
        IEnumerable<MethodBase> calls,
        Type declaringType,
        params string[] names) =>
        calls.Count(method => method.DeclaringType == declaringType && names.Contains(method.Name));

    private static bool ReferencesType(MethodInfo method, Type expected) =>
        IlInspection.ReadExecutableBody(method).Any(instruction => instruction.Operand switch
        {
            Type type => type == expected,
            FieldInfo field => field.DeclaringType == expected || field.FieldType == expected,
            MethodInfo called =>
                called.DeclaringType == expected ||
                called.ReturnType == expected ||
                called.GetGenericArguments().Contains(expected) ||
                called.GetParameters().Any(parameter => parameter.ParameterType == expected),
            _ => false
        });

    private static string? InvokedName(InvocationExpressionSyntax invocation) =>
        invocation.Expression switch
        {
            SimpleNameSyntax name => name.Identifier.ValueText,
            MemberAccessExpressionSyntax access => access.Name.Identifier.ValueText,
            MemberBindingExpressionSyntax binding => binding.Name.Identifier.ValueText,
            _ => null
        };

    private static bool IsZeroNumericLiteral(ExpressionSyntax expression)
    {
        while (expression is ParenthesizedExpressionSyntax parenthesized)
        {
            expression = parenthesized.Expression;
        }
        return expression is LiteralExpressionSyntax literal &&
            literal.IsKind(SyntaxKind.NumericLiteralExpression) &&
            Convert.ToDecimal(literal.Token.Value, CultureInfo.InvariantCulture) == 0m;
    }

    private static bool LoadsArgument(IlInstruction instruction, int argumentIndex)
    {
        if (instruction.OpCode == OpCodes.Ldarg_0) return argumentIndex == 0;
        if (instruction.OpCode == OpCodes.Ldarg_1) return argumentIndex == 1;
        if (instruction.OpCode == OpCodes.Ldarg_2) return argumentIndex == 2;
        if (instruction.OpCode == OpCodes.Ldarg_3) return argumentIndex == 3;
        return (instruction.OpCode == OpCodes.Ldarg ||
                instruction.OpCode == OpCodes.Ldarg_S ||
                instruction.OpCode == OpCodes.Ldarga ||
                instruction.OpCode == OpCodes.Ldarga_S) &&
            Convert.ToInt32(instruction.Operand, CultureInfo.InvariantCulture) == argumentIndex;
    }

    private static bool HasNegatedCall(ExpressionSyntax condition, string methodName) =>
        condition.DescendantNodesAndSelf()
            .OfType<PrefixUnaryExpressionSyntax>()
            .Any(prefix =>
                prefix.IsKind(SyntaxKind.LogicalNotExpression) &&
                prefix.Operand is InvocationExpressionSyntax invocation &&
                InvokedName(invocation) == methodName);

    private static bool HasNegatedMember(ExpressionSyntax condition, string memberName) =>
        condition.DescendantNodesAndSelf()
            .OfType<PrefixUnaryExpressionSyntax>()
            .Any(prefix =>
                prefix.IsKind(SyntaxKind.LogicalNotExpression) &&
                prefix.Operand is MemberAccessExpressionSyntax access &&
                access.Name.Identifier.ValueText == memberName);

    private static bool HasCallWithArguments(
        ExpressionSyntax condition,
        string methodName,
        params string[] arguments) =>
        condition.DescendantNodesAndSelf()
            .OfType<InvocationExpressionSyntax>()
            .Any(invocation =>
                InvokedName(invocation) == methodName &&
                invocation.ArgumentList.Arguments.Select(argument => argument.Expression.ToString())
                    .SequenceEqual(arguments, StringComparer.Ordinal));

    private static bool ReturnsZero(StatementSyntax statement) =>
        statement.DescendantNodesAndSelf()
            .OfType<ReturnStatementSyntax>()
            .Any(result => result.Expression is not null && IsZeroNumericLiteral(result.Expression));
}
