FROM node:18-bookworm-slim AS web-assets
WORKDIR /src
COPY package.json package-lock.json tailwind.config.cjs ./
RUN npm ci
COPY web/ /src/web/
RUN npm run build:css:prod

FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src

COPY web/TimelineForAudio.Web.csproj web/
RUN dotnet restore web/TimelineForAudio.Web.csproj

COPY web/ web/
COPY configs/ /src/configs/
COPY --from=web-assets /src/web/wwwroot/css/tailwind.css /src/web/wwwroot/css/tailwind.css
RUN dotnet publish web/TimelineForAudio.Web.csproj -c Release -o /app/publish

FROM mcr.microsoft.com/dotnet/aspnet:10.0
WORKDIR /app
COPY --from=build /app/publish .
COPY configs/ /app/config/
ENV ASPNETCORE_URLS=http://+:8080
EXPOSE 8080
ENTRYPOINT ["dotnet", "TimelineForAudio.Web.dll"]
