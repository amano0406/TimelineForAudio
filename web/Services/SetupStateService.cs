using Audio2Timeline.Web.Models;

namespace Audio2Timeline.Web.Services;

public sealed class SetupStateService(SettingsStore settingsStore)
{
    public async Task<SetupState> GetAsync(CancellationToken cancellationToken = default)
    {
        var settings = await settingsStore.LoadAsync(cancellationToken);
        var hasToken = await settingsStore.HasTokenAsync(cancellationToken);
        return new SetupState
        {
            HasSelectedLanguage = settings.LanguageSelected,
            HasToken = hasToken,
            TermsConfirmed = settings.HuggingfaceTermsConfirmed,
        };
    }
}
