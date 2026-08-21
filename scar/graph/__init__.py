"""HydraDB ontology client and named OpenCypher operations."""

from scar.graph.client import GraphClient, hydra_is_ready
from scar.graph.queries import (
    blast_radius,
    export_graph,
    link_call,
    link_import,
    link_led_to,
    link_same_signature,
    recall_for_context,
    supersede_correction,
    upsert_correction,
    upsert_error,
    upsert_file,
    upsert_repo,
    upsert_session,
    upsert_symbol,
    upsert_turn,
)
from scar.graph.schema import apply_schema

__all__ = [
    "GraphClient",
    "apply_schema",
    "blast_radius",
    "export_graph",
    "hydra_is_ready",
    "link_call",
    "link_import",
    "link_led_to",
    "link_same_signature",
    "recall_for_context",
    "supersede_correction",
    "upsert_correction",
    "upsert_error",
    "upsert_file",
    "upsert_repo",
    "upsert_session",
    "upsert_symbol",
    "upsert_turn",
]
