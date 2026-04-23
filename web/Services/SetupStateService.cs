using TimelineForAudio.Web.Models;

namespace TimelineForAudio.Web.Services;

public sealed class SetupStateService(SettingsStore settingsStore, RunStore runStore)
{
    public async Task<SetupState> GetAsync(CancellationToken cancellationToken = default)
    {
        var settings = await settingsStore.LoadAsync(cancellationToken);
        var hasToken = await settingsStore.HasTokenAsync(cancellationToken);
        var hasJobs = await runStore.HasAnyRunsAsync(cancellationToken);
        return new SetupState
        {
            HasSelectedLanguage = settings.LanguageSelected,
            HasSelectedComputeMode = settings.SetupComputeModeSelected ||
                (settings.LanguageSelected && hasToken && settings.HuggingfaceTermsConfirmed),
            HasToken = hasToken,
            TermsConfirmed = settings.HuggingfaceTermsConfirmed,
            HasJobs = hasJobs,
        };
    }
}
