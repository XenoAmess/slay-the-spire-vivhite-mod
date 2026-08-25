using ICSharpCode.Decompiler;
using ICSharpCode.Decompiler.CSharp;
using ICSharpCode.Decompiler.CSharp.Syntax;
using ICSharpCode.Decompiler.TypeSystem;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

if (args.Length < 2)
{
    Console.Error.WriteLine("Usage: GameKnowledge.Tool <assembly> list [filter] | decompile <full-type-name> | extract <output-dir>");
    return 2;
}

var assemblyPath = Path.GetFullPath(args[0]);
var command = args[1].ToLowerInvariant();
var decompiler = new CSharpDecompiler(
    assemblyPath,
    new DecompilerSettings { ThrowOnAssemblyResolveErrors = false });

if (command == "list")
{
    var filter = args.Length >= 3 ? args[2] : string.Empty;
    foreach (var type in decompiler.TypeSystem.MainModule.TopLevelTypeDefinitions
                 .Where(type => type.FullName.Contains(filter, StringComparison.OrdinalIgnoreCase))
                 .OrderBy(type => type.FullName, StringComparer.Ordinal))
    {
        Console.WriteLine(type.FullName);
    }
    return 0;
}

if (command == "decompile" && args.Length >= 3)
{
    Console.WriteLine(decompiler.DecompileTypeAsString(new FullTypeName(args[2])));
    return 0;
}

if (command == "extract" && args.Length >= 3)
{
    var outputDirectory = Path.GetFullPath(args[2]);
    Directory.CreateDirectory(outputDirectory);
    var options = new JsonSerializerOptions
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        WriteIndented = false
    };
    var records = new List<TypeMechanics>();
    var failures = new List<object>();

    foreach (var type in decompiler.TypeSystem.MainModule.TopLevelTypeDefinitions
                 .Where(type => ModelCategory(type.FullName) is not null)
                 .OrderBy(type => type.FullName, StringComparer.Ordinal))
    {
        var category = ModelCategory(type.FullName)!;
        try
        {
            var syntax = decompiler.DecompileType(new FullTypeName(type.FullName));
            var declaration = syntax.Descendants
                .OfType<TypeDeclaration>()
                .FirstOrDefault(node => node.Name == type.Name);
            if (declaration is null)
            {
                records.Add(new TypeMechanics(
                    type.FullName,
                    type.Name,
                    category,
                    ModelEntryId(type.FullName, type.Name),
                    type.Kind.ToString(),
                    type.IsAbstract,
                    false,
                    null,
                    type.DirectBaseTypes.Select(baseType => baseType.FullName)
                        .Where(name => !string.IsNullOrWhiteSpace(name))
                        .Distinct(StringComparer.Ordinal)
                        .OrderBy(name => name, StringComparer.Ordinal)
                        .ToArray(),
                    [],
                    [],
                    [],
                    []));
                continue;
            }

            var targetDeclaration = declaration!;
            records.Add(TypeFacts(
                targetDeclaration,
                type.FullName,
                category,
                false,
                null,
                type.Kind.ToString(),
                type.IsAbstract,
                type.DirectBaseTypes.Select(baseType => baseType.FullName)
                    .Where(name => !string.IsNullOrWhiteSpace(name))
                    .Distinct(StringComparer.Ordinal)
                    .OrderBy(name => name, StringComparer.Ordinal)
                    .ToArray()));

            foreach (var nested in NestedTypeDeclarations(targetDeclaration, type.FullName))
            {
                try
                {
                    records.Add(TypeFacts(
                        nested.Declaration,
                        nested.FullName,
                        category,
                        true,
                        nested.DeclaringTypeName,
                        nested.Declaration.ClassType.ToString(),
                        nested.Declaration.Modifiers.HasFlag(Modifiers.Abstract),
                        nested.Declaration.BaseTypes
                            .Select(baseType => Normalize(baseType.ToString()))
                            .Where(name => !string.IsNullOrWhiteSpace(name))
                            .Distinct(StringComparer.Ordinal)
                            .OrderBy(name => name, StringComparer.Ordinal)
                            .ToArray()));
                }
                catch (Exception exception)
                {
                    failures.Add(new { type_name = nested.FullName, error = exception.Message });
                }
            }
            foreach (var nestedDelegate in NestedDelegateDeclarations(targetDeclaration, type.FullName))
            {
                try
                {
                    records.Add(DelegateFacts(
                        nestedDelegate.Declaration,
                        nestedDelegate.FullName,
                        category,
                        nestedDelegate.DeclaringTypeName));
                }
                catch (Exception exception)
                {
                    failures.Add(new { type_name = nestedDelegate.FullName, error = exception.Message });
                }
            }
        }
        catch (Exception exception)
        {
            failures.Add(new { type_name = type.FullName, error = exception.Message });
        }
    }

    var outputHashes = new SortedDictionary<string, string>(StringComparer.Ordinal);
    foreach (var group in records.GroupBy(record => record.Category, StringComparer.Ordinal))
    {
        var fileName = group.Key + ".jsonl";
        var path = Path.Combine(outputDirectory, fileName);
        var body = string.Join("\n", group.Select(record => JsonSerializer.Serialize(record, options))) + "\n";
        File.WriteAllText(path + ".tmp", body, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
        File.Move(path + ".tmp", path, overwrite: true);
        outputHashes[fileName] = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(body))).ToLowerInvariant();
    }

    var assemblyHash = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(assemblyPath))).ToLowerInvariant();
    var manifest = new
    {
        schema_version = 2,
        source = new
        {
            assembly = Path.GetFileName(assemblyPath),
            assembly_sha256 = assemblyHash
        },
        generated_at_utc = DateTimeOffset.UtcNow.ToString("O"),
        extraction = "control-flow-free behavior facts, constructors, accessors, and nested types from locally installed managed assembly",
        counts = records.GroupBy(record => record.Category, StringComparer.Ordinal)
            .ToDictionary(group => group.Key, group => group.Count(), StringComparer.Ordinal),
        output_sha256 = outputHashes,
        failures
    };
    var manifestPath = Path.Combine(outputDirectory, "mechanics-manifest.json");
    File.WriteAllText(
        manifestPath + ".tmp",
        JsonSerializer.Serialize(manifest, new JsonSerializerOptions(options) { WriteIndented = true }) + "\n",
        new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
    File.Move(manifestPath + ".tmp", manifestPath, overwrite: true);

    Console.WriteLine($"Extracted {records.Count} gameplay types into {outputDirectory}; failures={failures.Count}");
    return failures.Count == 0 ? 0 : 1;
}

