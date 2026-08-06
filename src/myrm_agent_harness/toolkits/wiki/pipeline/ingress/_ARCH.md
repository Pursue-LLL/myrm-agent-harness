# ingress/

Wiki raw ingress SSOT — browser clip and URL markdown asset localization before `publish_raw`.

## File Index

| File | Role | Description | I/O/P |
| --- | --- | --- | --- |
| `types.py` | Types | `ClipMode`, `ClipAssetInput`, `ClipIngressRequest`, `UrlMarkdownIngressRequest`, `ClipIngressResult` | ✅ |
| `wikiignore.py` | Core | Vault `.wikiignore` load/write + gitignore-like pattern matching | ✅ |
| `asset_store.py` | Core | Clip asset bytes → `wiki/assets/` hash store; markdown image rewrite + public URL fetch | ✅ |
| `publish.py` | Core | `publish_clip_ingress`, `publish_url_markdown_ingress` → `raw_gate.publish_raw` | ✅ |
| `__init__.py` | Package | Public exports | — |

## Callers

| Caller | Entry | `publish_raw` caller |
| --- | --- | --- |
| Browser extension | server `clip/runner` → `publish_clip_ingress` | `extension` |
| Agent URL ingest | `wiki_agent_tools` → `publish_url_markdown_ingress` | `agent` |
| Settings import scan | `WikiStructure.scan_folder` → `.wikiignore` filter | — |

## Key Dependencies

- `pipeline.raw_gate` (`publish_raw`, `RawGateCaller`)
- `core.structure` (`WikiStructure`, raw path resolution)
- `toolkits.web_fetch` (`ContentPruningFilter`, `MarkdownGenerator`)
