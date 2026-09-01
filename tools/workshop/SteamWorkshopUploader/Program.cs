using System.Diagnostics;
using System.Text.Json;
using Steamworks;

internal static class Program
{
    private const string ModId = "Vivhite";

    private sealed record Options(
        uint AppId,
        ulong PublishedFileId,
        string ContentDirectory,
        string PreviewFile,
        string Title,
        string DescriptionFile,
        string Visibility,
        IReadOnlyList<string> Tags,
        ulong DependencyId,
        string Version,
        string ResultFile,
        TimeSpan Timeout);

    private sealed record CallEnvelope<T>(T Value, bool IoFailure) where T : struct;

    private sealed class PublishReceipt
    {
        public int schema { get; set; } = 1;
        public string mod_id { get; set; } = ModId;
        public uint app_id { get; set; }
        public ulong published_file_id { get; set; }
        public string url { get; set; } = "";
        public string version { get; set; } = "";
        public string visibility { get; set; } = "";
        public bool created { get; set; }
        public bool upload_complete { get; set; }
        public bool dependency_complete { get; set; }
        public ulong dependency_id { get; set; }
        public bool workshop_agreement_required { get; set; }
        public string status { get; set; } = "starting";
        public string error { get; set; } = "";
        public string finished_utc { get; set; } = "";
    }

