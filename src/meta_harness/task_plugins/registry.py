from __future__ import annotations

from dataclasses import dataclass

from meta_harness.task_plugins.base import TaskPlugin
from meta_harness.task_plugins.classification import ClassificationTaskPlugin
from meta_harness.task_plugins.code_repair import CodeRepairTaskPlugin
from meta_harness.task_plugins.extraction import ExtractionTaskPlugin
from meta_harness.task_plugins.web_scrape import WebScrapeTaskPlugin


@dataclass(slots=True)
class _PluginEntry:
    plugin: TaskPlugin


_PLUGIN_REGISTRY: dict[str, _PluginEntry] = {}


def _normalize_plugin_id(plugin_id: str) -> str:
    return str(plugin_id).strip().replace("-", "_")


def register_task_plugin(plugin: TaskPlugin) -> TaskPlugin:
    normalized = _normalize_plugin_id(plugin.plugin_id)
    _PLUGIN_REGISTRY[normalized] = _PluginEntry(plugin=plugin)
    _PLUGIN_REGISTRY[str(plugin.plugin_id)] = _PluginEntry(plugin=plugin)
    return plugin


def get_task_plugin(plugin_id: str) -> TaskPlugin:
    normalized = _normalize_plugin_id(plugin_id)
    entry = _PLUGIN_REGISTRY.get(normalized) or _PLUGIN_REGISTRY.get(plugin_id)
    if entry is None:
        available = ", ".join(list_task_plugins())
        raise KeyError(
            f"unknown task plugin '{plugin_id}'"
            + (f"; available: {available}" if available else "")
        )
    return entry.plugin


def list_task_plugins() -> list[str]:
    ids = {entry.plugin.plugin_id for entry in _PLUGIN_REGISTRY.values()}
    return sorted(ids)


def ensure_default_task_plugins() -> None:
    if _PLUGIN_REGISTRY:
        return
    for plugin in (
        WebScrapeTaskPlugin(),
        CodeRepairTaskPlugin(),
        ExtractionTaskPlugin(),
        ClassificationTaskPlugin(),
    ):
        register_task_plugin(plugin)


ensure_default_task_plugins()
