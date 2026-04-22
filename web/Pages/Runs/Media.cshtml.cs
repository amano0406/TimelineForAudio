using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using TimelineForAudio.Web.Models;
using TimelineForAudio.Web.Services;

namespace TimelineForAudio.Web.Pages.Runs;

public sealed class MediaModel(RunStore runStore) : PageModel
{
    public string JobId { get; private set; } = "";
    public string MediaId { get; private set; } = "";
    public string FileName { get; private set; } = "";
    public string ArtifactText { get; private set; } = "";
    public string PrimaryArtifactKind { get; private set; } = "";
    public string SelectedArtifactKind { get; private set; } = "";
    public bool HasIpaArtifact { get; private set; }
    public bool HasReadableTextArtifact { get; private set; }
    public int? SpeakerCount { get; private set; }
    public string? SpeakerCountStatus { get; private set; }
    public string? SpeakerCountNote { get; private set; }
    public IReadOnlyList<ArtifactConversationBlock> PreviewBlocks { get; private set; } = [];

    public async Task<IActionResult> OnGetAsync(
        string jobId,
        string mediaId,
        string? artifact,
        CancellationToken cancellationToken)
    {
        var mediaItem = await runStore.GetMediaArtifactItemAsync(jobId, mediaId, cancellationToken);
        if (mediaItem is null)
        {
            return NotFound();
        }

        var selectedArtifact = NormalizeArtifactKind(artifact, mediaItem);
        var artifactText = await runStore.ReadArtifactAsync(jobId, mediaId, selectedArtifact, cancellationToken);
        if (artifactText is null)
        {
            return NotFound();
        }

        JobId = jobId;
        MediaId = mediaId;
        FileName = string.IsNullOrWhiteSpace(mediaItem.FileName) ? mediaId : mediaItem.FileName;
        ArtifactText = artifactText;
        PrimaryArtifactKind = mediaItem.PrimaryArtifactKind;
        SelectedArtifactKind = selectedArtifact;
        HasIpaArtifact = !string.IsNullOrWhiteSpace(mediaItem.IpaPath);
        HasReadableTextArtifact = !string.IsNullOrWhiteSpace(mediaItem.ReadableTextPath);
        SpeakerCount = mediaItem.SpeakerCount;
        SpeakerCountStatus = mediaItem.SpeakerCountStatus;
        SpeakerCountNote = mediaItem.SpeakerCountNote;
        PreviewBlocks = BuildPreviewBlocks(artifactText, selectedArtifact);
        return Page();
    }

    private static string NormalizeArtifactKind(string? artifact, MediaArtifactItem mediaItem)
    {
        var normalized = (artifact ?? string.Empty).Trim().ToLowerInvariant();
        if ((normalized == "ipa") && !string.IsNullOrWhiteSpace(mediaItem.IpaPath))
        {
            return "ipa";
        }

        if ((normalized == "readable-text" || normalized == "readable_text" || normalized == "readable") &&
            !string.IsNullOrWhiteSpace(mediaItem.ReadableTextPath))
        {
            return "readable-text";
        }

        if (!string.IsNullOrWhiteSpace(mediaItem.ReadableTextPath))
        {
            return "readable-text";
        }

        if (!string.IsNullOrWhiteSpace(mediaItem.IpaPath))
        {
            return "ipa";
        }

        return mediaItem.PrimaryArtifactKind;
    }

    private static IReadOnlyList<ArtifactConversationBlock> BuildPreviewBlocks(string artifactText, string artifactKind)
    {
        if (string.IsNullOrWhiteSpace(artifactText))
        {
            return [];
        }

        var turns = ParseTurns(artifactText);
        if (turns.Count == 0)
        {
            return [];
        }

        var isIpa = string.Equals(artifactKind, "ipa", StringComparison.OrdinalIgnoreCase);
        var speakerOrder = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        var blocks = new List<ArtifactConversationBlock>();

        foreach (var turn in turns)
        {
            if (string.IsNullOrWhiteSpace(turn.Content))
            {
                continue;
            }

            var speaker = string.IsNullOrWhiteSpace(turn.Speaker) ? "Speaker" : turn.Speaker.Trim();
            if (!speakerOrder.ContainsKey(speaker))
            {
                speakerOrder[speaker] = speakerOrder.Count;
            }

            var alignment = speakerOrder[speaker] % 2 == 0 ? "left" : "right";
            if (blocks.Count > 0 &&
                string.Equals(blocks[^1].Speaker, speaker, StringComparison.OrdinalIgnoreCase))
            {
                blocks[^1].Content = string.Concat(blocks[^1].Content, "\n", turn.Content.Trim());
                continue;
            }

            blocks.Add(new ArtifactConversationBlock
            {
                Speaker = speaker,
                Content = turn.Content.Trim(),
                Alignment = alignment,
                IsIpa = isIpa,
            });
        }

        return blocks;
    }

    private static List<ParsedArtifactTurn> ParseTurns(string artifactText)
    {
        var turns = new List<ParsedArtifactTurn>();
        ParsedArtifactTurn? current = null;
        var lines = artifactText.Replace("\r\n", "\n", StringComparison.Ordinal).Split('\n');

        foreach (var rawLine in lines)
        {
            var line = rawLine.Trim();
            if (string.IsNullOrWhiteSpace(line))
            {
                continue;
            }

            if (line.StartsWith("### Turn ", StringComparison.Ordinal) ||
                line.StartsWith("## Turn ", StringComparison.Ordinal))
            {
                AddTurn(turns, current);
                current = new ParsedArtifactTurn();
                continue;
            }

            if (current is null)
            {
                continue;
            }

            if (line.StartsWith("Speaker:", StringComparison.Ordinal))
            {
                current.Speaker = ExtractInlineCodeValue(line);
                continue;
            }

            if (line.StartsWith("Text:", StringComparison.Ordinal))
            {
                current.Content = line["Text:".Length..].Trim();
                continue;
            }

            if (line.StartsWith("IPA:", StringComparison.Ordinal))
            {
                current.Content = line["IPA:".Length..].Trim();
                continue;
            }

            if (line.StartsWith("Time:", StringComparison.Ordinal))
            {
                continue;
            }

            if (!string.IsNullOrWhiteSpace(current.Content))
            {
                current.Content = string.Concat(current.Content, "\n", line);
            }
        }

        AddTurn(turns, current);
        return turns;
    }

    private static void AddTurn(ICollection<ParsedArtifactTurn> turns, ParsedArtifactTurn? turn)
    {
        if (turn is null || string.IsNullOrWhiteSpace(turn.Content))
        {
            return;
        }

        turns.Add(turn);
    }

    private static string ExtractInlineCodeValue(string line)
    {
        var firstTick = line.IndexOf('`');
        var lastTick = line.LastIndexOf('`');
        if (firstTick >= 0 && lastTick > firstTick)
        {
            return line[(firstTick + 1)..lastTick].Trim();
        }

        var separator = line.IndexOf(':');
        return separator >= 0 ? line[(separator + 1)..].Trim() : line.Trim();
    }

    public sealed class ArtifactConversationBlock
    {
        public string Speaker { get; set; } = "";
        public string Content { get; set; } = "";
        public string Alignment { get; set; } = "left";
        public bool IsIpa { get; set; }
    }

    private sealed class ParsedArtifactTurn
    {
        public string Speaker { get; set; } = "";
        public string Content { get; set; } = "";
    }
}
