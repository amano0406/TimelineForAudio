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

builder.Services.AddRazorPages();
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

    if (!setupState.HasSelectedLanguage)
    {
        if (IsAllowedBeforeLanguageSelection(path))
        {
            await next();
            return;
        }

        if (path.StartsWithSegments("/api", StringComparison.OrdinalIgnoreCase))
        {
            context.Response.StatusCode = StatusCodes.Status403Forbidden;
            await context.Response.WriteAsJsonAsync(
                new { error = "Choose a language before using this endpoint." },
                context.RequestAborted);
            return;
        }

        context.Response.Redirect("/language");
        return;
    }

    if (IsAllowedWithoutSetup(path))
    {
        await next();
        return;
    }

    if (path.StartsWithSegments("/api", StringComparison.OrdinalIgnoreCase))
    {
        context.Response.StatusCode = StatusCodes.Status403Forbidden;
        await context.Response.WriteAsJsonAsync(
            new { error = "Complete settings before using this endpoint." },
            context.RequestAborted);
        return;
    }

    context.Response.Redirect("/settings");
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

app.MapPost("/api/uploads", async (HttpRequest request, RunStore runStore, CancellationToken cancellationToken) =>
{
    if (!request.HasFormContentType)
    {
        return Results.BadRequest(new { error = "multipart/form-data is required." });
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
    CancellationToken cancellationToken) =>
{
    try
    {
        var created = await uploadSessionStore.RegisterFileAsync(sessionId, request, cancellationToken);
        return Results.Ok(created);
    }
    catch (InvalidOperationException ex)
    {
        return Results.BadRequest(new { error = ex.Message });
    }
});

app.MapPost("/api/uploads/sessions/{sessionId}/files/{fileId}/chunks/{chunkIndex:int}", async (
    string sessionId,
    string fileId,
    int chunkIndex,
    HttpRequest request,
    UploadSessionStore uploadSessionStore,
    CancellationToken cancellationToken) =>
{
    try
    {
        await uploadSessionStore.AppendChunkAsync(sessionId, fileId, chunkIndex, request.Body, cancellationToken);
        return Results.Ok(new { uploaded = true, chunkIndex });
    }
    catch (InvalidOperationException ex)
    {
        return Results.BadRequest(new { error = ex.Message });
    }
});

app.MapPost("/api/uploads/sessions/{sessionId}/complete", async (
    string sessionId,
    UploadSessionStore uploadSessionStore,
    CancellationToken cancellationToken) =>
{
    try
    {
        var items = await uploadSessionStore.CompleteSessionAsync(sessionId, cancellationToken);
        return Results.Ok(new { items, total = items.Count });
    }
    catch (InvalidOperationException ex)
    {
        return Results.BadRequest(new { error = ex.Message });
    }
});

app.MapDelete("/api/uploads/sessions/{sessionId}", async (
    string sessionId,
    UploadSessionStore uploadSessionStore,
    CancellationToken cancellationToken) =>
{
    try
    {
        var deleted = await uploadSessionStore.DeleteSessionAsync(sessionId, cancellationToken);
        return deleted ? Results.NoContent() : Results.NotFound();
    }
    catch (InvalidOperationException ex)
    {
        return Results.BadRequest(new { error = ex.Message });
    }
});

app.MapPost("/api/jobs", async (CreateJobCommand command, RunStore runStore, CancellationToken cancellationToken) =>
{
    try
    {
        var created = await runStore.CreateJobAsync(command, cancellationToken);
        return Results.Ok(new { jobId = created.JobId, runDirectory = created.RunDirectory });
    }
    catch (InvalidOperationException ex)
    {
        return Results.BadRequest(new { error = ex.Message });
    }
});

app.MapPost("/api/jobs/duplicates", async (
    DuplicatePreviewRequest request,
    RunStore runStore,
    CancellationToken cancellationToken) =>
{
    try
    {
        var preview = await runStore.PreviewDuplicatesAsync(request, cancellationToken);
        return Results.Ok(preview);
    }
    catch (InvalidOperationException ex)
    {
        return Results.BadRequest(new { error = ex.Message });
    }
});

app.MapGet("/api/jobs/{id}", async (string id, RunStore runStore, CancellationToken cancellationToken) =>
{
    var status = await runStore.GetJobStatusAsync(id, cancellationToken);
    return status is null ? Results.NotFound() : Results.Ok(status);
});

app.MapGet("/jobs/{id}/download", async (string id, RunStore runStore, CancellationToken cancellationToken) =>
{
    try
    {
        var archivePath = await runStore.BuildRunArchiveAsync(id, cancellationToken);
        return archivePath is null
            ? Results.NotFound()
            : Results.File(archivePath, "application/zip", $"{id}.zip");
    }
    catch (InvalidOperationException ex)
    {
        return Results.BadRequest(new { error = ex.Message });
    }
});

app.MapGet("/runs/{id}/download", (string id) => Results.Redirect(JobUrls.Download(id)));
app.MapGet("/runs/{jobId}/{mediaId}", (string jobId, string mediaId) => Results.Redirect(JobUrls.Media(jobId, mediaId)));
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

static bool IsAllowedBeforeLanguageSelection(PathString path) =>
    path.StartsWithSegments("/language", StringComparison.OrdinalIgnoreCase) ||
    path.StartsWithSegments("/Error", StringComparison.OrdinalIgnoreCase);

static bool IsAllowedWithoutSetup(PathString path) =>
    path.StartsWithSegments("/settings", StringComparison.OrdinalIgnoreCase) ||
    path.StartsWithSegments("/api/settings", StringComparison.OrdinalIgnoreCase) ||
    path.StartsWithSegments("/Error", StringComparison.OrdinalIgnoreCase);

static bool IsStaticAssetRequest(PathString path) =>
    Path.HasExtension(path.Value) ||
    path.StartsWithSegments("/css", StringComparison.OrdinalIgnoreCase) ||
    path.StartsWithSegments("/js", StringComparison.OrdinalIgnoreCase) ||
    path.StartsWithSegments("/lib", StringComparison.OrdinalIgnoreCase) ||
    path.StartsWithSegments("/images", StringComparison.OrdinalIgnoreCase);
