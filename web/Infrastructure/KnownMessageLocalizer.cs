namespace TimelineForAudio.Web.Infrastructure;

public static class KnownMessageLocalizer
{
    private static readonly IReadOnlyDictionary<string, string> MessageKeys =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["Choose a language before using this endpoint."] = "errors.api.language_required",
            ["Complete settings before using this endpoint."] = "errors.api.settings_required",
            ["multipart/form-data is required."] = "errors.api.multipart_required",
            ["No enabled output root is configured."] = "errors.no_output_root",
            ["No input audio files were selected."] = "errors.no_input_audio",
            ["The selected job could not be found."] = "errors.job_not_found",
            ["Finish the current job before running it again."] = "errors.job_rerun_active",
            ["The selected job does not have a reusable request."] = "errors.job_request_missing",
            ["The job is still in progress."] = "errors.job_in_progress",
            ["The upload file name is required."] = "errors.upload_file_name_required",
            ["The upload file size is invalid."] = "errors.upload_file_size_invalid",
            ["The upload file could not be found."] = "errors.upload_file_not_found",
            ["Chunks must be uploaded in order."] = "errors.upload_chunks_order",
            ["The upload session path is invalid."] = "errors.upload_session_path_invalid",
            ["The upload session could not be found."] = "errors.upload_session_not_found",
            ["The upload session is invalid."] = "errors.upload_session_invalid",
            ["Hugging Face token is not configured."] = "errors.hf_token_missing",
            ["Hugging Face gated model terms are not confirmed."] = "errors.hf_terms_unconfirmed",
            ["Queued for worker pickup."] = "status.queued_for_worker",
            ["Job completed."] = "status.job_completed",
            ["Job finished with errors."] = "status.job_finished_with_errors",
        };

    public static string Localize(string? message, Func<string, string> localize)
    {
        if (string.IsNullOrWhiteSpace(message))
        {
            return string.Empty;
        }

        var trimmed = message.Trim();
        if (MessageKeys.TryGetValue(trimmed, out var key))
        {
            return localize(key);
        }

        return message;
    }
}
