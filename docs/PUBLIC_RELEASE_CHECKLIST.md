# Release Checklist

- [ ] `settings.example.json` reflects the current CLI-only product contract
- [ ] `.\cli.ps1 settings init` works from Windows PowerShell
- [ ] `.\cli.ps1 items refresh` processes configured input roots
- [ ] `.\cli.ps1 items download` exports timeline JSON artifacts
- [ ] Docker CPU worker starts successfully
- [ ] Docker GPU worker starts successfully when NVIDIA Docker support is available
- [ ] A real audio sample produces `timeline.json`
- [ ] The primary artifact contains speaker labels, audio-relative timestamps, and phone tokens
