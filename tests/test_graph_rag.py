"""
tests/test_graph_rag.py — Comprehensive Unit & Integration Test Suite for GraphRAG.

Tests property graph schemas, multi-hop relationship traversals, fuzzy entity matching,
and fallback resilience across all surgical & clinical recovery domains.
"""

import pytest
from src.graph_rag.schema import CLINICAL_GRAPH_NODES, CLINICAL_GRAPH_RELS
from src.graph_rag.kuzu_graph import ClinicalGraphRAG


def test_graph_schema_definitions():
    """Verify property graph node and relationship definitions."""
    assert len(CLINICAL_GRAPH_NODES) >= 5
    assert len(CLINICAL_GRAPH_RELS) >= 4

    node_names = [n.name for n in CLINICAL_GRAPH_NODES]
    assert "Surgery" in node_names
    assert "Exercise" in node_names
    assert "Nutrient" in node_names

    rel_names = [r.name for r in CLINICAL_GRAPH_RELS]
    assert "CONTRAINDICATES" in rel_names
    assert "REQUIRES_REHAB" in rel_names
    assert "SUPPORTS_HEALING" in rel_names


def test_graph_rag_instantiation():
    """Test ClinicalGraphRAG engine initialization."""
    graph = ClinicalGraphRAG()
    assert graph is not None
    assert hasattr(graph, "query_contraindications")
    assert hasattr(graph, "query_multihop_chain")


@pytest.mark.parametrize(
    "query,expected_node",
    [
        ("I torn my ACL during soccer", "ACL Reconstruction"),
        ("Shoulder rotator cuff repair surgery", "Rotator Cuff Repair"),
        ("Meniscus tear knee pain", "Meniscus Repair"),
        ("Total knee replacement", "Total Knee Arthroplasty"),
    ],
)
def test_fuzzy_entity_matching(query, expected_node):
    """Test fuzzy entity resolution for ambiguous clinical queries."""
    graph = ClinicalGraphRAG()
    matched = graph.fuzzy_match_surgery(query)
    assert matched == expected_node


def test_query_contraindications():
    """Test contraindications traversal for surgical procedures."""
    graph = ClinicalGraphRAG()
    res = graph.query_contraindications("ACL Reconstruction")
    assert isinstance(res, list)
    assert len(res) > 0
    assert any("squat" in c.lower() or "chain" in c.lower() or "pivot" in c.lower() for c in res)


def test_query_healing_nutrients():
    """Test nutrient retrieval for healing pathways."""
    graph = ClinicalGraphRAG()
    res = graph.query_healing_nutrients("Rotator Cuff Repair")
    assert isinstance(res, list)
    assert len(res) > 0
    assert any("Protein" in n or "Vitamin" in n or "Collagen" in n for n in res)


def test_query_rehab_pathways():
    """Test rehabilitation exercise retrieval."""
    graph = ClinicalGraphRAG()
    res = graph.query_rehab_pathways("ACL Reconstruction")
    assert isinstance(res, list)
    assert len(res) > 0
    assert any("quad" in r.lower() or "leg raise" in r.lower() for r in res)


def test_multihop_chain_traversal():
    """Test full 3-hop graph traversal (Surgery -> Rehab -> Nutrients -> Synergies -> Contraindications)."""
    graph = ClinicalGraphRAG()
    chain = graph.query_multihop_chain("ACL surgery recovery")

    assert isinstance(chain, dict)
    assert chain["matched_entity"] == "ACL Reconstruction"
    assert "recovery_timeline_weeks" in chain
    assert len(chain["rehab_exercises"]) > 0
    assert len(chain["contraindicated_movements"]) > 0
    assert len(chain["multihop_nutrient_pathways"]) > 0

    # Verify nutrient synergistic pair multi-hop connection
    first_nutrient = chain["multihop_nutrient_pathways"][0]
    assert "nutrient" in first_nutrient
    assert "synergistic_pair" in first_nutrient
    assert "clinical_role" in first_nutrient


def test_unknown_entity_graceful_fallback():
    """Test graceful handling of unknown or unmapped entities."""
    graph = ClinicalGraphRAG()
    res = graph.query_contraindications("unmapped_obscure_condition_123")
    assert isinstance(res, list)
    assert len(res) > 0
    assert "clinician clearance" in res[0].lower() or "heavy loading" in res[0].lower()
