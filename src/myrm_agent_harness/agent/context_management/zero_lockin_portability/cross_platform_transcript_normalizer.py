# [INPUT] Raw JSON text or bytes from ChatGPT, Claude Web, Instinct, or generic formats
# [OUTPUT] CrossPlatformTranscriptNormalizer
# [POS] Ingestion and normalization engine converting heterogeneous export schemas into standard ArchivedSessionTree

"""Cross-platform transcript normalizer for ingesting external commercial exports."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import time
from typing import cast

from .portability_types import (
    ArchivedSessionNode,
    ArchivedSessionTree,
    ExportPlatformType,
    NodeRole,
)


class CrossPlatformTranscriptNormalizer:
    """Adaptive parser and normalizer converting heterogeneous export dumps to canonical trees."""

    @classmethod
    def detect_platform(cls, raw_data: object) -> ExportPlatformType:
        """Inspect json schema fingerprints to identify the originating commercial platform."""
        if isinstance(raw_data, dict):
            dict_data = cast(dict[str, object], raw_data)
            if "manifest" in dict_data and "sessions" in dict_data:
                return "universal_myrm"
            if "conversations" in dict_data and isinstance(dict_data["conversations"], list):
                return cls.detect_platform(dict_data["conversations"])
            if "chats" in dict_data or "chat_history" in dict_data:
                return "typingmind"

        if isinstance(raw_data, list) and len(raw_data) > 0:
            first = raw_data[0]
            if isinstance(first, dict):
                first_dict = cast(dict[str, object], first)
                if "mapping" in first_dict:
                    return "chatgpt"
                if "chat_messages" in first_dict or ("uuid" in first_dict and "name" in first_dict):
                    return "claude_web"
                if "messages" in first_dict:
                    return "instinct"

        return "unknown"

    @classmethod
    def normalize_archive(
        cls, raw_content: str | bytes
    ) -> tuple[list[ArchivedSessionTree], ExportPlatformType, list[str]]:
        """Parse raw export string or bytes, detect format, and produce standardized session trees."""
        errors: list[str] = []
        text_str = (
            raw_content.decode("utf-8", errors="replace")
            if isinstance(raw_content, bytes)
            else raw_content
        )

        try:
            parsed_json = json.loads(text_str)
        except Exception as ex:
            return ([], "unknown", [f"JSON decode failure: {ex}"])

        platform = cls.detect_platform(parsed_json)

        if platform == "chatgpt":
            trees, parse_errors = cls._normalize_chatgpt(parsed_json)
            return (trees, platform, parse_errors)
        if platform == "claude_web":
            trees, parse_errors = cls._normalize_claude_web(parsed_json)
            return (trees, platform, parse_errors)
        if platform == "universal_myrm":
            trees, parse_errors = cls._normalize_universal_myrm(parsed_json)
            return (trees, platform, parse_errors)
        if platform in ("instinct", "typingmind") or isinstance(parsed_json, list):
            trees, parse_errors = cls._normalize_generic_sessions(parsed_json, platform)
            return (trees, platform, parse_errors)

        errors.append("Unrecognized export archive format")
        return ([], "unknown", errors)

    @classmethod
    def _normalize_chatgpt(
        cls, parsed: object
    ) -> tuple[list[ArchivedSessionTree], list[str]]:
        """Parse ChatGPT conversations.json containing mapping tree structures."""
        trees: list[ArchivedSessionTree] = []
        errors: list[str] = []

        sess_list: list[dict[str, object]] = []
        if isinstance(parsed, list):
            sess_list = [cast(dict[str, object], item) for item in parsed if isinstance(item, dict)]
        elif isinstance(parsed, dict):
            convs = parsed.get("conversations")
            if isinstance(convs, list):
                sess_list = [cast(dict[str, object], item) for item in convs if isinstance(item, dict)]

        for item in sess_list:
            session_id = str(item.get("id", item.get("conversation_id", f"gpt_{len(trees)}")))
            title = str(item.get("title", "ChatGPT Conversation"))
            create_ts = float(cast(int | float, item.get("create_time", time.time())))
            update_ts = float(cast(int | float, item.get("update_time", create_ts)))
            created_iso = datetime.fromtimestamp(create_ts, tz=timezone.utc).isoformat()
            updated_iso = datetime.fromtimestamp(update_ts, tz=timezone.utc).isoformat()

            raw_mapping = cast(dict[str, object], item.get("mapping", {}))
            nodes: dict[str, ArchivedSessionNode] = {}
            root_node_ids: list[str] = []

            for node_id, raw_node_obj in raw_mapping.items():
                if not isinstance(raw_node_obj, dict):
                    continue
                node_dict = cast(dict[str, object], raw_node_obj)
                parent_id = str(node_dict["parent"]) if node_dict.get("parent") else None
                children_raw = cast(list[object], node_dict.get("children", []))
                children_ids = [str(c) for c in children_raw]

                msg_obj = node_dict.get("message")
                role: NodeRole = "user"
                content_text = ""
                model_name: str | None = None
                created_unix = create_ts

                if isinstance(msg_obj, dict):
                    author = cast(dict[str, object], msg_obj.get("author", {}))
                    author_role = str(author.get("role", "user")).lower()
                    if author_role == "assistant":
                        role = "assistant"
                    elif author_role == "system":
                        role = "system"
                    elif author_role in ("tool", "function"):
                        role = "tool"
                    else:
                        role = "user"

                    msg_content = cast(dict[str, object], msg_obj.get("content", {}))
                    parts = msg_content.get("parts")
                    if isinstance(parts, list):
                        content_text = "\n".join(str(p) for p in parts if p is not None)
                    elif "text" in msg_content:
                        content_text = str(msg_content["text"])

                    meta = cast(dict[str, object], msg_obj.get("metadata", {}))
                    if "model_slug" in meta:
                        model_name = str(meta["model_slug"])
                    if "create_time" in msg_obj and msg_obj["create_time"] is not None:
                        created_unix = float(cast(int | float, msg_obj["create_time"]))

                if parent_id is None:
                    root_node_ids.append(node_id)

                nodes[node_id] = ArchivedSessionNode(
                    node_id=node_id,
                    parent_id=parent_id,
                    children_ids=children_ids,
                    role=role,
                    content=content_text,
                    model_name=model_name,
                    created_at_unix=created_unix,
                    metadata={"source": "chatgpt"},
                )

            tree = ArchivedSessionTree(
                session_id=session_id,
                title=title,
                root_node_ids=root_node_ids,
                nodes=nodes,
                created_at_iso=created_iso,
                updated_at_iso=updated_iso,
                original_platform="chatgpt",
                tags=["chatgpt_import"],
            )
            trees.append(tree)

        return (trees, errors)

    @classmethod
    def _normalize_claude_web(
        cls, parsed: object
    ) -> tuple[list[ArchivedSessionTree], list[str]]:
        """Parse Claude Web export format containing linear or branched chat_messages."""
        trees: list[ArchivedSessionTree] = []
        errors: list[str] = []

        sess_list = [cast(dict[str, object], i) for i in cast(list[object], parsed) if isinstance(i, dict)]
        for item in sess_list:
            session_id = str(item.get("uuid", f"claude_{len(trees)}"))
            title = str(item.get("name", "Claude Conversation"))
            created_iso = str(item.get("created_at", datetime.now(timezone.utc).isoformat()))
            updated_iso = str(item.get("updated_at", created_iso))

            raw_messages = cast(list[object], item.get("chat_messages", []))
            nodes: dict[str, ArchivedSessionNode] = {}
            prev_node_id: str | None = None
            root_node_ids: list[str] = []

            for idx, msg_raw in enumerate(raw_messages):
                if not isinstance(msg_raw, dict):
                    continue
                msg_dict = cast(dict[str, object], msg_raw)
                node_id = str(msg_dict.get("uuid", f"{session_id}_msg_{idx}"))
                sender = str(msg_dict.get("sender", "human")).lower()
                role: NodeRole = "assistant" if sender == "assistant" else "user"
                content = str(msg_dict.get("text", ""))

                node = ArchivedSessionNode(
                    node_id=node_id,
                    parent_id=prev_node_id,
                    children_ids=[],
                    role=role,
                    content=content,
                    created_at_unix=time.time(),
                    metadata={"source": "claude_web"},
                )
                nodes[node_id] = node

                if prev_node_id is None:
                    root_node_ids.append(node_id)
                else:
                    parent_node = nodes[prev_node_id]
                    updated_children = list(parent_node.children_ids) + [node_id]
                    nodes[prev_node_id] = ArchivedSessionNode(
                        node_id=parent_node.node_id,
                        parent_id=parent_node.parent_id,
                        children_ids=updated_children,
                        role=parent_node.role,
                        content=parent_node.content,
                        created_at_unix=parent_node.created_at_unix,
                        metadata=parent_node.metadata,
                    )

                prev_node_id = node_id

            tree = ArchivedSessionTree(
                session_id=session_id,
                title=title,
                root_node_ids=root_node_ids,
                nodes=nodes,
                created_at_iso=created_iso,
                updated_at_iso=updated_iso,
                original_platform="claude_web",
                tags=["claude_import"],
            )
            trees.append(tree)

        return (trees, errors)

    @classmethod
    def _normalize_universal_myrm(
        cls, parsed: dict[str, object]
    ) -> tuple[list[ArchivedSessionTree], list[str]]:
        """Parse standard Universal Myrm payload."""
        from .universal_archive_spec import UniversalArchiveSpecEngine

        try:
            payload = UniversalArchiveSpecEngine.deserialize_payload(json.dumps(parsed))
            return (payload.sessions, [])
        except Exception as ex:
            return ([], [f"Failed to deserialize universal myrm format: {ex}"])

    @classmethod
    def _normalize_generic_sessions(
        cls, parsed: object, platform: ExportPlatformType
    ) -> tuple[list[ArchivedSessionTree], list[str]]:
        """Normalize generic JSON message list or chat collections."""
        trees: list[ArchivedSessionTree] = []
        errors: list[str] = []

        sess_items: list[dict[str, object]] = []
        if isinstance(parsed, list):
            sess_items = [cast(dict[str, object], x) for x in parsed if isinstance(x, dict)]
        elif isinstance(parsed, dict):
            for k in ("chats", "conversations", "messages"):
                val = parsed.get(k)
                if isinstance(val, list):
                    sess_items = [cast(dict[str, object], x) for x in val if isinstance(x, dict)]
                    break

        for idx, item in enumerate(sess_items):
            session_id = str(item.get("id", f"gen_{idx}"))
            title = str(item.get("title", f"Session {idx}"))
            now_iso = datetime.now(timezone.utc).isoformat()
            raw_msgs = cast(list[object], item.get("messages", []))

            nodes: dict[str, ArchivedSessionNode] = {}
            root_node_ids: list[str] = []
            prev_id: str | None = None

            for m_idx, m_raw in enumerate(raw_msgs):
                if not isinstance(m_raw, dict):
                    continue
                m_dict = cast(dict[str, object], m_raw)
                n_id = str(m_dict.get("id", f"{session_id}_{m_idx}"))
                r_str = str(m_dict.get("role", "user")).lower()
                role: NodeRole = "assistant" if r_str == "assistant" else "user"
                content = str(m_dict.get("content", ""))

                node = ArchivedSessionNode(
                    node_id=n_id,
                    parent_id=prev_id,
                    children_ids=[],
                    role=role,
                    content=content,
                    created_at_unix=time.time(),
                    metadata={"source": str(platform)},
                )
                nodes[n_id] = node
                if prev_id is None:
                    root_node_ids.append(n_id)
                else:
                    nodes[prev_id].children_ids.append(n_id)
                prev_id = n_id

            trees.append(
                ArchivedSessionTree(
                    session_id=session_id,
                    title=title,
                    root_node_ids=root_node_ids,
                    nodes=nodes,
                    created_at_iso=now_iso,
                    updated_at_iso=now_iso,
                    original_platform=platform,
                )
            )

        return (trees, errors)
