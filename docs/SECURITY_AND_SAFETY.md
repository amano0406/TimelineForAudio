# Security And Safety Notes

`TimelineForAudio` is a local-first CLI tool packaged through Python and Docker. It is not a multi-tenant hosted service and it does not attempt to sandbox the host machine.

That changes what matters most for safety.

## Main Safety Boundary

The primary concern is not remote attack surface. The primary concern is whether the app reads or deletes files outside the directories it is supposed to manage.

Current guardrails:

- source audio files are read from configured input directories and are not deleted by item cleanup
- generated item cleanup removes only selected master item directories
- run logs, locks, and work files are temporary Docker/container state
- output ZIPs are generated under the project `output` directory unless `--output` is specified
- Hugging Face tokens are stored in local-only `settings.json`, which is not tracked by Git

## What This App Does Not Claim

- no OS-level sandbox
- no hardened secret manager
- no guarantee against misuse if the user intentionally points the app at sensitive paths

This is acceptable for a personal local tool, but it should be stated clearly.

## Practical Risk Level For A Public Repo

For a public code repository, the risk is mostly about:

- accidentally committing private data
- shipping unsafe default paths
- deleting the wrong directories
- accidentally sharing local `settings.json`

Those are easier to manage than the risks of a hosted service.

## Recommended Ongoing Checks

- keep sample configs generic
- keep `settings.json` and run output ignored
- review delete paths whenever cleanup logic changes
- keep CLI smoke coverage on settings, items refresh, run status, and item download ZIP generation
- avoid adding broad recursive delete behavior without explicit root checks
