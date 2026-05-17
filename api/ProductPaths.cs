namespace TimelineForAudio.Api;

public sealed class ProductPaths
{
    public ProductPaths(string productRoot, string? settingsPath = null)
    {
        ProductRoot = Path.GetFullPath(productRoot);
        SettingsPath = Path.GetFullPath(
            string.IsNullOrWhiteSpace(settingsPath)
                ? Path.Combine(ProductRoot, "settings.json")
                : settingsPath);
        SettingsExamplePath = Path.Combine(ProductRoot, "settings.example.json");
        DockerComposePath = Path.Combine(ProductRoot, "docker-compose.yml");
        DockerComposeGpuPath = Path.Combine(ProductRoot, "docker-compose.gpu.yml");
        DockerPathsOverridePath = Path.Combine(ProductRoot, ".docker", "docker-compose.paths.yml");
    }

    public string ProductRoot { get; }

    public string SettingsPath { get; }

    public string SettingsExamplePath { get; }

    public string DockerComposePath { get; }

    public string DockerComposeGpuPath { get; }

    public string DockerPathsOverridePath { get; }

    public static ProductPaths Resolve(string[] args)
    {
        var explicitRoot = ArgValue(args, "--product-root")
            ?? Environment.GetEnvironmentVariable("TIMELINE_FOR_AUDIO_ROOT");
        var explicitSettings = ArgValue(args, "--settings-path")
            ?? Environment.GetEnvironmentVariable("TIMELINE_FOR_AUDIO_HOST_SETTINGS_PATH")
            ?? Environment.GetEnvironmentVariable("TIMELINE_FOR_AUDIO_SETTINGS_PATH");

        if (!string.IsNullOrWhiteSpace(explicitRoot))
        {
            return new ProductPaths(explicitRoot, explicitSettings);
        }

        var current = AppContext.BaseDirectory;
        for (var directory = new DirectoryInfo(current); directory is not null; directory = directory.Parent)
        {
            if (File.Exists(Path.Combine(directory.FullName, "docker-compose.yml"))
                && Directory.Exists(Path.Combine(directory.FullName, "worker")))
            {
                return new ProductPaths(directory.FullName, explicitSettings);
            }
        }

        return new ProductPaths(Directory.GetCurrentDirectory(), explicitSettings);
    }

    public static string? ArgValue(string[] args, string name)
    {
        for (var index = 0; index < args.Length; index++)
        {
            if (string.Equals(args[index], name, StringComparison.OrdinalIgnoreCase) && index + 1 < args.Length)
            {
                return args[index + 1];
            }

            var prefix = name + "=";
            if (args[index].StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            {
                return args[index][prefix.Length..];
            }
        }

        return null;
    }
}
