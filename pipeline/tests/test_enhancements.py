"""
Testy nových rozšíření pro zvýšení přesnosti a informovanosti (Fáze A a C):
- A1: TimeFrame penalizace a extrakce letopočtu
- A2: Detekce politických rolí (vláda vs. opozice)
- A3: Sněmovní tisky (TiskyRegistry)
- C1 & C3: Index konzistence (SCI) a pásma spolehlivosti
"""

from datetime import date
import pytest

from psp.client import PspClient
from psp.opendata import Registry
from psp.tisky import TiskyRegistry
from retrieval import _extract_year, CandidatePair, retrieve_candidates
from scoring import compute_sci, sci_label, compute_flip_attribution, FLIP_COALITION_COMPROMISE, FLIP_EXTERNAL_SHOCK, FLIP_OPPORTUNISTIC


# ---------------------------------------------------------------------------
# A1: TimeFrame extrakce a penalizace
# ---------------------------------------------------------------------------

class TestTimeFrameExtraction:
    def test_extract_year_valid(self):
        assert _extract_year("v roce 2023") == 2023
        assert _extract_year("2025") == 2025
        assert _extract_year("listopad 2021") == 2021

    def test_extract_year_invalid_or_empty(self):
        assert _extract_year("NEURČENO") is None
        assert _extract_year("") is None
        assert _extract_year("dnes") is None
        assert _extract_year("včera v rozpravě") is None


class TestTimeFrameRetrievalPenalty:
    class FakeEncoder:
        def embed(self, texts):
            import numpy as np
            # Jednoduché dummy embeddingy
            n = len(texts)
            vecs = np.ones((n, 4))
            for i in range(n):
                vecs[i] = vecs[i] / np.linalg.norm(vecs[i])
            return vecs

    def test_timeframe_conflict_penalized(self):
        encoder = self.FakeEncoder()
        query = {
            "claimId": "q1",
            "speakerIdOsoba": "spk1",
            "text": "Daně nezvýšíme.",
            "timeFrame": "v roce 2025",
        }
        corpus = [
            {
                "claimId": "c1",
                "speakerIdOsoba": "spk1",
                "text": "Daně nezvýšíme.",
                "timeFrame": "v roce 2022",  # jiný rok -> penalizace
            },
            {
                "claimId": "c2",
                "speakerIdOsoba": "spk1",
                "text": "Daně nezvýšíme.",
                "timeFrame": "v roce 2025",  # stejný rok -> bez penalizace
            },
        ]
        results = retrieve_candidates(query, corpus, encoder, top_k=2, timeframe_penalty=0.10)
        assert len(results) == 2
        # c2 má stejný rok, měl by mít vyšší skóre než c1
        assert results[0].candidate_claim_id == "c2"
        assert results[0].timeframe_conflict is False
        assert results[1].candidate_claim_id == "c1"
        assert results[1].timeframe_conflict is True


# ---------------------------------------------------------------------------
# A2: Politické role (vláda vs. opozice)
# ---------------------------------------------------------------------------

class TestPoliticalRoles:
    def test_registry_loads_governments_and_roles(self):
        client = PspClient()
        reg = Registry.load(client)

        # Babiš (6150): v říjnu 2025 opozice, v lednu 2026 člen vlády
        role_babis_2025 = reg.political_role_at("6150", date(2025, 10, 1))
        assert role_babis_2025["isGovernment"] is False
        assert role_babis_2025["role"] == "OPPOSITION_DEPUTY"

        role_babis_2026 = reg.political_role_at("6150", date(2026, 1, 15))
        assert role_babis_2026["isGovernment"] is True
        assert role_babis_2026["role"] == "MINISTER"

        # Fiala (6074): v říjnu 2025 člen vlády, v lednu 2026 opozice
        role_fiala_2025 = reg.political_role_at("6074", date(2025, 10, 1))
        assert role_fiala_2025["isGovernment"] is True
        assert role_fiala_2025["role"] == "MINISTER"

        role_fiala_2026 = reg.political_role_at("6074", date(2026, 1, 15))
        assert role_fiala_2026["isGovernment"] is False
        assert role_fiala_2026["role"] == "OPPOSITION_DEPUTY"


# ---------------------------------------------------------------------------
# A3: Sněmovní tisky
# ---------------------------------------------------------------------------

class TestTiskyRegistry:
    def test_parse_debate_tisk_numbers_and_phases(self):
        reg = TiskyRegistry.load()
        title1 = "6. Vládní návrh zákona, kterým se mění některé zákony v oblasti veřejných rozpočtů /sněmovní tisk 90/ – prvé čtení dle § 90 odst. 2"
        res1 = reg.parse_debate_tisk(title1)
        assert res1 is not None
        assert res1["cisloTisku"] == "90"
        assert res1["faze"] == "1. čtení"
        assert "rozpočt" in res1["nazev"].lower()

        title2 = "5. Návrh poslance Andreje Babiše na vydání zákona... /sněmovní tisk 78/ – prvé čtení dle § 90 odst. 2"
        res2 = reg.parse_debate_tisk(title2)
        assert res2 is not None
        assert res2["cisloTisku"] == "78"
        assert res2["faze"] == "1. čtení"

        title3 = "1. Projednání návrhu na vyslovení nedůvěry vládě České republiky"
        res3 = reg.parse_debate_tisk(title3)
        assert res3 is not None
        assert res3["faze"] == "Hlasování o nedůvěře"


# ---------------------------------------------------------------------------
# C1 & C3: SCI index a Flip Attribution
# ---------------------------------------------------------------------------

class TestSciAndFlipAttribution:
    def test_sci_calculation(self):
        assert compute_sci(0, []) == 1.0
        assert compute_sci(10, []) == 1.0
        # 10 závazků, 2 podstatné rozpory (0.90, 0.90) -> 1 - (1.8/10) = 0.82
        sci = compute_sci(10, [0.90, 0.90])
        assert abs(sci - 0.82) < 1e-4
        assert sci_label(sci) == "Znatelné obraty v čase"
        assert sci_label(0.88) == "Mírně proměnlivé postoje"
        assert sci_label(0.96) == "Vysoká konzistence"

    def test_flip_attribution(self):
        attr_coalition = compute_flip_attribution(
            arbiter_rationale="Šlo o koaliční kompromis při schvalování rozpočtu.",
            defense_evaluated="",
        )
        assert attr_coalition == FLIP_COALITION_COMPROMISE

        attr_shock = compute_flip_attribution(
            arbiter_rationale="Poslanec reagoval na neočekávaný inflační šok a růst cen energií.",
            defense_evaluated="",
            macro_context_available=True,
        )
        assert attr_shock == FLIP_EXTERNAL_SHOCK
