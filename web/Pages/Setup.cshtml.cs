using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using TimelineForAudio.Web.Models;
using TimelineForAudio.Web.Services;

namespace TimelineForAudio.Web.Pages;

public sealed class SetupModel(
    HuggingFaceAccessService accessService,
    SettingsStore settingsStore,
    SetupStateService setupStateService,
    WorkerCapabilityService workerCapabilityService,
    LanguageService languageService,
    JsonLocalizationService localizer) : PageModel
{
    private const string PyannoteModelId = "pyannote/speaker-diarization-community-1";

    [BindProperty]
    public string UiLanguage { get; set; } = "en";

    [BindProperty]
    public string ComputeMode { get; set; } = "cpu";

    [BindProperty]
    public string Token { get; set; } = "";

    public string Step { get; private set; } = "language";

    public SetupState SetupState { get; private set; } = new();

    public WorkerCapabilitySnapshot WorkerCapability { get; private set; } = new();

    public HuggingFaceAccessSnapshot AccessSnapshot { get; private set; } = new();

    public IReadOnlyList<SupportedLanguage> SupportedLanguages { get; private set; } = [];

    [TempData]
    public string? StatusMessage { get; set; }

    public string TokenSettingsUrl => "https://huggingface.co/settings/tokens";

    public string HuggingFaceJoinUrl => "https://huggingface.co/join";

    public string PyannoteModelUrl => "https://huggingface.co/pyannote/speaker-diarization-community-1";

    public async Task<IActionResult> OnGetAsync(string? step, CancellationToken cancellationToken)
    {
        await LoadPageAsync(step, cancellationToken);
        return Page();
    }

    public async Task<IActionResult> OnPostLanguageAsync(CancellationToken cancellationToken)
    {
        var normalizedLanguage = languageService.Normalize(UiLanguage);
        if (normalizedLanguage is null)
        {
            await LoadPageAsync("language", cancellationToken);
            ModelState.AddModelError(nameof(UiLanguage), L("language.form.required"));
            return Page();
        }

        var settings = await settingsStore.LoadAsync(cancellationToken);
        settings.UiLanguage = normalizedLanguage;
        settings.LanguageSelected = true;
        await settingsStore.SaveAsync(settings, cancellationToken: cancellationToken);

        return RedirectToPage(new { step = "compute", lang = normalizedLanguage });
    }

    public async Task<IActionResult> OnPostComputeAsync(CancellationToken cancellationToken)
    {
        WorkerCapability = await workerCapabilityService.GetAsync(cancellationToken);
        var normalizedMode = ComputeMode.Trim().ToLowerInvariant() == "gpu" ? "gpu" : "cpu";
        if (normalizedMode == "gpu" && !WorkerCapability.GpuAvailable)
        {
            await LoadPageAsync("compute", cancellationToken);
            ModelState.AddModelError(nameof(ComputeMode), L("settings.compute_mode.gpu_unavailable"));
            return Page();
        }

        var settings = await settingsStore.LoadAsync(cancellationToken);
        settings.ComputeMode = normalizedMode;
        settings.SetupComputeModeSelected = true;
        await settingsStore.SaveAsync(settings, cancellationToken: cancellationToken);

        return RedirectToPage(new { step = "account", lang = settings.UiLanguage });
    }

    public IActionResult OnPostAccount(string answer)
    {
        return RedirectToPage(new
        {
            step = string.Equals(answer, "no", StringComparison.OrdinalIgnoreCase) ? "register" : "token",
            lang = languageService.Resolve(Request),
        });
    }

    public IActionResult OnPostRegisterDone()
    {
        return RedirectToPage(new { step = "token", lang = languageService.Resolve(Request) });
    }

    public async Task<IActionResult> OnPostTokenAsync(CancellationToken cancellationToken)
    {
        var submittedToken = Token?.Trim();
        if (string.IsNullOrWhiteSpace(submittedToken))
        {
            await LoadPageAsync("token", cancellationToken);
            ModelState.AddModelError(nameof(Token), L("settings.token_required"));
            return Page();
        }

        var settings = await settingsStore.LoadAsync(cancellationToken);
        settings.HuggingfaceTermsConfirmed = false;
        await settingsStore.SaveAsync(
            settings,
            submittedToken,
            replaceToken: true,
            cancellationToken: cancellationToken);

        AccessSnapshot = await accessService.GetSnapshotAsync(cancellationToken);
        if (string.Equals(AccessSnapshot.AccessState, "authorized", StringComparison.OrdinalIgnoreCase))
        {
            settings = await settingsStore.LoadAsync(cancellationToken);
            settings.HuggingfaceTermsConfirmed = HasPyannoteAccess(AccessSnapshot);
            await settingsStore.SaveAsync(settings, cancellationToken: cancellationToken);
            return RedirectToPage(new { step = "complete", lang = settings.UiLanguage });
        }

        if (string.Equals(AccessSnapshot.AccessState, "approval_required", StringComparison.OrdinalIgnoreCase))
        {
            await LoadPageAsync("approval", cancellationToken);
            return Page();
        }

        await LoadPageAsync("token", cancellationToken);
        var key = string.Equals(AccessSnapshot.AccessState, "invalid_token", StringComparison.OrdinalIgnoreCase)
            ? "setup.token.invalid"
            : "setup.token.check_failed";
        ModelState.AddModelError(nameof(Token), L(key));
        return Page();
    }

    public async Task<IActionResult> OnPostCheckApprovalAsync(CancellationToken cancellationToken)
    {
        AccessSnapshot = await accessService.GetSnapshotAsync(cancellationToken);
        if (string.Equals(AccessSnapshot.AccessState, "authorized", StringComparison.OrdinalIgnoreCase))
        {
            var settings = await settingsStore.LoadAsync(cancellationToken);
            settings.HuggingfaceTermsConfirmed = HasPyannoteAccess(AccessSnapshot);
            await settingsStore.SaveAsync(settings, cancellationToken: cancellationToken);
            return RedirectToPage(new { step = "complete", lang = settings.UiLanguage });
        }

        await LoadPageAsync("approval", cancellationToken);
        ModelState.AddModelError(string.Empty, L("setup.approval.not_ready"));
        return Page();
    }

    private async Task LoadPageAsync(string? requestedStep, CancellationToken cancellationToken)
    {
        SetupState = await setupStateService.GetAsync(cancellationToken);
        WorkerCapability = await workerCapabilityService.GetAsync(cancellationToken);
        AccessSnapshot = await accessService.GetSnapshotAsync(cancellationToken);
        SupportedLanguages = languageService.GetSupportedLanguages();

        var settings = await settingsStore.LoadAsync(cancellationToken);
        UiLanguage = languageService.Normalize(settings.UiLanguage) ?? "en";
        ComputeMode = ResolveComputeMode(settings.ComputeMode);
        Token = string.Empty;
        Step = NormalizeStep(requestedStep, settings);
    }

    private string ResolveComputeMode(string? savedMode)
    {
        if (!SetupState.HasSelectedComputeMode && WorkerCapability.GpuAvailable)
        {
            return "gpu";
        }

        var preferred = savedMode?.Trim().ToLowerInvariant() == "gpu" ? "gpu" : "cpu";
        if (preferred == "gpu" && !WorkerCapability.GpuAvailable)
        {
            return "cpu";
        }

        return preferred;
    }

    private string NormalizeStep(string? requestedStep, AppSettingsDocument settings)
    {
        if (!settings.LanguageSelected)
        {
            return "language";
        }

        if (!settings.SetupComputeModeSelected)
        {
            return "compute";
        }

        if (SetupState.IsReady)
        {
            return "complete";
        }

        var normalized = requestedStep?.Trim().ToLowerInvariant();
        return normalized switch
        {
            "account" or "register" or "token" or "approval" => normalized,
            _ => AccessSnapshot.AccessState switch
            {
                "approval_required" => "approval",
                "invalid_token" or "unknown" => "token",
                _ when !SetupState.HasToken => "account",
                _ => "token",
            },
        };
    }

    private static bool HasPyannoteAccess(HuggingFaceAccessSnapshot snapshot) =>
        snapshot.Models.Any(static model =>
            string.Equals(model.ModelId, PyannoteModelId, StringComparison.OrdinalIgnoreCase) &&
            string.Equals(model.AccessState, "authorized", StringComparison.OrdinalIgnoreCase));

    private string L(string key) => localizer.Get(languageService.Resolve(Request), key);
}
