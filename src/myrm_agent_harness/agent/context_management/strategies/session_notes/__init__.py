"""Session Notes — real-time structured notes.

[INPUT]
- langchain_core.messages::BaseMessage (POS: LangChain 消息基类)
- langchain_core.language_models::BaseChatModel (POS: LangChain LLM 基类)

[OUTPUT]
- SessionNotes: 会话笔记数据结构
- SessionNotesManager: 后台异步更新管理器
- should_update_notes: 双阈值触发判断

[POS]
Real-time structured session notes. Asynchronously maintains notes during conversation, serving as zero-API-call summaries during compression.

"""

from .schemas import NoteSection, SessionNotes, SessionNotesConfig
from .trigger import should_update_notes
from .updater import NotesLoadCallback, NotesPersistCallback, SessionNotesManager

__all__ = [
    "NoteSection",
    "NotesLoadCallback",
    "NotesPersistCallback",
    "SessionNotes",
    "SessionNotesConfig",
    "SessionNotesManager",
    "should_update_notes",
]
