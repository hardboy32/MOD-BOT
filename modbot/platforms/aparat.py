"""Aparat adapter safety boundary.

A supported public API for live-chat ingestion and message moderation could not
be verified. Failing closed is safer than scraping undocumented private APIs.
"""
class AparatAdapter:
    def __init__(self, *args, **kwargs):
        raise RuntimeError(
            "Aparat integration is pending: no verified supported public API "
            "for reading live chat and deleting/timing out/banning users is available."
        )
