"""LinkedIn destination — publishes via linkin-bot's POST /post gateway."""

from .publisher import LinkedInPublisher
from .status import (
    LinkedInStatusError,
)
from .status import (
    fetch_payload as fetch_status_payload,
)
from .status import (
    get_status as get_linkedin_status,
)
from .status import (
    is_configured as linkedin_configured,
)
from .status import (
    status_url as linkedin_status_url,
)
from .status import (
    summarize as summarize_linkedin_status,
)

__all__ = [
    "LinkedInPublisher",
    "LinkedInStatusError",
    "fetch_status_payload",
    "get_linkedin_status",
    "linkedin_configured",
    "linkedin_status_url",
    "summarize_linkedin_status",
]
