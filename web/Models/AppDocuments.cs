using System.Text.Json.Serialization;

namespace TimelineForAudio.Web.Models;

public sealed class RootOption
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("displayName")]
    public string DisplayName { get; set; } = "";

    [JsonPropertyName("path")]
    public string Path { get; set; } = "";

    [JsonPropertyName("enabled")]
    public bool Enabled { get; set; } = true;
}

public sealed class AppSettingsDocument
{
    [JsonPropertyName("schemaVersion")]
    public int SchemaVersion { get; set; } = 1;

    [JsonPropertyName("inputRoots")]
    public List<RootOption> InputRoots { get; set; } = [];

    [JsonPropertyName("outputRoots")]
    public List<RootOption> OutputRoots { get; set; } = [];

    [JsonPropertyName("audioExtensions")]
    public List<string> AudioExtensions { get; set; } = [];

    [JsonIgnore]
    public List<string> VideoExtensions
    {
        get => AudioExtensions;
        set => AudioExtensions = value;
    }

    [JsonPropertyName("huggingfaceTermsConfirmed")]
    public bool HuggingfaceTermsConfirmed { get; set; }

    [JsonPropertyName("computeMode")]
    public string ComputeMode { get; set; } = "cpu";

    [JsonPropertyName("processingQuality")]
    public string ProcessingQuality { get; set; } = "standard";

    [JsonPropertyName("transcriptionInitialPrompt")]
    public string TranscriptionInitialPrompt { get; set; } = "";

    [JsonPropertyName("transcriptNormalizationMode")]
    public string TranscriptNormalizationMode { get; set; } = "deterministic";

    [JsonPropertyName("transcriptNormalizationGlossary")]
    public string TranscriptNormalizationGlossary { get; set; } = "";

    [JsonPropertyName("uiLanguage")]
    public string UiLanguage { get; set; } = "en";

    [JsonPropertyName("languageSelected")]
    public bool LanguageSelected { get; set; }
}

public sealed class UploadedFileReference
{
    [JsonPropertyName("referenceId")]
    public string ReferenceId { get; set; } = "";

    [JsonPropertyName("storedPath")]
    public string StoredPath { get; set; } = "";

    [JsonPropertyName("originalName")]
    public string OriginalName { get; set; } = "";

    [JsonPropertyName("sizeBytes")]
    public long SizeBytes { get; set; }
}

public sealed class UploadSessionDocument
{
    [JsonPropertyName("sessionId")]
    public string SessionId { get; set; } = "";

    [JsonPropertyName("createdAt")]
    public string CreatedAt { get; set; } = "";

    [JsonPropertyName("chunkSizeBytes")]
    public long ChunkSizeBytes { get; set; }

    [JsonPropertyName("files")]
    public List<UploadSessionFileDocument> Files { get; set; } = [];
}

public sealed class UploadSessionFileDocument
{
    [JsonPropertyName("fileId")]
    public string FileId { get; set; } = "";

    [JsonPropertyName("originalName")]
    public string OriginalName { get; set; } = "";

    [JsonPropertyName("sizeBytes")]
    public long SizeBytes { get; set; }

    [JsonPropertyName("expectedChunks")]
    public int ExpectedChunks { get; set; }

    [JsonPropertyName("uploadedChunks")]
    public int UploadedChunks { get; set; }

    [JsonPropertyName("storedPath")]
    public string StoredPath { get; set; } = "";
}

public sealed class CreateUploadSessionResponse
{
    [JsonPropertyName("sessionId")]
    public string SessionId { get; set; } = "";

    [JsonPropertyName("chunkSizeBytes")]
    public long ChunkSizeBytes { get; set; }
}

public sealed class CreateUploadFileRequest
{
    [JsonPropertyName("originalName")]
    public string OriginalName { get; set; } = "";

    [JsonPropertyName("sizeBytes")]
    public long SizeBytes { get; set; }
}

public sealed class CreateUploadFileResponse
{
    [JsonPropertyName("fileId")]
    public string FileId { get; set; } = "";

    [JsonPropertyName("expectedChunks")]
    public int ExpectedChunks { get; set; }
}

public sealed class ScanRequest
{
    [JsonPropertyName("sourceIds")]
    public List<string> SourceIds { get; set; } = [];
}

public sealed class CreateJobCommand
{
    [JsonPropertyName("sourceIds")]
    public List<string> SourceIds { get; set; } = [];

