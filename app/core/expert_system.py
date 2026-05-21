import json
from pathlib import Path
from app.models.schemas import NursingAssessment, ExpertRecommendation


class NursingExpertSystem:
    def __init__(self, kb_path: str = "data/nanda_nic_noc.json") -> None:
        self.kb_path = Path(kb_path)
        self.rules = self._load_rules()

    def _load_rules(self) -> list[dict]:
        with self.kb_path.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data.get("rules", [])

    def infer(self, assessment: NursingAssessment) -> list[ExpertRecommendation]:
        text_pool = " ".join(assessment.complaints + assessment.observations).lower()
        results: list[ExpertRecommendation] = []

        for rule in self.rules:
            hits = sum(1 for trigger in rule["triggers"] if trigger.lower() in text_pool)
            if hits == 0:
                continue

            confidence = min(1.0, hits / max(1, len(rule["triggers"])))
            results.append(
                ExpertRecommendation(
                    nanda_code=rule["nanda_code"],
                    nanda_label=rule["nanda_label"],
                    confidence=round(confidence, 2),
                    nic=rule["nic"],
                    noc=rule["noc"],
                )
            )

        return sorted(results, key=lambda x: x.confidence, reverse=True)
