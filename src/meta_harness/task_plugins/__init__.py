from __future__ import annotations

from meta_harness.task_plugins.base import BaseTaskPlugin, TaskPlugin
from meta_harness.task_plugins.classification import ClassificationTaskPlugin
from meta_harness.task_plugins.code_repair import CodeRepairTaskPlugin
from meta_harness.task_plugins.extraction import ExtractionTaskPlugin
from meta_harness.task_plugins.registry import (
    ensure_default_task_plugins,
    get_task_plugin,
    list_task_plugins,
    register_task_plugin,
)
from meta_harness.task_plugins.web_scrape import WebScrapeTaskPlugin

__all__ = [
    "BaseTaskPlugin",
    "ClassificationTaskPlugin",
    "CodeRepairTaskPlugin",
    "ExtractionTaskPlugin",
    "TaskPlugin",
    "WebScrapeTaskPlugin",
    "ensure_default_task_plugins",
    "get_task_plugin",
    "list_task_plugins",
    "register_task_plugin",
]
