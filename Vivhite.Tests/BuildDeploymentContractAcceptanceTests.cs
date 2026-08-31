using System.Diagnostics;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Xml.Linq;
using Vivhite.Tests.Acceptance;

namespace Vivhite.Tests;

internal static class BuildDeploymentContractAcceptanceTests
{
    private static readonly string[] TripletNames = ["Vivhite.dll", "Vivhite.pck", "Vivhite.json"];

    public static async Task RejectsSplitDeploymentAndPreservesSafeBuilds(RepositorySnapshot repository)
    {
        var projectPath = Path.Combine(repository.RootDirectory, "Vivhite", "Vivhite.csproj");
        var exportScriptPath = Path.Combine(repository.RootDirectory, "Vivhite", "tools", "Export-ModPck.ps1");
        var project = XDocument.Load(projectPath, LoadOptions.PreserveWhitespace);

        AssertStaticDeploymentOrder(project, exportScriptPath);
        await AssertEvaluatedPropertyContractAsync(repository.RootDirectory, projectPath);

        var scratchRoot = Path.Combine(
            repository.RootDirectory,
            ".tmp",
            $"vivhite-build-transaction-{Guid.NewGuid():N}");
        Directory.CreateDirectory(scratchRoot);

        try
        {
            await AssertSplitBuildsFailBeforeArtValidationAsync(
                repository.RootDirectory,
                projectPath,
                scratchRoot);
            await AssertCopyDisabledNeverTouchesLiveAsync(
                repository.RootDirectory,
                projectPath,
                scratchRoot);
            await AssertTransactionalPublisherAsync(
                repository.RootDirectory,
                exportScriptPath,
                scratchRoot);
        }
        finally
        {
            if (Directory.Exists(scratchRoot))
            {
                Directory.Delete(scratchRoot, recursive: true);
            }
        }
    }

    private static void AssertStaticDeploymentOrder(XDocument project, string exportScriptPath)
    {
        var initialTargets = SplitTargets((string?)project.Root?.Attribute("InitialTargets"));
        AcceptanceAssert.True(
            initialTargets.Contains("ValidateModDeploymentContract", StringComparer.Ordinal),
            "The deployment contract must be an InitialTarget so VIVH001 runs before source-art validation and compilation.");

        var propertyElements = project.Descendants()
            .Where(element => element.Name.LocalName is "RunPckExport" or "CopyModOnBuild")
            .ToArray();
        var runDefaults = propertyElements.Where(element => element.Name.LocalName == "RunPckExport").ToArray();
        var copyDefaults = propertyElements.Where(element => element.Name.LocalName == "CopyModOnBuild").ToArray();
        AcceptanceAssert.Equal(2, runDefaults.Length, "RunPckExport must retain its normal and fallback defaults.");
        AcceptanceAssert.Equal(2, copyDefaults.Length, "CopyModOnBuild must retain its safe shorthand and full-build defaults.");
        AcceptanceAssert.True(
            Array.IndexOf(propertyElements, runDefaults[^1]) < Array.IndexOf(propertyElements, copyDefaults[0]),
            "RunPckExport defaults must be evaluated before CopyModOnBuild defaults.");

        var modPckPath = project.Descendants()
            .Single(element => element.Name.LocalName == "ModPckPath")
            .Value.Trim();
        AcceptanceAssert.True(
            modPckPath.Contains("$(ModCandidateRoot)", StringComparison.Ordinal) &&
            !modPckPath.Contains("$(ModOutputDir)", StringComparison.Ordinal),
            $"ModPckPath must target the non-live candidate tree, not the live directory. Value: {modPckPath}");

        var validation = RequireTarget(project, "ValidateModDeploymentContract");
        var validationHooks = SplitTargets((string?)validation.Attribute("BeforeTargets"));
        foreach (var requiredHook in new[] { "BeforeBuild", "ValidateIroncladSkinAssets", "Build", "CopyMod", "ExportPCK" })
        {
            AcceptanceAssert.True(
                validationHooks.Contains(requiredHook, StringComparer.Ordinal),
                $"The deployment contract must also remain hooked before {requiredHook}.");
        }

        var contractError = validation.Elements()
            .SingleOrDefault(element => element.Name.LocalName == "Error" &&
                string.Equals((string?)element.Attribute("Code"), "VIVH001", StringComparison.Ordinal));
        AcceptanceAssert.True(contractError is not null, "ValidateModDeploymentContract must expose VIVH001.");
        var errorCondition = (string?)contractError!.Attribute("Condition") ?? string.Empty;
        foreach (var fragment in new[] { "CopyModOnBuild", "RunPckExport", "STS2_SKIP_PCK_EXPORT" })
        {
            AcceptanceAssert.True(
                errorCondition.Contains(fragment, StringComparison.Ordinal),
                $"VIVH001 must bind {fragment}. Condition: {errorCondition}");
        }

        var export = RequireTarget(project, "ExportPCK");
        var exportCondition = (string?)export.Attribute("Condition") ?? string.Empty;
        foreach (var fragment in new[] { "CopyModOnBuild", "RunPckExport", "STS2_SKIP_PCK_EXPORT" })
        {
            AcceptanceAssert.True(
                exportCondition.Contains(fragment, StringComparison.Ordinal),
                $"ExportPCK must require the complete transaction property {fragment}. Condition: {exportCondition}");
        }
        var exportCommand = export.Elements()
            .Single(element => element.Name.LocalName == "Exec")
            .Attribute("Command")?.Value ?? string.Empty;
        foreach (var argument in new[]
                 {
                     "-OutputPath \"$(ModPckPath)\"",
                     "-AssemblyPath \"$(TargetPath)\"",
                     "-ManifestPath",
                     "-ModOutputDir \"$(ModOutputDir)\"",
                     "-RitsuLibVersion \"$(RitsuLibVersion)\""
                 })
        {
            AcceptanceAssert.True(
                exportCommand.Contains(argument, StringComparison.Ordinal),
                $"ExportPCK must pass the complete candidate transaction input {argument}.");
        }

        var copy = RequireTarget(project, "CopyMod");
        AcceptanceAssert.True(
            SplitTargets((string?)copy.Attribute("AfterTargets")).Contains("Build", StringComparer.Ordinal),
            "CopyMod must remain the post-build transaction trigger.");
        AcceptanceAssert.True(
            SplitTargets((string?)copy.Attribute("DependsOnTargets")).Contains("ExportPCK", StringComparer.Ordinal),
            "CopyMod must depend on the complete ExportPCK transaction.");
        AcceptanceAssert.Empty(
            copy.Elements().Where(element => element.Name.LocalName == "Copy").ToArray(),
            "CopyMod must not overwrite any live artifact per file:");

        var source = File.ReadAllText(exportScriptPath, Encoding.UTF8);
        foreach (var requiredFragment in new[]
                 {
                     ".staging.",
                     ".previous.",
                     "[IO.Directory]::Move($liveDirectory, $backupDirectory)",
                     "[IO.Directory]::Move($siblingStagingDirectory, $liveDirectory)",
                     "Assert-ExactTriplet",
                     "Assert-DirectorySnapshot",
                     "Enter-DeploymentLock",
                     "Invoke-HistoricalResidueReconciliation",
                     "New-VerifiedRecoveryArchive",
                     "Remove-DirectoryIncrementally",
                     "The PCK candidate must be produced outside the live Mod directory"
                 })
        {
            AcceptanceAssert.True(
                source.Contains(requiredFragment, StringComparison.Ordinal),
                $"The publisher is missing the transaction primitive: {requiredFragment}");
        }
        AcceptanceAssert.True(
            !source.Contains("[IO.File]::Replace", StringComparison.Ordinal),
            "The publisher must switch directories, not replace an individual live PCK.");
    }

