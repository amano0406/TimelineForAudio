using System.Globalization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using TimelineForAudio.Web.Infrastructure;
using TimelineForAudio.Web.Models;
using TimelineForAudio.Web.Services;

namespace TimelineForAudio.Web.Pages.Jobs;

public sealed class IndexModel(
    RunStore runStore,
    LanguageService languageService,
    JsonLocalizationService localizer) : PageModel
{
    private const int PageSize = 30;

    public IReadOnlyList<RunSummary> RecentRuns { get; private set; } = [];

    public RunSummary? ActiveRun { get; private set; }

    [BindProperty(SupportsGet = true)]
    public int PageNumber { get; set; } = 1;

    public int TotalPages { get; private set; }
    public int TotalRuns { get; private set; }
    public int ActiveRuns { get; private set; }
    public int CompletedRuns { get; private set; }
    public int AttentionRuns { get; private set; }

    [TempData]
    public string? StatusMessage { get; set; }

    public async Task OnGetAsync(CancellationToken cancellationToken)
    {
        await LoadPageAsync(cancellationToken);
    }

    public async Task<IActionResult> OnPostDeleteAsync(string jobId, CancellationToken cancellationToken)
    {
        await LoadPageAsync(cancellationToken);
        try
        {
            await runStore.DeleteRunAsync(jobId, cancellationToken);
            StatusMessage = L("jobs.list.deleted");
            return RedirectToPage();
        }
        catch (InvalidOperationException ex)
        {
            ModelState.AddModelError(string.Empty, KnownMessageLocalizer.Localize(ex.Message, L));
            return Page();
        }
    }

    public async Task<IActionResult> OnPostDeleteAllAsync(string confirmation, CancellationToken cancellationToken)
    {
        await LoadPageAsync(cancellationToken);
        if (!string.Equals(confirmation, "DELETE", StringComparison.Ordinal))
        {
            ModelState.AddModelError(string.Empty, L("jobs.list.delete_all_invalid"));
            return Page();
        }

        var deleted = await runStore.DeleteAllRunsAsync(cancellationToken);
        StatusMessage = string.Format(CultureInfo.CurrentCulture, L("jobs.list.delete_all_deleted"), deleted);
        return RedirectToPage();
    }

    private async Task LoadPageAsync(CancellationToken cancellationToken)
    {
        var runs = await runStore.ListRunsAsync(cancellationToken);
        ActiveRun = runs.FirstOrDefault(static run =>
                       string.Equals(run.State, "running", StringComparison.OrdinalIgnoreCase))
                   ?? runs.FirstOrDefault(static run =>
                       string.Equals(run.State, "pending", StringComparison.OrdinalIgnoreCase));

        TotalRuns = runs.Count;
        ActiveRuns = runs.Count(static run =>
            string.Equals(run.State, "running", StringComparison.OrdinalIgnoreCase) ||
            string.Equals(run.State, "pending", StringComparison.OrdinalIgnoreCase));
        CompletedRuns = runs.Count(static run =>
            string.Equals(run.State, "completed", StringComparison.OrdinalIgnoreCase));
        AttentionRuns = runs.Count(static run =>
            string.Equals(run.State, "failed", StringComparison.OrdinalIgnoreCase) ||
            string.Equals(run.State, "canceled", StringComparison.OrdinalIgnoreCase));

        var totalCount = runs.Count;
        TotalPages = Math.Max(1, (int)Math.Ceiling(totalCount / (double)PageSize));
        PageNumber = Math.Clamp(PageNumber, 1, TotalPages);

        RecentRuns = runs
            .Skip((PageNumber - 1) * PageSize)
            .Take(PageSize)
            .ToList();
    }

    private string L(string key) => localizer.Get(languageService.Resolve(Request), key);
}
