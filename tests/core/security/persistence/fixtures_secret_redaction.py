"""Labeled corpus for password/credential redaction at the persistence boundary.

A positive passes when every secret is gone from the cleaned text and every ``kept`` fragment
(the label and the prose around the secret) survives, so a hit that eats a neighbouring word fails
as surely as a miss. Negatives must come back byte-identical: a redaction there silently corrupts
a user's memory or wiki page.
"""

from __future__ import annotations

from dataclasses import dataclass

_PROSE = "Section text about onboarding and reporting. " * 20


@dataclass(frozen=True, slots=True)
class Positive:
    id: str
    text: str
    secrets: tuple[str, ...]
    kept: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Negative:
    id: str
    text: str


POSITIVES: tuple[Positive, ...] = (
    Positive("assign-bare", "password=dragonfly", ("dragonfly",), ("password=",)),
    Positive("assign-quoted", 'password = "dragonfly"', ("dragonfly",), ('password = "',)),
    Positive("api-key-colon", "api_key: abcdef123456", ("abcdef123456",), ("api_key: ",)),
    Positive("token-assign", "token = abcd1234efgh5678", ("abcd1234efgh5678",), ("token = ",)),
    Positive("login-pair", "login: bob / password: dragonfly", ("dragonfly",), ("login: bob / password: ",)),
    Positive(
        "yaml-block",
        "db:\n  user: app\n  password: s3cretvalue99\n",
        ("s3cretvalue99",),
        ("db:\n  user: app\n  password: ",),
    ),
    Positive(
        "env-two-lines",
        "DB_PASSWORD=Zk9#mango42\nREDIS_PASSWORD=Ab1!cd2@ef",
        ("Zk9#mango42", "Ab1!cd2@ef"),
        ("DB_PASSWORD=",),
    ),
    Positive(
        "json",
        '{"password": "Zk9#mango42", "user": "bob"}',
        ("Zk9#mango42",),
        ('{"password": "', '"user": "bob"}'),
    ),
    Positive("zh-colon", "密码：abc123456，请勿转发。", ("abc123456",), ("密码：", "，请勿转发。")),
    Positive("zh-kouling", "口令: Zk9#mango42", ("Zk9#mango42",), ("口令: ",)),
    Positive("zh-sentence", "我的银行卡密码是 abc123456", ("abc123456",), ("我的银行卡密码是 ",)),
    Positive(
        "sentence-lower-digit",
        "my netflix password is mypassword123",
        ("mypassword123",),
        ("my netflix password is ",),
    ),
    Positive(
        "sentence-trailing-period",
        "The password is SuperSecret123.",
        ("SuperSecret123",),
        ("The password is [REDACTED].",),
    ),
    Positive(
        "secret-and-pin",
        "wifi password is hunter2hunter2 and the PIN is 482913",
        ("hunter2hunter2", "482913"),
        ("wifi password is ", " and the PIN is "),
    ),
    Positive(
        "two-passwords",
        "old password is Ab1!cd2@ef, new password is Zk9#mango42",
        ("Ab1!cd2@ef", "Zk9#mango42"),
        ("old password is ", ", new password is "),
    ),
    Positive(
        "network-name-kept",
        "The Wi-Fi password for MyHome-5G is Tr0ub4dor&3",
        ("Tr0ub4dor&3",),
        ("The Wi-Fi password for MyHome-5G is ",),
    ),
    Positive(
        "secret-before-keyword",
        "Use Zk9#mango42 as the password",
        ("Zk9#mango42",),
        ("Use ", " as the password"),
    ),
    Positive(
        "otp-numeric",
        "The OTP code is 582013 - enter it within 30 seconds.",
        ("582013",),
        ("The OTP code is ", " - enter it within 30 seconds."),
    ),
    Positive(
        "no-connector",
        "Login with user admin and password Xy7$kLm9pQ",
        ("Xy7$kLm9pQ",),
        ("Login with user admin and ",),
    ),
    Positive("zh-connector-no-space", "我的密码是Zk9#mango42", ("Zk9#mango42",), ("我的密码是",)),
    Positive("zh-change-to", "密码改成 hello12345678", ("hello12345678",), ("密码改成 ",)),
    Positive(
        "set-to",
        "Please set the password to Tr0ub4dor&3 today.",
        ("Tr0ub4dor&3",),
        ("Please set the password to ", " today."),
    ),
    Positive(
        "quoted-passphrase",
        'passphrase: "correct horse battery staple"',
        ("correct horse battery staple",),
        ("passphrase: ",),
    ),
    Positive(
        "markdown-list",
        "## Credentials\n- user: bob\n- password: hunter2hunter2\n",
        ("hunter2hunter2",),
        ("## Credentials\n- user: bob\n- password: ",),
    ),
    Positive(
        "doc-with-secret-at-the-end",
        f"Please read the docs. {_PROSE}\npassword: Zk9#mango42",
        ("Zk9#mango42",),
        (f"Please read the docs. {_PROSE}\npassword: ",),
    ),
)