    private static async Task AssertEvaluatedPropertyContractAsync(string root, string projectPath)
    {
        var defaultProperties = await ReadEvaluatedPropertiesAsync(
            root,
            projectPath,
            ["RunPckExport", "CopyModOnBuild", "ModPckPath", "ModOutputDir"]);
        AcceptanceAssert.Equal("true", defaultProperties["RunPckExport"], "Normal builds must export PCK.");
        AcceptanceAssert.Equal("true", defaultProperties["CopyModOnBuild"], "Normal builds must publish one full batch.");
        AcceptanceAssert.True(
            !Path.EndsInDirectorySeparator(defaultProperties["ModOutputDir"]),
            "The default live Mod directory must not end in a separator because MSBuild Exec quotes it before later PowerShell arguments.");
        AcceptanceAssert.True(
            !IsPathInside(defaultProperties["ModPckPath"], defaultProperties["ModOutputDir"]),
            "The evaluated PCK candidate path must be outside the live Mod directory.");

        var copyDisabled = await ReadEvaluatedPropertiesAsync(
            root,
            projectPath,
            ["RunPckExport", "CopyModOnBuild", "RitsuLibAutoCopy"],
            "/p:CopyModOnBuild=false");
        AcceptanceAssert.Equal("true", copyDisabled["RunPckExport"], "CopyModOnBuild=false must not rewrite RunPckExport.");
        AcceptanceAssert.Equal("false", copyDisabled["RitsuLibAutoCopy"], "CopyModOnBuild=false must default RitsuLib live copying to false.");

        var exportDisabled = await ReadEvaluatedPropertiesAsync(
            root,
            projectPath,
            ["CopyModOnBuild", "RitsuLibAutoCopy"],
            "/p:RunPckExport=false");
        AcceptanceAssert.Equal("false", exportDisabled["CopyModOnBuild"], "RunPckExport=false must default to no copy.");
        AcceptanceAssert.Equal("false", exportDisabled["RitsuLibAutoCopy"], "RunPckExport=false must default RitsuLib copying to false.");

        var skippedExport = await ReadEvaluatedPropertiesAsync(
            root,
            projectPath,
            ["RunPckExport", "CopyModOnBuild", "RitsuLibAutoCopy"],
            "/p:STS2_SKIP_PCK_EXPORT=1");
        AcceptanceAssert.Equal("true", skippedExport["RunPckExport"], "STS2_SKIP must not rewrite RunPckExport.");
        AcceptanceAssert.Equal("false", skippedExport["CopyModOnBuild"], "STS2_SKIP must default to no copy.");
        AcceptanceAssert.Equal("false", skippedExport["RitsuLibAutoCopy"], "STS2_SKIP must default RitsuLib copying to false.");
    }

    private static async Task AssertSplitBuildsFailBeforeArtValidationAsync(
        string root,
        string projectPath,
        string scratchRoot)
    {
        foreach (var scenario in new[]
                 {
                     new { Name = "run-disabled", Run = "false", Skip = "0" },
                     new { Name = "environment-skip", Run = "true", Skip = "1" }
                 })
        {
            var scenarioRoot = Path.Combine(scratchRoot, scenario.Name);
            var live = Path.Combine(scenarioRoot, "mods", "Vivhite");
            var candidate = Path.Combine(scenarioRoot, "candidate", "Vivhite.pck");
            var expected = InstallBatchA(live);
            var missingValidator = Path.Combine(scenarioRoot, "must-not-run-art-validator.ps1");

            var result = await RunDotnetAsync(
                root,
                "msbuild",
                projectPath,
                "/nologo",
                "/v:minimal",
                "/t:ValidateIroncladSkinAssets",
                "/p:DesignTimeBuild=false",
                $"/p:RunPckExport={scenario.Run}",
                "/p:CopyModOnBuild=true",
                $"/p:STS2_SKIP_PCK_EXPORT={scenario.Skip}",
                "/p:RitsuLibAutoCopy=false",
                $"/p:IroncladSkinValidator={missingValidator}",
                $"/p:ModOutputDir={EnsureTrailingSeparator(live)}",
                $"/p:ModPckPath={candidate}");

            AcceptanceAssert.True(result.ExitCode != 0, $"{scenario.Name} must be rejected.");
            AcceptanceAssert.True(
                result.Output.Contains("VIVH001", StringComparison.Ordinal),
                $"{scenario.Name} must fail with VIVH001 before any unrelated gate.{Environment.NewLine}{result.Output}");
            AcceptanceAssert.True(
                !result.Output.Contains("skin asset validator is missing", StringComparison.OrdinalIgnoreCase),
                $"{scenario.Name} reached the art gate before VIVH001.{Environment.NewLine}{result.Output}");
            AssertSnapshot(live, expected, $"{scenario.Name} live A batch");
            AcceptanceAssert.True(!Directory.Exists(Path.GetDirectoryName(candidate)), $"{scenario.Name} must not create a candidate tree.");
            AssertNoTransactionResidue(Path.GetDirectoryName(live)!, "Vivhite", $"{scenario.Name} split rejection");
        }
    }

    private static async Task AssertCopyDisabledNeverTouchesLiveAsync(
        string root,
        string projectPath,
        string scratchRoot)
    {
        var scenarioRoot = Path.Combine(scratchRoot, "copy-disabled");
        var live = Path.Combine(scenarioRoot, "mods", "Vivhite");
        var candidate = Path.Combine(scenarioRoot, "candidate", "Vivhite.pck");
        var expected = InstallBatchA(live);

        var result = await RunDotnetAsync(
            root,
            "msbuild",
            projectPath,
            "/nologo",
            "/v:minimal",
            "/t:CopyMod",
            "/p:DesignTimeBuild=false",
            "/p:RunPckExport=true",
            "/p:CopyModOnBuild=false",
            "/p:STS2_SKIP_PCK_EXPORT=0",
            $"/p:ModOutputDir={EnsureTrailingSeparator(live)}",
            $"/p:ModPckPath={candidate}");

        AcceptanceAssert.Equal(
            0,
            result.ExitCode,
            $"CopyModOnBuild=false must be a successful no-copy invocation.{Environment.NewLine}{result.Output}");
        AssertSnapshot(live, expected, "CopyModOnBuild=false live A batch");
        AcceptanceAssert.True(!Directory.Exists(Path.GetDirectoryName(candidate)), "CopyModOnBuild=false must not create a PCK candidate.");
        AssertNoTransactionResidue(Path.GetDirectoryName(live)!, "Vivhite", "CopyModOnBuild=false");
    }

