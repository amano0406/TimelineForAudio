namespace Audio2Timeline.Web.Services;

public sealed class AppPaths(IConfiguration configuration)
{
    public string RuntimeDefaultsPath { get; } =
        configuration["AUDIO2TIMELINE_RUNTIME_DEFAULTS"] ?? "/app/config/runtime.defaults.json";

    public string AppDataRoot { get; } =
        configuration["AUDIO2TIMELINE_APPDATA_ROOT"] ?? "/shared/app-data";

    public string UploadsRoot { get; } =
        configuration["AUDIO2TIMELINE_UPLOADS_ROOT"] ?? "/shared/uploads";

    public string OutputsRoot { get; } =
        configuration["AUDIO2TIMELINE_OUTPUTS_ROOT"] ??
        Path.Combine(configuration["AUDIO2TIMELINE_APPDATA_ROOT"] ?? "/shared/app-data", "outputs");

    public string HuggingFaceCacheRoot { get; } =
        configuration["AUDIO2TIMELINE_HF_CACHE_ROOT"] ?? "/cache/huggingface";

    public string TorchCacheRoot { get; } =
        configuration["AUDIO2TIMELINE_TORCH_CACHE_ROOT"] ?? "/cache/torch";

    public string SettingsPath => Path.Combine(AppDataRoot, "settings.json");

    public string TokenPath => Path.Combine(AppDataRoot, "secrets", "huggingface.token");

    public string DownloadsRoot => Path.Combine(AppDataRoot, "downloads");

    public string WorkerCapabilitiesPath => Path.Combine(AppDataRoot, "worker-capabilities.json");
}
