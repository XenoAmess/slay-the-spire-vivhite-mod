using System.Reflection;
using System.Text;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.Text;

namespace Vivhite.Tests.Acceptance;

internal sealed class RepositorySnapshot
{
    private readonly Dictionary<string, SourceType> _sourceTypesByFullName;

    private RepositorySnapshot(
        string rootDirectory,
        IReadOnlyList<SourceDocument> sourceDocuments,
        IReadOnlyList<SourceType> sourceTypes,
        Assembly compiledAssembly)
    {
        RootDirectory = rootDirectory;
        SourceDocuments = sourceDocuments;
        SourceTypes = sourceTypes;
        CompiledAssembly = compiledAssembly;
        _sourceTypesByFullName = sourceTypes.ToDictionary(type => type.FullName, StringComparer.Ordinal);

        CompiledProductionTypes = compiledAssembly.GetTypes()
            .Where(type => type.Namespace is not null &&
                (type.Namespace == "Vivhite" || type.Namespace.StartsWith("Vivhite.", StringComparison.Ordinal)) &&
                !type.Namespace.StartsWith("Vivhite.Tests", StringComparison.Ordinal))
            .OrderBy(type => type.FullName, StringComparer.Ordinal)
            .ToArray();
        RegisteredCards = CompiledProductionTypes
            .Where(type => FindAttribute(type, "RegisterCardAttribute") is not null)
            .OrderBy(type => type.FullName, StringComparer.Ordinal)
            .ToArray();
        VivhitePoolCards = RegisteredCards
            .Where(type => AttributeContainsType(
                FindAttribute(type, "RegisterCardAttribute")!,
                "Vivhite.Characters.VivhiteCardPool"))
            .OrderBy(type => type.FullName, StringComparer.Ordinal)
            .ToArray();
    }

    public string RootDirectory { get; }

    public string LocalizationDirectory => Path.Combine(RootDirectory, "Vivhite", "Vivhite", "localization");

    public string GodotProjectDirectory => Path.Combine(RootDirectory, "Vivhite", "Vivhite");

    public Assembly CompiledAssembly { get; }

    public IReadOnlyList<Type> CompiledProductionTypes { get; }

    public IReadOnlyList<Type> RegisteredCards { get; }

    public IReadOnlyList<Type> VivhitePoolCards { get; }

    public IReadOnlyList<SourceDocument> SourceDocuments { get; }

    public IReadOnlyList<SourceType> SourceTypes { get; }

    public static RepositorySnapshot Load()
    {
        var root = FindRepositoryRoot();
        var sourceDirectory = Path.Combine(root, "Vivhite", "VivhiteCode");
        var sourceFiles = Directory.GetFiles(sourceDirectory, "*.cs", SearchOption.AllDirectories)
            .Order(StringComparer.Ordinal)
            .ToArray();
        AcceptanceAssert.True(sourceFiles.Length > 0, $"No production C# files found under {sourceDirectory}.");

        var parseOptions = new CSharpParseOptions(LanguageVersion.CSharp13, DocumentationMode.Parse);
        var documents = new List<SourceDocument>();
        var sourceTypes = new List<SourceType>();
        var syntaxErrors = new List<string>();
        foreach (var sourceFile in sourceFiles)
        {
            var text = File.ReadAllText(sourceFile, Encoding.UTF8);
            var tree = CSharpSyntaxTree.ParseText(
                SourceText.From(text, Encoding.UTF8),
                parseOptions,
                sourceFile);
            syntaxErrors.AddRange(tree.GetDiagnostics()
                .Where(diagnostic => diagnostic.Severity == DiagnosticSeverity.Error)
                .Select(diagnostic => diagnostic.ToString()));

            var rootNode = tree.GetCompilationUnitRoot();
            documents.Add(new SourceDocument(sourceFile, rootNode));
            sourceTypes.AddRange(TopLevelClasses(rootNode.Members)
                .Select(declaration => new SourceType(sourceFile, declaration)));
        }

        AcceptanceAssert.Empty(syntaxErrors, "Production source has syntax errors:");
        var duplicateTypes = sourceTypes
            .GroupBy(type => type.FullName, StringComparer.Ordinal)
            .Where(group => group.Count() > 1)
            .Select(group => $"Duplicate top-level source type '{group.Key}'.")
            .ToArray();
        AcceptanceAssert.Empty(duplicateTypes, "Production source must have unique top-level type names:");

        // VivhiteCode/**/*.cs is linked into Vivhite.Tests.csproj. This reference proves the
        // production source under inspection was accepted by the C# compiler and is reflectable.
        var compiledAssembly = typeof(global::Vivhite.Entry).Assembly;
        AcceptanceAssert.True(
            ReferenceEquals(compiledAssembly, typeof(RepositorySnapshot).Assembly),
            "Acceptance must compile and reflect the exact linked VivhiteCode production source.");

        return new RepositorySnapshot(root, documents, sourceTypes, compiledAssembly);
    }

