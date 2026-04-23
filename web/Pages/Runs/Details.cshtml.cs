using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using TimelineForAudio.Web.Infrastructure;
using TimelineForAudio.Web.Models;
using TimelineForAudio.Web.Services;

namespace TimelineForAudio.Web.Pages.Runs;

public sealed class DetailsModel(
    RunStore runStore,
    LanguageService languageService,
    JsonLocalizationService localizer) : PageModel
{
    public RunDetails? Run { get; private set; }
    public ConversionInfoPreview? ConversionInfoPreview { get; private set; }
    public string? StatusMessage { get; private set; }

    public async Task<IActionResult> OnGetAsync(string id, CancellationToken cancellationToken)
    {
        Run = await runStore.GetRunDetailsAsync(id, cancellationToken);
        PopulateDerivedState();
        return Run is null ? NotFound() : Page();
    }

    public async Task<IActionResult> OnPostRerunAsync(string id, string mode, CancellationToken cancellationToken)
    {
        if (!string.Equals(mode, "original", StringComparison.OrdinalIgnoreCase) &&
            !string.Equals(mode, "current", StringComparison.OrdinalIgnoreCase))
        {
            return BadRequest();
        }

        try
        {
            var created = await runStore.CreateJobFromExistingAsync(
                id,
                useCurrentSettings: string.Equals(mode, "current", StringComparison.OrdinalIgnoreCase),
                cancellationToken);
            return Redirect(JobUrls.Details(created.JobId));
        }
        catch (InvalidOperationException ex)
        {
            StatusMessage = KnownMessageLocalizer.Localize(ex.Message, key => localizer.Get(languageService.Resolve(Request), key));
            Run = await runStore.GetRunDetailsAsync(id, cancellationToken);
            PopulateDerivedState();
            return Run is null ? NotFound() : Page();
        }
    }

    private void PopulateDerivedState()
    {
        ConversionInfoPreview = ParseConversionInfo(Run?.ConversionInfoText);
    }

    private static ConversionInfoPreview? ParseConversionInfo(string? markdown)
    {
        if (string.IsNullOrWhiteSpace(markdown))
        {
            return null;
        }

        var fields = new List<ConversionInfoField>();
        var notes = new List<string>();
        var paragraphs = new List<string>();
        var notesHeading = "Notes";
        ConversionInfoField? lastField = null;
        var inNotes = false;

        foreach (var rawLine in markdown.Replace("\r\n", "\n", StringComparison.Ordinal).Split('\n'))
        {
            var line = rawLine.TrimEnd();
            var trimmed = line.Trim();
            if (trimmed.Length == 0)
            {
                continue;
            }

            if (trimmed.StartsWith("#", StringComparison.Ordinal))
            {
                continue;
            }

            var bulletCandidate = line.TrimStart();
            if (bulletCandidate.StartsWith("- ", StringComparison.Ordinal))
            {
                var content = bulletCandidate[2..].Trim();
                if (content.Length == 0)
                {
                    continue;
                }

                if (string.Equals(content, "Notes:", StringComparison.OrdinalIgnoreCase))
                {
                    notesHeading = CleanMarkdownText(content.TrimEnd(':'));
                    inNotes = true;
                    lastField = null;
                    continue;
                }

                if (!inNotes)
                {
                    var separatorIndex = content.IndexOf(':');
                    if (separatorIndex > 0)
                    {
                        var field = new ConversionInfoField(
                            CleanMarkdownText(content[..separatorIndex]),
                            CleanMarkdownText(content[(separatorIndex + 1)..]));
                        fields.Add(field);
                        lastField = field;
                        continue;
                    }
                }

                notes.Add(CleanMarkdownText(content));
                lastField = null;
                continue;
            }

            if (lastField is not null &&
                (line.StartsWith("  ", StringComparison.Ordinal) || line.StartsWith("\t", StringComparison.Ordinal)))
            {
                lastField.AppendValue(CleanMarkdownText(trimmed));
                continue;
            }

            paragraphs.Add(CleanMarkdownText(trimmed));
            lastField = null;
            inNotes = false;
        }

        return fields.Count == 0 && notes.Count == 0 && paragraphs.Count == 0
            ? null
            : new ConversionInfoPreview(fields, notes, paragraphs, notesHeading);
    }

    private static string CleanMarkdownText(string value)
    {
        var cleaned = value.Replace("`", string.Empty, StringComparison.Ordinal).Trim();
        return string.Join(" ", cleaned.Split([' ', '\t'], StringSplitOptions.RemoveEmptyEntries));
    }
}

public sealed class ConversionInfoPreview(
    IReadOnlyList<ConversionInfoField> fields,
    IReadOnlyList<string> notes,
    IReadOnlyList<string> paragraphs,
    string notesHeading)
{
    public IReadOnlyList<ConversionInfoField> Fields { get; } = fields;
    public IReadOnlyList<string> Notes { get; } = notes;
    public IReadOnlyList<string> Paragraphs { get; } = paragraphs;
    public string NotesHeading { get; } = string.IsNullOrWhiteSpace(notesHeading) ? "Notes" : notesHeading;
}

public sealed class ConversionInfoField(string label, string value)
{
    public string Label { get; } = label;
    public string Value { get; private set; } = value;

    public void AppendValue(string extra)
    {
        if (string.IsNullOrWhiteSpace(extra))
        {
            return;
        }

        Value = string.IsNullOrWhiteSpace(Value)
            ? extra
            : $"{Value} {extra}";
    }
}
