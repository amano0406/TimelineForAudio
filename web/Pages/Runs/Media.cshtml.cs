using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using TimelineForAudio.Web.Services;

namespace TimelineForAudio.Web.Pages.Runs;

public sealed class MediaModel(RunStore runStore) : PageModel
{
    public string JobId { get; private set; } = "";
    public string MediaId { get; private set; } = "";
    public string TimelineText { get; private set; } = "";

    public async Task<IActionResult> OnGetAsync(string jobId, string mediaId, CancellationToken cancellationToken)
    {
        var timeline = await runStore.ReadTimelineAsync(jobId, mediaId, cancellationToken);
        if (timeline is null)
        {
            return NotFound();
        }

        JobId = jobId;
        MediaId = mediaId;
        TimelineText = timeline;
        return Page();
    }
}
