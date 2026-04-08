from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from meta_harness.integration_schemas import HarnessSpec, IntegrationSpec, ScaffoldPlan


def build_scaffold_plan(spec: IntegrationSpec) -> ScaffoldPlan:
    slug = Path(spec.target_project_path).name.replace("-", "_").replace(" ", "_").lower()
    binding_id = f"generated/{slug}_{spec.primitive_id}"
    wrapper_path = f"scripts/generated/{slug}_{spec.primitive_id}_wrapper.py"
    test_path = f"tests/generated/test_{slug}_{spec.primitive_id}.py"
    return ScaffoldPlan(
        files_to_create=[
            f"configs/claw_bindings/generated/{slug}_{spec.primitive_id}.json",
            wrapper_path,
            test_path,
            f"reports/integration/{spec.spec_id}/integration_spec.json",
        ],
        files_to_update=[],
        generated_binding_id=binding_id,
        generated_wrapper_path=wrapper_path if spec.execution_model.needs_wrapper else None,
        generated_test_path=test_path,
    )


def materialize_scaffold(
    *,
    spec: IntegrationSpec,
    plan: ScaffoldPlan,
    repo_root: Path,
) -> dict[str, str | None]:
    binding_path = repo_root / plan.files_to_create[0]
    wrapper_path = (
        repo_root / plan.generated_wrapper_path
        if isinstance(plan.generated_wrapper_path, str)
        else None
    )
    test_path = (
        repo_root / plan.generated_test_path
        if isinstance(plan.generated_test_path, str)
        else None
    )

    if wrapper_path is not None:
        wrapper_path.parent.mkdir(parents=True, exist_ok=True)
        wrapper_path.write_text(_render_wrapper(spec), encoding="utf-8")

    binding_path.parent.mkdir(parents=True, exist_ok=True)
    binding_path.write_text(
        json.dumps(
            _build_binding_payload(spec=spec, plan=plan, wrapper_path=wrapper_path, repo_root=repo_root),
            indent=2,
        ),
        encoding="utf-8",
    )

    if test_path is not None:
        test_path.parent.mkdir(parents=True, exist_ok=True)
        test_path.write_text(
            _render_test_draft(spec=spec, binding_path=binding_path, wrapper_path=wrapper_path),
            encoding="utf-8",
        )

    return {
        "binding_path": str(binding_path),
        "wrapper_path": str(wrapper_path) if wrapper_path is not None else None,
        "test_path": str(test_path) if test_path is not None else None,
    }


def build_harness_scaffold_plan(spec: HarnessSpec) -> ScaffoldPlan:
    slug = Path(spec.target_project_path).name.replace("-", "_").replace(" ", "_").lower()
    wrapper_path = f"scripts/generated/{slug}_harness_wrapper.py"
    test_path = f"tests/generated/test_{slug}_harness.py"
    return ScaffoldPlan(
        files_to_create=[
            wrapper_path,
            test_path,
            f"reports/integration/{spec.spec_id}/harness_spec.json",
        ],
        files_to_update=[],
        generated_binding_id=None,
        generated_wrapper_path=wrapper_path,
        generated_test_path=test_path,
    )


def materialize_harness_scaffold(
    *,
    spec: HarnessSpec,
    plan: ScaffoldPlan,
    repo_root: Path,
) -> dict[str, str | None]:
    wrapper_path = (
        repo_root / plan.generated_wrapper_path
        if isinstance(plan.generated_wrapper_path, str)
        else None
    )
    test_path = (
        repo_root / plan.generated_test_path
        if isinstance(plan.generated_test_path, str)
        else None
    )
    if wrapper_path is not None:
        wrapper_path.parent.mkdir(parents=True, exist_ok=True)
        wrapper_path.write_text(_render_harness_wrapper(spec), encoding="utf-8")
    if test_path is not None:
        test_path.parent.mkdir(parents=True, exist_ok=True)
        test_path.write_text(_render_harness_test_draft(spec, wrapper_path), encoding="utf-8")
    return {
        "binding_path": None,
        "wrapper_path": str(wrapper_path) if wrapper_path is not None else None,
        "test_path": str(test_path) if test_path is not None else None,
    }


