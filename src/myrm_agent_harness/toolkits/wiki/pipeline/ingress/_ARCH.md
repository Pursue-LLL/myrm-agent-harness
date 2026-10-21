# ingress/

Wiki raw ingress SSOT — browser clip and URL markdown asset localization before `publish_raw`.

## File Index

| File | Role | Description | I/O/P |
| --- | --- | --- | --- |
| `types.py` | Types | `ClipMode`, `ClipAssetInput`, `ClipIngressRequest`, `UrlMarkdownIngressRequest`, `ClipIngressResult` | ✅ |
| `wikiignore.py` | Core | Vault `.wikiignore` load/write + gitignore-like pattern matching | ✅ |
| `asset_store.py` | Core | Clip asset bytes → `wiki/assets/` hash store; markdown image rewrite + public URL fetch | ✅ |
| `publish.py` | Core | `publish_clip_ingress`, `publish_url_markdown_ingress` → `raw_gate.publish_raw` | ✅ |
| `video_segment_parser.py` | Core | Subtitle segment parsing, sliding-window merging, and markdown synthesis | ✅ |
| `video_ingress.py` | Core | `publish_video_url_ingress`, `publish_media_ingress` → `raw_gate.publish_raw` | ✅ |
| `__init__.py` | Package | Public exports | ✅ |

## Callers

| Caller | Entry | `publish_raw` caller |
| --- | --- | --- |
| Browser extension | server `clip/runner` → `publish_clip_ingress` | `extension` |
| Agent URL ingest | `wiki_agent_tools` → `publish_url_markdown_ingress` | `agent` |
| Settings import scan | `WikiStructure.scan_folder` → `.wikiignore` filter | — |

## Key Dependencies

- `pipeline.raw_gate` (`publish_raw`, `RawGateCaller`, extension re-clip replace via `replace_source_url`)
- `core.structure` (`WikiStructure`, raw path resolution)
- `toolkits.web_fetch` (`ContentPruningFilter`, `MarkdownGenerator`)

## Clip path defaults

- Default raw path: `clips/{YYYY-MM}/web_{sha12(source_url)}.md` (title in frontmatter only).
- Asset pipeline: multipart Track A → `localize_public_markdown_images` Track B for remaining refs.
- Re-clip: extension + matching frontmatter `source_url` replaces existing raw at stable path.