    [JsonPropertyName("selectedPaths")]
    public List<string> SelectedPaths { get; set; } = [];

    [JsonPropertyName("outputRootId")]
    public string OutputRootId { get; set; } = "runs";

    [JsonPropertyName("reprocessDuplicates")]
    public bool ReprocessDuplicates { get; set; }

    [JsonPropertyName("uploadedFiles")]
    public List<UploadedFileReference> UploadedFiles { get; set; } = [];
}

public sealed class DuplicatePreviewRequest
{
    [JsonPropertyName("outputRootId")]
    public string OutputRootId { get; set; } = "runs";

    [JsonPropertyName("uploadedFiles")]
    public List<UploadedFileReference> UploadedFiles { get; set; } = [];
}

public sealed class DuplicatePreviewItem
{
    [JsonPropertyName("referenceId")]
    public string ReferenceId { get; set; } = "";

    [JsonPropertyName("displayName")]
    public string DisplayName { get; set; } = "";

    [JsonPropertyName("existingJobId")]
    public string? ExistingJobId { get; set; }

    [JsonPropertyName("existingMediaId")]
    public string? ExistingMediaId { get; set; }

    [JsonPropertyName("timelinePath")]
    public string? TimelinePath { get; set; }
}

public sealed class DuplicatePreviewResponse
{
    [JsonPropertyName("totalCount")]
    public int TotalCount { get; set; }

    [JsonPropertyName("duplicateCount")]
    public int DuplicateCount { get; set; }

    [JsonPropertyName("newCount")]
    public int NewCount { get; set; }

    [JsonPropertyName("duplicates")]
    public List<DuplicatePreviewItem> Duplicates { get; set; } = [];
}

public sealed class HuggingFaceSaveRequest
{
    [JsonPropertyName("token")]
    public string? Token { get; set; }

    [JsonPropertyName("termsConfirmed")]
    public bool TermsConfirmed { get; set; }
}

public sealed class HuggingFaceAccessSnapshot
{
    [JsonPropertyName("hasToken")]
    public bool HasToken { get; set; }

    [JsonPropertyName("termsConfirmed")]
    public bool TermsConfirmed { get; set; }

    [JsonPropertyName("accessState")]
    public string AccessState { get; set; } = "unknown";

    [JsonPropertyName("accessMessage")]
    public string AccessMessage { get; set; } = "";

    [JsonPropertyName("models")]
    public List<GatedModelStatusItem> Models { get; set; } = [];
}

public sealed class GatedModelStatusItem
{
    [JsonPropertyName("modelId")]
    public string ModelId { get; set; } = "";

    [JsonPropertyName("displayName")]
    public string DisplayName { get; set; } = "";

    [JsonPropertyName("purpose")]
    public string Purpose { get; set; } = "";

    [JsonPropertyName("approvalUrl")]
    public string ApprovalUrl { get; set; } = "";

    [JsonPropertyName("requiresApproval")]
    public bool RequiresApproval { get; set; }

    [JsonPropertyName("tokenConfigured")]
    public bool TokenConfigured { get; set; }

    [JsonPropertyName("termsConfirmed")]
    public bool TermsConfirmed { get; set; }

    [JsonPropertyName("accessState")]
    public string AccessState { get; set; } = "unknown";
}

public sealed class WorkerCapabilitySnapshot
{
    [JsonPropertyName("generatedAt")]
    public string? GeneratedAt { get; set; }

    [JsonPropertyName("torchInstalled")]
    public bool TorchInstalled { get; set; }

    [JsonPropertyName("torchCudaBuilt")]
    public bool TorchCudaBuilt { get; set; }

    [JsonPropertyName("gpuAvailable")]
    public bool GpuAvailable { get; set; }

    [JsonPropertyName("deviceCount")]
    public int DeviceCount { get; set; }

    [JsonPropertyName("deviceNames")]
    public List<string> DeviceNames { get; set; } = [];

    [JsonPropertyName("deviceMemoryGiB")]
    public List<double> DeviceMemoryGiB { get; set; } = [];

    [JsonPropertyName("maxGpuMemoryGiB")]
    public double MaxGpuMemoryGiB { get; set; }

    [JsonPropertyName("message")]
    public string Message { get; set; } = "";
}

public sealed class ModelCacheSnapshot
{
    [JsonPropertyName("hasCache")]
    public bool HasCache { get; set; }

    [JsonPropertyName("totalBytes")]
    public long TotalBytes { get; set; }

