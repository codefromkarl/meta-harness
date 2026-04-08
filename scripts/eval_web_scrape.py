from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from meta_harness.web_scrape_evaluator import evaluate_web_scrape_run


def main() -> None:
    print(json.dumps(evaluate_web_scrape_run(Path.cwd())))


if __name__ == "__main__":
    main()
