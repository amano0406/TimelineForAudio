using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Audio2Timeline.Web.Infrastructure;
using Audio2Timeline.Web.Models;
using Audio2Timeline.Web.Services;

namespace Audio2Timeline.Web.Pages.Runs;

public sealed class DetailsModel(RunStore runStore) : PageModel
{
    public RunDetails? Run { get; private set; }
    public string? StatusMessage { get; private set; }

    public async Task<IActionResult> OnGetAsync(string id, CancellationToken cancellationToken)
    {
        Run = await runStore.GetRunDetailsAsync(id, cancellationToken);
        return Run is null ? NotFound() : Page();
    }

    public async Task<IActionResult> OnPostRerunAsync(string id, string mode, CancellationToken cancellationToken)
    {
        if (!string.Equals(mode, "original", StringComparison.OrdinalIgnoreCase) &&
            !string.Equals(mode, "current", StringComparison.OrdinalIgnoreCase))
        {
            return BadRequest();
        }

        try
        {
            var created = await runStore.CreateJobFromExistingAsync(
                id,
                useCurrentSettings: string.Equals(mode, "current", StringComparison.OrdinalIgnoreCase),
                cancellationToken);
            return Redirect(JobUrls.Details(created.JobId));
        }
        catch (InvalidOperationException ex)
        {
            StatusMessage = ex.Message;
            Run = await runStore.GetRunDetailsAsync(id, cancellationToken);
            return Run is null ? NotFound() : Page();
        }
    }
}