    [JsonPropertyName("directoryCount")]
    public int DirectoryCount { get; set; }
}

public sealed class SetupState
{
    public bool HasToken { get; set; }

    public bool TermsConfirmed { get; set; }

    public bool HasSelectedLanguage { get; set; }

    public bool IsReady => HasSelectedLanguage;
}

public sealed class ScannedAudioItem
{
    public string SourceId { get; set; } = "";
    public string SourceKind { get; set; } = "mounted_root";
    public string OriginalPath { get; set; } = "";
    public string DisplayName { get; set; } = "";
    public long SizeBytes { get; set; }
}

public sealed class InputItemDocument
{
    [JsonPropertyName("input_id")]
    public string InputId { get; set; } = "";

    [JsonPropertyName("source_kind")]
    public string SourceKind { get; set; } = "";

    [JsonPropertyName("source_id")]
    public string SourceId { get; set; } = "";

    [JsonPropertyName("original_path")]
    public string OriginalPath { get; set; } = "";

    [JsonPropertyName("display_name")]
    public string DisplayName { get; set; } = "";

    [JsonPropertyName("size_bytes")]
    public long SizeBytes { get; set; }

    [JsonPropertyName("uploaded_path")]
    public string? UploadedPath { get; set; }
}

public sealed class JobRequestDocument
{
    [JsonPropertyName("schema_version")]
    public int SchemaVersion { get; set; } = 1;

    [JsonPropertyName("job_id")]
    public string JobId { get; set; } = "";

    [JsonPropertyName("created_at")]
    public string CreatedAt { get; set; } = "";

    [JsonPropertyName("output_root_id")]
    public string OutputRootId { get; set; } = "";

    [JsonPropertyName("output_root_path")]
    public string OutputRootPath { get; set; } = "";

    [JsonPropertyName("profile")]
    public string Profile { get; set; } = "quality-first";

    [JsonPropertyName("compute_mode")]
    public string ComputeMode { get; set; } = "cpu";

    [JsonPropertyName("processing_quality")]
    public string ProcessingQuality { get; set; } = "standard";

    [JsonPropertyName("pipeline_version")]
    public string PipelineVersion { get; set; } = "";

    [JsonPropertyName("conversion_signature")]
    public string ConversionSignature { get; set; } = "";

    [JsonPropertyName("transcription_backend")]
    public string TranscriptionBackend { get; set; } = "";

    [JsonPropertyName("transcription_model_id")]
    public string TranscriptionModelId { get; set; } = "";

    [JsonPropertyName("transcription_initial_prompt")]
    public string? TranscriptionInitialPrompt { get; set; }

    [JsonPropertyName("transcript_normalization_mode")]
    public string TranscriptNormalizationMode { get; set; } = "deterministic";

    [JsonPropertyName("transcript_normalization_glossary")]
    public string? TranscriptNormalizationGlossary { get; set; }

    [JsonPropertyName("diarization_enabled")]
    public bool DiarizationEnabled { get; set; }

    [JsonPropertyName("diarization_model_id")]
    public string? DiarizationModelId { get; set; }

    [JsonPropertyName("vad_backend")]
    public string VadBackend { get; set; } = "";

    [JsonPropertyName("vad_model_id")]
    public string VadModelId { get; set; } = "";

    [JsonPropertyName("reprocess_duplicates")]
    public bool ReprocessDuplicates { get; set; }

    [JsonPropertyName("token_enabled")]
    public bool TokenEnabled { get; set; }

    [JsonPropertyName("input_items")]
    public List<InputItemDocument> InputItems { get; set; } = [];
}

public sealed class JobStatusDocument
{
    [JsonPropertyName("schema_version")]
    public int SchemaVersion { get; set; } = 1;

    [JsonPropertyName("job_id")]
    public string JobId { get; set; } = "";

    [JsonPropertyName("state")]
    public string State { get; set; } = "pending";

    [JsonPropertyName("current_stage")]
    public string CurrentStage { get; set; } = "queued";

    [JsonPropertyName("message")]
    public string Message { get; set; } = "";

    [JsonPropertyName("warnings")]
    public List<string> Warnings { get; set; } = [];

    [JsonPropertyName("items_total")]
    public int ItemsTotal { get; set; }

    [JsonIgnore]
    public int VideosTotal
    {
        get => ItemsTotal;
        set => ItemsTotal = value;
    }