NEGATIVES: tuple[Negative, ...] = (
    Negative("pin-as-verb", "Remember to pin the message in the group. Developers should read Onboarding first."),
    Negative("pwd-shell-command", "Run pwd to print the working directory. Contributors must follow Conventions."),
    Negative(
        "keyword-far-from-words",
        f"Please read the docs. {_PROSE}Reset the password in Settings. Employees attend training.",
    ),
    Negative("policy-prose", "Employees must rotate the password regularly. Always use a password manager."),
    Negative("password-manager-names", "1Password and Bitwarden are password managers. Please evaluate Dashlane."),
    Negative("policy-colon", "Password policy: minimum 12 characters, rotate every 90 days."),
    Negative("field-required", "Password: required"),
    Negative("requirement-sentence", "password: must be at least 12 characters"),
    Negative("secret-word-value", "secret: Employees only"),
    Negative("bearer-template", "Token: Bearer <jwt>"),
    Negative("placeholder-value", "api_key: your-api-key-here"),
    Negative("already-redacted", "password: [REDACTED]"),
    Negative("already-redacted-vendor", "api_key: [REDACTED:openai_api_key]"),
    Negative("known-short-example", "password: hunter2"),
    Negative("numeric-example", "password: 1234567890"),
    Negative("weak-sentence-value", "The password is abcd12"),
    Negative("rotation-sentence", "The staging password is being rotated quarterly."),
    Negative("type-annotation", "def login(password: Optional[str] = None) -> bool:"),
    Negative("constant-reference", "password=DB_PASSWORD"),
    Negative("env-template", "password: ${DB_PASSWORD}"),
    Negative("zh-policy", "请定期修改密码，员工需要遵守安全规范。"),
    Negative("zh-label-without-ascii-value", "密码：必填，长度不少于12位"),
    Negative("zh-policy-colon", "密码策略：至少12位，每90天更换。"),
    Negative("forgot-password-chat", "I forgot my password again. The Mobile Application Team met on Tuesday."),
    Negative("stored-in-manager", "My password is stored in the Password-Manager app"),
    Negative("device-name-near-keyword", "I forgot my password on my iPhone15Pro again, so I used Face ID."),
    Negative("year-near-2fa", "The 2FA was enabled since 2024 on the main account."),
    Negative("masked-value", "password: ********"),
    Negative("url-value", "Reset your password: https://example.com/reset?code=abc123def456"),
    Negative(
        "short-policy-values",
        "Set the password to expire after 90 days. The password field accepts up to 128 characters.",
    ),
    Negative("otp-label-prose", "OTP: one-time password sent via SMS"),
    Negative("code-reference-values", "api_key: process.env.OPENAI_API_KEY\nconst token = getToken();"),
    Negative("token-count-config", "max_tokens: 4096, token_count: 1500, tokenizer: sentencepiece"),
)
