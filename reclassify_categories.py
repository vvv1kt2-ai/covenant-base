"""One-off (rerunnable) migration: reclassify stored covenants into the unified 7-category taxonomy.

Deterministic and idempotent — safe to rerun after the classifier improves.
See covenant_models.reclassify_results for the rules.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from covenant_models import reclassify_results

if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "results.json"
    changed = reclassify_results(path)
    print(f"Reclassified {changed} covenant categories in {path}")
