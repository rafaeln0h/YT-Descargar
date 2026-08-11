"""Single source of truth for the application release."""

VERSION = "0.013"
RELEASE_TAG = f"v{VERSION}"
RELEASE_CHANNEL = "stable"


def version_payload() -> dict[str, str]:
    return {
        "version": VERSION,
        "tag": RELEASE_TAG,
        "channel": RELEASE_CHANNEL,
    }
