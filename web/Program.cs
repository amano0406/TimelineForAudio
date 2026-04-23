using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.Http.Features;
using TimelineForAudio.Web.Infrastructure;
using TimelineForAudio.Web.Models;
using TimelineForAudio.Web.Services;

var builder = WebApplication.CreateBuilder(args);
var appPaths = new AppPaths(builder.Configuration);
var dataProtectionPath = Path.Combine(appPaths.AppDataRoot, "data-protection");
const long MaxUploadBytes = 8L * 1024 * 1024 * 1024;

Directory.CreateDirectory(dataProtectionPath);

builder.WebHost.ConfigureKestrel(options =>
{
    options.Limits.MaxRequestBodySize = MaxUploadBytes;
});

builder.Services
    .AddRazorPages()
    .AddMvcOptions(options =>
    {
        options.SuppressImplicitRequiredAttributeForNonNullableReferenceTypes = true;
    });
builder.Services.AddSingleton(appPaths);
builder.Services.AddSingleton<AppInstanceService>();
builder.Services.AddDataProtection()
    .PersistKeysToFileSystem(new DirectoryInfo(dataProtectionPath))
    .SetApplicationName("TimelineForAudio");
builder.Services.AddAntiforgery(options =>
{
    options.Cookie.Name = "TimelineForAudio.antiforgery";
});
builder.Services.Configure<FormOptions>(options =>
{
    options.MultipartBodyLengthLimit = MaxUploadBytes;
});
builder.Services.AddSingleton<SettingsStore>();
builder.Services.AddSingleton<SetupStateService>();
builder.Services.AddSingleton<ModelCacheService>();
builder.Services.AddSingleton<WorkerCapabilityService>();
builder.Services.AddSingleton<ScanService>();
builder.Services.AddSingleton<RunStore>();
builder.Services.AddSingleton<UploadSessionStore>();
builder.Services.AddSingleton<LanguageService>();
builder.Services.AddSingleton<JsonLocalizationService>();
builder.Services.AddHttpClient<HuggingFaceAccessService>(client =>
{
    client.Timeout = TimeSpan.FromSeconds(10);
});
builder.Services.AddHostedService<UploadCleanupService>();

var app = builder.Build();

if (!app.Environment.IsDevelopment())
{
    app.UseExceptionHandler("/Error");
}

app.UseRouting();
app.Use(async (context, next) =>
{
    var path = context.Request.Path;
    if (IsStaticAssetRequest(path))
    {
        await next();
        return;
    }

    var setupStateService = context.RequestServices.GetRequiredService<SetupStateService>();
    var setupState = await setupStateService.GetAsync(context.RequestAborted);
    context.Items["SetupState"] = setupState;

    if (setupState.IsReady)
    {
        await next();
        return;
    }

    if (IsAllowedDuringSetup(path))
    {
        await next();
        return;
    }

    if (setupState.HasJobs && IsExistingJobPath(path))
    {
        await next();
        return;
    }

    if (path.StartsWithSegments("/api", StringComparison.OrdinalIgnoreCase))
    {
        context.Response.StatusCode = StatusCodes.Status403Forbidden;
        var languageService = context.RequestServices.GetRequiredService<LanguageService>();
        var localizer = context.RequestServices.GetRequiredService<JsonLocalizationService>();
        await context.Response.WriteAsJsonAsync(
            new
            {
                error = localizer.Get(
                    languageService.Resolve(context.Request),
                    "errors.api.settings_required"),
            },
            context.RequestAborted);
        return;
    }

    context.Response.Redirect("/setup");
});
app.UseAuthorization();

app.MapStaticAssets();
app.MapRazorPages()
    .WithStaticAssets();

app.MapPost("/api/scan", async (ScanRequest request, ScanService scanService, CancellationToken cancellationToken) =>
{
    var items = await scanService.ScanAsync(request.SourceIds, cancellationToken);
    return Results.Ok(new { items, total = items.Count });
});

app.MapPost("/api/uploads", async (
    HttpRequest request,
    RunStore runStore,
    LanguageService languageService,
    JsonLocalizationService localizer,
    CancellationToken cancellationToken) =>
{
    if (!request.HasFormContentType)
    {
        return LocalizedBadRequest(request, languageService, localizer, "errors.api.multipart_required");
    }

    var form = await request.ReadFormAsync(cancellationToken);
    var items = await runStore.SaveUploadsAsync(form.Files, cancellationToken);
    return Results.Ok(new { items, total = items.Count });
});