Console.Error.WriteLine($"Unknown or incomplete command: {command}");
return 2;

static string? ModelCategory(string fullName)
{
    const string prefix = "MegaCrit.Sts2.Core.Models.";
    if (fullName.StartsWith(prefix, StringComparison.Ordinal))
    {
        var relative = fullName[prefix.Length..];
        var parts = relative.Split('.', 2);
        if (parts.Length == 1)
        {
            return "model_bases";
        }
        var segment = parts[0];
        return segment switch
        {
            "Cards" => "cards",
            "Relics" => "relics",
            "Potions" => "potions",
            "Monsters" => "monsters",
            "Encounters" => "encounters",
            "Events" => "events",
            "Powers" => "powers",
            "Characters" => "characters",
            "Acts" => "acts",
            "Orbs" => "orbs",
            "Enchantments" => "enchantments",
            "Afflictions" => "afflictions",
            "Modifiers" => "modifiers",
            "CardPools" => "card_pools",
            "RelicPools" => "relic_pools",
            "PotionPools" => "potion_pools",
            _ => "models_" + ToSnakeCase(segment)
        };
    }

    return fullName switch
    {
        _ when fullName.StartsWith("MegaCrit.Sts2.Core.AutoSlay.", StringComparison.Ordinal) => "rules_autoslay",
        _ when fullName.StartsWith("MegaCrit.Sts2.Core.Entities.Ascension.", StringComparison.Ordinal) => "rules_ascension",
        "MegaCrit.Sts2.Core.Helpers.AscensionHelper" => "rules_ascension",
        _ when fullName.StartsWith("MegaCrit.Sts2.Core.Map.", StringComparison.Ordinal) => "rules_map",
        _ when fullName.StartsWith("MegaCrit.Sts2.Core.Odds.", StringComparison.Ordinal) => "rules_odds",
        _ when fullName.StartsWith("MegaCrit.Sts2.Core.Rewards.", StringComparison.Ordinal) => "rules_rewards",
        _ when fullName.StartsWith("MegaCrit.Sts2.Core.Entities.Merchant.", StringComparison.Ordinal) => "rules_merchant",
        _ when fullName.StartsWith("MegaCrit.Sts2.Core.Entities.RestSite.", StringComparison.Ordinal) => "rules_rest_site",
        _ when fullName.StartsWith("MegaCrit.Sts2.Core.Rooms.", StringComparison.Ordinal) => "rules_rooms",
        _ when fullName.StartsWith("MegaCrit.Sts2.Core.MonsterMoves.", StringComparison.Ordinal) => "rules_monster_moves",
        _ when fullName.StartsWith("MegaCrit.Sts2.Core.Unlocks.", StringComparison.Ordinal) => "rules_unlocks",
        _ when fullName.StartsWith("MegaCrit.Sts2.Core.Timeline.", StringComparison.Ordinal) => "rules_unlocks",
        "MegaCrit.Sts2.Core.Combat.CombatState" => "rules_combat",
        "MegaCrit.Sts2.Core.Entities.Players.PlayerCombatState" => "rules_combat",
        "MegaCrit.Sts2.Core.Entities.Cards.CardPile" => "rules_combat",
        "MegaCrit.Sts2.Core.Runs.RunState" => "rules_run",
        _ when fullName.StartsWith("MegaCrit.Sts2.Core.Factories.", StringComparison.Ordinal) => "rules_factories",
        _ when fullName.StartsWith("MegaCrit.Sts2.GameInfo.Objects.", StringComparison.Ordinal) => "rules_game_info",
        _ => null
    };
}