    [JsonPropertyName("items_done")]
    public int ItemsDone { get; set; }

    [JsonIgnore]
    public int VideosDone
    {
        get => ItemsDone;
        set => ItemsDone = value;
    }

    [JsonPropertyName("items_skipped")]
    public int ItemsSkipped { get; set; }

    [JsonIgnore]
    public int VideosSkipped
    {
        get => ItemsSkipped;
        set => ItemsSkipped = value;
    }

    [JsonPropertyName("items_failed")]
    public int ItemsFailed { get; set; }

    [JsonIgnore]
    public int VideosFailed
    {
        get => ItemsFailed;
        set => ItemsFailed = value;
    }

    [JsonPropertyName("current_item")]
    public string? CurrentItem { get; set; }

    [JsonIgnore]
    public string? CurrentMedia
    {
        get => CurrentItem;
        set => CurrentItem = value;
    }

    [JsonPropertyName("current_item_elapsed_sec")]
    public double CurrentItemElapsedSec { get; set; }

    [JsonIgnore]
    public double CurrentMediaElapsedSec
    {
        get => CurrentItemElapsedSec;
        set => CurrentItemElapsedSec = value;
    }

    [JsonPropertyName("current_stage_elapsed_sec")]
    public double CurrentStageElapsedSec { get; set; }

    [JsonPropertyName("processed_duration_sec")]
    public double ProcessedDurationSec { get; set; }

    [JsonPropertyName("total_duration_sec")]
    public double TotalDurationSec { get; set; }

    [JsonPropertyName("estimated_remaining_sec")]
    public double? EstimatedRemainingSec { get; set; }

    [JsonPropertyName("progress_percent")]
    public double ProgressPercent { get; set; }

    [JsonPropertyName("started_at")]
    public string? StartedAt { get; set; }

    [JsonPropertyName("updated_at")]
    public string? UpdatedAt { get; set; }

    [JsonPropertyName("completed_at")]
    public string? CompletedAt { get; set; }
}

public sealed class JobResultDocument
{
    [JsonPropertyName("schema_version")]
    public int SchemaVersion { get; set; } = 1;

    [JsonPropertyName("job_id")]
    public string JobId { get; set; } = "";

    [JsonPropertyName("state")]
    public string State { get; set; } = "pending";

    [JsonPropertyName("run_dir")]
    public string RunDir { get; set; } = "";

    [JsonPropertyName("output_root_id")]
    public string OutputRootId { get; set; } = "";

    [JsonPropertyName("output_root_path")]
    public string OutputRootPath { get; set; } = "";

    [JsonPropertyName("processed_count")]
    public int ProcessedCount { get; set; }

    [JsonPropertyName("skipped_count")]
    public int SkippedCount { get; set; }

    [JsonPropertyName("error_count")]
    public int ErrorCount { get; set; }

    [JsonPropertyName("batch_count")]
    public int BatchCount { get; set; }

    [JsonPropertyName("timeline_index_path")]
    public string? TimelineIndexPath { get; set; }

    [JsonPropertyName("warnings")]
    public List<string> Warnings { get; set; } = [];
}

public sealed class ManifestItemDocument
{
    [JsonPropertyName("input_id")]
    public string InputId { get; set; } = "";

    [JsonPropertyName("source_kind")]
    public string SourceKind { get; set; } = "";

    [JsonPropertyName("original_path")]
    public string OriginalPath { get; set; } = "";

    [JsonPropertyName("file_name")]
    public string FileName { get; set; } = "";

    [JsonPropertyName("size_bytes")]
    public long SizeBytes { get; set; }

    [JsonPropertyName("duration_seconds")]
    public double DurationSeconds { get; set; }

    [JsonPropertyName("source_hash")]
    public string SourceHash { get; set; } = "";

    [JsonIgnore]
    public string Sha256
    {
        get => SourceHash;
        set => SourceHash = value;
    }

    [JsonPropertyName("conversion_signature")]
    public string ConversionSignature { get; set; } = "";

    [JsonPropertyName("duplicate_status")]
    public string DuplicateStatus { get; set; } = "";

    [JsonPropertyName("duplicate_of")]
    public string? DuplicateOf { get; set; }

    [JsonPropertyName("audio_id")]
    public string? AudioId { get; set; }

    [JsonIgnore]
    public string? MediaId
    {
        get => AudioId;
        set => AudioId = value;
    }

    [JsonPropertyName("status")]
    public string Status { get; set; } = "pending";