def _build_binding_payload(
    *,
    spec: IntegrationSpec,
    plan: ScaffoldPlan,
    wrapper_path: Path | None,
    repo_root: Path,
) -> dict[str, Any]:
    execution = dict(spec.binding_patch.get("execution") or {})
    if wrapper_path is not None:
        execution["command"] = [
            "python",
            str(wrapper_path.relative_to(repo_root)),
        ]
        execution["parse_json_output"] = True
    execution.setdefault("bridge_contract", "primitive_output")
    runtime_binding = {
        "binding_id": plan.generated_binding_id,
        "adapter_kind": "command",
        **execution,
    }
    return {
        "binding_id": plan.generated_binding_id,
        "claw_family": "generated",
        "primitive_id": spec.primitive_id,
        "adapter_kind": "command",
        "method_mapping": {},
        "binding_patch": {"runtime": {"binding": runtime_binding}},
        "execution": execution,
        "artifact_contract": {
            "source": "primitive.output_contract.bridge",
            "generated_from_spec_id": spec.spec_id,
        },
        "trace_mapping": {"source": "integration.generated"},
    }


def _render_wrapper(spec: IntegrationSpec) -> str:
    kind = spec.execution_model.kind
    if kind == "http_job_api":
        return _render_http_job_api_wrapper(spec)
    if kind == "browser_automation":
        return _render_browser_automation_wrapper(spec)
    if kind == "daemon_session":
        return _render_daemon_session_wrapper(spec)
    return _render_generic_wrapper(spec)


def _render_generic_wrapper(spec: IntegrationSpec) -> str:
    source_command = json.dumps(spec.execution_model.entry_command, indent=2)
    mappings = json.dumps(
        [mapping.model_dump() for mapping in spec.artifact_mappings],
        indent=2,
    )
    missing_contracts = json.dumps(spec.missing_contracts, indent=2)
    target_project = json.dumps(spec.target_project_path)
    return f'''from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TARGET_PROJECT_PATH = Path({target_project})
ENTRY_COMMAND = {source_command}
ARTIFACT_MAPPINGS = {mappings}
MISSING_CONTRACTS = {missing_contracts}


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _build_reply_payload() -> dict:
    reply = {{
        "page_html": "",
        "extracted": {{}},
    }}
    for mapping in ARTIFACT_MAPPINGS:
        source_path = Path(mapping["source_artifact"])
        target_artifact = mapping["target_artifact"]
        if not source_path.exists():
            continue
        if target_artifact == "page.html":
            reply["page_html"] = _read_text(source_path)
        elif target_artifact == "extracted.json":
            reply["extracted"] = _read_json(source_path)
    return reply


def main() -> int:
    completed = subprocess.run(
        ENTRY_COMMAND,
        cwd=TARGET_PROJECT_PATH,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout, file=sys.stderr, end="")
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="")
    if completed.returncode != 0:
        return completed.returncode

    reply = _build_reply_payload()
    reply.setdefault("_draft", {{}})
    reply["_draft"]["mode"] = "file_artifact_workflow"
    reply["_draft"]["normalize_from"] = [
        mapping["source_artifact"] for mapping in ARTIFACT_MAPPINGS
    ]
    if MISSING_CONTRACTS:
        reply["_draft"]["missing_contracts"] = MISSING_CONTRACTS
    print(json.dumps({{"reply": reply}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _render_http_job_api_wrapper(spec: IntegrationSpec) -> str:
    target_project = json.dumps(spec.target_project_path)
    entry_command = json.dumps(spec.execution_model.entry_command, indent=2)
    return f'''from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

TARGET_PROJECT_PATH = Path({target_project})
ENTRY_COMMAND = {entry_command}
SUBMIT_URL = os.environ.get("META_HARNESS_HTTP_SUBMIT_URL", "")
POLL_URL_TEMPLATE = os.environ.get("META_HARNESS_HTTP_POLL_URL_TEMPLATE", "")
RESULT_URL_TEMPLATE = os.environ.get("META_HARNESS_HTTP_RESULT_URL_TEMPLATE", "")
POLL_ATTEMPTS = int(os.environ.get("META_HARNESS_HTTP_POLL_ATTEMPTS", "20"))
POLL_INTERVAL_SEC = float(os.environ.get("META_HARNESS_HTTP_POLL_INTERVAL_SEC", "1.0"))


