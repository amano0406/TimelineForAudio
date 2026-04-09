namespace TimelineForAudio.Web.Services;

public sealed class AppPaths(IConfiguration configuration)
{
    public string RuntimeDefaultsPath { get; } =
        configuration["TIMELINE_FOR_AUDIO_RUNTIME_DEFAULTS"] ?? "/app/config/runtime.defaults.json";

    public string AppDataRoot { get; } =
        configuration["TIMELINE_FOR_AUDIO_APPDATA_ROOT"] ?? "/shared/app-data";

    public string UploadsRoot { get; } =
        configuration["TIMELINE_FOR_AUDIO_UPLOADS_ROOT"] ?? "/shared/uploads";

    public string OutputsRoot { get; } =
        configuration["TIMELINE_FOR_AUDIO_OUTPUTS_ROOT"] ??
        Path.Combine(configuration["TIMELINE_FOR_AUDIO_APPDATA_ROOT"] ?? "/shared/app-data", "outputs");

    public string HuggingFaceCacheRoot { get; } =
        configuration["TIMELINE_FOR_AUDIO_HF_CACHE_ROOT"] ?? "/cache/huggingface";

    public string TorchCacheRoot { get; } =
        configuration["TIMELINE_FOR_AUDIO_TORCH_CACHE_ROOT"] ?? "/cache/torch";

    public string SettingsPath => Path.Combine(AppDataRoot, "settings.json");

    public string TokenPath => Path.Combine(AppDataRoot, "secrets", "huggingface.token");

    public string DownloadsRoot => Path.Combine(AppDataRoot, "downloads");

    public string WorkerCapabilitiesPath => Path.Combine(AppDataRoot, "worker-capabilities.json");
}
