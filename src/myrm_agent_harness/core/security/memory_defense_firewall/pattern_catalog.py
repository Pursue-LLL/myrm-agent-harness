"""Catalog of 45 sensitive secrets, credentials, and PII detection patterns."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .types import PatternSpec, SensitiveCategory


@dataclass(slots=True, frozen=True)
class CompiledPattern:
    """Pre-compiled regex pattern spec for fast memory defense scanning."""

    spec: PatternSpec
    compiled_regex: re.Pattern[str]


def _build_builtin_specs() -> list[PatternSpec]:
    specs: list[PatternSpec] = [
        # 1-10: Major AI & Developer API Keys
        PatternSpec(
            pattern_id="openai_key",
            name="OpenAI API Key",
            category=SensitiveCategory.API_KEY,
            regex_pattern=r"sk-[a-zA-Z0-9]{32,64}|sk-proj-[a-zA-Z0-9_-]{40,}",
            replacement_tag="[REDACTED_OPENAI_KEY]",
            description="OpenAI legacy and project secret keys",
        ),
        PatternSpec(
            pattern_id="anthropic_key",
            name="Anthropic API Key",
            category=SensitiveCategory.API_KEY,
            regex_pattern=r"sk-ant-[a-zA-Z0-9_-]{40,}",
            replacement_tag="[REDACTED_ANTHROPIC_KEY]",
            description="Anthropic Claude API key",
        ),
        PatternSpec(
            pattern_id="github_pat",
            name="GitHub Personal Access Token",
            category=SensitiveCategory.API_KEY,
            regex_pattern=r"ghp_[a-zA-Z0-9]{36}",
            replacement_tag="[REDACTED_GITHUB_PAT]",
            description="GitHub classical personal access token",
        ),
        PatternSpec(
            pattern_id="github_fine_grained",
            name="GitHub Fine-Grained Token",
            category=SensitiveCategory.API_KEY,
            regex_pattern=r"github_pat_[a-zA-Z0-9]{22}_[a-zA-Z0-9]{59}",
            replacement_tag="[REDACTED_GITHUB_PAT]",
            description="GitHub beta fine-grained access token",
        ),
        PatternSpec(
            pattern_id="github_oauth",
            name="GitHub OAuth Access Token",
            category=SensitiveCategory.API_KEY,
            regex_pattern=r"gho_[a-zA-Z0-9]{36}",
            replacement_tag="[REDACTED_GITHUB_TOKEN]",
            description="GitHub OAuth application user token",
        ),
        PatternSpec(
            pattern_id="github_refresh_token",
            name="GitHub Refresh Token",
            category=SensitiveCategory.API_KEY,
            regex_pattern=r"ghr_[a-zA-Z0-9]{36}",
            replacement_tag="[REDACTED_GITHUB_REFRESH_TOKEN]",
            description="GitHub user refresh token",
        ),
        PatternSpec(
            pattern_id="gitlab_pat",
            name="GitLab Personal Access Token",
            category=SensitiveCategory.API_KEY,
            regex_pattern=r"glpat-[a-zA-Z0-9\-_]{20,}",
            replacement_tag="[REDACTED_GITLAB_PAT]",
            description="GitLab personal access token",
        ),
        PatternSpec(
            pattern_id="huggingface_token",
            name="HuggingFace Token",
            category=SensitiveCategory.API_KEY,
            regex_pattern=r"hf_[a-zA-Z0-9]{34}",
            replacement_tag="[REDACTED_HF_TOKEN]",
            description="HuggingFace user API token",
        ),
        PatternSpec(
            pattern_id="npm_token",
            name="NPM Access Token",
            category=SensitiveCategory.API_KEY,
            regex_pattern=r"npm_[a-zA-Z0-9]{36}",
            replacement_tag="[REDACTED_NPM_TOKEN]",
            description="NPM registry automation token",
        ),
        PatternSpec(
            pattern_id="pypi_token",
            name="PyPI API Token",
            category=SensitiveCategory.API_KEY,
            regex_pattern=r"pypi-AgEIcHlwaS5vcmc[a-zA-Z0-9\-_]{50,}",
            replacement_tag="[REDACTED_PYPI_TOKEN]",
            description="Python Package Index publish token",
        ),
        # 11-18: Cloud Provider Credentials
        PatternSpec(
            pattern_id="aws_access_key_id",
            name="AWS Access Key ID",
            category=SensitiveCategory.CLOUD_CREDENTIAL,
            regex_pattern=r"\b(AKIA|ASIA|AROA)[0-9A-Z]{16}\b",
            replacement_tag="[REDACTED_AWS_KEY_ID]",
            description="Amazon Web Services access key identifier",
        ),
        PatternSpec(
            pattern_id="aws_secret_key",
            name="AWS Secret Access Key",
            category=SensitiveCategory.CLOUD_CREDENTIAL,
            regex_pattern=r"(?i)aws_secret_access_key\s*[:=]\s*['\"]?([a-zA-Z0-9/+=]{40})['\"]?",
            replacement_tag="[REDACTED_AWS_SECRET]",
            description="AWS 40-character secret access key assignment",
        ),
        PatternSpec(
            pattern_id="google_api_key",
            name="Google API Key",
            category=SensitiveCategory.CLOUD_CREDENTIAL,
            regex_pattern=r"AIza[0-9A-Za-z\-_]{35}",
            replacement_tag="[REDACTED_GOOGLE_KEY]",
            description="Google Cloud and Maps public/service key",
        ),
        PatternSpec(
            pattern_id="gcp_oauth",
            name="Google OAuth Access Token",
            category=SensitiveCategory.CLOUD_CREDENTIAL,
            regex_pattern=r"ya29\.[0-9A-Za-z\-_]{30,}",
            replacement_tag="[REDACTED_GCP_TOKEN]",
            description="Google Cloud temporary bearer token",
        ),
        PatternSpec(
            pattern_id="azure_subscription_key",
            name="Azure Subscription Key",
            category=SensitiveCategory.CLOUD_CREDENTIAL,
            regex_pattern=r"(?i)(azure[_\s-]?key|ocp-apim-subscription-key)\s*[:=]\s*['\"]?([a-f0-9]{32})['\"]?",
            replacement_tag="[REDACTED_AZURE_KEY]",
            description="Microsoft Azure API Management and Cognitive service key",
        ),
        # 16-24: SaaS & Messaging Integration Keys
        PatternSpec(
            pattern_id="slack_bot_token",
            name="Slack Bot Token",
            category=SensitiveCategory.API_KEY,
            regex_pattern=r"xoxb-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24}",
            replacement_tag="[REDACTED_SLACK_BOT_TOKEN]",
            description="Slack bot integration token",
        ),
        PatternSpec(
            pattern_id="slack_user_token",
            name="Slack User Token",
            category=SensitiveCategory.API_KEY,
            regex_pattern=r"xoxp-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24}",
            replacement_tag="[REDACTED_SLACK_USER_TOKEN]",
            description="Slack user API token",
        ),
        PatternSpec(
            pattern_id="slack_webhook",
            name="Slack Webhook URL",
            category=SensitiveCategory.API_KEY,
            regex_pattern=r"https://hooks\.slack\.com/services/T[0-9A-Z]{8,}/B[0-9A-Z]{8,}/[0-9A-Za-z]{24}",
            replacement_tag="[REDACTED_SLACK_WEBHOOK]",
            description="Slack incoming webhook secret URL",
        ),
        PatternSpec(
            pattern_id="discord_bot_token",
            name="Discord Bot Token",
            category=SensitiveCategory.API_KEY,
            regex_pattern=r"[MN][A-Za-z0-9]{23,25}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27}",
            replacement_tag="[REDACTED_DISCORD_TOKEN]",
            description="Discord bot gateway authentication token",
        ),
        PatternSpec(
            pattern_id="stripe_secret_key",
            name="Stripe Secret Key",
            category=SensitiveCategory.API_KEY,
            regex_pattern=r"sk_live_[0-9a-zA-Z]{24,34}",
            replacement_tag="[REDACTED_STRIPE_KEY]",
            description="Stripe production API secret key",
        ),
        PatternSpec(
            pattern_id="stripe_restricted_key",
            name="Stripe Restricted Key",
            category=SensitiveCategory.API_KEY,
            regex_pattern=r"rk_live_[0-9a-zA-Z]{24,34}",
            replacement_tag="[REDACTED_STRIPE_RK]",
            description="Stripe restricted permission key",
        ),
        PatternSpec(
            pattern_id="sendgrid_api_key",
            name="SendGrid API Key",
            category=SensitiveCategory.API_KEY,
            regex_pattern=r"SG\.[a-zA-Z0-9_\-\.]{60,70}",
            replacement_tag="[REDACTED_SENDGRID_KEY]",
            description="SendGrid email delivery service key",
        ),
        PatternSpec(
            pattern_id="twilio_api_key",
            name="Twilio API Key",
            category=SensitiveCategory.API_KEY,
            regex_pattern=r"\bSK[0-9a-fA-F]{32}\b",
            replacement_tag="[REDACTED_TWILIO_KEY]",
            description="Twilio developer API secret key",
        ),
        PatternSpec(
            pattern_id="mailgun_api_key",
            name="Mailgun API Key",
            category=SensitiveCategory.API_KEY,
            regex_pattern=r"key-[0-9a-zA-Z]{32}",
            replacement_tag="[REDACTED_MAILGUN_KEY]",
            description="Mailgun transaction email API key",
        ),
        # 25-30: Cryptographic Private Keys
        PatternSpec(
            pattern_id="rsa_private_key",
            name="RSA Private Key",
            category=SensitiveCategory.PRIVATE_KEY,
            regex_pattern=r"-----BEGIN RSA PRIVATE KEY-----[\s\S]+?-----END RSA PRIVATE KEY-----",
            replacement_tag="[REDACTED_RSA_PRIVATE_KEY]",
            description="PKCS#1 RSA private key block",
        ),
        PatternSpec(
            pattern_id="openssh_private_key",
            name="OpenSSH Private Key",
            category=SensitiveCategory.PRIVATE_KEY,
            regex_pattern=r"-----BEGIN OPENSSH PRIVATE KEY-----[\s\S]+?-----END OPENSSH PRIVATE KEY-----",
            replacement_tag="[REDACTED_OPENSSH_PRIVATE_KEY]",
            description="OpenSSH format private key block",
        ),
        PatternSpec(
            pattern_id="pgp_private_key",
            name="PGP Private Key",
            category=SensitiveCategory.PRIVATE_KEY,
            regex_pattern=r"-----BEGIN PGP PRIVATE KEY BLOCK-----[\s\S]+?-----END PGP PRIVATE KEY BLOCK-----",
            replacement_tag="[REDACTED_PGP_PRIVATE_KEY]",
            description="PGP/GPG encrypted private key block",
        ),
        PatternSpec(
            pattern_id="ec_private_key",
            name="EC Private Key",
            category=SensitiveCategory.PRIVATE_KEY,
            regex_pattern=r"-----BEGIN EC PRIVATE KEY-----[\s\S]+?-----END EC PRIVATE KEY-----",
            replacement_tag="[REDACTED_EC_PRIVATE_KEY]",
            description="Elliptic Curve private key block",
        ),
        PatternSpec(
            pattern_id="generic_private_key",
            name="Generic Private Key",
            category=SensitiveCategory.PRIVATE_KEY,
            regex_pattern=r"-----BEGIN PRIVATE KEY-----[\s\S]+?-----END PRIVATE KEY-----",
            replacement_tag="[REDACTED_PRIVATE_KEY]",
            description="Standard PKCS#8 unencrypted private key",
        ),
        # 30-33: Database Credentials & Generic Tokens
        PatternSpec(
            pattern_id="database_url_password",
            name="Database Connection Password",
            category=SensitiveCategory.DATABASE_URL,
            regex_pattern=r"(?i)(postgres|postgresql|mysql|mongodb|redis)://[^:\s]+:([^@\s]+)@",
            replacement_tag="[REDACTED_DB_PASSWORD]",
            description="Embedded database URI passwords",
        ),
        PatternSpec(
            pattern_id="jwt_token",
            name="JSON Web Token (JWT)",
            category=SensitiveCategory.TOKEN_JWT,
            regex_pattern=r"\beyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\b",
            replacement_tag="[REDACTED_JWT]",
            description="Three-part base64 encoded signed JWT",
        ),
        PatternSpec(
            pattern_id="vault_token",
            name="HashiCorp Vault Token",
            category=SensitiveCategory.TOKEN_JWT,
            regex_pattern=r"\bs\.[a-zA-Z0-9]{24}\b",
            replacement_tag="[REDACTED_VAULT_TOKEN]",
            description="HashiCorp Vault client root/service token",
        ),
        PatternSpec(
            pattern_id="shopify_shared_secret",
            name="Shopify Shared Secret",
            category=SensitiveCategory.API_KEY,
            regex_pattern=r"shpss_[a-fA-F0-9]{32}",
            replacement_tag="[REDACTED_SHOPIFY_SECRET]",
            description="Shopify partner app shared secret",
        ),
        PatternSpec(
            pattern_id="postman_api_key",
            name="Postman API Key",
            category=SensitiveCategory.API_KEY,
            regex_pattern=r"PMAK-[a-fA-F0-9]{24}-[a-fA-F0-9]{34}",
            replacement_tag="[REDACTED_POSTMAN_KEY]",
            description="Postman workspace access key",
        ),
        # 35-39: Financial & Credit Cards
        PatternSpec(
            pattern_id="credit_card_visa",
            name="Visa Credit Card",
            category=SensitiveCategory.PII_FINANCIAL,
            regex_pattern=r"\b4[0-9]{12}(?:[0-9]{3})?\b",
            replacement_tag="[REDACTED_CREDIT_CARD]",
            description="Standard 13 or 16 digit Visa card",
        ),
        PatternSpec(
            pattern_id="credit_card_mastercard",
            name="MasterCard",
            category=SensitiveCategory.PII_FINANCIAL,
            regex_pattern=r"\b5[1-5][0-9]{14}\b",
            replacement_tag="[REDACTED_CREDIT_CARD]",
            description="16 digit MasterCard standard number",
        ),
        PatternSpec(
            pattern_id="credit_card_amex",
            name="American Express Card",
            category=SensitiveCategory.PII_FINANCIAL,
            regex_pattern=r"\b3[47][0-9]{13}\b",
            replacement_tag="[REDACTED_CREDIT_CARD]",
            description="15 digit Amex card",
        ),
        # 38-41: National Identification Numbers
        PatternSpec(
            pattern_id="chinese_id_card",
            name="Chinese Citizen ID",
            category=SensitiveCategory.PII_ID,
            regex_pattern=r"\b[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b",
            replacement_tag="[REDACTED_CHINESE_ID]",
            description="18-digit Chinese resident ID number",
        ),
        PatternSpec(
            pattern_id="us_ssn",
            name="US Social Security Number",
            category=SensitiveCategory.PII_ID,
            regex_pattern=r"\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b",
            replacement_tag="[REDACTED_SSN]",
            description="Standard format US SSN (XXX-XX-XXXX)",
        ),
        # 40-45: Personal Contact & Direct Identifiers
        PatternSpec(
            pattern_id="chinese_phone",
            name="Chinese Mobile Phone",
            category=SensitiveCategory.PII_CONTACT,
            regex_pattern=r"\b(?:(?:\+|00)86)?1[3-9]\d{9}\b",
            replacement_tag="[REDACTED_PHONE_NUMBER]",
            description="11-digit mainland China mobile phone",
        ),
        PatternSpec(
            pattern_id="us_phone",
            name="North American Phone Number",
            category=SensitiveCategory.PII_CONTACT,
            regex_pattern=r"\b(?:\+1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
            replacement_tag="[REDACTED_PHONE_NUMBER]",
            description="10-digit North American telephone number",
        ),
        PatternSpec(
            pattern_id="email_address",
            name="Email Address",
            category=SensitiveCategory.PII_CONTACT,
            regex_pattern=r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
            replacement_tag="[REDACTED_EMAIL]",
            description="Standard internet email address",
        ),
        PatternSpec(
            pattern_id="square_access_token",
            name="Square Access Token",
            category=SensitiveCategory.API_KEY,
            regex_pattern=r"sq0atp-[0-9A-Za-z\-_]{22}",
            replacement_tag="[REDACTED_SQUARE_TOKEN]",
            description="Square Payments OAuth access token",
        ),
        PatternSpec(
            pattern_id="discord_webhook",
            name="Discord Webhook URL",
            category=SensitiveCategory.API_KEY,
            regex_pattern=r"https://discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]+",
            replacement_tag="[REDACTED_DISCORD_WEBHOOK]",
            description="Discord channel incoming webhook secret URL",
        ),
        PatternSpec(
            pattern_id="generic_bearer_token",
            name="Generic Bearer Secret Token",
            category=SensitiveCategory.API_KEY,
            regex_pattern=r"(?i)bearer\s+([a-zA-Z0-9_\-\.]{28,})",
            replacement_tag="[REDACTED_BEARER_TOKEN]",
            description="Explicit authorization bearer token sequence",
        ),
    ]
    return specs


_BUILTIN_SPECS = _build_builtin_specs()


def get_builtin_patterns() -> list[PatternSpec]:
    """Retrieve full catalog of 45 sensitive detection patterns."""
    return list(_BUILTIN_SPECS)


def get_compiled_patterns() -> list[CompiledPattern]:
    """Retrieve pre-compiled regex pattern objects."""
    compiled: list[CompiledPattern] = []
    for spec in _BUILTIN_SPECS:
        try:
            rgx = re.compile(spec.regex_pattern)
            compiled.append(CompiledPattern(spec=spec, compiled_regex=rgx))
        except re.error:
            continue
    return compiled