    public static async Task<int> Main(string[] args)
    {
        Options options;
        try
        {
            options = ParseOptions(args);
            ValidateInputs(options);
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine($"[workshop] input_error={exception.Message}");
            return 2;
        }

        var receipt = new PublishReceipt
        {
            app_id = options.AppId,
            published_file_id = options.PublishedFileId,
            version = options.Version,
            visibility = options.Visibility,
            dependency_id = options.DependencyId
        };

        Environment.SetEnvironmentVariable("SteamAppId", options.AppId.ToString());
        Environment.SetEnvironmentVariable("SteamGameId", options.AppId.ToString());

        Console.WriteLine($"[workshop] steam_running={SteamAPI.IsSteamRunning()}");
        var initResult = SteamAPI.InitEx(out var initError);
        if (initResult != ESteamAPIInitResult.k_ESteamAPIInitResult_OK)
        {
            receipt.status = "steam_init_failed";
            receipt.error = $"{initResult}: {initError}";
            receipt.finished_utc = DateTimeOffset.UtcNow.ToString("O");
            WriteReceipt(options.ResultFile, receipt);
            Console.Error.WriteLine($"[workshop] steam_init_failed={receipt.error}");
            return 3;
        }

        try
        {
            if (!SteamUser.BLoggedOn())
                throw new InvalidOperationException("Steam is running, but the current client user is not logged on.");
            if (SteamUtils.GetAppID() != (AppId_t)options.AppId)
                throw new InvalidOperationException($"Steam initialized the wrong App ID: {SteamUtils.GetAppID()}.");
            if (!SteamApps.BIsSubscribed())
                throw new InvalidOperationException($"The logged-in Steam account does not own App {options.AppId}.");

            Console.WriteLine($"[workshop] app_id={SteamUtils.GetAppID()} logged_on=true owns_app=true ui_language={SteamUtils.GetSteamUILanguage()}");

            var eula = await AwaitCallAsync<WorkshopEULAStatus_t>(
                SteamUGC.GetWorkshopEULAStatus(), options.Timeout, "eula");
            if (eula.IoFailure)
                throw new InvalidOperationException("Could not verify the Workshop agreement because the Steam call had an I/O failure.");
            if (eula.Value.m_eResult == EResult.k_EResultOK && eula.Value.m_bNeedsAction)
            {
                receipt.workshop_agreement_required = true;
                throw new InvalidOperationException("The Steam Workshop legal agreement must be accepted by the logged-in user before publishing.");
            }
            if (eula.Value.m_eResult is EResult.k_EResultInvalidParam or EResult.k_EResultNotSupported)
            {
                // Some ready-to-use Workshops do not expose GetWorkshopEULAStatus.
                // CreateItem and SubmitItemUpdate still return the authoritative
                // agreement-required flag, so continue and fail closed on those.
                Console.WriteLine($"[workshop] eula_preflight=unsupported result={eula.Value.m_eResult}");
            }
            else if (eula.Value.m_eResult != EResult.k_EResultOK)
            {
                throw new InvalidOperationException($"Could not verify the Workshop agreement: result={eula.Value.m_eResult}.");
            }

            var itemId = options.PublishedFileId;
            if (itemId == 0)
            {
                var matches = await FindOwnedItemsAsync((AppId_t)options.AppId, options.Title, options.Timeout);
                if (matches.Count > 1)
                    throw new InvalidOperationException($"Found multiple owned Vivhite Workshop candidates: {string.Join(",", matches)}.");
                if (matches.Count == 1)
                {
                    itemId = matches[0];
                    Console.WriteLine($"[workshop] existing_item={itemId}");
                }
            }

            if (itemId == 0)
            {
                var created = await AwaitCallAsync<CreateItemResult_t>(
                    SteamUGC.CreateItem((AppId_t)options.AppId, EWorkshopFileType.k_EWorkshopFileTypeCommunity),
                    options.Timeout,
                    "create_item");
                if (created.IoFailure || created.Value.m_eResult != EResult.k_EResultOK)
                    throw new InvalidOperationException($"CreateItem failed: io_failure={created.IoFailure}, result={created.Value.m_eResult}.");
                itemId = (ulong)created.Value.m_nPublishedFileId;
                receipt.created = true;
                receipt.published_file_id = itemId;
                receipt.url = ItemUrl(itemId);
                receipt.workshop_agreement_required = created.Value.m_bUserNeedsToAcceptWorkshopLegalAgreement;
                receipt.status = "item_created";
                WriteReceipt(options.ResultFile, receipt);
                Console.WriteLine($"[workshop] created_item={itemId} url={receipt.url}");
                if (created.Value.m_bUserNeedsToAcceptWorkshopLegalAgreement)
                    throw new InvalidOperationException("Steam created the item, but requires acceptance of the Workshop legal agreement before upload.");
            }

            receipt.published_file_id = itemId;
            receipt.url = ItemUrl(itemId);
            await UploadItemAsync(options, (PublishedFileId_t)itemId, receipt);

            if (options.DependencyId != 0)
            {
                var dependencyPresent = await HasDependencyAsync(
                    (PublishedFileId_t)itemId,
                    (PublishedFileId_t)options.DependencyId,
                    options.Timeout);
                if (!dependencyPresent)
                {
                    var dependency = await AwaitCallAsync<AddUGCDependencyResult_t>(
                        SteamUGC.AddDependency((PublishedFileId_t)itemId, (PublishedFileId_t)options.DependencyId),
                        options.Timeout,
                        "add_dependency");
                    if (dependency.IoFailure || dependency.Value.m_eResult != EResult.k_EResultOK)
                        throw new InvalidOperationException($"AddDependency failed: io_failure={dependency.IoFailure}, result={dependency.Value.m_eResult}.");
                    Console.WriteLine($"[workshop] dependency_added={options.DependencyId}");
                }
                else
                {
                    Console.WriteLine($"[workshop] dependency_present={options.DependencyId}");
                }
                receipt.dependency_complete = true;
            }
            else
            {
                receipt.dependency_complete = true;
            }

            receipt.status = "published";
            receipt.finished_utc = DateTimeOffset.UtcNow.ToString("O");
            WriteReceipt(options.ResultFile, receipt);
            Console.WriteLine($"[workshop] published_item={itemId} url={receipt.url} visibility={options.Visibility}");
            return 0;
        }
        catch (Exception exception)
        {
            receipt.status = "failed";
            receipt.error = exception.Message;
            receipt.finished_utc = DateTimeOffset.UtcNow.ToString("O");
            WriteReceipt(options.ResultFile, receipt);
            Console.Error.WriteLine($"[workshop] failure={exception.Message}");
            if (receipt.published_file_id != 0)
                Console.Error.WriteLine($"[workshop] retained_item={receipt.published_file_id} url={receipt.url}");
            return 4;
        }
        finally
        {
            SteamAPI.Shutdown();
        }
    }