app.MapPost("/api/uploads/sessions", async (UploadSessionStore uploadSessionStore, CancellationToken cancellationToken) =>
{
    var session = await uploadSessionStore.CreateSessionAsync(cancellationToken);
    return Results.Ok(session);
});

app.MapPost("/api/uploads/sessions/{sessionId}/files", async (
    string sessionId,
    CreateUploadFileRequest request,
    UploadSessionStore uploadSessionStore,
    HttpRequest httpRequest,
    LanguageService languageService,
    JsonLocalizationService localizer,
    CancellationToken cancellationToken) =>
{
    try
    {
        var created = await uploadSessionStore.RegisterFileAsync(sessionId, request, cancellationToken);
        return Results.Ok(created);
    }
    catch (InvalidOperationException ex)
    {
        return LocalizedBadRequestForException(httpRequest, languageService, localizer, ex);
    }
});

app.MapPost("/api/uploads/sessions/{sessionId}/files/{fileId}/chunks/{chunkIndex:int}", async (
    string sessionId,
    string fileId,
    int chunkIndex,
    HttpRequest request,
    UploadSessionStore uploadSessionStore,
    LanguageService languageService,
    JsonLocalizationService localizer,
    CancellationToken cancellationToken) =>
{
    try
    {
        await uploadSessionStore.AppendChunkAsync(sessionId, fileId, chunkIndex, request.Body, cancellationToken);
        return Results.Ok(new { uploaded = true, chunkIndex });
    }
    catch (InvalidOperationException ex)
    {
        return LocalizedBadRequestForException(request, languageService, localizer, ex);
    }
});

app.MapPost("/api/uploads/sessions/{sessionId}/complete", async (
    string sessionId,
    UploadSessionStore uploadSessionStore,
    HttpRequest request,
    LanguageService languageService,
    JsonLocalizationService localizer,
    CancellationToken cancellationToken) =>
{
    try
    {
        var items = await uploadSessionStore.CompleteSessionAsync(sessionId, cancellationToken);
        return Results.Ok(new { items, total = items.Count });
    }
    catch (InvalidOperationException ex)
    {
        return LocalizedBadRequestForException(request, languageService, localizer, ex);
    }
});

app.MapDelete("/api/uploads/sessions/{sessionId}", async (
    string sessionId,
    UploadSessionStore uploadSessionStore,
    HttpRequest request,
    LanguageService languageService,
    JsonLocalizationService localizer,
    CancellationToken cancellationToken) =>
{
    try
    {
        var deleted = await uploadSessionStore.DeleteSessionAsync(sessionId, cancellationToken);
        return deleted ? Results.NoContent() : Results.NotFound();
    }
    catch (InvalidOperationException ex)
    {
        return LocalizedBadRequestForException(request, languageService, localizer, ex);
    }
});

app.MapPost("/api/jobs", async (
    CreateJobCommand command,
    RunStore runStore,
    HttpRequest request,
    LanguageService languageService,
    JsonLocalizationService localizer,
    CancellationToken cancellationToken) =>
{
    try
    {
        var created = await runStore.CreateJobAsync(command, cancellationToken);
        return Results.Ok(new { jobId = created.JobId, runDirectory = created.RunDirectory });
    }
    catch (InvalidOperationException ex)
    {
        return LocalizedBadRequestForException(request, languageService, localizer, ex);
    }
});

app.MapGet("/api/jobs/{id}", async (string id, RunStore runStore, CancellationToken cancellationToken) =>
{
    var status = await runStore.GetJobStatusAsync(id, cancellationToken);
    return status is null ? Results.NotFound() : Results.Ok(status);
});

app.MapGet("/jobs/{id}/download", async (
    string id,
    string? artifact,
    RunStore runStore,
    HttpRequest request,
    LanguageService languageService,
    JsonLocalizationService localizer,
    CancellationToken cancellationToken) =>
{
    try
    {
        var archivePath = await runStore.BuildRunArchiveAsync(id, artifact, cancellationToken);
        return archivePath is null
            ? Results.NotFound()
            : Results.File(archivePath, "application/zip", Path.GetFileName(archivePath));
    }
    catch (InvalidOperationException ex)
    {
        return LocalizedBadRequestForException(request, languageService, localizer, ex);
    }
});

