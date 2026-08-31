using ICSharpCode.Decompiler;
using ICSharpCode.Decompiler.CSharp;
using ICSharpCode.Decompiler.Metadata;
using ICSharpCode.Decompiler.TypeSystem;

if (args.Length != 2)
{
    Console.Error.WriteLine("usage: Decompiler <sts2.dll> <output-directory>");
    return 2;
}

var assemblyPath = Path.GetFullPath(args[0]);
var outputDirectory = Path.GetFullPath(args[1]);
Directory.CreateDirectory(outputDirectory);

var resolver = new UniversalAssemblyResolver(
    assemblyPath,
    throwOnError: false,
    targetFramework: ".NETCoreApp,Version=v9.0");
var settings = new DecompilerSettings(LanguageVersion.Latest)
{
    ThrowOnAssemblyResolveErrors = false,
};
var decompiler = new CSharpDecompiler(assemblyPath, resolver, settings);

var requestedTypeNames = new[]
{
    "MegaCrit.Sts2.Core.Nodes.NGame",
    "MegaCrit.Sts2.Core.Models.CharacterModel",
    "MegaCrit.Sts2.Core.Nodes.Screens.CharacterSelect.NCharacterSelectScreen",
    "MegaCrit.Sts2.Core.Nodes.Screens.MainMenu.NMainMenu",
    "MegaCrit.Sts2.Core.Nodes.Screens.DailyRun.NDailyRunLoadScreen",
    "MegaCrit.Sts2.Core.Nodes.Screens.CustomRun.NCustomRunLoadScreen",
    "MegaCrit.Sts2.Core.Nodes.Screens.CharacterSelect.NMultiplayerLoadGameScreen",
};

var transitionTypeNames = decompiler.TypeSystem.MainModule.TypeDefinitions
    .Where(type => type.FullName.Contains("Transition", StringComparison.OrdinalIgnoreCase))
    .Select(type => type.FullName)
    .OrderBy(name => name, StringComparer.Ordinal)
    .ToArray();
File.WriteAllLines(Path.Combine(outputDirectory, "transition-types.txt"), transitionTypeNames);

var typeNames = requestedTypeNames
    .Concat(transitionTypeNames)
    .Distinct(StringComparer.Ordinal)
    .ToArray();

foreach (var typeName in typeNames)
{
    var source = decompiler.DecompileTypeAsString(new FullTypeName(typeName));
    var fileName = typeName.Replace('.', '_') + ".cs";
    File.WriteAllText(Path.Combine(outputDirectory, fileName), source);
    Console.WriteLine($"wrote {fileName}");
}

return 0;
