# Release Checklist

- [ ] `settings.example.json` reflects the current CLI-only product contract
- [ ] `.\cli.ps1 settings init` works from Windows PowerShell
- [ ] `.\cli.ps1 refresh` processes configured input roots
- [ ] `.\cli.ps1 jobs archive` exports timeline JSON artifacts
- [ ] Docker CPU worker starts successfully
- [ ] Docker GPU worker starts successfully when NVIDIA Docker support is available
- [ ] A real audio sample produces `speaker-acoustic-units-timeline.json`
- [ ] The primary artifact contains speaker labels, audio-relative timestamps, and acoustic units
