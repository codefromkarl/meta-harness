from __future__ import annotations

import json
from pathlib import Path

TARGET_PROJECT_PATH = Path("/home/yuanzhi/Develop/tools/rtk")


def main() -> int:
    # TODO: attach or launch the browser automation flow (Playwright / Selenium).
    # TODO: reuse login state if required and persist page.html plus extracted.json.
    draft = {
        "reply": {
            "page_html": "",
            "extracted": {},
            "_draft": {
                "mode": "browser_automation",
                "playwright": "pending implementation",
                "target_project_path": str(TARGET_PROJECT_PATH),
            },
        }
    }
    print(json.dumps(draft, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