    private static async Task AssertTransactionalPublisherAsync(
        string root,
        string exportScriptPath,
        string scratchRoot)
    {
        var harnessRoot = Path.Combine(scratchRoot, "publisher");
        var inputs = Path.Combine(harnessRoot, "inputs");
        var fakeProject = Path.Combine(harnessRoot, "godot-project");
        var liveParent = Path.Combine(harnessRoot, "mods");
        var live = Path.Combine(liveParent, "Vivhite");
        Directory.CreateDirectory(inputs);
        Directory.CreateDirectory(fakeProject);
        Directory.CreateDirectory(liveParent);

        var assemblyPath = Path.Combine(inputs, "Vivhite.dll");
        var manifestPath = Path.Combine(inputs, "Vivhite.json");
        File.WriteAllText(assemblyPath, "B-DLL-CONTENT", new UTF8Encoding(false));
        File.WriteAllText(
            manifestPath,
            """
            {
              "id": "Vivhite",
              "batch_marker": "B-JSON-CONTENT",
              "dependencies": [
                { "id": "STS2-RitsuLib", "version": "OLD-VERSION" }
              ]
            }
            """,
            new UTF8Encoding(false));

        var fakeGodot = Path.Combine(harnessRoot, "fake-godot.cmd");
        File.WriteAllText(
            fakeGodot,
            """
            @echo off
            setlocal
            set "last="
            :collect
            if "%~1"=="" goto write
            set "last=%~1"
            shift
            goto collect
            :write
            >"%last%" echo B-PCK-CONTENT
            exit /b 0
            """,
            Encoding.ASCII);

        var validator = Path.Combine(harnessRoot, "fake-validator.ps1");
        File.WriteAllText(
            validator,
            """
            param(
                [string]$ProjectDir,
                [string]$Phase,
                [string]$PckPath,
                [string]$RuntimeLayout
            )
            if ($Phase -ne 'Pck' -or -not (Test-Path -LiteralPath $PckPath) -or (Get-Item -LiteralPath $PckPath).Length -le 0) {
                exit 29
            }
            exit 0
            """,
            new UTF8Encoding(false));

        var failurePoints = new[]
        {
            "PckExport",
            "PckValidation",
            "ManifestSync",
            "CandidateJson",
            "CandidateDll",
            "CandidateVerification",
            "SiblingCreate",
            "SiblingPck",
            "SiblingDll",
            "SiblingJson",
            "SiblingVerification",
            "BeforeSwitch",
            "AfterLiveBackup",
            "AfterStagePromotion",
            "LiveVerification",
            "BackupCleanup"
        };

        foreach (var failurePoint in failurePoints)
        {
            var expectedA = InstallBatchA(live);
            var candidate = Path.Combine(harnessRoot, "candidates", failurePoint, "Vivhite.pck");
            var result = await RunPublisherAsync(
                root,
                exportScriptPath,
                fakeGodot,
                fakeProject,
                validator,
                assemblyPath,
                manifestPath,
                candidate,
                live,
                failurePoint);

            AcceptanceAssert.True(
                result.ExitCode != 0 && result.Output.Contains(failurePoint, StringComparison.OrdinalIgnoreCase),
                $"The {failurePoint} injection must fail at its named step.{Environment.NewLine}{result.Output}");
            if (string.Equals(failurePoint, "BackupCleanup", StringComparison.Ordinal))
            {
                AssertLiveBatch(live, "B-DLL-CONTENT", "B-PCK-CONTENT", "B-JSON-CONTENT");
                AssertNoTransactionResidue(liveParent, "Vivhite", failurePoint);
                var recoveryArchive = RequireSingleRecoveryArchive(liveParent, "Vivhite", failurePoint);
                AssertRecoveryArchive(recoveryArchive, expectedA, failurePoint);
                var workDirectory = RequireSingleQuarantineWorkDirectory(liveParent, "Vivhite", failurePoint);
                AcceptanceAssert.True(
                    Snapshot(workDirectory).Count < expectedA.Count,
                    "BackupCleanup injection must occur after real per-item deletion has already made the disposable work directory partial.");

                var committedB = Snapshot(live);
                var reconcileCandidate = Path.Combine(harnessRoot, "candidates", "backup-cleanup-reconcile", "Vivhite.pck");
                var reconcile = await RunPublisherAsync(
                    root,
                    exportScriptPath,
                    fakeGodot,
                    fakeProject,
                    validator,
                    assemblyPath,
                    manifestPath,
                    reconcileCandidate,
                    live,
                    "PckExport");
                AcceptanceAssert.True(
                    reconcile.ExitCode != 0 && reconcile.Output.Contains("PckExport", StringComparison.OrdinalIgnoreCase),
                    $"The locked restart must reconcile a protected cleanup residue before reaching PckExport.{Environment.NewLine}{reconcile.Output}");
                AssertSnapshot(live, committedB, "BackupCleanup restart live B batch");
                AssertNoQuarantineResidue(liveParent, "Vivhite", "BackupCleanup restart");
                continue;
            }
            AssertSnapshot(live, expectedA, $"{failurePoint} rolled-back live A batch");
            AcceptanceAssert.True(!Directory.Exists(Path.GetDirectoryName(candidate)), $"{failurePoint} left a candidate directory.");
            AssertNoTransactionResidue(liveParent, "Vivhite", failurePoint);
        }

        var successExpectedA = InstallBatchA(live);
        AcceptanceAssert.True(successExpectedA.Count > 3, "The A batch fixture must include extra directory content so rollback checks a whole directory.");
        var successCandidate = Path.Combine(harnessRoot, "candidates", "success", "Vivhite.pck");
        var success = await RunPublisherAsync(
            root,
            exportScriptPath,
            fakeGodot,
            fakeProject,
            validator,
            assemblyPath,
            manifestPath,
            successCandidate,
            live,
            failurePoint: string.Empty);

        AcceptanceAssert.Equal(
            0,
            success.ExitCode,
            $"The B batch transaction must succeed.{Environment.NewLine}{success.Output}");
        AcceptanceAssert.SetEqual(
            TripletNames,
            Directory.GetFiles(live).Select(Path.GetFileName).OfType<string>().ToArray(),
            "The successful live B directory must contain exactly one three-file batch.");
        AcceptanceAssert.Empty(Directory.GetDirectories(live), "The successful live B directory must not contain A-batch subdirectories:");
        AcceptanceAssert.Equal("B-DLL-CONTENT", File.ReadAllText(Path.Combine(live, "Vivhite.dll"), Encoding.UTF8), "Live DLL must be batch B.");
        AcceptanceAssert.True(
            File.ReadAllText(Path.Combine(live, "Vivhite.pck"), Encoding.UTF8).Contains("B-PCK-CONTENT", StringComparison.Ordinal),
            "Live PCK must be batch B.");
        var liveManifest = File.ReadAllText(Path.Combine(live, "Vivhite.json"), Encoding.UTF8);
        AcceptanceAssert.True(liveManifest.Contains("B-JSON-CONTENT", StringComparison.Ordinal), "Live JSON must be batch B.");
        AcceptanceAssert.True(liveManifest.Contains("\"version\": \"9.9.9\"", StringComparison.Ordinal), "Live JSON must use the synchronized dependency version.");
        AcceptanceAssert.True(
            File.ReadAllText(manifestPath, Encoding.UTF8).Contains("OLD-VERSION", StringComparison.Ordinal),
            "Candidate synchronization must not rewrite the source manifest.");
        AcceptanceAssert.True(!Directory.Exists(Path.GetDirectoryName(successCandidate)), "Success must clean the non-live candidate directory.");
        AssertNoTransactionResidue(liveParent, "Vivhite", "successful B commit");
        AssertNoQuarantineResidue(liveParent, "Vivhite", "successful B commit");

        await AssertHistoricalResidueRecoveryAsync(
            root,
            exportScriptPath,
            fakeGodot,
            fakeProject,
            validator,
            assemblyPath,
            manifestPath,
            harnessRoot);
        await AssertRealBackupCleanupFailureAsync(
            root,
            exportScriptPath,
            fakeGodot,
            fakeProject,
            validator,
            assemblyPath,
            manifestPath,
            harnessRoot);
        await AssertCrossProcessSerializationAsync(
            root,
            exportScriptPath,
            fakeProject,
            validator,
            harnessRoot);
    }