app.MapGet("/jobs/{jobId}/{mediaId}/markdown", async (
    string jobId,
    string mediaId,
    string? artifact,
    RunStore runStore,
    CancellationToken cancellationToken) =>
{
    var artifactPath = await runStore.GetArtifactPathAsync(jobId, mediaId, artifact, cancellationToken);
    return artifactPath is null
        ? Results.NotFound()
        : Results.File(artifactPath, "text/markdown; charset=utf-8", Path.GetFileName(artifactPath));
});

app.MapGet("/jobs/{id}/conversion-info/markdown", async (
    string id,
    RunStore runStore,
    CancellationToken cancellationToken) =>
{
    var conversionInfoPath = await runStore.GetConversionInfoPathAsync(id, cancellationToken);
    return conversionInfoPath is null
        ? Results.NotFound()
        : Results.File(conversionInfoPath, "text/markdown; charset=utf-8", Path.GetFileName(conversionInfoPath));
});

app.MapGet("/runs/{id}/download", (string id) => Results.Redirect(JobUrls.Download(id)));
app.MapGet("/runs/{jobId}/{mediaId}", (string jobId, string mediaId) => Results.Redirect(JobUrls.Media(jobId, mediaId)));
app.MapGet("/runs/{jobId}/{mediaId}/markdown", (string jobId, string mediaId, string? artifact) =>
    Results.Redirect(JobUrls.MediaMarkdown(jobId, mediaId, artifact)));
app.MapGet("/runs/{id}/conversion-info/markdown", (string id) =>
    Results.Redirect(JobUrls.ConversionInfoMarkdown(id)));
app.MapGet("/runs/{id}", (string id) => Results.Redirect(JobUrls.Details(id)));

app.MapPost("/api/settings/huggingface", async (HuggingFaceSaveRequest request, SettingsStore settingsStore, HuggingFaceAccessService accessService, CancellationToken cancellationToken) =>
{
    await settingsStore.SaveHuggingFaceAsync(request.Token, request.TermsConfirmed, cancellationToken);
    var snapshot = await accessService.GetSnapshotAsync(cancellationToken);
    return Results.Ok(snapshot);
});

app.MapGet("/api/settings/huggingface/status", async (HuggingFaceAccessService accessService, CancellationToken cancellationToken) =>
{
    var snapshot = await accessService.GetSnapshotAsync(cancellationToken);
    return Results.Ok(snapshot);
});

app.MapGet("/api/app/version", (AppInstanceService appInstanceService) =>
{
    return Results.Ok(new
    {
        instanceId = appInstanceService.InstanceId,
        startedAt = appInstanceService.StartedAt,
    });
});

app.Run();

static bool IsAllowedDuringSetup(PathString path) =>
    path.StartsWithSegments("/setup", StringComparison.OrdinalIgnoreCase) ||
    path.StartsWithSegments("/api/settings", StringComparison.OrdinalIgnoreCase) ||
    path.StartsWithSegments("/Error", StringComparison.OrdinalIgnoreCase);

static bool IsExistingJobPath(PathString path) =>
    (path.StartsWithSegments("/jobs", StringComparison.OrdinalIgnoreCase) &&
     !path.StartsWithSegments("/jobs/new", StringComparison.OrdinalIgnoreCase)) ||
    path.StartsWithSegments("/runs", StringComparison.OrdinalIgnoreCase);

static bool IsStaticAssetRequest(PathString path) =>
    Path.HasExtension(path.Value) ||
    path.StartsWithSegments("/css", StringComparison.OrdinalIgnoreCase) ||
    path.StartsWithSegments("/js", StringComparison.OrdinalIgnoreCase) ||
    path.StartsWithSegments("/lib", StringComparison.OrdinalIgnoreCase) ||
    path.StartsWithSegments("/images", StringComparison.OrdinalIgnoreCase);

static IResult LocalizedBadRequest(
    HttpRequest request,
    LanguageService languageService,
    JsonLocalizationService localizer,
    string key) =>
    Results.BadRequest(new
    {
        error = localizer.Get(languageService.Resolve(request), key),
    });

static IResult LocalizedBadRequestForException(
    HttpRequest request,
    LanguageService languageService,
    JsonLocalizationService localizer,
    InvalidOperationException exception) =>
    Results.BadRequest(new
    {
        error = KnownMessageLocalizer.Localize(
            exception.Message,
            key => localizer.Get(languageService.Resolve(request), key)),
    });
