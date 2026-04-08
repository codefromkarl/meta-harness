# External Strategy Evaluation

## 目标

这份文档说明如何把仓库外部发现的方法整理成 `strategy_card`，再接入 Meta-Harness 的通用 benchmark 流程。

公开版保留的是通用机制：

1. 用 `strategy_card` 表达外部方法
2. 做 compatibility 检查与 shortlist
3. 生成 benchmark spec 或直接跑 benchmark
4. 结合报告决定是否把方法物化为 candidate

仓库不再内置任何特定私有项目的策略资产或专属模板。

## Strategy Card

核心字段定义见 `src/meta_harness/schemas.py`：

- `strategy_id`
- `title`
- `source`
- `category`
- `group`
- `priority`
- `change_type`
- `variant_name`
- `hypothesis`
- `implementation_id`
- `variant_type`
- `compatibility`
- `expected_benefits`
- `expected_costs`
- `config_patch`
- `code_patch`
- `expected_signals`
- `risk_notes`
- `tags`

最常见的三类：

- `config_only`
- `patch_based`
- `not_yet_executable`

## 示例

下面是仓库内 `web_scrape` 方法卡的一个简化例子：

```json
{
  "strategy_id": "web_scrape/selector-only",
  "title": "Selector Only",
  "source": "reference://web_scrape/selector_only",
  "category": "web_scrape",
  "primitive_id": "web_scrape",
  "change_type": "config_only",
  "variant_type": "method_family",
  "variant_name": "selector_only",
  "hypothesis": "Stable recurring pages should avoid unnecessary AI hops.",
  "config_patch": {
    "workflow": {
      "primitives": {
        "web_scrape": {
          "pipeline": "selector_only",
          "timeout_ms": 5000
        }
      }
    }
  },
  "expected_signals": {
    "fingerprints": {
      "scrape.mode": "selector"
    }
  }
}
```

## CLI

直接从若干 strategy cards 生成 benchmark spec：

```bash
PYTHONPATH=src python -m meta_harness.cli strategy build-spec \
  --experiment web-scrape-methods \
  --baseline current_pipeline \
  --output configs/benchmarks/web_scrape_methods.json \
  configs/strategy_cards/web_scrape/selector_only.json \
  configs/strategy_cards/web_scrape/html_to_markdown_llm.json
```

查看 compatibility：

```bash
PYTHONPATH=src python -m meta_harness.cli strategy inspect \
  --profile demo_public \
  --project demo_public \
  --config-root configs \
  configs/strategy_cards/web_scrape/selector_only.json
```

批量 shortlist：

```bash
PYTHONPATH=src python -m meta_harness.cli strategy shortlist \
  --profile demo_public \
  --project demo_public \
  --config-root configs \
  configs/strategy_cards/web_scrape/html_to_markdown_llm.json \
  configs/strategy_cards/web_scrape/selector_only.json \
  configs/strategy_cards/web_scrape/vlm_visual_extract.json \
  configs/strategy_cards/web_scrape/headless_fingerprint_proxy.json
```

直接执行 benchmark：

```bash
PYTHONPATH=src python -m meta_harness.cli strategy benchmark \
  --profile demo_public \
  --project demo_public \
  --config-root configs \
  --runs-root runs \
  --candidates-root candidates \
  --task-set task_sets/demo/failure_repair.json \
  --experiment web-scrape-methods \
  --baseline current_pipeline \
  configs/strategy_cards/web_scrape/selector_only.json \
  configs/strategy_cards/web_scrape/html_to_markdown_llm.json
```

## 仓库内公开示例资产

- `configs/strategy_cards/web_scrape/html_to_markdown_llm.json`
- `configs/strategy_cards/web_scrape/selector_only.json`
- `configs/strategy_cards/web_scrape/vlm_visual_extract.json`
- `configs/strategy_cards/web_scrape/headless_fingerprint_proxy.json`
- `configs/primitives/web_scrape.json`
- `scripts/eval_web_scrape.py`

## 推荐流程

1. 先把外部方法整理成 `strategy_card`
2. 用 `strategy inspect` 看能否在当前 profile/project 下执行
3. 用 `strategy shortlist` 做初筛
4. 用 `strategy build-spec` 或 `strategy benchmark` 跑一轮通用评测
5. 只有结果稳定后，再把方法物化成 candidate 或 proposal