    private static async Task AssertHistoricalResidueRecoveryAsync(
        string root,
        string exportScriptPath,
        string fakeGodot,
        string fakeProject,
        string validator,
        string assemblyPath,
        string manifestPath,
        string harnessRoot)
    {
        var historyRoot = Path.Combine(harnessRoot, "historical-residue");

        var recoverRoot = Path.Combine(historyRoot, "recover-unique-previous");
        var recoverParent = Path.Combine(recoverRoot, "mods");
        var recoverLive = Path.Combine(recoverParent, "Vivhite");
        Directory.CreateDirectory(recoverParent);
        var recoverPrevious = Path.Combine(recoverParent, $".Vivhite.previous.{Guid.NewGuid():N}");
        var recoverExpected = InstallExactBatch(recoverPrevious, "RECOVER-A");
        var recover = await RunPublisherAsync(
            root,
            exportScriptPath,
            fakeGodot,
            fakeProject,
            validator,
            assemblyPath,
            manifestPath,
            Path.Combine(recoverRoot, "candidate", "Vivhite.pck"),
            recoverLive,
            "PckExport");
        AcceptanceAssert.True(
            recover.ExitCode != 0 && recover.Output.Contains("Recovered the unique complete previous batch", StringComparison.Ordinal),
            $"A missing live directory must recover its sole complete previous batch under the lock before publishing.{Environment.NewLine}{recover.Output}");
        AssertSnapshot(recoverLive, recoverExpected, "recovered unique previous batch");
        AssertNoTransactionResidue(recoverParent, "Vivhite", "unique previous recovery");

        var cleanupRoot = Path.Combine(historyRoot, "clean-complete-staging");
        var cleanupParent = Path.Combine(cleanupRoot, "mods");
        var cleanupLive = Path.Combine(cleanupParent, "Vivhite");
        var cleanupExpected = InstallBatchA(cleanupLive);
        var completeStaging = Path.Combine(cleanupParent, $".Vivhite.staging.{Guid.NewGuid():N}");
        InstallExactBatch(completeStaging, "STALE-STAGING");
        var cleanup = await RunPublisherAsync(
            root,
            exportScriptPath,
            fakeGodot,
            fakeProject,
            validator,
            assemblyPath,
            manifestPath,
            Path.Combine(cleanupRoot, "candidate", "Vivhite.pck"),
            cleanupLive,
            "PckExport");
        AcceptanceAssert.True(
            cleanup.ExitCode != 0 && cleanup.Output.Contains("Safely reconciled complete historical residue", StringComparison.Ordinal),
            $"A complete stale staging directory beside a complete live batch must be safely quarantined and cleaned first.{Environment.NewLine}{cleanup.Output}");
        AssertSnapshot(cleanupLive, cleanupExpected, "live batch beside cleaned staging residue");
        AssertNoTransactionResidue(cleanupParent, "Vivhite", "complete staging reconciliation");
        AssertNoQuarantineResidue(cleanupParent, "Vivhite", "complete staging reconciliation");

        var ambiguousRoot = Path.Combine(historyRoot, "reject-multiple");
        var ambiguousParent = Path.Combine(ambiguousRoot, "mods");
        var ambiguousLive = Path.Combine(ambiguousParent, "Vivhite");
        var ambiguousExpected = InstallBatchA(ambiguousLive);
        InstallExactBatch(Path.Combine(ambiguousParent, $".Vivhite.previous.{Guid.NewGuid():N}"), "OLD-ONE");
        InstallExactBatch(Path.Combine(ambiguousParent, $".Vivhite.failed.{Guid.NewGuid():N}"), "OLD-TWO");
        var ambiguous = await RunPublisherAsync(
            root,
            exportScriptPath,
            fakeGodot,
            fakeProject,
            validator,
            assemblyPath,
            manifestPath,
            Path.Combine(ambiguousRoot, "candidate", "Vivhite.pck"),
            ambiguousLive,
            "PckExport");
        AcceptanceAssert.True(
            ambiguous.ExitCode != 0 && ambiguous.Output.Contains("Ambiguous Vivhite transaction history", StringComparison.Ordinal),
            $"Multiple historical residues must fail closed before candidate production.{Environment.NewLine}{ambiguous.Output}");
        AssertSnapshot(ambiguousLive, ambiguousExpected, "live batch beside ambiguous residues");
        AcceptanceAssert.True(!Directory.Exists(Path.Combine(ambiguousRoot, "candidate")), "Ambiguous history must fail before creating a candidate.");

        var partialRoot = Path.Combine(historyRoot, "reject-partial");
        var partialParent = Path.Combine(partialRoot, "mods");
        var partialLive = Path.Combine(partialParent, "Vivhite");
        var partialExpected = InstallBatchA(partialLive);
        var partialStaging = Path.Combine(partialParent, $".Vivhite.staging.{Guid.NewGuid():N}");
        Directory.CreateDirectory(partialStaging);
        File.WriteAllText(Path.Combine(partialStaging, "Vivhite.json"), "PARTIAL", new UTF8Encoding(false));
        var partial = await RunPublisherAsync(
            root,
            exportScriptPath,
            fakeGodot,
            fakeProject,
            validator,
            assemblyPath,
            manifestPath,
            Path.Combine(partialRoot, "candidate", "Vivhite.pck"),
            partialLive,
            "PckExport");
        AcceptanceAssert.True(
            partial.ExitCode != 0 && partial.Output.Contains("incomplete", StringComparison.OrdinalIgnoreCase),
            $"A partial historical residue must fail closed without being deleted or published over.{Environment.NewLine}{partial.Output}");
        AssertSnapshot(partialLive, partialExpected, "live batch beside partial residue");
        AcceptanceAssert.True(File.Exists(Path.Combine(partialStaging, "Vivhite.json")), "Fail-closed partial residue must remain available for diagnosis.");

        if (OperatingSystem.IsWindows())
        {
            var unknownRoot = Path.Combine(historyRoot, "reject-unknown-hash");
            var unknownParent = Path.Combine(unknownRoot, "mods");
            var unknownLive = Path.Combine(unknownParent, "Vivhite");
            var unknownExpected = InstallBatchA(unknownLive);
            var unknownPrevious = Path.Combine(unknownParent, $".Vivhite.previous.{Guid.NewGuid():N}");
            InstallExactBatch(unknownPrevious, "LOCKED-HASH");
            CommandResult unknown;
            using (var locked = new FileStream(
                       Path.Combine(unknownPrevious, "Vivhite.pck"),
                       FileMode.Open,
                       FileAccess.Read,
                       FileShare.None))
            {
                unknown = await RunPublisherAsync(
                    root,
                    exportScriptPath,
                    fakeGodot,
                    fakeProject,
                    validator,
                    assemblyPath,
                    manifestPath,
                    Path.Combine(unknownRoot, "candidate", "Vivhite.pck"),
                    unknownLive,
                    "PckExport");
            }
            AcceptanceAssert.True(unknown.ExitCode != 0, $"An unreadable residue hash must fail closed.{Environment.NewLine}{unknown.Output}");
            AssertSnapshot(unknownLive, unknownExpected, "live batch beside unreadable previous residue");
            AcceptanceAssert.True(Directory.Exists(unknownPrevious), "Unreadable previous residue must remain untouched for diagnosis.");
        }
    }

