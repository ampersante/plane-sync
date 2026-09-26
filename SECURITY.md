# Security Policy

plane-sync is a local CLI; there's no hosted service to secure, but a few things matter.

## Secrets

- The Plane API token lives in `.env` (`PLANE_API_TOKEN=...`) or an equivalent environment
  variable — never in `profiles.json`, and never committed to git.
- `~/.config/plane-sync/.env` and `~/.config/plane-sync/profiles.json` live outside the
  install directory; treat them like credentials.

## Write safety

- `plane-sync write` (`plane_write.py`) runs in **dry-run mode by default**. Mutating
  changes against your Plane workspace only happen with an explicit `--execute` flag.

## Reporting a vulnerability

Please report security issues privately via GitHub Security Advisories — this repo's
**Security** tab → **Report a vulnerability** — rather than opening a public issue.
