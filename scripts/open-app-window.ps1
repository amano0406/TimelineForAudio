param(
    [Parameter(Mandatory = $true)]
    [string]$Url,

    [int]$Width = 960,

    [int]$Height = 640
)

$supported = @(
    @{
        Name = "Google Chrome"
        Path = "C:\Program Files\Google\Chrome\Application\chrome.exe"
    },
    @{
        Name = "Microsoft Edge"
        Path = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    },
    @{
        Name = "Microsoft Edge"
        Path = "C:\Program Files\Microsoft\Edge\Application\msedge.exe"
    },
    @{
        Name = "Brave"
        Path = "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
    },
    @{
        Name = "Chromium"
        Path = "C:\Program Files\Chromium\Application\chrome.exe"
    }
)

$selected = $supported | Where-Object { Test-Path $_.Path } | Select-Object -First 1

if ($selected) {
    Write-Output ("Opening dedicated app window with {0}..." -f $selected.Name)
    Start-Process -FilePath $selected.Path -ArgumentList @("--app=$Url", "--window-size=$Width,$Height")
    exit 0
}

Write-Output "No supported Chromium-based app-mode browser was found. Opening the default browser instead."
Start-Process $Url
exit 0
