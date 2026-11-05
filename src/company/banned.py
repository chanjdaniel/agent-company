"""The model-provider and broker variables no session may hold and no tracked file may name, in one place.

The launcher reads this at run time, and the scan builds its rule from it.
So this file joins the scan's own files, as the one place in the package that names what it bans.
"""

import re

VENDORS = ("ANTHROPIC", "OPENAI", "GEMINI", "GOOGLE", "MISTRAL", "COHERE", "OPENROUTER", "GROQ", "DEEPSEEK", "XAI", "TOGETHER")
_VENDOR_KEYS = ("API_KEY", "AUTH_TOKEN", "BASE_URL")
_PROVIDERS = ("BEDROCK", "VERTEX", "FOUNDRY")

VARIABLES = (
    *(f"{vendor}_{key}" for vendor in VENDORS for key in _VENDOR_KEYS),
    *(f"CLAUDE_CODE_USE_{provider}" for provider in _PROVIDERS),
    "CLAUDE_CODE_OAUTH_TOKEN",
    "AWS_BEARER_TOKEN_BEDROCK",
)

# What the scan looks for in a tracked file.
MODEL_KEY_VARIABLE = re.compile(
    rf"\b(?:{'|'.join(VENDORS)})_(?:{'|'.join(_VENDOR_KEYS)})\b"
    rf"|\bCLAUDE_CODE_USE_(?:{'|'.join(_PROVIDERS)})\b"
    r"|\bCLAUDE_CODE_OAUTH_TOKEN\b"
    r"|\bAWS_BEARER_TOKEN_BEDROCK\b"
)

# The variables a broker's own tools read its credentials and host from, live ones among them. The key lives only in its file.
BROKER_KEY_VARIABLE = re.compile(r"\bAPCA_[A-Z_]+\b")

# Wider at run time than in a file: whatever else picks a provider or an account under these prefixes goes too.
_PREFIXES = ("ANTHROPIC_", "CLAUDE_CODE_USE_", "APCA_")


def is_banned(name: str) -> bool:
    """Whether this variable may not reach a session."""
    return name in VARIABLES or name.startswith(_PREFIXES)
