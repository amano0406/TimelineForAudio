using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using TimelineForAudio.Web.Infrastructure;
using TimelineForAudio.Web.Models;
using TimelineForAudio.Web.Services;

namespace TimelineForAudio.Web.Pages;

public sealed class SettingsModel(
    HuggingFaceAccessService accessService,
    ModelCacheService modelCacheService,
    SettingsStore settingsStore,
    SetupStateService setupStateService,
    WorkerCapabilityService workerCapabilityService,
    LanguageService languageService,
    JsonLocalizationService localizer) : PageModel
{
    public HuggingFaceAccessSnapshot Snapshot { get; private set; } = new();

    public SetupState SetupState { get; private set; } = new();

    public IReadOnlyList<GatedModelStatusItem> ModelStatuses { get; private set; } = [];

    public ModelCacheSnapshot ModelCache { get; private set; } = new();

    public WorkerCapabilitySnapshot WorkerCapability { get; private set; } = new();

    [BindProperty]
    public string Token { get; set; } = "";

    [BindProperty]
    public string ComputeMode { get; set; } = "cpu";

    [BindProperty]
    public string ProcessingQuality { get; set; } = "standard";

    [BindProperty]
    public string UiLanguage { get; set; } = "en";

    public string? StatusMessage { get; private set; }

    public string TokenSettingsUrl => "https://huggingface.co/settings/tokens";

    public string PyannoteModelUrl => "https://huggingface.co/pyannote/speaker-diarization-community-1";

    public bool IsGpuHighQualityRecommended =>
        WorkerCapability.GpuAvailable &&
        (WorkerCapability.MaxGpuMemoryGiB <= 0 || WorkerCapability.MaxGpuMemoryGiB >= RuntimeProfile.HighQualityRecommendedGpuMemoryGiB);

    public bool IsGpuHighQualityExperimental =>
        WorkerCapability.GpuAvailable &&
        WorkerCapability.MaxGpuMemoryGiB >= RuntimeProfile.HighQualityWarningGpuMemoryGiB &&
        WorkerCapability.MaxGpuMemoryGiB < RuntimeProfile.HighQualityRecommendedGpuMemoryGiB;

    public bool IsGpuHighQualityLowMemory =>
        WorkerCapability.GpuAvailable &&
        WorkerCapability.MaxGpuMemoryGiB > 0 &&
        WorkerCapability.MaxGpuMemoryGiB < RuntimeProfile.HighQualityWarningGpuMemoryGiB;

    public async Task OnGetAsync(CancellationToken cancellationToken)
    {
        await LoadPageAsync(cancellationToken);
    }

    public async Task<IActionResult> OnPostSaveAsync(CancellationToken cancellationToken)
    {
        WorkerCapability = await workerCapabilityService.GetAsync(cancellationToken);
        if (string.Equals(ComputeMode, "gpu", StringComparison.OrdinalIgnoreCase) && !WorkerCapability.GpuAvailable)
        {
            ModelState.AddModelError(nameof(ComputeMode), L("settings.compute_mode.gpu_unavailable"));
        }

        if (!ModelState.IsValid)
        {
            await LoadPageAsync(cancellationToken);
            StatusMessage = L("settings.save_blocked");
            return Page();
        }

        var settings = await settingsStore.LoadAsync(cancellationToken);
        settings.ComputeMode = ComputeMode;
        settings.ProcessingQuality = ProcessingQuality;
        settings.UiLanguage = languageService.Normalize(UiLanguage) ?? "en";
        settings.LanguageSelected = true;
        settings.HuggingfaceTermsConfirmed = false;
        await settingsStore.SaveAsync(
            settings,
            string.IsNullOrWhiteSpace(Token) ? null : Token,
            replaceToken: !string.IsNullOrWhiteSpace(Token),
            cancellationToken: cancellationToken);

        Snapshot = await accessService.GetSnapshotAsync(cancellationToken);
        settings.HuggingfaceTermsConfirmed = Snapshot.Models.Any(static model =>
            string.Equals(model.ModelId, "pyannote/speaker-diarization-community-1", StringComparison.OrdinalIgnoreCase) &&
            string.Equals(model.AccessState, "authorized", StringComparison.OrdinalIgnoreCase));
        await settingsStore.SaveAsync(settings, cancellationToken: cancellationToken);

        await LoadPageAsync(cancellationToken);
        TempData["StatusMessage"] = L("settings.save_success");
        return RedirectToPage("/Jobs/New");
    }

    public async Task<IActionResult> OnPostClearModelCacheAsync(CancellationToken cancellationToken)
    {
        var cleared = await modelCacheService.ClearAsync(cancellationToken);
        TempData["StatusMessage"] = cleared > 0
            ? L("settings.cache.cleared")
            : L("settings.cache.empty");
        return RedirectToPage();
    }

    private async Task LoadPageAsync(CancellationToken cancellationToken)
    {
        Snapshot = await accessService.GetSnapshotAsync(cancellationToken);
        SetupState = await setupStateService.GetAsync(cancellationToken);
        ModelStatuses = Snapshot.Models;
        ModelCache = await modelCacheService.GetSnapshotAsync(cancellationToken);
        WorkerCapability = await workerCapabilityService.GetAsync(cancellationToken);
        Token = "";
        var settings = await settingsStore.LoadAsync(cancellationToken);
        ComputeMode = settings.ComputeMode;
        if (!WorkerCapability.GpuAvailable && string.Equals(ComputeMode, "gpu", StringComparison.OrdinalIgnoreCase))
        {
            ComputeMode = "cpu";
        }
        ProcessingQuality = settings.ProcessingQuality;
        UiLanguage = languageService.Normalize(settings.UiLanguage) ?? "en";
        StatusMessage ??= TempData["StatusMessage"] as string;
    }

    private string L(string key) => localizer.Get(languageService.Resolve(Request), key);
}