static string ToSnakeCase(string value)
{
    var builder = new StringBuilder(value.Length + 8);
    for (var index = 0; index < value.Length; index++)
    {
        var character = value[index];
        if (index > 0 && char.IsUpper(character) && !char.IsUpper(value[index - 1]))
        {
            builder.Append('_');
        }
        builder.Append(char.ToLowerInvariant(character));
    }
    return builder.ToString();
}

static string? ModelEntryId(string fullName, string typeName)
{
    if (!fullName.StartsWith("MegaCrit.Sts2.Core.Models.", StringComparison.Ordinal)
        || !fullName["MegaCrit.Sts2.Core.Models.".Length..].Contains('.'))
    {
        return null;
    }
    var camelSplit = Regex.Replace(typeName.Trim(), "([A-Za-z0-9]|\\G(?!^))([A-Z])", "$1_$2");
    var whitespaceCollapsed = Regex.Replace(camelSplit.ToUpperInvariant(), "\\s+", "_");
    return Regex.Replace(whitespaceCollapsed, "[^A-Z0-9_]", string.Empty);
}

static TypeMechanics TypeFacts(
    TypeDeclaration declaration,
    string fullName,
    string category,
    bool isNested,
    string? declaringTypeName,
    string typeKind,
    bool isAbstract,
    string[] baseTypes)
{
    var properties = declaration.Members.OfType<PropertyDeclaration>()
        .Select(PropertyFacts)
        .OrderBy(property => property.Name, StringComparer.Ordinal)
        .ToArray();
    var fields = declaration.Members.OfType<FieldDeclaration>()
        .SelectMany(FieldFacts)
        .Concat(declaration.Members.OfType<EnumMemberDeclaration>().Select((member, index) => new FieldFact(
            member.Name,
            "enum",
            member.Initializer.IsNull ? index.ToString() : Normalize(member.Initializer.ToString()),
            true)))
        .OrderBy(field => field.Name, StringComparer.Ordinal)
        .ToArray();
    var constructors = declaration.Members.OfType<ConstructorDeclaration>()
        .Select(ConstructorFacts)
        .ToList();
    if (declaration.PrimaryConstructorParameters.Any())
    {
        constructors.Add(new ConstructorFact(
            "primary",
            declaration.PrimaryConstructorParameters
                .Select(parameter => Normalize(parameter.ToString()))
                .ToArray(),
            null,
            [],
            [],
            [],
            [],
            [],
            []));
    }
    var methods = declaration.Members.OfType<MethodDeclaration>()
        .Select(MethodFacts)
        .OrderBy(method => method.Name, StringComparer.Ordinal)
        .ThenBy(method => string.Join(",", method.Parameters), StringComparer.Ordinal)
        .ToArray();

    return new TypeMechanics(
        fullName,
        declaration.Name,
        category,
        isNested ? null : ModelEntryId(fullName, declaration.Name),
        typeKind,
        isAbstract,
        isNested,
        declaringTypeName,
        baseTypes,
        fields,
        properties,
        constructors
            .OrderBy(constructor => constructor.Kind, StringComparer.Ordinal)
            .ThenBy(constructor => string.Join(",", constructor.Parameters), StringComparer.Ordinal)
            .ToArray(),
        methods);
}