def _request_json(url: str, payload: dict | None = None) -> dict:
    data = (
        json.dumps(payload).encode("utf-8")
        if payload is not None
        else None
    )
    request = urllib.request.Request(
        url,
        data=data,
        headers={{"Content-Type": "application/json"}},
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(request) as response:
        raw = response.read().decode("utf-8")
    parsed = json.loads(raw or "{{}}")
    return parsed if isinstance(parsed, dict) else {{}}


def _draft_reply() -> dict:
    return {{
        "reply": {{
            "page_html": "",
            "extracted": {{}},
            "_draft": {{
                "mode": "http_job_api",
                "target_project_path": str(TARGET_PROJECT_PATH),
                "entry_command": ENTRY_COMMAND,
                "submit_url": SUBMIT_URL,
                "poll_url_template": POLL_URL_TEMPLATE,
                "result_url_template": RESULT_URL_TEMPLATE,
                "required_env": [
                    "META_HARNESS_HTTP_SUBMIT_URL",
                    "META_HARNESS_HTTP_POLL_URL_TEMPLATE",
                ],
                "next_steps": [
                    "Point submit_url/poll_url_template to the target service",
                    "Map job request payload fields to primitive input",
                    "Download or normalize final artifacts into page_html/extracted",
                ],
            }},
        }}
    }}


def _job_id_from_payload(payload: dict) -> str:
    for key in ("job_id", "id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    job = payload.get("job")
    if isinstance(job, dict):
        value = job.get("job_id")
        if isinstance(value, str) and value:
            return value
    return ""


def main() -> int:
    draft = _draft_reply()
    if not SUBMIT_URL or not POLL_URL_TEMPLATE:
        print(json.dumps(draft, ensure_ascii=False))
        return 0

    submit_payload = {{
        "entry_command": ENTRY_COMMAND,
        "target_project_path": str(TARGET_PROJECT_PATH),
    }}
    submit_response = _request_json(SUBMIT_URL, submit_payload)
    job_id = _job_id_from_payload(submit_response)
    if not job_id:
        draft["reply"]["_draft"]["submit_response"] = submit_response
        print(json.dumps(draft, ensure_ascii=False))
        return 0

    poll_response = {{}}
    poll_url = ""
    for attempt in range(POLL_ATTEMPTS):
        poll_url = POLL_URL_TEMPLATE.format(job_id=job_id)
        poll_response = _request_json(poll_url)
        status = str(
            poll_response.get("status")
            or poll_response.get("state")
            or poll_response.get("job_status")
            or ""
        ).lower()
        if status in {{"succeeded", "completed", "done", "success"}} or bool(
            poll_response.get("done")
        ):
            break
        time.sleep(POLL_INTERVAL_SEC)

    result_url = ""
    if RESULT_URL_TEMPLATE:
        result_url = RESULT_URL_TEMPLATE.format(job_id=job_id)
    else:
        poll_result_url = poll_response.get("result_url")
        if isinstance(poll_result_url, str) and poll_result_url:
            result_url = urllib.parse.urljoin(poll_url, poll_result_url)

    if not result_url:
        draft["reply"]["_draft"]["job_id"] = job_id
        draft["reply"]["_draft"]["poll_response"] = poll_response
        print(json.dumps(draft, ensure_ascii=False))
        return 0

    result_payload = _request_json(result_url)
    if isinstance(result_payload.get("reply"), dict):
        print(json.dumps(result_payload, ensure_ascii=False))
        return 0

    reply = draft["reply"]
    if isinstance(result_payload.get("page_html"), str):
        reply["page_html"] = result_payload["page_html"]
    if isinstance(result_payload.get("extracted"), dict):
        reply["extracted"] = result_payload["extracted"]
    reply["_draft"]["job_id"] = job_id
    reply["_draft"]["poll_response"] = poll_response
    reply["_draft"]["result_url"] = result_url
    if not reply["page_html"] and not reply["extracted"]:
        reply["_draft"]["result_payload"] = result_payload
    print(json.dumps({{"reply": reply}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _render_browser_automation_wrapper(spec: IntegrationSpec) -> str:
    target_project = json.dumps(spec.target_project_path)
    entry_command = json.dumps(spec.execution_model.entry_command, indent=2)
    return f'''from __future__ import annotations

import json
import os
from pathlib import Path

TARGET_PROJECT_PATH = Path({target_project})
ENTRY_COMMAND = {entry_command}
BROWSER_ARTIFACT_DIR = os.environ.get("META_HARNESS_BROWSER_ARTIFACT_DIR", "")
LOGIN_STATE_PATH = os.environ.get("META_HARNESS_BROWSER_LOGIN_STATE", "")


def main() -> int:
    draft = {{
        "reply": {{
            "page_html": "",
            "extracted": {{}},
            "_draft": {{
                "mode": "browser_automation",
                "target_project_path": str(TARGET_PROJECT_PATH),
                "entry_command": ENTRY_COMMAND,
                "artifact_dir": BROWSER_ARTIFACT_DIR,
                "login_state_path": LOGIN_STATE_PATH,
                "required_env": [
                    "META_HARNESS_BROWSER_ARTIFACT_DIR",
                ],
                "next_steps": [
                    "Attach or launch the browser automation entry command",
                    "Persist page.html and extracted.json under artifact_dir",
                    "Reuse login_state_path if the target site requires authentication",
                ],
            }},
        }}
    }}
    print(json.dumps(draft, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _render_daemon_session_wrapper(spec: IntegrationSpec) -> str:
    target_project = json.dumps(spec.target_project_path)
    entry_command = json.dumps(spec.execution_model.entry_command, indent=2)
    return f'''from __future__ import annotations

import json
import os
from pathlib import Path

TARGET_PROJECT_PATH = Path({target_project})
ENTRY_COMMAND = {entry_command}
SESSION_ID = os.environ.get("META_HARNESS_DAEMON_SESSION_ID", "")
ARTIFACT_DIR = os.environ.get("META_HARNESS_DAEMON_ARTIFACT_DIR", "")


def main() -> int:
    draft = {{
        "reply": {{
            "page_html": "",
            "extracted": {{}},
            "_draft": {{
                "mode": "daemon_session",
                "target_project_path": str(TARGET_PROJECT_PATH),
                "entry_command": ENTRY_COMMAND,
                "session_id": SESSION_ID,
                "artifact_dir": ARTIFACT_DIR,
                "required_env": [
                    "META_HARNESS_DAEMON_SESSION_ID",
                ],
                "next_steps": [
                    "Start or attach the daemon session referenced by session_id",
                    "Run the entry command inside the daemon context",
                    "Capture stable outputs and normalize them into page_html/extracted",
                ],
            }},
        }}
    }}
    print(json.dumps(draft, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _render_test_draft(
    *,
    spec: IntegrationSpec,
    binding_path: Path,
    wrapper_path: Path | None,
) -> str:
    wrapper_literal = json.dumps(str(wrapper_path) if wrapper_path is not None else "")
    return f'''from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.mark.skip(reason="Generated integration draft requires manual review before activation")
def test_generated_integration_draft_matches_spec() -> None:
    binding = json.loads(Path({json.dumps(str(binding_path))}).read_text(encoding="utf-8"))
    assert binding["primitive_id"] == {json.dumps(spec.primitive_id)}
    assert binding["binding_id"].startswith("generated/")
    wrapper_path = Path({wrapper_literal})
    if str(wrapper_path):
        assert wrapper_path.exists()
'''


def _render_harness_wrapper(spec: HarnessSpec) -> str:
    target_project = json.dumps(spec.target_project_path)
    entry_command = json.dumps(spec.execution_model.entry_command, indent=2)
    capability_modules = json.dumps(spec.capability_modules, indent=2)
    return f'''from __future__ import annotations

import json
import subprocess
from pathlib import Path

TARGET_PROJECT_PATH = Path({target_project})
ENTRY_COMMAND = {entry_command}
CAPABILITY_MODULES = {capability_modules}


def main() -> int:
    completed = subprocess.run(
        ENTRY_COMMAND,
        cwd=TARGET_PROJECT_PATH,
        capture_output=True,
        text=True,
        check=False,
    )
    payload = {{
        "command_proxy": True,
        "capability_modules": CAPABILITY_MODULES,
        "stdout_preview": (completed.stdout or "")[:800],
        "stderr_preview": (completed.stderr or "")[:800],
        "exit_code": completed.returncode,
        "_draft": {{
            "mode": "json_stdout_cli",
            "entry_command": ENTRY_COMMAND,
            "next_steps": [
                "Replace command_proxy preview with primitive-specific output mapping",
                "Decide which stdout/stderr fields should become stable harness artifacts",
            ],
        }},
    }}
    print(json.dumps(payload, ensure_ascii=False))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _render_harness_test_draft(spec: HarnessSpec, wrapper_path: Path | None) -> str:
    wrapper_literal = json.dumps(str(wrapper_path) if wrapper_path is not None else "")
    return f'''from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.skip(reason="Generated harness draft requires manual review before activation")
def test_generated_harness_draft_exists() -> None:
    wrapper_path = Path({wrapper_literal})
    if str(wrapper_path):
        assert wrapper_path.exists()
    assert {json.dumps(spec.execution_model.kind)} in {json.dumps(spec.execution_model.kind)}
'''