    public SourceType RequireSourceType(string fullName)
    {
        if (_sourceTypesByFullName.TryGetValue(fullName, out var sourceType))
        {
            return sourceType;
        }
        throw new AcceptanceFailureException($"Required production source type is missing: {fullName}");
    }

    public SourceType? FindSourceType(Type runtimeType) =>
        runtimeType.FullName is null ? null : _sourceTypesByFullName.GetValueOrDefault(runtimeType.FullName);

    public string CardId(Type cardType) => $"VIVHITE_CARD_{ToUpperSnakeCase(cardType.Name)}";

    public static CustomAttributeData? FindAttribute(Type type, string attributeTypeName) =>
        type.GetCustomAttributesData()
            .SingleOrDefault(attribute => attribute.AttributeType.Name == attributeTypeName);

    public static bool AttributeContainsType(CustomAttributeData attribute, string expectedFullName) =>
        attribute.ConstructorArguments.Any(argument => ArgumentContainsType(argument, expectedFullName)) ||
        attribute.NamedArguments.Any(argument => ArgumentContainsType(argument.TypedValue, expectedFullName));

    private static bool ArgumentContainsType(CustomAttributeTypedArgument argument, string expectedFullName)
    {
        if (argument.Value is Type type)
        {
            return type.FullName == expectedFullName;
        }
        if (argument.Value is IReadOnlyCollection<CustomAttributeTypedArgument> arguments)
        {
            return arguments.Any(item => ArgumentContainsType(item, expectedFullName));
        }
        return false;
    }

    private static IEnumerable<ClassDeclarationSyntax> TopLevelClasses(SyntaxList<MemberDeclarationSyntax> members)
    {
        foreach (var member in members)
        {
            switch (member)
            {
                case BaseNamespaceDeclarationSyntax namespaceDeclaration:
                    foreach (var declaration in TopLevelClasses(namespaceDeclaration.Members))
                    {
                        yield return declaration;
                    }
                    break;
                case ClassDeclarationSyntax classDeclaration:
                    yield return classDeclaration;
                    break;
            }
        }
    }

    private static string FindRepositoryRoot()
    {
        var candidates = new List<string>();
        var configured = Environment.GetEnvironmentVariable("VIVHITE_REPO_ROOT");
        if (!string.IsNullOrWhiteSpace(configured))
        {
            candidates.Add(configured);
        }
        candidates.Add(Directory.GetCurrentDirectory());
        candidates.Add(AppContext.BaseDirectory);

        foreach (var candidate in candidates)
        {
            var directory = new DirectoryInfo(Path.GetFullPath(candidate));
            while (directory is not null)
            {
                if (File.Exists(Path.Combine(directory.FullName, "AGENTS.md")) &&
                    File.Exists(Path.Combine(directory.FullName, "Vivhite", "Vivhite.csproj")))
                {
                    return directory.FullName;
                }
                directory = directory.Parent;
            }
        }

        throw new DirectoryNotFoundException(
            "Could not locate AGENTS.md plus Vivhite/Vivhite.csproj. Run from the repository or set VIVHITE_REPO_ROOT.");
    }

    private static string ToUpperSnakeCase(string value)
    {
        var builder = new StringBuilder(value.Length + 8);
        for (var index = 0; index < value.Length; index++)
        {
            var current = value[index];
            if (index > 0 && char.IsUpper(current))
            {
                var previous = value[index - 1];
                var nextIsLower = index + 1 < value.Length && char.IsLower(value[index + 1]);
                if (char.IsLower(previous) || char.IsDigit(previous) || (char.IsUpper(previous) && nextIsLower))
                {
                    builder.Append('_');
                }
            }
            builder.Append(char.ToUpperInvariant(current));
        }
        return builder.ToString();
    }
}

internal sealed record SourceDocument(string FilePath, CompilationUnitSyntax Root);

internal sealed class SourceType
{
    public SourceType(string filePath, ClassDeclarationSyntax declaration)
    {
        FilePath = filePath;
        Declaration = declaration;
        Name = declaration.Identifier.ValueText;
        Namespace = declaration.Ancestors().OfType<BaseNamespaceDeclarationSyntax>().FirstOrDefault()?.Name.ToString() ?? string.Empty;
        var metadataName = declaration.TypeParameterList is { Parameters.Count: > 0 } typeParameters
            ? $"{Name}`{typeParameters.Parameters.Count}"
            : Name;
        FullName = string.IsNullOrEmpty(Namespace) ? metadataName : $"{Namespace}.{metadataName}";
    }

    public string FilePath { get; }

    public ClassDeclarationSyntax Declaration { get; }

    public string Name { get; }

    public string Namespace { get; }

    public string FullName { get; }

    public string RelativePath(string repositoryRoot) => Path.GetRelativePath(repositoryRoot, FilePath);
}