static IEnumerable<NestedTypeInfo> NestedTypeDeclarations(
    TypeDeclaration declaration,
    string declaringFullName)
{
    foreach (var nested in declaration.Members.OfType<TypeDeclaration>())
    {
        var fullName = declaringFullName + "+" + nested.Name;
        yield return new NestedTypeInfo(nested, fullName, declaringFullName);
        foreach (var descendant in NestedTypeDeclarations(nested, fullName))
        {
            yield return descendant;
        }
    }
}

static IEnumerable<NestedDelegateInfo> NestedDelegateDeclarations(
    TypeDeclaration declaration,
    string declaringFullName)
{
    foreach (var nestedDelegate in declaration.Members.OfType<DelegateDeclaration>())
    {
        yield return new NestedDelegateInfo(
            nestedDelegate,
            declaringFullName + "+" + nestedDelegate.Name,
            declaringFullName);
    }
    foreach (var nestedType in declaration.Members.OfType<TypeDeclaration>())
    {
        var nestedFullName = declaringFullName + "+" + nestedType.Name;
        foreach (var descendant in NestedDelegateDeclarations(nestedType, nestedFullName))
        {
            yield return descendant;
        }
    }
}

static TypeMechanics DelegateFacts(
    DelegateDeclaration declaration,
    string fullName,
    string category,
    string declaringTypeName)
{
    var invoke = new MethodFact(
        "Invoke",
        Normalize(declaration.ReturnType.ToString()),
        declaration.Parameters.Select(parameter => Normalize(parameter.ToString())).ToArray(),
        [],
        [],
        [],
        [],
        [],
        []);
    return new TypeMechanics(
        fullName,
        declaration.Name,
        category,
        null,
        "Delegate",
        false,
        true,
        declaringTypeName,
        ["System.MulticastDelegate"],
        [],
        [],
        [],
        [invoke]);
}

static string Normalize(string value) => string.Join(" ", value.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));

static PropertyFact PropertyFacts(PropertyDeclaration property)
{
    var accessors = new List<AccessorFact>();
    if (!property.Getter.IsNull)
    {
        accessors.Add(AccessorFacts(property.Getter, "get"));
    }
    if (!property.Setter.IsNull)
    {
        accessors.Add(AccessorFacts(property.Setter, "set"));
    }
    return new PropertyFact(
        property.Name,
        Normalize(property.ReturnType.ToString()),
        PropertyExpressions(property),
        accessors.ToArray());
}

static string[] PropertyExpressions(PropertyDeclaration property)
{
    var expressions = new List<string>();
    if (!property.ExpressionBody.IsNull)
    {
        expressions.Add(Normalize(property.ExpressionBody.ToString()));
    }
    if (!property.Initializer.IsNull)
    {
        expressions.Add("initializer: " + Normalize(property.Initializer.ToString()));
    }
    if (!property.Getter.IsNull)
    {
        expressions.AddRange(property.Getter.Body.Descendants
            .OfType<ReturnStatement>()
            .Where(statement => !statement.Expression.IsNull)
            .Select(statement => Normalize(statement.Expression.ToString())));
    }
    return expressions.Distinct(StringComparer.Ordinal).ToArray();
}

static IEnumerable<FieldFact> FieldFacts(FieldDeclaration field)
{
    foreach (var variable in field.Variables)
    {
        var value = variable.Initializer.IsNull ? null : Normalize(variable.Initializer.ToString());
        yield return new FieldFact(variable.Name, Normalize(field.ReturnType.ToString()), value,
            field.Modifiers.HasFlag(Modifiers.Const));
    }
}

