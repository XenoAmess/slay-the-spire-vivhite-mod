using System.Reflection;
using System.Reflection.Emit;
using System.Runtime.CompilerServices;

namespace Vivhite.Tests.Acceptance;

internal static class IlInspection
{
    private static readonly IReadOnlyDictionary<ushort, OpCode> OpCodesByValue =
        typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static)
            .Where(field => field.FieldType == typeof(OpCode))
            .Select(field => (OpCode)field.GetValue(null)!)
            .ToDictionary(opCode => unchecked((ushort)opCode.Value));

    public static IReadOnlyList<IlInstruction> ReadExecutableBody(MethodInfo method)
    {
        var asyncStateMachine = method.GetCustomAttribute<AsyncStateMachineAttribute>();
        var executable = asyncStateMachine?.StateMachineType.GetMethod(
            "MoveNext",
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic) ?? method;
        return Read(executable);
    }

    public static IReadOnlyList<MethodBase> CalledMethods(MethodInfo method) =>
        ReadExecutableBody(method)
            .Select(instruction => instruction.Operand)
            .OfType<MethodBase>()
            .ToArray();

    public static IReadOnlyList<IlInstruction> Read(MethodInfo method)
    {
        var bytes = method.GetMethodBody()?.GetILAsByteArray();
        if (bytes is null)
        {
            return [];
        }

        var result = new List<IlInstruction>();
        var index = 0;
        while (index < bytes.Length)
        {
            var offset = index;
            ushort key = bytes[index++];
            if (key == 0xfe)
            {
                key = (ushort)(0xfe00 | bytes[index++]);
            }
            if (!OpCodesByValue.TryGetValue(key, out var opCode))
            {
                throw new InvalidDataException($"Unknown IL opcode 0x{key:x4} at {method.DeclaringType?.FullName}.{method.Name}+0x{offset:x4}.");
            }

            object? operand = opCode.OperandType switch
            {
                OperandType.InlineNone => null,
                OperandType.ShortInlineI => (sbyte)bytes[index++],
                OperandType.InlineI => ReadInt32(bytes, ref index),
                OperandType.InlineI8 => ReadInt64(bytes, ref index),
                OperandType.ShortInlineR => ReadSingle(bytes, ref index),
                OperandType.InlineR => ReadDouble(bytes, ref index),
                OperandType.ShortInlineVar => bytes[index++],
                OperandType.InlineVar => ReadUInt16(bytes, ref index),
                OperandType.ShortInlineBrTarget => index + 1 + (sbyte)bytes[index++],
                OperandType.InlineBrTarget => ReadBranchTarget(bytes, ref index),
                OperandType.InlineSwitch => ReadSwitchTargets(bytes, ref index),
                OperandType.InlineString => method.Module.ResolveString(ReadInt32(bytes, ref index)),
                OperandType.InlineField or OperandType.InlineMethod or OperandType.InlineType or OperandType.InlineTok =>
                    ResolveMember(method, ReadInt32(bytes, ref index)),
                OperandType.InlineSig => method.Module.ResolveSignature(ReadInt32(bytes, ref index)),
                _ => throw new InvalidDataException($"Unsupported IL operand type {opCode.OperandType}.")
            };
            result.Add(new IlInstruction(offset, opCode, operand));
        }
        return result;
    }

    private static MemberInfo ResolveMember(MethodInfo method, int token) =>
        method.Module.ResolveMember(
            token,
            method.DeclaringType?.GetGenericArguments(),
            method.IsGenericMethod ? method.GetGenericArguments() : null)!;

    private static int ReadBranchTarget(byte[] bytes, ref int index)
    {
        var delta = ReadInt32(bytes, ref index);
        return index + delta;
    }

    private static int[] ReadSwitchTargets(byte[] bytes, ref int index)
    {
        var count = ReadInt32(bytes, ref index);
        var baseOffset = index + (count * sizeof(int));
        var targets = new int[count];
        for (var targetIndex = 0; targetIndex < count; targetIndex++)
        {
            targets[targetIndex] = baseOffset + ReadInt32(bytes, ref index);
        }
        return targets;
    }

    private static ushort ReadUInt16(byte[] bytes, ref int index)
    {
        var value = BitConverter.ToUInt16(bytes, index);
        index += sizeof(ushort);
        return value;
    }

    private static int ReadInt32(byte[] bytes, ref int index)
    {
        var value = BitConverter.ToInt32(bytes, index);
        index += sizeof(int);
        return value;
    }

    private static long ReadInt64(byte[] bytes, ref int index)
    {
        var value = BitConverter.ToInt64(bytes, index);
        index += sizeof(long);
        return value;
    }

    private static float ReadSingle(byte[] bytes, ref int index)
    {
        var value = BitConverter.ToSingle(bytes, index);
        index += sizeof(float);
        return value;
    }

    private static double ReadDouble(byte[] bytes, ref int index)
    {
        var value = BitConverter.ToDouble(bytes, index);
        index += sizeof(double);
        return value;
    }
}

internal sealed record IlInstruction(int Offset, OpCode OpCode, object? Operand);
