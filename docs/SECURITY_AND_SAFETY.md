# Security And Safety Notes

`TimelineForAudio` is a local-first desktop-style tool packaged through Docker. It is not a multi-tenant hosted service and it does not attempt to sandbox the host machine.

That changes what matters most for safety.

## Main Safety Boundary

The primary concern is not remote attack surface. The primary concern is whether the app reads or deletes files outside the directories it is supposed to manage.

Current guardrails:

- uploaded files are stored under the configured uploads root
- uploaded-file cleanup deletes only directories under that uploads root
- completed run deletion removes only the selected run directory
- output ZIPs are generated under the app-data downloads directory
- Hugging Face tokens are stored outside the repository in app-data

## What This App Does Not Claim

- no OS-level sandbox
- no privilege separation between web and worker beyond directory boundaries
- no hardened secret manager
- no guarantee against misuse if the user intentionally points the app at sensitive paths

This is acceptable for a personal local tool, but it should be stated clearly.

## Practical Risk Level For A Public Repo

For a public code repository, the risk is mostly about:

- accidentally committing private data
- shipping unsafe default paths
- deleting the wrong directories
- unclear behavior around token storage

Those are easier to manage than the risks of a hosted service.

## Recommended Ongoing Checks

- keep sample configs generic
- keep `.env` and run output ignored
- review delete paths whenever cleanup logic changes
- keep E2E smoke coverage on setup, run details, and ZIP download
- avoid adding broad recursive delete behavior without explicit root checks
