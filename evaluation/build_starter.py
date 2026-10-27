"""Rebuild an explicitly synthetic corpus, split by document, without real issuers."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "datasets" / "synthetic-v0.1"


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    facts = []
    documents = []
    for i in range(1, 6):
        source_id = f"synthetic-{i}"
        split = "train" if i <= 3 else "dev" if i == 4 else "holdout"
        metrics = {"revenue": str(1000 + i*50), "net_income": str(100+i*10),
                   "credit_losses": str(-20-i), "active_customers": str(200000+i*1000)}
        lines = ["SYNTHETIC TEST DOCUMENT. NOT A REAL COMPANY.",
                 f"Example Bank {i} | FY 2025", "Financial values: USD millions. Customers: persons."]
        for metric, value in metrics.items():
            lines.append(f"{metric}: {value}")
            facts.append({
                "id": f"{source_id}-{metric}", "company": f"Example Bank {i}",
                "metric": metric, "period": "FY2025",
                "currency": "N/A" if metric == "active_customers" else "USD",
                "unit": "persons" if metric == "active_customers" else "money",
                "scale": "one" if metric == "active_customers" else "million",
                "source_id": source_id, "locator": f"line:{len(lines)}",
                "value": value, "abs_tolerance": "0", "split": split,
                "review_state": "synthetic_unreviewed",
            })
        content = "\n".join(lines) + "\n"
        file = ROOT / f"{source_id}.txt"
        file.write_text(content, encoding="utf-8")
        documents.append({"source_id": source_id, "file": file.name, "split": split,
                          "sha256": hashlib.sha256(content.encode()).hexdigest()})
    for split in ("train", "dev", "holdout"):
        (ROOT / f"{split}.json").write_text(json.dumps(
            [f for f in facts if f["split"] == split], indent=2) + "\n", encoding="utf-8")
    (ROOT / "manifest.json").write_text(json.dumps({
        "version": "0.1", "synthetic": True, "production_qualified": False,
        "documents": documents, "facts": len(facts),
        "reviewers": [], "real_corpus_status": "awaiting_independent_annotation",
    }, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
