# Public Wheels Repository Setup

Harness **source** stays in the private repo `Pursue-LLL/myrm-agent-harness`.
Compiled wheels are published to a **public, source-free** repo so OSS CI, Docker,
Tauri, and SaaS image builds can download them without a PAT.

## One-time setup

1. Create an **empty public** GitHub repository: `Pursue-LLL/myrm-agent-harness-wheels`
   - No source code, no default branch content required (README optional).
   - Releases only.

2. Create a fine-grained PAT (or classic token) with **Contents: Read and write**
   on `myrm-agent-harness-wheels` only.

3. Add secret to **private** `myrm-agent-harness` repo:
   - Name: `MYRM_HARNESS_WHEELS_PUBLISH_TOKEN`
   - Value: the PAT from step 2

4. Push a harness tag (`v*`) or re-run `build-core-wheels.yml` for an existing tag.

## Publish flow

`build-core-wheels.yml` on tag push:

1. Builds 6 platform core wheels + 1 stripped release wheel (private repo CI).
2. Writes `harness_release_manifest.json` (SHA256 per wheel).
3. Publishes wheels + manifest to **`myrm-agent-harness-wheels`** (public, anonymous download).

Private repo Actions artifacts retain build outputs for audit (30-day retention).

## Consumer default

OSS monorepo `scripts/dev/install_harness_dev.sh` defaults to:

```bash
MYRM_HARNESS_RELEASE_REPO=Pursue-LLL/myrm-agent-harness-wheels
```

Pin version via `scripts/dev/harness_release_version.txt` (e.g. `0.1.0-rc1`).

## Re-publish an existing tag (e.g. after fixing CI)

If `v0.1.0-rc1` was pushed before public wheels mirroring was configured:

```bash
# On private harness repo — deletes remote tag only, keeps local commit
git push origin :refs/tags/v0.1.0-rc1
git push origin v0.1.0-rc1
```

Or re-run the failed workflow from GitHub Actions UI if artifacts are still available.

## Verify anonymous access

```bash
curl -sL "https://api.github.com/repos/Pursue-LLL/myrm-agent-harness-wheels/releases/tags/v0.1.0-rc1" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('assets',[])), 'assets')"
```

Expect **7** `.whl` files (1 release + 6 core platforms) plus **`harness_release_manifest.json`**.
