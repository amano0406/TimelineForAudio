FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build

WORKDIR /src
COPY api/TimelineForAudio.Api.csproj api/
RUN dotnet restore api/TimelineForAudio.Api.csproj

COPY api/ api/
RUN dotnet publish api/TimelineForAudio.Api.csproj -c Release -o /app/publish --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:10.0

WORKDIR /app
COPY --from=build /app/publish .

ENTRYPOINT ["dotnet", "TimelineForAudio.Api.dll"]
