"""Claim lexicons and evidence-shape patterns for the execution-claim verifier.

Declarative tables only: the sentence/claim patterns, the request-side intents
that gate bare result forms, the strict test-runner list, the outbound command
and tool-name vocabulary, and the evidence-shape vetoes (dry runs, zero-test
outputs, PATH rewrites, read-only MCP calls). The verifier module reads them and
owns the decision flow.

[INPUT]
- agent.security.guards.loop_guard::VerificationCategory (POS: 验证类别 SSOT)

[OUTPUT]
- 断言识别、排除、意图与证据形状的全部正则表

[POS]
完成门禁断言语料库。与判定逻辑分离，方便逐条扩充语料并对照测试。
"""

from __future__ import annotations

import re

from myrm_agent_harness.agent.security.guards.loop_guard import VerificationCategory

_MCP_PTC_BASH_MARKER = "skills.mcp_"

# ---------------------------------------------------------------------------
# Sentence segmentation and exclusion filters
# ---------------------------------------------------------------------------


_FENCED_BLOCK: re.Pattern[str] = re.compile(r"```[\s\S]*?```")
_INLINE_CODE: re.Pattern[str] = re.compile(r"`[^`\n]+`")
_SENTENCE_SPLIT: re.Pattern[str] = re.compile(r"[。！？；\n]+|(?<=[.!?])\s+")

_ATTRIBUTION: re.Pattern[str] = re.compile(
    r"(?:文档|README|报告|教程|指南|资料|官方|规范|说明)(?:中|里|上)?\s*(?:说|称|指出|表明|写明|提到|要求|建议|声明)"
    r"|(?:^|[，。；\s])(?:据|根据|按照|依照)[^，。；\n]{0,12}(?:说|称|指出|表明|描述|规定)"
    r"|\b(?:according to|per the docs?|the docs? (?:say|says)|documentation (?:says|states))\b",
    re.IGNORECASE,
)
_CONDITIONAL: re.Pattern[str] = re.compile(
    r"(?:如果|若|一旦|只要|即可|才能|将会|将来|即将|计划|打算|准备|应当|应该)"
    r"|\b(?:if|once|unless|should|would|will|plan to|intend to)\b",
    re.IGNORECASE,
)
_NEGATED: re.Pattern[str] = re.compile(
    r"(?:未|没有|没能|无法|尚未|不该|不(?:会|能|可)再?)\s*(?:通过|修复|发送|发布|部署|提交|实现|发出|上线|完成)"
    r"|\b(?:not|never|unable to|didn't|did not|haven't|hasn't)\s+(?:run|ran|send|sent|fix|fixed|deploy|deployed|publish|published|pass|passed)\b",
    re.IGNORECASE,
)
_EXPLANATION_CONTEXT: re.Pattern[str] = re.compile(
    r"(?:示例|例如|比如|教程|如何|怎么|步骤)"
    r"|\b(?:for example|e\.g\.|such as|tutorial|how to)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Verification claims
# ---------------------------------------------------------------------------


_VERIFICATION_RESULT_ZH: re.Pattern[str] = re.compile(
    r"(?:所有|全部|每一个|各项)?(?:测试|单测|用例|回归|测试套件|lint|静态检查|类型检查|类型校验|构建|编译)"
    r"[^\n。！？；]{0,12}?(?:全部|均|都|已|一律)?(?:通过|成功|全绿|无(?:失败|错误|告警|警告)|零(?:失败|错误))"
    r"|(?:pytest|vitest|jest|go test|npm test|cargo test)[^\n]{0,30}?\d+\s*(?:passed|个?通过)"
)
_VERIFICATION_RESULT_EN: re.Pattern[str] = re.compile(
    r"\b(?:all|every)\s+(?:tests?|checks?)\s+(?:pass|passed|are\s+passing|are\s+green)\b"
    r"|\b(?:tests?|lint|type\s*-?\s*check|build)\s+(?:is|are|was|were)?\s*(?:clean|passed|passes|green|succeeds?)\b"
    r"|\b\d+\s+passed\b",
    re.IGNORECASE,
)
_VERIFICATION_FIRST_PERSON: re.Pattern[str] = re.compile(
    r"我(?:们)?(?:已经|已|刚刚|刚)?(?:运行|跑|执行|做了|做过)[^\n。！？；]{0,12}(?:测试|单测|用例|回归|lint|类型检查|构建|编译)"
    r"|\bi\s+(?:ran|executed|launched)\b[^\n.]{0,24}\b(?:tests?|lint|build|suite)\b",
    re.IGNORECASE,
)

# Claim categories a sentence can reference. The claim must be grounded per
# mentioned category — "tests pass, lint clean" needs both records.
_CATEGORY_KEYWORDS: tuple[tuple[VerificationCategory, tuple[str, ...]], ...] = (
    (
        VerificationCategory.TEST,
        (
            "测试",
            "单测",
            "用例",
            "回归",
            "pytest",
            "vitest",
            "jest",
            "go test",
            "npm test",
            "cargo test",
            "tests",
            "test suite",
        ),
    ),
    (
        VerificationCategory.LINT,
        ("lint", "eslint", "ruff", "flake8", "pylint", "静态检查", "代码风格", "prettier", "biome"),
    ),
    (
        VerificationCategory.TYPECHECK,
        ("类型检查", "类型校验", "类型标注", "mypy", "pyright", "tsc", "type check", "typecheck", "type-check"),
    ),
    (
        VerificationCategory.BUILD,
        ("构建", "编译", "build", "compile"),
    ),
)

# Real test runners only. A generic interpreter can print anything, so it can
# never anchor a "tests passed" claim.
_STRICT_TEST_RUNNER: re.Pattern[str] = re.compile(
    r"^(?:pytest|py\.test|vitest|jest|tox|nox|rspec|"
    r"make\s+(?:test|check)|just\s+test|"
    r"python[0-9.]*\s+-m\s+(?:pytest|unittest)|"
    r"(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?test|"
    r"cargo\s+test|go\s+test|dotnet\s+test|mvn\s+(?:test|verify)|gradle\s+test|"
    r"deno\s+test|bundle\s+exec\s+rspec|php(?:unit|artisan\s+test))\b",
    re.IGNORECASE,
)
_COMMAND_SEPARATOR: re.Pattern[str] = re.compile(r"&&|\|\||[;\n]")
_ENV_ASSIGNMENT_PREFIX: re.Pattern[str] = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)+")

