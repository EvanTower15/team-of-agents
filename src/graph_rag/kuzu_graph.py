"""
src/graph_rag/kuzu_graph.py — curated clinical reference lookup for 4 common
post-op surgeries (contraindications, rehab exercises, nutrient synergies),
with an optional real KuzuDB graph backing.

Honest status as shipped: ``kuzu`` is not in requirements.txt, so
``kuzu_available`` is always False in practice and every query method below
reads from the in-memory ``self.nodes`` dict, not a real graph traversal.
The schema/populate/query_contraindications Cypher methods exist for a real
KuzuDB backend but are currently unreachable from the rest of the codebase
(only ``query_multihop_chain`` is called, and it never touches ``self.conn``).
If you want the real graph DB path, add ``kuzu`` to requirements.txt and wire
a caller to ``query_contraindications`` instead.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Dict, Any

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
KUZU_DB_DIR = str(_REPO_ROOT / "kuzu_db")


class ClinicalGraphRAG:
    """Multi-hop property graph interface for clinical recovery relationships."""

    def __init__(self, db_path: str = KUZU_DB_DIR) -> None:
        self.db_path = db_path
        self.kuzu_available = False
        self._init_memory_graph()
        self._init_db()

    def _init_memory_graph(self) -> None:
        """Comprehensive clinical graph fallback supporting multi-hop queries."""
        self.nodes = {
            "surgeries": {
                "ACL Reconstruction": {
                    "procedure": "Anterior Cruciate Ligament Reconstruction",
                    "recovery_weeks": 24,
                    "rehab": ["quad sets", "straight leg raises", "heel slides", "stationary cycling"],
                    "contraindicates": ["heavy open kinetic chain knee extensions", "pivoting", "deep squatting > 90 deg", "jumping"],
                    "nutrients": ["Protein (2.0g/kg)", "Vitamin C (500mg)", "Collagen Peptides", "Zinc"],
                },
                "Meniscus Repair": {
                    "procedure": "Arthroscopic Meniscus Repair",
                    "recovery_weeks": 16,
                    "rehab": ["passive knee flexion", "quad isometric sets", "seated leg press (light)"],
                    "contraindicates": ["deep loaded squats > 90 deg", "impact running", "torsional pivoting"],
                    "nutrients": ["Omega-3 Fatty Acids (2000mg)", "Leucine", "Vitamin D", "Calcium"],
                },
                "Rotator Cuff Repair": {
                    "procedure": "Arthroscopic Rotator Cuff Repair",
                    "recovery_weeks": 20,
                    "rehab": ["Codman pendulum exercises", "scapular retraction", "passive shoulder elevation"],
                    "contraindicates": ["overhead lifting", "behind-the-neck shoulder press", "ballistic arm swinging"],
                    "nutrients": ["Protein (2.0g/kg)", "Vitamin C", "Vitamin D", "Magnesium"],
                },
                "Total Knee Arthroplasty": {
                    "procedure": "Total Knee Replacement",
                    "recovery_weeks": 26,
                    "rehab": ["ankle pumps", "quad sets", "seated knee flexion stretches"],
                    "contraindicates": ["high-impact jumping", "heavy deadlifts", "forceful knee hyperflexion"],
                    "nutrients": ["Calcium (1200mg)", "Vitamin D (2000 IU)", "Protein", "Zinc"],
                },
            },
            "injuries": {
                "ACL Tear": {"body_part": "knee", "rehab": ["quad sets", "hamstring curls", "proprioception balance training"]},
                "Rotator Cuff Tendonitis": {"body_part": "shoulder", "rehab": ["Codman pendulums", "wall slides", "external rotation with bands"]},
                "Patellofemoral Pain": {"body_part": "knee", "rehab": ["VMO quad strengthening", "hip abductor clamshells"]},
            },
            "nutrients": {
                "Vitamin C": {"category": "Vitamin", "synergy": "Collagen Peptides", "role": "Cross-links collagen fibers for tendon & ligament repair"},
                "Collagen Peptides": {"category": "Protein/Supplement", "synergy": "Vitamin C", "role": "Provides hydroxyproline substrate for joint tissue"},
                "Calcium": {"category": "Mineral", "synergy": "Vitamin D", "role": "Bone matrix remineralization & neuromuscular contraction"},
                "Vitamin D": {"category": "Vitamin", "synergy": "Calcium", "role": "Enhances intestinal calcium absorption & muscle protein synthesis"},
                "Omega-3 Fatty Acids": {"category": "Fatty Acid", "synergy": "Protein", "role": "Resolves systemic inflammation & attenuates muscle atrophy"},
            },
        }

    def _init_db(self) -> None:
        Path(self.db_path).mkdir(parents=True, exist_ok=True)
        try:
            import kuzu
            self.db = kuzu.Database(self.db_path)
            self.conn = kuzu.Connection(self.db)
            self.kuzu_available = True
            self._create_schema()
            self._populate_kuzu_nodes()
            print(f"[graph_rag] KuzuDB engine initialized at '{self.db_path}'.")
        except Exception as exc:
            # Expected in this repo as shipped: kuzu isn't in requirements.txt.
            # Logged (not silently swallowed) so it's clear from the console
            # that every query below is reading the static in-memory dict.
            self.kuzu_available = False
            print(f"[graph_rag] KuzuDB unavailable, using in-memory fallback data: {exc}")

    def _create_schema(self) -> None:
        if not self.kuzu_available:
            return
        try:
            self.conn.execute("CREATE NODE TABLE IF NOT EXISTS Surgery(name STRING, recovery_weeks INT64, PRIMARY KEY(name))")
            self.conn.execute("CREATE NODE TABLE IF NOT EXISTS Exercise(name STRING, PRIMARY KEY(name))")
            self.conn.execute("CREATE NODE TABLE IF NOT EXISTS Nutrient(name STRING, category STRING, PRIMARY KEY(name))")
            self.conn.execute("CREATE REL TABLE IF NOT EXISTS CONTRAINDICATES(FROM Surgery TO Exercise)")
            self.conn.execute("CREATE REL TABLE IF NOT EXISTS REQUIRES_REHAB(FROM Surgery TO Exercise)")
            self.conn.execute("CREATE REL TABLE IF NOT EXISTS SUPPORTS_HEALING(FROM Nutrient TO Surgery)")
        except Exception as e:
            print(f"[graph_rag] Schema create notice: {e}")

    def _populate_kuzu_nodes(self) -> None:
        if not self.kuzu_available:
            return
        try:
            for sname, sdata in self.nodes["surgeries"].items():
                self.conn.execute(
                    "MERGE (s:Surgery {name: $name}) ON CREATE SET s.recovery_weeks = $rw",
                    {"name": sname, "rw": sdata["recovery_weeks"]},
                )
                for ex in sdata["contraindicates"]:
                    self.conn.execute("MERGE (e:Exercise {name: $name})", {"name": ex})
                    self.conn.execute(
                        "MATCH (s:Surgery {name: $sname}), (e:Exercise {name: $ename}) "
                        "MERGE (s)-[:CONTRAINDICATES]->(e)",
                        {"sname": sname, "ename": ex},
                    )
                for ex in sdata["rehab"]:
                    self.conn.execute("MERGE (e:Exercise {name: $name})", {"name": ex})
                    self.conn.execute(
                        "MATCH (s:Surgery {name: $sname}), (e:Exercise {name: $ename}) "
                        "MERGE (s)-[:REQUIRES_REHAB]->(e)",
                        {"sname": sname, "ename": ex},
                    )
                for nut in sdata["nutrients"]:
                    self.conn.execute("MERGE (n:Nutrient {name: $name, category: 'Supplement'})", {"name": nut})
                    self.conn.execute(
                        "MATCH (n:Nutrient {name: $nname}), (s:Surgery {name: $sname}) "
                        "MERGE (n)-[:SUPPORTS_HEALING]->(s)",
                        {"nname": nut, "sname": sname},
                    )
        except Exception as exc:
            print(f"[graph_rag] Kuzu populate notice: {exc}")

    def fuzzy_match_surgery(self, query: str) -> str | None:
        """Fuzzy match a user query to known surgery/injury nodes."""
        q_lower = query.lower()
        if "rotator" in q_lower or "shoulder" in q_lower:
            return "Rotator Cuff Repair"
        if "meniscus" in q_lower:
            return "Meniscus Repair"
        if "arthroplasty" in q_lower or "replacement" in q_lower:
            return "Total Knee Arthroplasty"
        if "acl" in q_lower or "cruciate" in q_lower:
            return "ACL Reconstruction"

        best_match = None
        best_score = 0
        for sname in self.nodes["surgeries"]:
            words = set(sname.lower().split())
            score = sum(1 for w in words if w in q_lower)
            if score > best_score:
                best_score = score
                best_match = sname

        if best_score > 0:
            return best_match
        return None

    def query_contraindications(self, procedure_or_injury: str) -> List[str]:
        """Find exercises or activities contraindicated for a given surgery/injury."""
        match_key = self.fuzzy_match_surgery(procedure_or_injury)
        if match_key and match_key in self.nodes["surgeries"]:
            return self.nodes["surgeries"][match_key]["contraindicates"]

        if self.kuzu_available:
            try:
                res = self.conn.execute(
                    "MATCH (s:Surgery)-[:CONTRAINDICATES]->(e:Exercise) "
                    "WHERE lower(s.name) CONTAINS lower($proc) RETURN e.name",
                    {"proc": procedure_or_injury},
                )
                out = []
                while res.has_next():
                    out.append(res.get_next()[0])
                if out:
                    return out
            except Exception:
                pass

        return ["heavy open kinetic chain loading without clinician clearance"]

    def query_healing_nutrients(self, procedure_or_injury: str) -> List[str]:
        """Retrieve key healing nutrients for a surgery/injury."""
        match_key = self.fuzzy_match_surgery(procedure_or_injury)
        if match_key and match_key in self.nodes["surgeries"]:
            return self.nodes["surgeries"][match_key]["nutrients"]

        return ["Protein (2.0g/kg)", "Vitamin C", "Vitamin D", "Zinc"]

    def query_rehab_pathways(self, procedure_or_injury: str) -> List[str]:
        """Retrieve recommended rehabilitation exercises."""
        match_key = self.fuzzy_match_surgery(procedure_or_injury)
        if match_key and match_key in self.nodes["surgeries"]:
            return self.nodes["surgeries"][match_key]["rehab"]

        return ["gentle isometric contractions", "range of motion exercises"]

    def query_multihop_chain(self, query: str) -> Dict[str, Any]:
        """Look up curated contraindications/rehab/nutrients for a surgery
        mentioned in the query. Returns matched_entity=None (and no other
        fields) when nothing genuinely matches -- previously this defaulted
        to "ACL Reconstruction" unconditionally, which meant every synthesis
        call injected ACL-specific contraindications into completely
        unrelated questions (e.g. a beginner strength-program request would
        get "no pivoting, no deep squatting" stapled on). That silently
        violated this project's own grounding rule (§7.1: don't improvise
        content the question didn't ask for)."""
        matched_surgery = self.fuzzy_match_surgery(query)
        if not matched_surgery:
            return {"matched_entity": None}
        sdata = self.nodes["surgeries"][matched_surgery]

        # Multi-hop nutrient synergies
        nutrient_details = []
        for nut in sdata["nutrients"]:
            clean_nut = nut.split("(")[0].strip()
            syn = self.nodes["nutrients"].get(clean_nut, {}).get("synergy", "Protein")
            role = self.nodes["nutrients"].get(clean_nut, {}).get("role", "Accelerates tissue healing")
            nutrient_details.append({"nutrient": nut, "synergistic_pair": syn, "clinical_role": role})

        return {
            "matched_entity": matched_surgery,
            "procedure": sdata["procedure"],
            "recovery_timeline_weeks": sdata["recovery_weeks"],
            "rehab_exercises": sdata["rehab"],
            "contraindicated_movements": sdata["contraindicates"],
            "multihop_nutrient_pathways": nutrient_details,
        }


if __name__ == "__main__":
    graph = ClinicalGraphRAG()
    chain = graph.query_multihop_chain("I had ACL surgery on my knee")
    print("Multi-Hop Graph Pathway Result:")
    import json
    print(json.dumps(chain, indent=2))
