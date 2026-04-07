from __future__ import annotations

import json


def main() -> None:
    print(
        json.dumps(
            {
                "capability_scores": {
                    "web_scrape": {
                        "success_rate": 1.0,
                    }
                }
            }
        )
    )


if __name__ == "__main__":
    main()
