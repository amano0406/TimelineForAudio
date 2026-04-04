using System.Net;
using System.Text.RegularExpressions;
using System.IO.Compression;
using Microsoft.Playwright;

namespace Audio2Timeline.E2E;

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

    [TestMethod]
    public async Task Root_Redirects_To_NewJob()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/");

        await Expect(Page).ToHaveURLAsync(new Regex(".*/jobs/new$"));
        await Expect(Page.Locator("html")).ToHaveAttributeAsync("lang", "en");
        await Expect(Page.GetByRole(AriaRole.Heading, new() { Name = "New Job" })).ToBeVisibleAsync();
        await Expect(Page.GetByRole(AriaRole.Link, new() { Name = "Jobs" })).ToBeVisibleAsync();
    }

    [TestMethod]
    public async Task Settings_Shows_Save_Button_And_ProcessingQuality()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/settings");

        await Expect(Page.Locator("html")).ToHaveAttributeAsync("lang", "en");
        await Expect(Page.GetByRole(AriaRole.Heading, new() { Name = "Settings" })).ToBeVisibleAsync();
        await Expect(Page.GetByRole(AriaRole.Button, new() { Name = "Save And Continue" })).ToBeVisibleAsync();
        await Expect(Page.GetByLabel("Language")).ToBeVisibleAsync();
        await Expect(Page.GetByText("Processing Quality")).ToBeVisibleAsync();
    }

    [TestMethod]
    public async Task Settings_DoesNotExpose_SavedTokenValue()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/settings");

        await Expect(Page.GetByLabel("Hugging Face Token")).ToHaveValueAsync(string.Empty);
        var html = await Page.ContentAsync();
        Assert.IsFalse(html.Contains("hf_test_token_value", StringComparison.Ordinal));
    }

    [TestMethod]
    public async Task Settings_Localizes_SavedModels_Section_In_Japanese()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/settings?lang=ja");

        await Expect(Page.Locator("html")).ToHaveAttributeAsync("lang", "ja");
        await Expect(Page.GetByRole(AriaRole.Heading, new() { Name = "保存済みモデル" })).ToBeVisibleAsync();
        await Expect(Page.GetByText("Saved Models", new() { Exact = true })).ToHaveCountAsync(0);
    }

    [TestMethod]
    public async Task NewJob_UsesModal_When_NoInputIsSelected()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/jobs/new");

        await Page.GetByRole(AriaRole.Button, new() { Name = "Start" }).ClickAsync();

        await Expect(Page.GetByRole(AriaRole.Heading, new() { Name = "Choose Videos First" })).ToBeVisibleAsync();
        await Page.GetByRole(AriaRole.Button, new() { Name = "OK" }).ClickAsync();
        await Expect(Page.GetByRole(AriaRole.Heading, new() { Name = "Choose Videos First" })).ToHaveCountAsync(0);
    }

    [TestMethod]
    public async Task NewJob_ShowsDuplicateDecisionModal_ForPreviouslyConvertedUpload()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/jobs/new");

        await Page.Locator("#upload-files-input").SetInputFilesAsync(_fixture.DuplicateUploadPath);
        await Expect(Page.Locator("#selected-items-list").GetByText("already-processed.mp4")).ToBeVisibleAsync();

        await Page.GetByRole(AriaRole.Button, new() { Name = "Start" }).ClickAsync();

        await Expect(Page.GetByRole(AriaRole.Heading, new() { Name = "Previously Converted Files Found" })).ToBeVisibleAsync();
        await Expect(Page.Locator("#decision-modal-list").GetByText("already-processed.mp4")).ToBeVisibleAsync();
        await Page.GetByRole(AriaRole.Button, new() { Name = "Cancel" }).ClickAsync();
        await Expect(Page.GetByRole(AriaRole.Heading, new() { Name = "Previously Converted Files Found" })).ToHaveCountAsync(0);
        await Expect(Page).ToHaveURLAsync(new Regex(".*/jobs/new$"));
    }

    [TestMethod]
    public async Task Jobs_Page_Shows_Completed_Run()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/jobs");

        var row = Page.Locator("tr").Filter(new() { HasText = _fixture.CompletedJobId });
        await Expect(Page.GetByRole(AriaRole.Heading, new() { Name = "Jobs", Exact = true })).ToBeVisibleAsync();
        await Expect(Page.GetByText("Now Processing")).ToHaveCountAsync(0);
        await Expect(Page.GetByText(_fixture.CompletedJobId)).ToBeVisibleAsync();
        await Expect(row).ToContainTextAsync("1 MB");
        await Expect(row).ToContainTextAsync("1m 10s");
        await Expect(row).ToContainTextAsync("2m 7s");
        await Expect(row.GetByRole(AriaRole.Link, new() { Name = "ZIP" })).ToBeVisibleAsync();
    }

    [TestMethod]
    public async Task Jobs_Page_Prefers_Running_Run_In_Active_Panel()
    {
        var runningJobId = await _fixture.CreateRunningRunAsync();
        var pendingJobId = await _fixture.CreatePendingRunAsync();
        try
        {
            await Page.GotoAsync($"{_fixture.BaseUrl}/jobs");

            var activePanel = Page.Locator("section.panel").Filter(new() { HasText = "Now Processing" });
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
    public async Task Jobs_Page_Counts_Skipped_Items_In_Progress_And_Shows_Zip()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/jobs");

        var row = Page.Locator("tr").Filter(new() { HasText = _fixture.DuplicateSkippedJobId });
        await Expect(row).ToContainTextAsync(_fixture.DuplicateSkippedJobId);
        await Expect(row).ToContainTextAsync("1 / 1");
        await Expect(row).ToContainTextAsync("Processed 0 | Reused 1 | Errors 0");
        await Expect(row.GetByRole(AriaRole.Link, new() { Name = "ZIP" })).ToBeVisibleAsync();
    }

    [TestMethod]
    public async Task Jobs_Page_FallsBack_To_TerminalCounts_When_Legacy_Progress_IsMissing()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/jobs");

        var row = Page.Locator("tr").Filter(new() { HasText = _fixture.LegacyDuplicateProgressJobId });
        await Expect(row).ToContainTextAsync(_fixture.LegacyDuplicateProgressJobId);
        await Expect(row).ToContainTextAsync("1 / 1");
        await Expect(row).ToContainTextAsync("Processed 0 | Reused 1 | Errors 0");
    }

    [TestMethod]
    public async Task CompletedRunDetails_ExposeZip_AndTimeline()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/jobs/{_fixture.CompletedJobId}");

        await Expect(Page.GetByRole(AriaRole.Heading, new() { Name = _fixture.CompletedJobId })).ToBeVisibleAsync();
        await Expect(Page.GetByText("Elapsed Time")).ToBeVisibleAsync();
        await Expect(Page.GetByText("2m 7s")).ToBeVisibleAsync();
        await Expect(Page.GetByText("This Job Settings", new() { Exact = true })).ToBeVisibleAsync();
        await Expect(Page.GetByText("Compute Mode: CPU")).ToBeVisibleAsync();
        await Expect(Page.GetByText("Processing Quality: Standard")).ToBeVisibleAsync();
        await Expect(Page.GetByText("Current Settings", new() { Exact = true })).ToBeVisibleAsync();
        await Expect(Page.GetByText("Compute Mode: GPU")).ToBeVisibleAsync();
        await Expect(Page.GetByText("Processing Quality: High")).ToBeVisibleAsync();
        await Expect(Page.GetByRole(AriaRole.Button, new() { Name = "Run Again With Same Settings" })).ToBeVisibleAsync();
        await Expect(Page.GetByRole(AriaRole.Button, new() { Name = "Run Again With Current Settings" })).ToBeVisibleAsync();
        await Expect(Page.GetByRole(AriaRole.Link, new() { Name = "Download ZIP" })).ToBeVisibleAsync();
        await Expect(Page.GetByRole(AriaRole.Link, new() { Name = _fixture.CompletedMediaId })).ToBeVisibleAsync();

        await Page.GetByRole(AriaRole.Link, new() { Name = _fixture.CompletedMediaId }).ClickAsync();
        await Expect(Page).ToHaveURLAsync(new Regex($".*/jobs/{_fixture.CompletedJobId}/{_fixture.CompletedMediaId}$"));
        await Expect(Page.Locator("pre")).ToContainTextAsync("Video Timeline");
        await Expect(Page.Locator("pre")).ToContainTextAsync("public test sample");
    }

    [TestMethod]
    public async Task DuplicateSkippedRunDetails_Show_ReusedTimeline()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/jobs/{_fixture.DuplicateSkippedJobId}");

        await Expect(Page.GetByRole(AriaRole.Heading, new() { Name = _fixture.DuplicateSkippedJobId })).ToBeVisibleAsync();
        await Expect(Page.GetByText("1 / 1")).ToBeVisibleAsync();
        await Expect(Page.GetByText("Processed 0 | Reused 1 | Errors 0")).ToBeVisibleAsync();
        await Expect(Page.GetByRole(AriaRole.Link, new() { Name = "Download ZIP" })).ToBeVisibleAsync();
        await Expect(Page.GetByRole(AriaRole.Link, new() { Name = _fixture.DuplicateSkippedMediaId })).ToBeVisibleAsync();
        await Expect(Page.GetByText($"Reused from job: {_fixture.CompletedJobId}")).ToBeVisibleAsync();

        await Page.GetByRole(AriaRole.Link, new() { Name = _fixture.DuplicateSkippedMediaId }).ClickAsync();
        await Expect(Page).ToHaveURLAsync(new Regex($".*/jobs/{_fixture.DuplicateSkippedJobId}/{_fixture.DuplicateSkippedMediaId}$"));
        await Expect(Page.Locator("pre")).ToContainTextAsync("Video Timeline");
        await Expect(Page.Locator("pre")).ToContainTextAsync("public test sample");
    }

    [TestMethod]
    public async Task DuplicateSkippedRun_CanDownloadZip()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/jobs/{_fixture.DuplicateSkippedJobId}");

        var download = await Page.RunAndWaitForDownloadAsync(async () =>
        {
            await Page.GetByRole(AriaRole.Link, new() { Name = "Download ZIP" }).ClickAsync();
        });

        var zipPath = Path.Combine(_fixture.TempRoot, $"{_fixture.DuplicateSkippedJobId}.zip");
        await download.SaveAsAsync(zipPath);

        using var archive = ZipFile.OpenRead(zipPath);
        Assert.IsTrue(archive.Entries.Any(entry => entry.FullName.StartsWith("timelines/", StringComparison.Ordinal)));
    }

    [TestMethod]
    public async Task CompletedRunDetails_CanDownloadZip()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/jobs/{_fixture.CompletedJobId}");

        var download = await Page.RunAndWaitForDownloadAsync(async () =>
        {
            await Page.GetByRole(AriaRole.Link, new() { Name = "Download ZIP" }).ClickAsync();
        });

        Assert.AreEqual($"{_fixture.CompletedJobId}.zip", download.SuggestedFilename);
    }

    [TestMethod]
    public async Task Jobs_Page_Shows_Zip_For_PartiallyFailed_Run()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/jobs");

        var row = Page.Locator("tr").Filter(new() { HasText = _fixture.PartialFailedJobId });
        await Expect(row).ToContainTextAsync(_fixture.PartialFailedJobId);
        await Expect(row.GetByRole(AriaRole.Link, new() { Name = "ZIP" })).ToBeVisibleAsync();
    }

    [TestMethod]
    public async Task PartiallyFailedRunDetails_CanDownloadZip_WithFailureReport()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/jobs/{_fixture.PartialFailedJobId}");

        await Expect(Page.GetByRole(AriaRole.Heading, new() { Name = _fixture.PartialFailedJobId })).ToBeVisibleAsync();
        await Expect(Page.GetByRole(AriaRole.Link, new() { Name = "Download ZIP" })).ToBeVisibleAsync();
        await Expect(Page.GetByRole(AriaRole.Link, new() { Name = _fixture.PartialFailedMediaId })).ToBeVisibleAsync();

        var download = await Page.RunAndWaitForDownloadAsync(async () =>
        {
            await Page.GetByRole(AriaRole.Link, new() { Name = "Download ZIP" }).ClickAsync();
        });

        var zipPath = Path.Combine(_fixture.TempRoot, $"{_fixture.PartialFailedJobId}.zip");
        await download.SaveAsAsync(zipPath);

        using var archive = ZipFile.OpenRead(zipPath);
        Assert.IsTrue(archive.Entries.Any(entry => entry.FullName.StartsWith("timelines/", StringComparison.Ordinal)));
        Assert.IsNotNull(archive.GetEntry("FAILURE_REPORT.md"));
        Assert.IsNotNull(archive.GetEntry("logs/worker.log"));

        using var reportReader = new StreamReader(archive.GetEntry("FAILURE_REPORT.md")!.Open());
        var reportText = await reportReader.ReadToEndAsync();
        StringAssert.Contains(reportText, "broken-call.mp4");
        StringAssert.Contains(reportText, "CUDA failed with error unknown error");
    }

    [TestMethod]
    public async Task FailedRunWithoutTimelines_HidesZip_AndDownloadReturnsBadRequest()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/jobs");

        var row = Page.Locator("tr").Filter(new() { HasText = _fixture.FailedNoTimelineJobId });
        await Expect(row).ToContainTextAsync(_fixture.FailedNoTimelineJobId);
        await Expect(row.GetByRole(AriaRole.Link, new() { Name = "ZIP" })).ToHaveCountAsync(0);

        await Page.GotoAsync($"{_fixture.BaseUrl}/jobs/{_fixture.FailedNoTimelineJobId}");
        await Expect(Page.GetByRole(AriaRole.Link, new() { Name = "Download ZIP" })).ToHaveCountAsync(0);

        using var client = new HttpClient();
        using var response = await client.GetAsync($"{_fixture.BaseUrl}/jobs/{_fixture.FailedNoTimelineJobId}/download");
        Assert.AreEqual(HttpStatusCode.BadRequest, response.StatusCode);
        var body = await response.Content.ReadAsStringAsync();
        StringAssert.Contains(body, "No completed timelines are available to download for this job.");
    }

    [TestMethod]
    public async Task RunningRun_HidesZip_AndDownloadReturnsBadRequest()
    {
        var jobId = await _fixture.CreateRunningRunAsync();
        try
        {
            await Page.GotoAsync($"{_fixture.BaseUrl}/jobs");

            var row = Page.Locator("tr").Filter(new() { HasText = jobId });
            await Expect(row).ToContainTextAsync(jobId);
            await Expect(row.GetByRole(AriaRole.Link, new() { Name = "ZIP" })).ToHaveCountAsync(0);

            await Page.GotoAsync($"{_fixture.BaseUrl}/jobs/{jobId}");
            await Expect(Page.GetByRole(AriaRole.Link, new() { Name = "Download ZIP" })).ToHaveCountAsync(0);

            using var client = new HttpClient();
            using var response = await client.GetAsync($"{_fixture.BaseUrl}/jobs/{jobId}/download");
            Assert.AreEqual(HttpStatusCode.BadRequest, response.StatusCode);
            var body = await response.Content.ReadAsStringAsync();
            StringAssert.Contains(body, "The job is still in progress.");
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

    [TestMethod]
    public async Task Root_DoesNotRequire_Token_After_Language_IsSelected()
    {
        try
        {
            await _fixture.SetTokenAsync(null);

            await Page.GotoAsync($"{_fixture.BaseUrl}/");

            await Expect(Page).ToHaveURLAsync(new Regex(".*/jobs/new$"));
        }
        finally
        {
            await _fixture.SetTokenAsync("hf_test_token_value");
        }
    }

    [TestMethod]
    public async Task CompletedRun_CanRerunWithOriginalSettings()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/jobs/{_fixture.CompletedJobId}");

        await Page.GetByRole(AriaRole.Button, new() { Name = "Run Again With Same Settings" }).ClickAsync();
        await Expect(Page).ToHaveURLAsync(new Regex(".*/jobs/job-[^/]+$"));

        var rerunJobId = new Uri(Page.Url).Segments[^1].Trim('/');
        try
        {
            var request = await _fixture.ReadJobRequestSettingsAsync(rerunJobId);
            Assert.AreEqual("cpu", request.ComputeMode);
            Assert.AreEqual("standard", request.ProcessingQuality);
            Assert.IsTrue(request.ReprocessDuplicates);
        }
        finally
        {
            await _fixture.DeleteRunAsync(rerunJobId);
        }
    }

    [TestMethod]
    public async Task CompletedRun_CanRerunWithCurrentSettings()
    {
        await Page.GotoAsync($"{_fixture.BaseUrl}/jobs/{_fixture.CompletedJobId}");

        await Page.GetByRole(AriaRole.Button, new() { Name = "Run Again With Current Settings" }).ClickAsync();
        await Expect(Page).ToHaveURLAsync(new Regex(".*/jobs/job-[^/]+$"));

        var rerunJobId = new Uri(Page.Url).Segments[^1].Trim('/');
        try
        {
            var request = await _fixture.ReadJobRequestSettingsAsync(rerunJobId);
            Assert.AreEqual("gpu", request.ComputeMode);
            Assert.AreEqual("high", request.ProcessingQuality);
            Assert.IsTrue(request.ReprocessDuplicates);
        }
        finally
        {
            await _fixture.DeleteRunAsync(rerunJobId);
        }
    }
}