# ---------------------------------------------------------------------------
# Outbound / irreversible action claims
# ---------------------------------------------------------------------------


_OUTBOUND_FIRST_PERSON: re.Pattern[str] = re.compile(
    r"我(?:们)?(?:已经|已|刚刚|刚)?(?:发送|发出|寄出|投递|转发|发布|上线|部署|提交|下单|付款|支付|购买|报名|预约)"
    r"|\b(?:i|we)(?:'ve| have)\s+(?:sent|emailed|posted|published|submitted|deployed|shipped|paid|ordered|booked|pushed)\b",
    re.IGNORECASE,
)
_OUTBOUND_BARE_RESULT: re.Pattern[str] = re.compile(
    r"已(?:经)?(?:发送|发出|寄出|投递|转发|发布|上线|部署|下单|付款|支付|报名|预约|提交)|(?:发送|发布|部署|提交|交付)完成"
    r"|\b(?:has|have)\s+been\s+(?:sent|emailed|published|submitted|deployed)\b"
    r"|\bsuccessfully\s+(?:sent|emailed|published|submitted|deployed)\b",
    re.IGNORECASE,
)
_OUTBOUND_COMMAND: re.Pattern[str] = re.compile(
    r"\b(?:curl|wget|ssh|scp|sftp|rsync|mail|sendmail|mailx|mutt|swaks|telnet|ncat)\b"
    r"|\bgit\s+(?:push|commit)\b|\bgh\s+|\bglab\s+"
    r"|\b(?:npm|pnpm|yarn)\s+publish\b|\bdocker\s+push\b|\bpodman\s+push\b"
    r"|\bkubectl\s+(?:apply|create|delete|replace)\b|\bhelm\s+(?:install|upgrade)\b"
    r"|\b(?:vercel|netlify)\s+deploy\b|\baws\s+s3\s+(?:cp|sync)\b|\bgsutil\s+cp\b"
    r"|\b(?:ftp|nc)\s+",
    re.IGNORECASE,
)
_OUTBOUND_TOOL_NAME: re.Pattern[str] = re.compile(
    r"(?:send|post|publish|mail|message|notify|webhook|deploy|submit|share|upload)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Code modification claims
# ---------------------------------------------------------------------------


_EDIT_CLAIM_ZH: re.Pattern[str] = re.compile(
    r"已(?:经)?(?:修复|改好|修好|修复完成|完成修改|实现(?:了|完成)?|重构(?:了|完成)?|优化(?:了|完成)?)"
)
_EDIT_CLAIM_EN: re.Pattern[str] = re.compile(
    r"\b(?:i|we)(?:'ve| have)?\s+(?:fixed|implemented|refactored|patched)\b",
    re.IGNORECASE,
)
_BASH_MUTATION: re.Pattern[str] = re.compile(
    r"\b(?:sed\s+-i|perl\s+-pi|git\s+apply|patch\b|tee\b|truncate\b|mv\b|cp\b|rsync\b|install\s+-m)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Request-side intents (gate bare result forms; never gate first-person forms)
# ---------------------------------------------------------------------------


_VERIFICATION_INTENT: re.Pattern[str] = re.compile(
    r"(?:跑|运行|执行|测一?下|测一测|验证|检查|核对)(?:一下|一遍)?[^。！？\n]{0,10}(?:测试|单测|用例|回归|lint|构建|编译)"
    r"|\b(?:run|execute)\s+(?:the\s+)?(?:tests?|checks?|lint|build|type\s*-?\s*check)\b"
    r"|\bcheck\s+(?:the\s+)?(?:tests?|lint|build|type\s*-?\s*check)\b",
    re.IGNORECASE,
)
_ACTION_INTENT: re.Pattern[str] = re.compile(
    r"(?:发送|发个|发给|发出|寄出|投递|转发|发布|上线|部署|提交|下单|付款|支付|报名|预约)"
    r"|发(?:邮件|报价|消息|通知|短信|文件|一封|一份|给|出)"
    r"|\b(?:send|email|publish|deploy|submit|order|pay|push)\b",
    re.IGNORECASE,
)
_EDIT_INTENT: re.Pattern[str] = re.compile(
    r"(?:修复|修一下|修好|改一下|改好|改正|修改|实现|重构|优化|加上|去掉|删除|更新)"
    r"|\b(?:fix|implement|refactor|patch|update|change|modify|optimize)\b",
    re.IGNORECASE,
)
_CODE_CONTEXT: re.Pattern[str] = re.compile(
    r"(?:代码|文件|函数|方法|模块|脚本|接口|接口层|逻辑|报错|异常|bug|测试|仓库|分支|程序|页面|组件|样式|性能|编译|构建)"
    r"|\b(?:code|file|function|method|module|script|api|endpoint|bug|error|test|repo|branch|component|build|performance)\b",
    re.IGNORECASE,
)

#: Test runs that only collect or select cases prove nothing about passing.
_TEST_DRY_RUN: re.Pattern[str] = re.compile(
    r"--collect-only|--co\b|--list-tests|--dry-run|--deselect",
    re.IGNORECASE,
)
#: A PATH rewrite can point the runner name at a substitute binary.
_TEST_PATH_REWRITE: re.Pattern[str] = re.compile(r"(?:^|[\s;&])PATH=", re.IGNORECASE)
#: Zero-test outcomes never ground a pass claim.
_TEST_ZERO_SHAPE: re.Pattern[str] = re.compile(
    r"\b0\s+passed\b|\bno tests? ran\b|\bno tests? found\b|\bno test files\b|"
    r"\bcollected 0 items\b|\bran 0 tests\b|\b0 passing\b|\btests:\s*0\b|\[no test files\]|\[no tests to run\]",
    re.IGNORECASE,
)


#: Read-only MCP calls (list/search/get/...) never ground an outbound claim.
_READONLY_MCP_TOOL: re.Pattern[str] = re.compile(
    r"(?:^|_)(?:get|list|search|read|fetch|query|describe|inspect|watch|find|count|status)(?:_|$)",
    re.IGNORECASE,
)
