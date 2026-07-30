"""
src/graph_rag/schema.py — GraphRAG Property Graph Schema.

Defines clinical entity nodes and relationship edges for multi-hop graph queries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class NodeSchema:
    name: str
    properties: Dict[str, str]


@dataclass
class RelSchema:
    name: str
    src_node: str
    dst_node: str
    properties: Dict[str, str] = field(default_factory=dict)


CLINICAL_GRAPH_NODES = [
    NodeSchema("Injury", {"name": "STRING", "body_part": "STRING", "severity": "STRING"}),
    NodeSchema("Surgery", {"name": "STRING", "procedure": "STRING", "recovery_weeks": "INT64"}),
    NodeSchema("Exercise", {"name": "STRING", "target_muscle": "STRING", "joint_impact": "STRING"}),
    NodeSchema("Nutrient", {"name": "STRING", "category": "STRING", "daily_target": "STRING"}),
    NodeSchema("Restriction", {"name": "STRING", "precaution": "STRING", "duration": "STRING"}),
]

CLINICAL_GRAPH_RELS = [
    RelSchema("REQUIRES_REHAB", "Surgery", "Exercise"),
    RelSchema("CONTRAINDICATES", "Restriction", "Exercise"),
    RelSchema("SUPPORTS_HEALING", "Nutrient", "Surgery"),
    RelSchema("TARGETS_INJURY", "Exercise", "Injury"),
    RelSchema("SYNERGIZES_WITH", "Nutrient", "Nutrient"),
]
