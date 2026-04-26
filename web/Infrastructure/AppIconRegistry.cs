namespace TimelineForAudio.Web.Infrastructure;

public sealed record AppIconDefinition(string SpritePath, string SymbolId);

public static class AppIconRegistry
{
    public const string SpritePath = "/lib/icons/lucide/lucide.svg";

    public static AppIconDefinition Resolve(string alias)
    {
        var symbolId = alias switch
        {
            AppIcons.NavNewJob => "plus",
            AppIcons.NavJobs => "list",
            AppIcons.NavSettings => "settings-2",
            AppIcons.ChooseFiles => "audio-lines",
            AppIcons.ChooseFolder => "folder-open",
            AppIcons.StartConversion => "play",
            AppIcons.OpenDetails => "eye",
            AppIcons.Download => "download",
            AppIcons.Copy => "copy",
            AppIcons.Delete => "trash-2",
            AppIcons.Help => "circle-question-mark",
            AppIcons.MoreActions => "ellipsis",
            AppIcons.OpenExternal => "external-link",
            AppIcons.Previous => "chevron-left",
            AppIcons.Next => "chevron-right",
            AppIcons.Expand => "chevron-down",
            AppIcons.Save => "save",
            AppIcons.StatusReady => "circle-check-big",
            _ => "circle-question-mark",
        };

        return new AppIconDefinition(SpritePath, symbolId);
    }
}