    private static async Task UploadItemAsync(Options options, PublishedFileId_t itemId, PublishReceipt receipt)
    {
        var handle = SteamUGC.StartItemUpdate((AppId_t)options.AppId, itemId);
        if (handle == UGCUpdateHandle_t.Invalid)
            throw new InvalidOperationException("StartItemUpdate returned an invalid handle.");

        Require(SteamUGC.SetItemTitle(handle, options.Title), "SetItemTitle");
        Require(SteamUGC.SetItemDescription(handle, File.ReadAllText(options.DescriptionFile)), "SetItemDescription");
        Require(SteamUGC.SetItemContent(handle, options.ContentDirectory), "SetItemContent");
        Require(SteamUGC.SetItemPreview(handle, options.PreviewFile), "SetItemPreview");
        Require(SteamUGC.SetItemVisibility(handle, ParseVisibility(options.Visibility)), "SetItemVisibility");
        Require(SteamUGC.SetItemMetadata(handle, JsonSerializer.Serialize(new
        {
            schema = 1,
            mod_id = ModId,
            version = options.Version,
            min_game_version = "0.111.0",
            dependency = "STS2-RitsuLib@0.5.14"
        })), "SetItemMetadata");
        if (options.Tags.Count > 0)
            Require(SteamUGC.SetItemTags(handle, options.Tags.ToList(), false), "SetItemTags");

        var lastProgress = DateTimeOffset.MinValue;
        var stopwatch = Stopwatch.StartNew();
        void ReportProgress()
        {
            if (DateTimeOffset.UtcNow - lastProgress < TimeSpan.FromSeconds(2))
                return;
            var status = SteamUGC.GetItemUpdateProgress(handle, out var processed, out var total);
            var percent = total == 0 ? 0 : (processed * 100.0 / total);
            Console.WriteLine($"[workshop] upload_status={status} bytes={processed}/{total} percent={percent:F1} elapsed_s={stopwatch.Elapsed.TotalSeconds:F0}");
            lastProgress = DateTimeOffset.UtcNow;
        }

        var changeNote = receipt.created
            ? $"Vivhite {options.Version} - initial Steam Workshop release"
            : $"Vivhite {options.Version} - package and metadata refresh";
        var submitted = await AwaitCallAsync<SubmitItemUpdateResult_t>(
            SteamUGC.SubmitItemUpdate(handle, changeNote),
            options.Timeout,
            "submit_item_update",
            ReportProgress);
        stopwatch.Stop();
        if (submitted.IoFailure || submitted.Value.m_eResult != EResult.k_EResultOK)
            throw new InvalidOperationException($"SubmitItemUpdate failed: io_failure={submitted.IoFailure}, result={submitted.Value.m_eResult}.");
        receipt.workshop_agreement_required = submitted.Value.m_bUserNeedsToAcceptWorkshopLegalAgreement;
        if (submitted.Value.m_bUserNeedsToAcceptWorkshopLegalAgreement)
            throw new InvalidOperationException("The content uploaded, but Steam requires acceptance of the Workshop legal agreement before publication.");
        receipt.upload_complete = true;
        receipt.status = "content_uploaded";
        WriteReceipt(options.ResultFile, receipt);
        Console.WriteLine($"[workshop] upload_complete=true elapsed_s={stopwatch.Elapsed.TotalSeconds:F1}");
    }

    private static async Task<bool> HasDependencyAsync(
        PublishedFileId_t itemId,
        PublishedFileId_t dependencyId,
        TimeSpan timeout)
    {
        var query = SteamUGC.CreateQueryUGCDetailsRequest(new[] { itemId }, 1);
        if (query == UGCQueryHandle_t.Invalid)
            throw new InvalidOperationException("CreateQueryUGCDetailsRequest returned an invalid handle.");
        try
        {
            Require(SteamUGC.SetReturnChildren(query, true), "SetReturnChildren");
            var completed = await AwaitCallAsync<SteamUGCQueryCompleted_t>(
                SteamUGC.SendQueryUGCRequest(query), timeout, "query_dependencies");
            if (completed.IoFailure || completed.Value.m_eResult != EResult.k_EResultOK)
                throw new InvalidOperationException($"Dependency query failed: io_failure={completed.IoFailure}, result={completed.Value.m_eResult}.");
            if (completed.Value.m_unNumResultsReturned != 1 || !SteamUGC.GetQueryUGCResult(query, 0, out var details))
                throw new InvalidOperationException("Dependency query did not return the requested Workshop item.");
            if (details.m_eResult != EResult.k_EResultOK)
                throw new InvalidOperationException($"Dependency item details failed: result={details.m_eResult}.");
            if (details.m_unNumChildren == 0)
                return false;

            var children = new PublishedFileId_t[details.m_unNumChildren];
            if (!SteamUGC.GetQueryUGCChildren(query, 0, children, details.m_unNumChildren))
                throw new InvalidOperationException("Steam did not return the requested Workshop dependency list.");
            return children.Any(child => child == dependencyId);
        }
        finally
        {
            SteamUGC.ReleaseQueryUGCRequest(query);
        }
    }

