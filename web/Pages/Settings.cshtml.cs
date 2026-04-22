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
    private const string LegacyMaskedTokenValue = "hf_saved_token_masked";
    private const string DisplayMaskedTokenValue = "••••••••••••••••";

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
    public string UiLanguage { get; set; } = "en";

    public bool HasSavedTokenConfigured { get; private set; }

    public bool HasPersistedSettings { get; private set; }

    public bool SavedGpuPreferenceUnavailable { get; private set; }

    public string TokenMaskValue => DisplayMaskedTokenValue;

    public string TokenPreview { get; private set; } = string.Empty;

    public bool ShowTokenEditor { get; private set; }

    public string? StatusMessage { get; private set; }

    public string TokenSettingsUrl => "https://huggingface.co/settings/tokens";

    public string PyannoteModelUrl => "https://huggingface.co/pyannote/speaker-diarization-community-1";

    public async Task OnGetAsync(CancellationToken cancellationToken)
    {
        await LoadPageAsync(cancellationToken);
    }

    public async Task<IActionResult> OnPostSaveAsync(CancellationToken cancellationToken)
    {
        WorkerCapability = await workerCapabilityService.GetAsync(cancellationToken);
        var hasSavedTokenConfigured = await settingsStore.HasTokenAsync(cancellationToken);
        var submittedToken = Token?.Trim();
        if (string.Equals(ComputeMode, "gpu", StringComparison.OrdinalIgnoreCase) && !WorkerCapability.GpuAvailable)
        {
            ModelState.AddModelError(nameof(ComputeMode), L("settings.compute_mode.gpu_unavailable"));
        }

        if (!ModelState.IsValid)
        {
            await LoadPageAsync(cancellationToken);
            if (!string.IsNullOrWhiteSpace(submittedToken))
            {
                Token = submittedToken;
                ShowTokenEditor = true;
            }
            StatusMessage = L("settings.save_blocked");
            return Page();
        }

        var settings = await settingsStore.LoadAsync(cancellationToken);
        settings.ComputeMode = ComputeMode;
        settings.UiLanguage = languageService.Normalize(UiLanguage) ?? "en";
        settings.LanguageSelected = true;
        settings.HuggingfaceTermsConfirmed = false;
        var replaceToken =
            !string.IsNullOrWhiteSpace(submittedToken) &&
            !(hasSavedTokenConfigured && (
                string.Equals(submittedToken, LegacyMaskedTokenValue, StringComparison.Ordinal) ||
                string.Equals(submittedToken, DisplayMaskedTokenValue, StringComparison.Ordinal)));
        await settingsStore.SaveAsync(
            settings,
            replaceToken ? submittedToken : null,
            replaceToken: replaceToken,
            cancellationToken: cancellationToken);

        Snapshot = await accessService.GetSnapshotAsync(cancellationToken);
        settings.HuggingfaceTermsConfirmed = Snapshot.Models.Any(static model =>
            string.Equals(model.ModelId, "pyannote/speaker-diarization-community-1", StringComparison.OrdinalIgnoreCase) &&
            string.Equals(model.AccessState, "authorized", StringComparison.OrdinalIgnoreCase));
        await settingsStore.SaveAsync(settings, cancellationToken: cancellationToken);

        TempData["StatusMessage"] = Snapshot.AccessState switch
        {
            "authorized" => L("settings.save_success"),
            "approval_required" => L("settings.save_pending"),
            "invalid_token" => L("settings.save_invalid_token"),
            "unknown" => L("settings.save_check"),
            _ => L("settings.save_success"),
        };
        return RedirectToPage(new { lang = settings.UiLanguage });
    }

    public async Task<IActionResult> OnPostClearModelCacheAsync(CancellationToken cancellationToken)
    {
        var cleared = await modelCacheService.ClearAsync(cancellationToken);
        TempData["StatusMessage"] = cleared > 0
            ? L("settings.cache.cleared")
            : L("settings.cache.empty");
        return RedirectToPage(new { lang = languageService.Resolve(Request) });
    }

    public async Task<IActionResult> OnPostResetAppAsync(CancellationToken cancellationToken)
    {
        var normalizedLanguage = languageService.Resolve(Request);
        WorkerCapability = await workerCapabilityService.GetAsync(cancellationToken);
        var defaultComputeMode = WorkerCapability.GpuAvailable ? "gpu" : "cpu";

        await modelCacheService.ClearAsync(cancellationToken);
        await settingsStore.SaveAsync(
            new AppSettingsDocument
            {
                UiLanguage = normalizedLanguage,
                LanguageSelected = true,
                ComputeMode = defaultComputeMode,
                HuggingfaceTermsConfirmed = false,
            },
            token: null,
            replaceToken: true,
            cancellationToken: cancellationToken);

        TempData["StatusMessage"] = L("settings.maintenance.reset_done");
        return RedirectToPage(new { lang = normalizedLanguage });
    }

    private async Task LoadPageAsync(CancellationToken cancellationToken)
    {
        Snapshot = await accessService.GetSnapshotAsync(cancellationToken);
        SetupState = await setupStateService.GetAsync(cancellationToken);
        ModelStatuses = Snapshot.Models;
        ModelCache = await modelCacheService.GetSnapshotAsync(cancellationToken);
        WorkerCapability = await workerCapabilityService.GetAsync(cancellationToken);
        HasSavedTokenConfigured = Snapshot.HasToken;
        var savedToken = HasSavedTokenConfigured
            ? await settingsStore.ReadTokenAsync(cancellationToken)
            : null;
        Token = string.Empty;
        TokenPreview = CreateTokenPreview(savedToken);
        ShowTokenEditor = !HasSavedTokenConfigured;
        var settings = await settingsStore.LoadAsync(cancellationToken);
        HasPersistedSettings = await settingsStore.HasPersistedSettingsAsync(cancellationToken);
        SavedGpuPreferenceUnavailable = HasPersistedSettings &&
            string.Equals(settings.ComputeMode, "gpu", StringComparison.OrdinalIgnoreCase) &&
            !WorkerCapability.GpuAvailable;

        ComputeMode = HasPersistedSettings
            ? settings.ComputeMode
            : (WorkerCapability.GpuAvailable ? "gpu" : "cpu");

        if (!WorkerCapability.GpuAvailable && string.Equals(ComputeMode, "gpu", StringComparison.OrdinalIgnoreCase))
        {
            ComputeMode = "cpu";
        }
        UiLanguage = languageService.Normalize(settings.UiLanguage) ?? "en";
        StatusMessage ??= TempData["StatusMessage"] as string;
    }

    private static string CreateTokenPreview(string? token)
    {
        if (string.IsNullOrWhiteSpace(token))
        {
            return string.Empty;
        }

        var trimmed = token.Trim();
        if (trimmed.Length <= 8)
        {
            return $"{trimmed[..Math.Min(2, trimmed.Length)]}••••••••{trimmed[^Math.Min(2, trimmed.Length)..]}";
        }

        return $"{trimmed[..4]}••••••••{trimmed[^4..]}";
    }

    private string L(string key) => localizer.Get(languageService.Resolve(Request), key);
}