static ConstructorFact ConstructorFacts(ConstructorDeclaration constructor)
{
    var behavior = BehaviorFacts(constructor.Body);
    return new ConstructorFact(
        constructor.Modifiers.HasFlag(Modifiers.Static) ? "static" : "instance",
        constructor.Parameters.Select(parameter => Normalize(parameter.ToString())).ToArray(),
        constructor.Initializer.IsNull ? null : Normalize(constructor.Initializer.ToString()),
        behavior.Calls,
        behavior.Creates,
        behavior.Assignments,
        behavior.Conditions,
        behavior.Switches,
        behavior.Returns);
}

static AccessorFact AccessorFacts(Accessor accessor, string fallbackKind)
{
    var behavior = BehaviorFacts(accessor.Body);
    var keyword = Normalize(accessor.Keyword.ToString());
    return new AccessorFact(
        string.IsNullOrWhiteSpace(keyword) ? fallbackKind : keyword,
        behavior.Calls,
        behavior.Creates,
        behavior.Assignments,
        behavior.Conditions,
        behavior.Switches,
        behavior.Returns);
}

static BehaviorFact BehaviorFacts(AstNode scope)
{
    string[] Collect<T>(Func<T, string> render) where T : AstNode =>
        scope.Descendants.OfType<T>()
            .Select(render)
            .Select(value => Normalize(value))
            .Where(value => !string.IsNullOrWhiteSpace(value))
            .Distinct(StringComparer.Ordinal)
            .ToArray();

    return new BehaviorFact(
        scope.Descendants.OfType<InvocationExpression>()
            .Where(node => !node.Ancestors.TakeWhile(ancestor => ancestor != scope)
                .OfType<InvocationExpression>().Any())
            .Select(node => Normalize(node.ToString()))
            .Distinct(StringComparer.Ordinal)
            .ToArray(),
        Collect<ObjectCreateExpression>(node => node.ToString()),
        Collect<AssignmentExpression>(node => node.ToString()),
        Collect<IfElseStatement>(node => node.Condition.ToString()),
        Collect<SwitchStatement>(node => node.Expression.ToString()),
        Collect<ReturnStatement>(node => node.Expression.IsNull ? string.Empty : node.Expression.ToString()));
}

static MethodFact MethodFacts(MethodDeclaration method)
{
    var behavior = BehaviorFacts(method.Body);
    return new MethodFact(
        method.Name,
        Normalize(method.ReturnType.ToString()),
        method.Parameters.Select(parameter => Normalize(parameter.ToString())).ToArray(),
        behavior.Calls,
        behavior.Creates,
        behavior.Assignments,
        behavior.Conditions,
        behavior.Switches,
        behavior.Returns);
}

internal sealed record TypeMechanics(
    string TypeName,
    string Name,
    string Category,
    string? EntryId,
    string TypeKind,
    bool IsAbstract,
    bool IsNested,
    string? DeclaringTypeName,
    string[] BaseTypes,
    FieldFact[] Fields,
    PropertyFact[] Properties,
    ConstructorFact[] Constructors,
    MethodFact[] Methods);

internal sealed record NestedTypeInfo(TypeDeclaration Declaration, string FullName, string DeclaringTypeName);
internal sealed record NestedDelegateInfo(DelegateDeclaration Declaration, string FullName, string DeclaringTypeName);
internal sealed record FieldFact(string Name, string Type, string? Value, bool IsConst);
internal sealed record PropertyFact(string Name, string Type, string[] Expressions, AccessorFact[] Accessors);
internal sealed record ConstructorFact(
    string Kind,
    string[] Parameters,
    string? Initializer,
    string[] Calls,
    string[] Creates,
    string[] Assignments,
    string[] Conditions,
    string[] Switches,
    string[] Returns);
internal sealed record AccessorFact(
    string Kind,
    string[] Calls,
    string[] Creates,
    string[] Assignments,
    string[] Conditions,
    string[] Switches,
    string[] Returns);
internal sealed record BehaviorFact(
    string[] Calls,
    string[] Creates,
    string[] Assignments,
    string[] Conditions,
    string[] Switches,
    string[] Returns);
internal sealed record MethodFact(
    string Name,
    string ReturnType,
    string[] Parameters,
    string[] Calls,
    string[] Creates,
    string[] Assignments,
    string[] Conditions,
    string[] Switches,
    string[] Returns);