    [JsonPropertyName("container_name")]
    public string? ContainerName { get; set; }

    [JsonPropertyName("extension")]
    public string? Extension { get; set; }

    [JsonPropertyName("audio_codec")]
    public string? AudioCodec { get; set; }

    [JsonPropertyName("audio_channels")]
    public int? AudioChannels { get; set; }

    [JsonPropertyName("audio_sample_rate")]
    public int? AudioSampleRate { get; set; }

    [JsonPropertyName("bitrate")]
    public int? Bitrate { get; set; }

    [JsonPropertyName("diarization_enabled")]
    public bool DiarizationEnabled { get; set; }

    [JsonPropertyName("model_id")]
    public string? ModelId { get; set; }

    [JsonPropertyName("model_version")]
    public string? ModelVersion { get; set; }

    [JsonPropertyName("pipeline_version")]
    public string? PipelineVersion { get; set; }

    [JsonPropertyName("captured_at")]
    public string? CapturedAt { get; set; }

    [JsonPropertyName("processing_wall_seconds")]
    public double? ProcessingWallSeconds { get; set; }

    [JsonPropertyName("stage_elapsed_seconds")]
    public Dictionary<string, double> StageElapsedSeconds { get; set; } = [];

    [JsonPropertyName("pause_summary")]
    public Dictionary<string, object?> PauseSummary { get; set; } = [];

    [JsonPropertyName("loudness_summary")]
    public Dictionary<string, object?> LoudnessSummary { get; set; } = [];

    [JsonPropertyName("speaking_rate_summary")]
    public Dictionary<string, object?> SpeakingRateSummary { get; set; } = [];

    [JsonPropertyName("pitch_summary")]
    public Dictionary<string, object?> PitchSummary { get; set; } = [];

    [JsonPropertyName("speaker_confidence_summary")]
    public Dictionary<string, object?> SpeakerConfidenceSummary { get; set; } = [];

    [JsonPropertyName("diarization_quality_summary")]
    public Dictionary<string, object?> DiarizationQualitySummary { get; set; } = [];

    [JsonPropertyName("optional_voice_feature_summary")]
    public Dictionary<string, object?> OptionalVoiceFeatureSummary { get; set; } = [];
}

public sealed class ManifestDocument
{
    [JsonPropertyName("schema_version")]
    public int SchemaVersion { get; set; } = 1;

    [JsonPropertyName("job_id")]
    public string JobId { get; set; } = "";

    [JsonPropertyName("generated_at")]
    public string GeneratedAt { get; set; } = "";

    [JsonPropertyName("items")]
    public List<ManifestItemDocument> Items { get; set; } = [];
}

public sealed class RunSummary
{
    public string JobId { get; set; } = "";
    public string RunDirectory { get; set; } = "";
    public string OutputRootId { get; set; } = "";
    public string State { get; set; } = "pending";
    public string CurrentStage { get; set; } = "queued";
    public int VideosTotal { get; set; }
    public int VideosDone { get; set; }
    public int VideosSkipped { get; set; }
    public int VideosFailed { get; set; }
    public long TotalSizeBytes { get; set; }
    public double TotalDurationSec { get; set; }
    public double? ElapsedWallSec { get; set; }
    public double? EstimatedRemainingSec { get; set; }
    public double ProgressPercent { get; set; }
    public bool HasDownloadableArchive { get; set; }
    public string? UpdatedAt { get; set; }
    public string? CreatedAt { get; set; }
}

public sealed class TimelineMediaItem
{
    public string MediaId { get; set; } = "";
    public string SourcePath { get; set; } = "";
    public string TimelinePath { get; set; } = "";
    public string Status { get; set; } = "pending";
    public bool IsReferencedDuplicate { get; set; }
    public string? ReferencedJobId { get; set; }
    public string? ReferencedMediaId { get; set; }
}

public sealed class RunDetails
{
    public string JobId { get; set; } = "";
    public string RunDirectory { get; set; } = "";
    public double? ElapsedWallSec { get; set; }
    public JobRequestDocument? Request { get; set; }
    public AppSettingsDocument? CurrentSettings { get; set; }
    public JobStatusDocument? Status { get; set; }
    public JobResultDocument? Result { get; set; }
    public ManifestDocument? Manifest { get; set; }
    public IReadOnlyList<TimelineMediaItem> TimelineItems { get; set; } = [];
    public string LogTail { get; set; } = "";
}
