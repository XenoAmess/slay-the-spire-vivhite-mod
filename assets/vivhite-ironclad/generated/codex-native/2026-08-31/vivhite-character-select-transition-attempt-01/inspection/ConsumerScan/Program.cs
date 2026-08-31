using System.Reflection;
using System.Reflection.Emit;
using System.Runtime.Loader;
using System.Security.Cryptography;
using System.Text.Json;

if (args.Length != 2)
{
    Console.Error.WriteLine("usage: ConsumerScan <sts2.dll> <report.json>");
    return 2;
}

var assemblyPath = Path.GetFullPath(args[0]);
var outputPath = Path.GetFullPath(args[1]);
var assemblyDirectory = Path.GetDirectoryName(assemblyPath)!;
AssemblyLoadContext.Default.Resolving += (_, name) =>
{
    var candidate = Path.Combine(assemblyDirectory, $"{name.Name}.dll");
    return File.Exists(candidate) ? AssemblyLoadContext.Default.LoadFromAssemblyPath(candidate) : null;
};

var assembly = AssemblyLoadContext.Default.LoadFromAssemblyPath(assemblyPath);
var characterType = assembly.GetType("MegaCrit.Sts2.Core.Models.CharacterModel", throwOnError: true)!;
var getter = characterType.GetProperty(
    "CharacterSelectTransitionPath",
    BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)!.GetMethod!;

var opcodes = typeof(OpCodes)
    .GetFields(BindingFlags.Public | BindingFlags.Static)
    .Select(field => (OpCode)field.GetValue(null)!)
    .ToDictionary(opcode => unchecked((ushort)opcode.Value));

var callers = new List<object>();
foreach (var type in GetLoadableTypes(assembly))
{
    const BindingFlags flags = BindingFlags.Instance | BindingFlags.Static |
                               BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
    var members = type.GetMethods(flags).Cast<MethodBase>().Concat(type.GetConstructors(flags));
    foreach (var method in members)
    {
        var body = method.GetMethodBody();
        var il = body?.GetILAsByteArray();
        if (il is null)
        {
            continue;
        }

        for (var position = 0; position < il.Length;)
        {
            var offset = position;
            ushort opcodeValue = il[position++];
            if (opcodeValue == 0xFE)
            {
                opcodeValue = (ushort)(0xFE00 | il[position++]);
            }
            var opcode = opcodes[opcodeValue];
            var operandPosition = position;
            var operandSize = GetOperandSize(opcode.OperandType, il, operandPosition);

            if (opcode.OperandType == OperandType.InlineMethod)
            {
                var token = BitConverter.ToInt32(il, operandPosition);
                try
                {
                    var resolved = method.Module.ResolveMethod(
                        token,
                        type.GetGenericArguments(),
                        method.IsGenericMethod ? method.GetGenericArguments() : null);
                    if (resolved?.Module == getter.Module && resolved.MetadataToken == getter.MetadataToken)
                    {
                        callers.Add(new
                        {
                            declaring_type = type.FullName,
                            method = method.ToString(),
                            il_offset = offset,
                            opcode = opcode.Name,
                        });
                    }
                }
                catch (ArgumentException)
                {
                    // Generic metadata tokens unrelated to the target getter can be unresolved.
                }
            }
            position += operandSize;
        }
    }
}

var report = new
{
    schema = "vivhite-character-select-transition-consumer-scan/v1",
    assembly_path = assemblyPath,
    assembly_sha256 = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(assemblyPath))).ToLowerInvariant(),
    target_getter = $"{getter.DeclaringType!.FullName}.{getter.Name}",
    target_metadata_token = $"0x{getter.MetadataToken:X8}",
    callers,
};

Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
File.WriteAllText(outputPath, JsonSerializer.Serialize(report, new JsonSerializerOptions
{
    WriteIndented = true,
}) + Environment.NewLine);
Console.WriteLine(JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }));
return 0;

static IEnumerable<Type> GetLoadableTypes(Assembly assembly)
{
    try
    {
        return assembly.GetTypes();
    }
    catch (ReflectionTypeLoadException exception)
    {
        return exception.Types.Where(type => type is not null)!;
    }
}

static int GetOperandSize(OperandType operandType, byte[] il, int position) => operandType switch
{
    OperandType.InlineNone => 0,
    OperandType.ShortInlineBrTarget or OperandType.ShortInlineI or OperandType.ShortInlineVar => 1,
    OperandType.InlineVar => 2,
    OperandType.InlineBrTarget or OperandType.InlineField or OperandType.InlineI or
        OperandType.InlineMethod or OperandType.InlineSig or OperandType.InlineString or
        OperandType.InlineTok or OperandType.InlineType or OperandType.ShortInlineR => 4,
    OperandType.InlineI8 or OperandType.InlineR => 8,
    OperandType.InlineSwitch => 4 + 4 * BitConverter.ToInt32(il, position),
    _ => throw new InvalidOperationException($"Unsupported IL operand type: {operandType}"),
};