    private static async Task AssertRealBackupCleanupFailureAsync(
        string root,
        string exportScriptPath,
        string fakeGodot,
        string fakeProject,
        string validator,
        string assemblyPath,
        string manifestPath,
        string harnessRoot)
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        var scenarioRoot = Path.Combine(harnessRoot, "real-cleanup-failure");
        var liveParent = Path.Combine(scenarioRoot, "mods");
        var live = Path.Combine(liveParent, "Vivhite");
        var expectedA = InstallBatchA(live);
        for (var index = 0; index < 32; index++)
        {
            var extra = Path.Combine(live, "preserved", $"old-{index:D2}.bin");
            File.WriteAllBytes(extra, Enumerable.Repeat((byte)index, 4096).ToArray());
        }
        using (var largeOldPck = new FileStream(
                   Path.Combine(live, "Vivhite.pck"),
                   FileMode.Open,
                   FileAccess.Write,
                   FileShare.None))
        {
            largeOldPck.SetLength(64L * 1024 * 1024);
        }
        expectedA = Snapshot(live);

        var lockQuarantinedPck = WaitForQuarantinedPckHandleAsync(liveParent, "Vivhite", TimeSpan.FromSeconds(20));
        var cleanupTask = RunPublisherAsync(
            root,
            exportScriptPath,
            fakeGodot,
            fakeProject,
            validator,
            assemblyPath,
            manifestPath,
            Path.Combine(scenarioRoot, "candidate", "Vivhite.pck"),
            live,
            failurePoint: string.Empty);
        CommandResult cleanupFailure;
        using (var locked = await lockQuarantinedPck)
        {
            cleanupFailure = await cleanupTask;
        }

        AcceptanceAssert.True(
            cleanupFailure.ExitCode != 0 && cleanupFailure.Output.Contains("Protected Vivhite cleanup failed", StringComparison.Ordinal),
            $"A real mid-delete sharing violation must be reported as a failed cleanup, never a successful commit.{Environment.NewLine}{cleanupFailure.Output}");
        AssertLiveBatch(live, "B-DLL-CONTENT", "B-PCK-CONTENT", "B-JSON-CONTENT");
        AssertNoTransactionResidue(liveParent, "Vivhite", "real cleanup sharing violation");
        var recoveryArchive = RequireSingleRecoveryArchive(liveParent, "Vivhite", "real cleanup sharing violation");
        AssertRecoveryArchive(recoveryArchive, expectedA, "real cleanup sharing violation");
        var partialWork = RequireSingleQuarantineWorkDirectory(liveParent, "Vivhite", "real cleanup sharing violation");
        AcceptanceAssert.True(
            Snapshot(partialWork).Count < expectedA.Count,
            "The exclusive-handle test must hit during actual per-item deletion, after the disposable directory becomes partial.");