    private static async Task<List<ulong>> FindOwnedItemsAsync(AppId_t appId, string title, TimeSpan timeout)
    {
        var matches = new HashSet<ulong>();
        var accountId = SteamUser.GetSteamID().GetAccountID();
        for (uint page = 1; page <= 20; page++)
        {
            var query = SteamUGC.CreateQueryUserUGCRequest(
                accountId,
                EUserUGCList.k_EUserUGCList_Published,
                EUGCMatchingUGCType.k_EUGCMatchingUGCType_Items,
                EUserUGCListSortOrder.k_EUserUGCListSortOrder_LastUpdatedDesc,
                appId,
                appId,
                page);
            if (query == UGCQueryHandle_t.Invalid)
                throw new InvalidOperationException("CreateQueryUserUGCRequest returned an invalid handle.");
            try
            {
                Require(SteamUGC.SetReturnMetadata(query, true), "SetReturnMetadata");
                var completed = await AwaitCallAsync<SteamUGCQueryCompleted_t>(
                    SteamUGC.SendQueryUGCRequest(query), timeout, $"query_owned_page_{page}");
                if (completed.IoFailure || completed.Value.m_eResult != EResult.k_EResultOK)
                    throw new InvalidOperationException($"Owned item query failed: io_failure={completed.IoFailure}, result={completed.Value.m_eResult}.");

                for (uint index = 0; index < completed.Value.m_unNumResultsReturned; index++)
                {
                    if (!SteamUGC.GetQueryUGCResult(query, index, out var details))
                        continue;
                    var exactTitle = string.Equals(details.m_rgchTitle, title, StringComparison.OrdinalIgnoreCase);
                    var containsName = details.m_rgchTitle.Contains("Vivhite", StringComparison.OrdinalIgnoreCase);
                    var metadata = "";
                    var metadataMatch = SteamUGC.GetQueryUGCMetadata(query, index, out metadata, 4096)
                        && metadata.Contains("\"mod_id\":\"Vivhite\"", StringComparison.OrdinalIgnoreCase);
                    if (exactTitle || containsName || metadataMatch)
                        matches.Add((ulong)details.m_nPublishedFileId);
                }

                if (page * 50 >= completed.Value.m_unTotalMatchingResults || completed.Value.m_unNumResultsReturned == 0)
                    break;
            }
            finally
            {
                SteamUGC.ReleaseQueryUGCRequest(query);
            }
        }
        return matches.OrderBy(value => value).ToList();
    }

    private static async Task<CallEnvelope<T>> AwaitCallAsync<T>(
        SteamAPICall_t call,
        TimeSpan timeout,
        string operation,
        Action? progress = null) where T : struct
    {
        if (call == SteamAPICall_t.Invalid)
            throw new InvalidOperationException($"{operation} returned an invalid Steam API call handle.");

        var completion = new TaskCompletionSource<CallEnvelope<T>>(TaskCreationOptions.RunContinuationsAsynchronously);
        using var result = CallResult<T>.Create((value, ioFailure) =>
            completion.TrySetResult(new CallEnvelope<T>(value, ioFailure)));
        result.Set(call);
        var deadline = DateTimeOffset.UtcNow + timeout;
        while (!completion.Task.IsCompleted)
        {
            SteamAPI.RunCallbacks();
            progress?.Invoke();
            if (DateTimeOffset.UtcNow >= deadline)
                throw new TimeoutException($"Timed out waiting for Steam operation '{operation}' after {timeout.TotalSeconds:F0} seconds.");
            await Task.Delay(50);
        }
        SteamAPI.RunCallbacks();
        return await completion.Task;
    }

    private static void Require(bool success, string operation)
    {
        if (!success)
            throw new InvalidOperationException($"Steam rejected {operation} before submission.");
    }

