using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using TimelineForAudio.Web.Models;
using TimelineForAudio.Web.Services;

namespace TimelineForAudio.Web.Pages.Jobs;

public sealed class NewModel(
    RunStore runStore,
    SettingsStore settingsStore,
    LanguageService languageService,
    JsonLocalizationService localizer) : PageModel
{
    [BindProperty]
    public List<IFormFile> UploadFiles { get; set; } = [];

    [BindProperty]
    public List<IFormFile> UploadDirectoryFiles { get; set; } = [];

    [TempData]
    public string? StatusMessage { get; set; }

    public IReadOnlyList<string> AllowedExtensions { get; private set; } = [];

    public string AcceptAttribute => string.Join(",", AllowedExtensions);

    public string AllowedExtensionsDisplay => string.Join(", ", AllowedExtensions);

    public async Task OnGetAsync(CancellationToken cancellationToken)
    {
        await LoadPageStateAsync(cancellationToken);
    }

    public async Task<IActionResult> OnPostExecuteAsync(CancellationToken cancellationToken)
    {
        await LoadPageStateAsync(cancellationToken);

        var files = UploadFiles.Concat(UploadDirectoryFiles).ToList();
        if (files.Count == 0)
        {
            ModelState.AddModelError(string.Empty, L("jobs.new.select_input"));
            return Page();
        }

        var unsupported = files
            .Where(file => !IsSupportedExtension(file.FileName))
            .Select(static file => file.FileName)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(static value => value, StringComparer.CurrentCultureIgnoreCase)
            .ToList();
        if (unsupported.Count > 0)
        {
            ModelState.AddModelError(
                string.Empty,
                string.Format(
                    System.Globalization.CultureInfo.CurrentCulture,
                    L("jobs.new.unsupported_server"),
                    string.Join(", ", unsupported)));
            return Page();
        }

        var uploaded = await runStore.SaveUploadsAsync(files, cancellationToken);
        var created = await runStore.CreateJobAsync(
            new CreateJobCommand
            {
                UploadedFiles = uploaded.ToList(),
            },
            cancellationToken);

        return RedirectToPage("/Runs/Details", new { id = created.JobId });
    }

    private string L(string key) => localizer.Get(languageService.Resolve(Request), key);

    private async Task LoadPageStateAsync(CancellationToken cancellationToken)
    {
        var settings = await settingsStore.LoadAsync(cancellationToken);
        AllowedExtensions = settings.AudioExtensions
            .Select(static value => value.Trim())
            .Where(static value => !string.IsNullOrWhiteSpace(value))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(static value => value, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private bool IsSupportedExtension(string fileName)
    {
        if (AllowedExtensions.Count == 0)
        {
            return true;
        }

        var extension = Path.GetExtension(fileName)?.Trim().ToLowerInvariant();
        if (string.IsNullOrWhiteSpace(extension))
        {
            return false;
        }

        return AllowedExtensions.Contains(extension, StringComparer.OrdinalIgnoreCase);
    }
}
