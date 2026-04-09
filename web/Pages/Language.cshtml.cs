using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using TimelineForAudio.Web.Services;

namespace TimelineForAudio.Web.Pages;

public sealed class LanguageModel(
    SettingsStore settingsStore,
    LanguageService languageService,
    JsonLocalizationService localizer) : PageModel
{
    [BindProperty]
    public string UiLanguage { get; set; } = "en";

    public async Task OnGetAsync(CancellationToken cancellationToken)
    {
        var settings = await settingsStore.LoadAsync(cancellationToken);
        UiLanguage = languageService.Normalize(settings.UiLanguage) ?? "en";
    }

    public async Task<IActionResult> OnPostAsync(CancellationToken cancellationToken)
    {
        var normalizedLanguage = languageService.Normalize(UiLanguage);
        if (normalizedLanguage is null)
        {
            ModelState.AddModelError(nameof(UiLanguage), L("language.form.required"));
            return Page();
        }

        var settings = await settingsStore.LoadAsync(cancellationToken);
        settings.UiLanguage = normalizedLanguage;
        settings.LanguageSelected = true;
        await settingsStore.SaveAsync(settings, cancellationToken: cancellationToken);

        return RedirectToPage("/Settings");
    }

    private string L(string key) => localizer.Get(languageService.Resolve(Request), key);
}