    private static ERemoteStoragePublishedFileVisibility ParseVisibility(string value) =>
        value.ToLowerInvariant() switch
        {
            "public" => ERemoteStoragePublishedFileVisibility.k_ERemoteStoragePublishedFileVisibilityPublic,
            "friends" => ERemoteStoragePublishedFileVisibility.k_ERemoteStoragePublishedFileVisibilityFriendsOnly,
            "private" => ERemoteStoragePublishedFileVisibility.k_ERemoteStoragePublishedFileVisibilityPrivate,
            "unlisted" => ERemoteStoragePublishedFileVisibility.k_ERemoteStoragePublishedFileVisibilityUnlisted,
            _ => throw new ArgumentOutOfRangeException(nameof(value), value, "Visibility must be public, friends, private, or unlisted.")
        };

    private static Options ParseOptions(string[] args)
    {
        var values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        for (var index = 0; index < args.Length; index += 2)
        {
            if (index + 1 >= args.Length || !args[index].StartsWith("--", StringComparison.Ordinal))
                throw new ArgumentException("Arguments must be provided as --name value pairs.");
            values[args[index][2..]] = args[index + 1];
        }

        string Required(string name) => values.TryGetValue(name, out var value) && !string.IsNullOrWhiteSpace(value)
            ? value
            : throw new ArgumentException($"Missing required argument --{name}.");

        var tags = values.TryGetValue("tags", out var rawTags)
            ? rawTags.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            : Array.Empty<string>();
        return new Options(
            uint.Parse(Required("app-id")),
            ulong.Parse(values.GetValueOrDefault("published-file-id", "0")),
            Path.GetFullPath(Required("content")),
            Path.GetFullPath(Required("preview")),
            Required("title"),
            Path.GetFullPath(Required("description-file")),
            values.GetValueOrDefault("visibility", "public"),
            tags,
            ulong.Parse(values.GetValueOrDefault("dependency-id", "0")),
            Required("version"),
            Path.GetFullPath(Required("result")),
            TimeSpan.FromSeconds(int.Parse(values.GetValueOrDefault("timeout-seconds", "900"))));
    }

    private static void ValidateInputs(Options options)
    {
        if (options.AppId == 0)
            throw new ArgumentException("App ID must be non-zero.");
        if (!Directory.Exists(options.ContentDirectory))
            throw new DirectoryNotFoundException($"Content directory does not exist: {options.ContentDirectory}");
        var files = Directory.GetFiles(options.ContentDirectory).Select(Path.GetFileName).OrderBy(value => value).ToArray();
        var expected = new[] { "Vivhite.dll", "Vivhite.json", "Vivhite.pck" };
        if (!files.SequenceEqual(expected, StringComparer.OrdinalIgnoreCase) || Directory.GetDirectories(options.ContentDirectory).Length != 0)
            throw new InvalidOperationException($"Workshop content must be the exact Vivhite triplet; found: {string.Join(",", files)}.");
        if (!File.Exists(options.PreviewFile))
            throw new FileNotFoundException("Preview file does not exist.", options.PreviewFile);
        var previewBytes = new FileInfo(options.PreviewFile).Length;
        if (previewBytes < 16 || previewBytes >= 1_000_000)
            throw new InvalidOperationException($"Preview must be at least 16 bytes and less than 1,000,000 bytes; found {previewBytes}.");
        if (!File.Exists(options.DescriptionFile))
            throw new FileNotFoundException("Description file does not exist.", options.DescriptionFile);
        if (options.Title.Length is < 1 or > 128)
            throw new InvalidOperationException("Workshop title must contain 1 to 128 characters.");
        var description = File.ReadAllText(options.DescriptionFile);
        if (string.IsNullOrWhiteSpace(description) || description.Length > 8000)
            throw new InvalidOperationException("Workshop description must contain 1 to 8000 characters.");
        if (options.Timeout < TimeSpan.FromSeconds(30) || options.Timeout > TimeSpan.FromHours(2))
            throw new InvalidOperationException("Timeout must be between 30 and 7200 seconds.");
        _ = ParseVisibility(options.Visibility);
    }

    private static string ItemUrl(ulong itemId) => $"https://steamcommunity.com/sharedfiles/filedetails/?id={itemId}";

    private static void WriteReceipt(string path, PublishReceipt receipt)
    {
        var directory = Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(directory))
            Directory.CreateDirectory(directory);
        var temporary = path + ".tmp";
        File.WriteAllText(temporary, JsonSerializer.Serialize(receipt, new JsonSerializerOptions { WriteIndented = true }));
        File.Move(temporary, path, true);
    }
}