        var committedB = Snapshot(live);
        var reconcile = await RunPublisherAsync(
            root,
            exportScriptPath,
            fakeGodot,
            fakeProject,
            validator,
            assemblyPath,
            manifestPath,
            Path.Combine(scenarioRoot, "reconcile-candidate", "Vivhite.pck"),
            live,
            "PckExport");
        AcceptanceAssert.True(
            reconcile.ExitCode != 0 && reconcile.Output.Contains("PckExport", StringComparison.OrdinalIgnoreCase),
            $"After the handle is released, the next locked run must finish cleanup before candidate work.{Environment.NewLine}{reconcile.Output}");
        AssertSnapshot(live, committedB, "live B after real cleanup reconciliation");
        AssertNoQuarantineResidue(liveParent, "Vivhite", "real cleanup reconciliation");
    }

    private static async Task AssertCrossProcessSerializationAsync(
        string root,
        string exportScriptPath,
        string fakeProject,
        string validator,
        string harnessRoot)
    {
        await AssertConcurrentPairAsync(
            root,
            exportScriptPath,
            fakeProject,
            validator,
            Path.Combine(harnessRoot, "concurrent-failure-then-success"),
            firstFailurePoint: "AfterStagePromotion",
            secondFailurePoint: string.Empty,
            expectedLiveMarker: "P2");
        await AssertConcurrentPairAsync(
            root,
            exportScriptPath,
            fakeProject,
            validator,
            Path.Combine(harnessRoot, "concurrent-success-then-failure"),
            firstFailurePoint: string.Empty,
            secondFailurePoint: "AfterStagePromotion",
            expectedLiveMarker: "P1");
    }

    private static async Task AssertConcurrentPairAsync(
        string root,
        string exportScriptPath,
        string fakeProject,
        string validator,
        string scenarioRoot,
        string firstFailurePoint,
        string secondFailurePoint,
        string expectedLiveMarker)
    {
        var liveParent = Path.Combine(scenarioRoot, "mods");
        var live = Path.Combine(liveParent, "Vivhite");
        var initialA = InstallBatchA(live);
        var release = Path.Combine(scenarioRoot, "release-p1.marker");
        var p1Signal = Path.Combine(scenarioRoot, "p1-godot-entered.marker");
        var p2Signal = Path.Combine(scenarioRoot, "p2-godot-entered.marker");
        var p1 = CreatePublisherFixture(scenarioRoot, "P1", p1Signal, release);
        var p2 = CreatePublisherFixture(scenarioRoot, "P2", p2Signal, releasePath: null);

        var firstTask = RunPublisherAsync(
            root,
            exportScriptPath,
            p1.GodotPath,
            fakeProject,
            validator,
            p1.AssemblyPath,
            p1.ManifestPath,
            Path.Combine(scenarioRoot, "candidate-p1", "Vivhite.pck"),
            live,
            firstFailurePoint);
        await WaitForFileAsync(p1Signal, TimeSpan.FromSeconds(20));

        var timeoutSignal = Path.Combine(scenarioRoot, "timeout-godot-entered.marker");
        var timeoutFixture = CreatePublisherFixture(scenarioRoot, "TIMEOUT", timeoutSignal, releasePath: null);
        var timedOut = await RunPublisherAsync(
            root,
            exportScriptPath,
            timeoutFixture.GodotPath,
            fakeProject,
            validator,
            timeoutFixture.AssemblyPath,
            timeoutFixture.ManifestPath,
            Path.Combine(scenarioRoot, "candidate-timeout", "Vivhite.pck"),
            live,
            failurePoint: string.Empty,
            lockTimeoutSeconds: 1);
        AcceptanceAssert.True(
            timedOut.ExitCode != 0 && timedOut.Output.Contains("Timed out after 1 seconds", StringComparison.Ordinal),
            $"Lock contention must fail in a bounded way without entering candidate or switch work.{Environment.NewLine}{timedOut.Output}");
        AcceptanceAssert.True(!File.Exists(timeoutSignal), "A lock-timeout contender reached Godot candidate export.");
        AssertSnapshot(live, initialA, "live A while a lock-timeout contender exits");

        var normalizedAlias = Path.Combine(liveParent, "normalization-alias", "..", "Vivhite");
        var secondTask = RunPublisherAsync(
            root,
            exportScriptPath,
            p2.GodotPath,
            fakeProject,
            validator,
            p2.AssemblyPath,
            p2.ManifestPath,
            Path.Combine(scenarioRoot, "candidate-p2", "Vivhite.pck"),
            normalizedAlias,
            secondFailurePoint);
        await Task.Delay(400);
        AcceptanceAssert.True(
            !File.Exists(p2Signal),
            "P2 reached candidate export while P1 still held the normalized live-directory deployment lock.");
        File.WriteAllText(release, "release", new UTF8Encoding(false));

        var first = await firstTask;
        var second = await secondTask;
        AcceptanceAssert.True(
            first.CompletedUtc <= second.CompletedUtc,
            "The second publisher must not return before the first lock holder releases the complete transaction.");
        AcceptanceAssert.True(
            first.Output.Contains("Acquired normalized deployment lock", StringComparison.Ordinal) &&
            second.Output.Contains("Acquired normalized deployment lock", StringComparison.Ordinal),
            $"Both processes must prove acquisition of the same normalized-path lock.{Environment.NewLine}P1:{Environment.NewLine}{first.Output}{Environment.NewLine}P2:{Environment.NewLine}{second.Output}");

        if (string.IsNullOrEmpty(firstFailurePoint))
        {
            AcceptanceAssert.Equal(0, first.ExitCode, $"P1 was expected to succeed.{Environment.NewLine}{first.Output}");
        }
        else
        {
            AcceptanceAssert.True(first.ExitCode != 0, $"P1 was expected to fail.{Environment.NewLine}{first.Output}");
        }
        if (string.IsNullOrEmpty(secondFailurePoint))
        {
            AcceptanceAssert.Equal(0, second.ExitCode, $"P2 was expected to succeed.{Environment.NewLine}{second.Output}");
        }
        else
        {
            AcceptanceAssert.True(second.ExitCode != 0, $"P2 was expected to fail.{Environment.NewLine}{second.Output}");
        }

        AssertLiveBatch(
            live,
            $"{expectedLiveMarker}-DLL-CONTENT",
            $"{expectedLiveMarker}-PCK-CONTENT",
            $"{expectedLiveMarker}-JSON-CONTENT");
        AssertNoTransactionResidue(liveParent, "Vivhite", $"concurrent pair ending in {expectedLiveMarker}");
        AssertNoQuarantineResidue(liveParent, "Vivhite", $"concurrent pair ending in {expectedLiveMarker}");
    }

    private static async Task<CommandResult> RunPublisherAsync(
        string workingDirectory,
        string scriptPath,
        string godotPath,
        string projectPath,
        string validatorPath,
        string assemblyPath,
        string manifestPath,
        string candidatePath,
        string livePath,
        string failurePoint,
        int lockTimeoutSeconds = 120)
    {
        var arguments = new List<string>
        {
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            scriptPath,
            "-GodotExe",
            godotPath,
            "-ProjectDir",
            projectPath,
            "-Preset",
            "Test",
            "-OutputPath",
            candidatePath,
            "-ValidatorPath",
            validatorPath,
            "-AssemblyPath",
            assemblyPath,
            "-ManifestPath",
            manifestPath,
            "-ModOutputDir",
            livePath,
            "-RitsuLibVersion",
            "9.9.9",
            "-IroncladSkinRuntimeLayout",
            "v3-five-page",
            "-PowerShellExe",
            ResolvePowerShellHost(),
            "-LockTimeoutSeconds",
            lockTimeoutSeconds.ToString(System.Globalization.CultureInfo.InvariantCulture)
        };
        if (!string.IsNullOrEmpty(failurePoint))
        {
            arguments.Add("-FailurePoint");
            arguments.Add(failurePoint);
        }
        return await RunProcessAsync(ResolvePowerShellHost(), workingDirectory, arguments);
    }

    private static PublisherFixture CreatePublisherFixture(
        string scenarioRoot,
        string marker,
        string signalPath,
        string? releasePath)
    {
        var fixtureRoot = Path.Combine(scenarioRoot, marker.ToLowerInvariant());
        Directory.CreateDirectory(fixtureRoot);
        var assemblyPath = Path.Combine(fixtureRoot, "Vivhite.dll");
        var manifestPath = Path.Combine(fixtureRoot, "Vivhite.json");
        var godotPath = Path.Combine(fixtureRoot, "fake-godot.cmd");
        File.WriteAllText(assemblyPath, $"{marker}-DLL-CONTENT", new UTF8Encoding(false));
        File.WriteAllText(
            manifestPath,
            $$"""
            {
              "id": "Vivhite",
              "batch_marker": "{{marker}}-JSON-CONTENT",
              "dependencies": [
                { "id": "STS2-RitsuLib", "version": "OLD-VERSION" }
              ]
            }
            """,
            new UTF8Encoding(false));

        var command = new List<string>
        {
            "@echo off",
            "setlocal",
            "set \"last=\"",
            ":collect",
            "if \"%~1\"==\"\" goto entered",
            "set \"last=%~1\"",
            "shift",
            "goto collect",
            ":entered",
            $">\"{signalPath}\" echo entered"
        };
        if (!string.IsNullOrEmpty(releasePath))
        {
            command.Add(":wait_release");
            command.Add($"if exist \"{releasePath}\" goto write");
            command.Add("ping 127.0.0.1 -n 2 >nul");
            command.Add("goto wait_release");
        }
        command.Add(":write");
        command.Add($">\"%last%\" echo {marker}-PCK-CONTENT");
        command.Add("exit /b 0");
        File.WriteAllLines(godotPath, command, Encoding.ASCII);
        return new PublisherFixture(assemblyPath, manifestPath, godotPath);
    }

    private static async Task WaitForFileAsync(string path, TimeSpan timeout)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (!File.Exists(path) && DateTime.UtcNow < deadline)
        {
            await Task.Delay(25);
        }
        AcceptanceAssert.True(File.Exists(path), $"Timed out waiting for process barrier '{path}'.");
    }

    private static async Task<FileStream> WaitForQuarantinedPckHandleAsync(
        string liveParent,
        string liveName,
        TimeSpan timeout)
    {
        var quarantineRoot = GetQuarantineModRoot(liveParent, liveName);
        var deadline = DateTime.UtcNow + timeout;
        Exception? lastError = null;
        while (DateTime.UtcNow < deadline)
        {
            if (Directory.Exists(quarantineRoot))
            {
                foreach (var work in Directory.GetDirectories(quarantineRoot, "work.*", SearchOption.TopDirectoryOnly))
                {
                    var pck = Path.Combine(work, "Vivhite.pck");
                    if (!File.Exists(pck))
                    {
                        continue;
                    }
                    try
                    {
                        return new FileStream(pck, FileMode.Open, FileAccess.Read, FileShare.Read);
                    }
                    catch (IOException exception)
                    {
                        lastError = exception;
                    }
                }
            }
            await Task.Delay(2);
        }
        throw new AcceptanceFailureException(
            $"Timed out acquiring a real cleanup-time handle under '{quarantineRoot}'. Last error: {lastError?.Message}");
    }

    private static IReadOnlyDictionary<string, string> InstallExactBatch(string directory, string marker)
    {
        if (Directory.Exists(directory))
        {
            Directory.Delete(directory, recursive: true);
        }
        Directory.CreateDirectory(directory);
        File.WriteAllText(Path.Combine(directory, "Vivhite.dll"), $"{marker}-DLL", new UTF8Encoding(false));
        File.WriteAllText(Path.Combine(directory, "Vivhite.pck"), $"{marker}-PCK", new UTF8Encoding(false));
        File.WriteAllText(Path.Combine(directory, "Vivhite.json"), $"{marker}-JSON", new UTF8Encoding(false));
        return Snapshot(directory);
    }

    private static void AssertLiveBatch(
        string live,
        string expectedDllMarker,
        string expectedPckMarker,
        string expectedJsonMarker)
    {
        AcceptanceAssert.SetEqual(
            TripletNames,
            Directory.GetFiles(live).Select(Path.GetFileName).OfType<string>().ToArray(),
            "Live directory must contain exactly one DLL/PCK/JSON batch.");
        AcceptanceAssert.Empty(Directory.GetDirectories(live), "Live directory must have no mixed-batch subdirectories:");
        AcceptanceAssert.True(
            File.ReadAllText(Path.Combine(live, "Vivhite.dll"), Encoding.UTF8).Contains(expectedDllMarker, StringComparison.Ordinal),
            $"Live DLL does not belong to expected batch '{expectedDllMarker}'.");
        AcceptanceAssert.True(
            File.ReadAllText(Path.Combine(live, "Vivhite.pck"), Encoding.UTF8).Contains(expectedPckMarker, StringComparison.Ordinal),
            $"Live PCK does not belong to expected batch '{expectedPckMarker}'.");
        AcceptanceAssert.True(
            File.ReadAllText(Path.Combine(live, "Vivhite.json"), Encoding.UTF8).Contains(expectedJsonMarker, StringComparison.Ordinal),
            $"Live JSON does not belong to expected batch '{expectedJsonMarker}'.");
    }

    private static string GetQuarantineModRoot(string liveParent, string liveName) =>
        Path.Combine(Directory.GetParent(Path.GetFullPath(liveParent))!.FullName, ".vivhite-deploy-quarantine", liveName);

    private static string RequireSingleRecoveryArchive(string liveParent, string liveName, string subject)
    {
        var root = GetQuarantineModRoot(liveParent, liveName);
        var archives = Directory.Exists(root)
            ? Directory.GetFiles(root, "recovery.*.zip", SearchOption.TopDirectoryOnly)
            : [];
        AcceptanceAssert.Equal(1, archives.Length, $"{subject} must retain exactly one verifiable recovery archive.");
        return archives[0];
    }

    private static string RequireSingleQuarantineWorkDirectory(string liveParent, string liveName, string subject)
    {
        var root = GetQuarantineModRoot(liveParent, liveName);
        var work = Directory.Exists(root)
            ? Directory.GetDirectories(root, "work.*", SearchOption.TopDirectoryOnly)
            : [];
        AcceptanceAssert.Equal(1, work.Length, $"{subject} must retain exactly one identifiable disposable work directory.");
        return work[0];
    }

    private static void AssertRecoveryArchive(
        string archivePath,
        IReadOnlyDictionary<string, string> expected,
        string subject)
    {
        using var archive = ZipFile.OpenRead(archivePath);
        var manifestEntry = archive.GetEntry("vivhite-recovery-manifest.json");
        AcceptanceAssert.True(manifestEntry is not null, $"{subject} recovery archive is missing its embedded manifest.");
        using var reader = new StreamReader(manifestEntry!.Open(), Encoding.UTF8);
        using var manifest = JsonDocument.Parse(reader.ReadToEnd());
        AcceptanceAssert.Equal(
            "VivhiteDeploymentRecovery/v1",
            manifest.RootElement.GetProperty("format").GetString() ?? string.Empty,
            $"{subject} recovery archive format changed.");
        var records = manifest.RootElement.GetProperty("files")
            .EnumerateArray()
            .ToDictionary(
                item => item.GetProperty("path").GetString() ?? string.Empty,
                item => item,
                StringComparer.Ordinal);
        AcceptanceAssert.SetEqual(expected.Keys.ToArray(), records.Keys.ToArray(), $"{subject} recovery manifest membership changed.");
        AcceptanceAssert.Equal(expected.Count + 1, archive.Entries.Count, $"{subject} recovery ZIP contains unmanifested entries.");
        foreach (var pair in expected)
        {
            var record = records[pair.Key];
            AcceptanceAssert.Equal(pair.Value, record.GetProperty("sha256").GetString() ?? string.Empty, $"{subject} manifest hash changed for {pair.Key}.");
            var entry = archive.GetEntry($"batch/{pair.Key}");
            AcceptanceAssert.True(entry is not null, $"{subject} recovery ZIP is missing batch/{pair.Key}.");
            using var stream = entry!.Open();
            var hash = Convert.ToHexString(SHA256.HashData(stream));
            AcceptanceAssert.Equal(pair.Value, hash, $"{subject} recovery payload hash changed for {pair.Key}.");
            AcceptanceAssert.Equal(entry.Length, record.GetProperty("length").GetInt64(), $"{subject} recovery length changed for {pair.Key}.");
        }
    }

    private static void AssertNoQuarantineResidue(string liveParent, string liveName, string subject)
    {
        var root = GetQuarantineModRoot(liveParent, liveName);
        AcceptanceAssert.True(!Directory.Exists(root), $"{subject} left a Vivhite quarantine directory at '{root}'.");
    }

    private static IReadOnlyDictionary<string, string> InstallBatchA(string liveDirectory)
    {
        if (Directory.Exists(liveDirectory))
        {
            Directory.Delete(liveDirectory, recursive: true);
        }
        Directory.CreateDirectory(liveDirectory);
        File.WriteAllText(Path.Combine(liveDirectory, "Vivhite.dll"), "A-DLL", new UTF8Encoding(false));
        File.WriteAllText(Path.Combine(liveDirectory, "Vivhite.pck"), "A-PCK", new UTF8Encoding(false));
        File.WriteAllText(Path.Combine(liveDirectory, "Vivhite.json"), "A-JSON", new UTF8Encoding(false));
        var preserved = Path.Combine(liveDirectory, "preserved");
        Directory.CreateDirectory(preserved);
        File.WriteAllText(Path.Combine(preserved, "A-marker.txt"), "A-WHOLE-DIRECTORY", new UTF8Encoding(false));
        return Snapshot(liveDirectory);
    }

    private static IReadOnlyDictionary<string, string> Snapshot(string directory)
    {
        return Directory.GetFiles(directory, "*", SearchOption.AllDirectories)
            .Order(StringComparer.Ordinal)
            .ToDictionary(
                path => Path.GetRelativePath(directory, path).Replace('\\', '/'),
                path => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))),
                StringComparer.Ordinal);
    }

    private static void AssertSnapshot(
        string directory,
        IReadOnlyDictionary<string, string> expected,
        string subject)
    {
        AcceptanceAssert.True(Directory.Exists(directory), $"{subject} directory disappeared.");
        var actual = Snapshot(directory);
        AcceptanceAssert.SetEqual(expected.Keys.ToArray(), actual.Keys.ToArray(), $"{subject} directory membership changed.");
        foreach (var pair in expected)
        {
            AcceptanceAssert.Equal(pair.Value, actual[pair.Key], $"{subject} hash changed for {pair.Key}.");
        }
    }

    private static void AssertNoTransactionResidue(string parent, string liveName, string subject)
    {
        var residue = Directory.GetDirectories(parent)
            .Where(path =>
            {
                var name = Path.GetFileName(path);
                return name.StartsWith($".{liveName}.staging.", StringComparison.OrdinalIgnoreCase) ||
                    name.StartsWith($".{liveName}.previous.", StringComparison.OrdinalIgnoreCase) ||
                    name.StartsWith($".{liveName}.failed.", StringComparison.OrdinalIgnoreCase);
            })
            .ToArray();
        AcceptanceAssert.Empty(residue, $"{subject} left sibling transaction directories:");
    }

    private static XElement RequireTarget(XDocument project, string name)
    {
        var target = project.Descendants()
            .SingleOrDefault(element => element.Name.LocalName == "Target" &&
                string.Equals((string?)element.Attribute("Name"), name, StringComparison.Ordinal));
        return target ?? throw new AcceptanceFailureException($"Required MSBuild target is missing: {name}");
    }

    private static string[] SplitTargets(string? value) =>
        (value ?? string.Empty)
            .Split(';', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);

    private static bool IsPathInside(string path, string directory)
    {
        var fullPath = Path.GetFullPath(path);
        var fullDirectory = EnsureTrailingSeparator(Path.GetFullPath(directory));
        return fullPath.StartsWith(fullDirectory, StringComparison.OrdinalIgnoreCase);
    }

    private static async Task<IReadOnlyDictionary<string, string>> ReadEvaluatedPropertiesAsync(
        string workingDirectory,
        string projectPath,
        IReadOnlyCollection<string> propertyNames,
        params string[] globalProperties)
    {
        var arguments = new List<string>
        {
            "msbuild",
            projectPath,
            "/nologo",
            $"/getProperty:{string.Join(',', propertyNames)}",
            "/p:DesignTimeBuild=false"
        };
        arguments.AddRange(globalProperties);
        var result = await RunDotnetAsync(workingDirectory, arguments.ToArray());
        AcceptanceAssert.Equal(0, result.ExitCode, $"MSBuild property evaluation failed.{Environment.NewLine}{result.Output}");

        var jsonStart = result.Output.IndexOf('{');
        var jsonEnd = result.Output.LastIndexOf('}');
        AcceptanceAssert.True(jsonStart >= 0 && jsonEnd >= jsonStart, $"MSBuild did not return property JSON.{Environment.NewLine}{result.Output}");
        using var document = JsonDocument.Parse(result.Output[jsonStart..(jsonEnd + 1)]);
        var properties = document.RootElement.GetProperty("Properties");
        return propertyNames.ToDictionary(
            propertyName => propertyName,
            propertyName => properties.GetProperty(propertyName).GetString() ?? string.Empty,
            StringComparer.Ordinal);
    }

    private static Task<CommandResult> RunDotnetAsync(string workingDirectory, params string[] arguments) =>
        RunProcessAsync(ResolveDotnetHost(), workingDirectory, arguments);

    private static async Task<CommandResult> RunProcessAsync(
        string executable,
        string workingDirectory,
        IEnumerable<string> arguments)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = executable,
            WorkingDirectory = workingDirectory,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true
        };
        foreach (var inheritedProperty in new[]
                 {
                     "RunPckExport",
                     "CopyModOnBuild",
                     "STS2_SKIP_PCK_EXPORT",
                     "RitsuLibAutoCopy",
                     "DesignTimeBuild"
                 })
        {
            startInfo.Environment.Remove(inheritedProperty);
        }
        foreach (var argument in arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        using var process = new Process { StartInfo = startInfo };
        AcceptanceAssert.True(process.Start(), $"Could not start '{startInfo.FileName}'.");
        var standardOutput = process.StandardOutput.ReadToEndAsync();
        var standardError = process.StandardError.ReadToEndAsync();
        using var timeout = new CancellationTokenSource(TimeSpan.FromMinutes(4));
        try
        {
            await process.WaitForExitAsync(timeout.Token);
        }
        catch (OperationCanceledException)
        {
            process.Kill(entireProcessTree: true);
            throw new AcceptanceFailureException($"Timed out running '{executable}'.");
        }

        var output = string.Join(
            Environment.NewLine,
            new[] { await standardOutput, await standardError }.Where(value => !string.IsNullOrWhiteSpace(value)));
        return new CommandResult(process.ExitCode, output, DateTime.UtcNow);
    }

    private static string ResolveDotnetHost()
    {
        var configuredHost = Environment.GetEnvironmentVariable("DOTNET_HOST_PATH");
        if (!string.IsNullOrWhiteSpace(configuredHost) && File.Exists(configuredHost))
        {
            return configuredHost;
        }
        var dotnetRoot = Environment.GetEnvironmentVariable("DOTNET_ROOT");
        if (!string.IsNullOrWhiteSpace(dotnetRoot))
        {
            var rootedHost = Path.Combine(dotnetRoot, OperatingSystem.IsWindows() ? "dotnet.exe" : "dotnet");
            if (File.Exists(rootedHost))
            {
                return rootedHost;
            }
        }
        return OperatingSystem.IsWindows() ? "dotnet.exe" : "dotnet";
    }

    private static string ResolvePowerShellHost()
    {
        var systemRoot = Environment.GetFolderPath(Environment.SpecialFolder.Windows);
        var windowsPowerShell = Path.Combine(systemRoot, "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
        return File.Exists(windowsPowerShell) ? windowsPowerShell : "pwsh";
    }

    private static string EnsureTrailingSeparator(string path) =>
        path.EndsWith(Path.DirectorySeparatorChar) ? path : path + Path.DirectorySeparatorChar;

    private sealed record CommandResult(int ExitCode, string Output, DateTime CompletedUtc);

    private sealed record PublisherFixture(string AssemblyPath, string ManifestPath, string GodotPath);
}
