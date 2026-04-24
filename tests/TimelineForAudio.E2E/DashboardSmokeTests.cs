using System.IO.Compression;
using System.Net;
using System.Text.RegularExpressions;
using Microsoft.Playwright;

namespace TimelineForAudio.E2E;

[TestClass]
public sealed class DashboardSmokeTests : PageTest
{
    private static TestAppFixture _fixture = null!;

    [ClassInitialize]
    public static async Task InitializeAsync(TestContext _)
    {
        _fixture = await TestAppFixture.StartAsync();
    }

    [ClassCleanup]
    public static async Task CleanupAsync()
    {
        if (_fixture is not null)
        {
            await _fixture.DisposeAsync();
        }
    }

    private ILocator JobCard(string jobId) =>
        Page.Locator("article.job-card").Filter(new() { HasText = jobId });

    [TestMethod]
    public async Task Root_Redirects_To_NewJob_When_Setup_IsReady()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/");

        await Expect(Page).ToHaveURLAsync(new Regex(".*/jobs/new$"));
        await Expect(Page.Locator("html")).ToHaveAttributeAsync("lang", "en");
        await Expect(Page.GetByRole(AriaRole.Heading, new() { Name = "New Job", Exact = true })).ToBeVisibleAsync();
        await Expect(Page.GetByRole(AriaRole.Link, new() { Name = "Jobs", Exact = true })).ToBeVisibleAsync();
    }

    [TestMethod]
    public async Task Root_Redirects_To_Setup_When_Token_IsMissing()
    {
        try
        {
            await _fixture.SetTokenAsync(null);

            await Page.GotoAsync($"{_fixture.BaseUrl}/");

            StringAssert.Contains(Page.Url, "/setup", StringComparison.Ordinal);
            await Expect(Page.GetByRole(AriaRole.Heading, new() { Name = "First-Time Setup", Exact = true })).ToBeVisibleAsync();
            await Expect(Page.GetByText("Hugging Face", new() { Exact = true })).ToBeVisibleAsync();
        }
        finally
        {
            await _fixture.SetTokenAsync("hf_test_token_value");
        }
    }

    [TestMethod]
    public async Task Settings_Shows_ProcessingMode_And_SaveButton()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/settings");

        await Expect(Page.Locator("html")).ToHaveAttributeAsync("lang", "en");
        await Expect(Page.GetByRole(AriaRole.Heading, new() { Name = "Settings", Exact = true })).ToBeVisibleAsync();
        await Expect(Page.GetByRole(AriaRole.Button, new() { Name = "Save Settings", Exact = true })).ToBeVisibleAsync();
        await Expect(Page.GetByLabel("Language", new() { Exact = true })).ToBeVisibleAsync();
        await Expect(Page.GetByText("Processing Mode", new() { Exact = true })).ToBeVisibleAsync();
        await Expect(Page.GetByText("Hugging Face Connection", new() { Exact = true })).ToBeVisibleAsync();
        await Expect(Page.GetByText("App Language", new() { Exact = true })).ToBeVisibleAsync();
    }

    [TestMethod]
    public async Task Settings_DoesNotExpose_SavedTokenValue()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/settings");

        var preview = await Page.Locator("#token-preview-value").InnerTextAsync();
        StringAssert.StartsWith(preview, "hf_t", StringComparison.Ordinal);
        StringAssert.EndsWith(preview, "alue", StringComparison.Ordinal);

        var html = await Page.ContentAsync();
        Assert.IsFalse(html.Contains("hf_test_token_value", StringComparison.Ordinal));

        await Page.GetByRole(AriaRole.Button, new() { Name = "Change", Exact = true }).ClickAsync();
        await Expect(Page.Locator("#settings-token-modal")).ToBeVisibleAsync();
        await Expect(Page.Locator("#settings-token-modal-input")).ToHaveValueAsync(string.Empty);
    }

    [TestMethod]
    public async Task Settings_ChangeToken_CanBeCancelled()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/settings");

        await Expect(Page.Locator("#settings-token-modal")).ToBeHiddenAsync();
        await Page.GetByRole(AriaRole.Button, new() { Name = "Change", Exact = true }).ClickAsync();
        await Expect(Page.Locator("#settings-token-modal")).ToBeVisibleAsync();

        var tokenInput = Page.Locator("#settings-token-modal-input");
        await tokenInput.FillAsync("hf_new_token_value");
        await Page.Locator("#settings-token-modal-cancel").ClickAsync();
        await Expect(Page.Locator("#settings-token-modal")).ToBeHiddenAsync();

        await Page.GetByRole(AriaRole.Button, new() { Name = "Change", Exact = true }).ClickAsync();
        await Expect(tokenInput).ToHaveValueAsync(string.Empty);
    }

    [TestMethod]
    public async Task Settings_DeleteAllJobs_RequiresExactDeleteConfirmation()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/settings");

        await Page.GetByRole(AriaRole.Button, new() { Name = "Delete All Jobs", Exact = true }).ClickAsync();
        await Expect(Page.Locator("#settings-confirm-modal")).ToBeVisibleAsync();

        await Page.Locator("#settings-confirm-modal-input").FillAsync("delete");
        await Page.Locator("#settings-confirm-modal-submit").ClickAsync();

        await Expect(Page.Locator("#settings-confirm-modal-error")).ToHaveTextAsync("Type DELETE exactly to continue.");
        await Expect(Page.Locator("#settings-confirm-modal")).ToBeVisibleAsync();

        await Page.Locator("#settings-confirm-modal-cancel").ClickAsync();
        await Expect(Page.Locator("#settings-confirm-modal")).ToBeHiddenAsync();
    }

    [TestMethod]
    public async Task Settings_Localizes_Current_Sections_In_Japanese()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/settings?lang=ja");

        await Expect(Page.Locator("html")).ToHaveAttributeAsync("lang", "ja");
        await Expect(Page.GetByRole(AriaRole.Heading, new() { Name = "設定", Exact = true })).ToBeVisibleAsync();
        await Expect(Page.GetByText("処理モード", new() { Exact = true })).ToBeVisibleAsync();
        await Expect(Page.GetByText("Hugging Face 接続", new() { Exact = true })).ToBeVisibleAsync();
        await Expect(Page.GetByText("アプリの言語", new() { Exact = true })).ToBeVisibleAsync();
        await Expect(Page.GetByRole(AriaRole.Button, new() { Name = "設定を保存", Exact = true })).ToBeVisibleAsync();
    }

    [TestMethod]
    public async Task NewJob_ShowsInlineValidation_When_NoInputIsSelected()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/jobs/new");

        await Page.GetByRole(AriaRole.Button, new() { Name = "Start Conversion", Exact = true }).ClickAsync();

        await Expect(Page.Locator("#selection-feedback")).ToContainTextAsync("Choose audio files or a folder first.");
        await Expect(Page.GetByRole(AriaRole.Dialog)).ToHaveCountAsync(0);
    }

    [TestMethod]
    public async Task NewJob_ShowsSupplementalNotesGuidance_InJapanese()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/jobs/new?lang=ja");

        await Expect(Page.Locator("html")).ToHaveAttributeAsync("lang", "ja");
        await Expect(Page.Locator("#supplemental-context-text")).ToBeVisibleAsync();
        var placeholder = await Page.Locator("#supplemental-context-text").GetAttributeAsync("placeholder");
        StringAssert.Contains(placeholder ?? string.Empty, "人物名");
    }

    [TestMethod]
    public async Task Jobs_Page_Shows_Completed_Run_Card()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/jobs");

        var card = JobCard(_fixture.CompletedJobId);
        await Expect(Page.GetByRole(AriaRole.Heading, new() { Name = "Jobs", Exact = true })).ToBeVisibleAsync();
        await Expect(Page.GetByRole(AriaRole.Heading, new() { Name = "Recent Jobs", Exact = true })).ToBeVisibleAsync();
        await Expect(card).ToBeVisibleAsync();
        await Expect(card).ToContainTextAsync("1 MB");
        await Expect(card).ToContainTextAsync("1m 10s");
        await Expect(card).ToContainTextAsync("2m 7s");
        await Expect(card).ToContainTextAsync("IPA + Readable Text");
        await Expect(card.GetByRole(AriaRole.Button, new() { Name = "Download", Exact = true })).ToBeVisibleAsync();
    }

    [TestMethod]
    public async Task Jobs_Page_Prefers_Running_Run_In_Active_Panel()
    {
        var runningJobId = await _fixture.CreateRunningRunAsync();
        var pendingJobId = await _fixture.CreatePendingRunAsync();
        try
        {
            await Page.GotoAsync($"{_fixture.BaseUrl}/jobs");

            var activePanel = Page.Locator("section.panel.accent-panel");
            await Expect(activePanel).ToContainTextAsync("Now Processing");
            await Expect(activePanel).ToContainTextAsync(runningJobId);
            await Expect(activePanel).Not.ToContainTextAsync(pendingJobId);
        }
        finally
        {
            await _fixture.DeleteRunAsync(runningJobId);
            await _fixture.DeleteRunAsync(pendingJobId);
        }
    }

    [TestMethod]
    public async Task RunningRun_CanBeDeleted_FromJobsList()
    {
        var runningJobId = await _fixture.CreateLockedRunningRunAsync();
        try
        {
            await Page.GotoAsync($"{_fixture.BaseUrl}/jobs");

            var card = JobCard(runningJobId);
            await Expect(card).ToBeVisibleAsync();
            await card.GetByRole(AriaRole.Button, new() { Name = "Delete", Exact = true }).ClickAsync();
            await Expect(Page.Locator("#confirm-modal")).ToBeVisibleAsync();
            await Page.Locator("#confirm-modal-submit").ClickAsync();
            await Expect(Page.GetByText(runningJobId, new() { Exact = true })).ToHaveCountAsync(0);
            Assert.IsTrue(File.Exists(Path.Combine(_fixture.TempRoot, "outputs", "runs", runningJobId, ".delete-requested")));
        }
        finally
        {
            await _fixture.DeleteRunAsync(runningJobId);
        }
    }

    [TestMethod]
    public async Task CompletedRunDetails_ShowsArtifacts_AndReadablePreview()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/jobs/{_fixture.CompletedJobId}");

        await Expect(Page.GetByRole(AriaRole.Heading, new() { Name = _fixture.CompletedJobId, Exact = true })).ToBeVisibleAsync();
        await Expect(Page.GetByText("Processing Time", new() { Exact = true })).ToBeVisibleAsync();
        await Expect(Page.GetByText("2m 7s", new() { Exact = true })).ToBeVisibleAsync();
        await Expect(Page.GetByRole(AriaRole.Heading, new() { Name = "Per-file Results", Exact = true })).ToBeVisibleAsync();
        await Expect(Page.GetByText("sample-call.wav", new() { Exact = true })).ToBeVisibleAsync();
        await Expect(Page.GetByText("Conversion Info", new() { Exact = true })).ToBeVisibleAsync();
        await Expect(Page.Locator("#details-download-button")).ToBeVisibleAsync();

        var artifactCard = Page.Locator(".detail-artifact-card").Filter(new() { HasText = "sample-call.wav" });
        await artifactCard.GetByRole(AriaRole.Link, new() { Name = "Readable Text", Exact = true }).ClickAsync();

        await Expect(Page).ToHaveURLAsync(new Regex($".*/jobs/{_fixture.CompletedJobId}/{_fixture.CompletedMediaId}(\\?artifact=readable-text)?$"));
        await Expect(Page.GetByText("Readable View", new() { Exact = true })).ToBeVisibleAsync();
        await Expect(Page.GetByText("Hello, this is a public test sample.", new() { Exact = true })).ToBeVisibleAsync();
        await Expect(Page.GetByText("Nice to meet you. This is the reply.", new() { Exact = true })).ToBeVisibleAsync();
    }

    [TestMethod]
    public async Task DuplicateSkippedRunDetails_ShowsCacheReuse()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/jobs/{_fixture.DuplicateSkippedJobId}");

        await Expect(Page.GetByRole(AriaRole.Heading, new() { Name = _fixture.DuplicateSkippedJobId, Exact = true })).ToBeVisibleAsync();
        await Expect(Page.Locator(".status-badge").Filter(new() { HasText = "Cache Reused" })).ToBeVisibleAsync();
        await Expect(Page.GetByText($"Reused from job: {_fixture.CompletedJobId}", new() { Exact = true })).ToBeVisibleAsync();

        var artifactCard = Page.Locator(".detail-artifact-card").Filter(new() { HasText = "already-processed.wav" });
        await Expect(artifactCard.GetByRole(AriaRole.Link, new() { Name = "Readable Text", Exact = true })).ToBeVisibleAsync();
        await Expect(artifactCard.GetByRole(AriaRole.Link, new() { Name = "IPA", Exact = true })).ToBeVisibleAsync();
    }

    [TestMethod]
    public async Task CompletedRunDetails_CanDownloadReadableTextZip()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/jobs/{_fixture.CompletedJobId}");

        await Page.Locator("#details-download-button").ClickAsync();
        await Expect(Page.Locator("#details-download-modal")).ToBeVisibleAsync();
        await Expect(Page.Locator("#details-download-modal-readable")).ToBeVisibleAsync();
        await Expect(Page.Locator("#details-download-modal-ipa")).ToBeVisibleAsync();

        var download = await Page.RunAndWaitForDownloadAsync(async () =>
        {
            await Page.Locator("#details-download-modal-readable").ClickAsync();
        });

        Assert.AreEqual($"{_fixture.CompletedJobId}-readable-text.zip", download.SuggestedFilename);
        var zipPath = Path.Combine(_fixture.TempRoot, $"{_fixture.CompletedJobId}-readable-text.zip");
        await download.SaveAsAsync(zipPath);

        using var archive = ZipFile.OpenRead(zipPath);
        Assert.IsTrue(archive.Entries.Any(entry => entry.FullName.StartsWith("readable-text/", StringComparison.Ordinal)));
        Assert.IsNotNull(archive.GetEntry("CONVERSION_INFO.md"));
        Assert.IsNotNull(archive.GetEntry("README.html"));
    }

    [TestMethod]
    public async Task PartiallyFailedRunDetails_CanDownloadZip_WithFailureReport()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/jobs/{_fixture.PartialFailedJobId}");

        await Expect(Page.GetByRole(AriaRole.Heading, new() { Name = _fixture.PartialFailedJobId, Exact = true })).ToBeVisibleAsync();
        await Page.Locator("#details-download-button").ClickAsync();
        await Expect(Page.Locator("#details-download-modal-readable")).ToBeVisibleAsync();

        var download = await Page.RunAndWaitForDownloadAsync(async () =>
        {
            await Page.Locator("#details-download-modal-readable").ClickAsync();
        });

        var zipPath = Path.Combine(_fixture.TempRoot, $"{_fixture.PartialFailedJobId}-readable-text.zip");
        await download.SaveAsAsync(zipPath);

        using var archive = ZipFile.OpenRead(zipPath);
        Assert.IsTrue(archive.Entries.Any(entry => entry.FullName.StartsWith("readable-text/", StringComparison.Ordinal)));
        Assert.IsNotNull(archive.GetEntry("FAILURE_REPORT.md"));
        Assert.IsNotNull(archive.GetEntry("logs/worker.log"));

        await using var reportStream = archive.GetEntry("FAILURE_REPORT.md")!.Open();
        using var reportReader = new StreamReader(reportStream);
        var reportText = await reportReader.ReadToEndAsync();
        StringAssert.Contains(reportText, "broken-call.wav");
        StringAssert.Contains(reportText, "CUDA failed with error unknown error");
    }

    [TestMethod]
    public async Task FailedRunWithoutArtifacts_HidesDownload_AndDownloadReturnsBadRequest()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/jobs");

        var card = JobCard(_fixture.FailedNoTimelineJobId);
        await Expect(card).ToBeVisibleAsync();
        await Expect(card.Locator("button[data-download-job-id]")).ToHaveCountAsync(0);

        await Page.GotoAsync($"{_fixture.BaseUrl}/jobs/{_fixture.FailedNoTimelineJobId}");
        await Expect(Page.Locator("#details-download-button")).ToHaveCountAsync(0);

        using var client = new HttpClient();
        using var response = await client.GetAsync($"{_fixture.BaseUrl}/jobs/{_fixture.FailedNoTimelineJobId}/download?artifact=readable-text");
        Assert.AreEqual(HttpStatusCode.BadRequest, response.StatusCode);
        var body = await response.Content.ReadAsStringAsync();
        StringAssert.Contains(body, "No completed Readable Text artifacts are available to download for this job.");
    }

    [TestMethod]
    public async Task RunningRun_HidesDownload_AndDownloadReturnsBadRequest()
    {
        var jobId = await _fixture.CreateRunningRunAsync();
        try
        {
            await Page.GotoAsync($"{_fixture.BaseUrl}/jobs");

            var card = JobCard(jobId);
            await Expect(card).ToBeVisibleAsync();
            await Expect(card.Locator("button[data-download-job-id]")).ToHaveCountAsync(0);

            await Page.GotoAsync($"{_fixture.BaseUrl}/jobs/{jobId}");
            await Expect(Page.Locator("#details-download-button")).ToHaveCountAsync(0);

            using var client = new HttpClient();
            using var response = await client.GetAsync($"{_fixture.BaseUrl}/jobs/{jobId}/download?artifact=ipa");
            Assert.AreEqual(HttpStatusCode.BadRequest, response.StatusCode);
            var body = await response.Content.ReadAsStringAsync();
            StringAssert.Contains(body, "This job is still in progress.");
        }
        finally
        {
            await _fixture.DeleteRunAsync(jobId);
        }
    }

    [TestMethod]
    public async Task LegacyRunUrls_Redirect_To_JobUrls()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/runs/{_fixture.CompletedJobId}");
        await Expect(Page).ToHaveURLAsync(new Regex($".*/jobs/{_fixture.CompletedJobId}$"));

        await Page.GotoAsync($"{_fixture.BaseUrl}/runs/{_fixture.CompletedJobId}/{_fixture.CompletedMediaId}");
        await Expect(Page).ToHaveURLAsync(new Regex($".*/jobs/{_fixture.CompletedJobId}/{_fixture.CompletedMediaId}$"));
    }
}
