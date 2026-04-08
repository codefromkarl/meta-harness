from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException

from meta_harness.api.contracts import (
    AnnotationCreateRequest,
    DatasetBuildTaskSetRequest,
    DatasetDeriveSplitRequest,
    DatasetExtractFailuresRequest,
    DatasetIngestAnnotationsRequest,
    DatasetPromoteRequest,
    GateEvaluateByPolicyRequest,
    GateEvaluateRequest,
)


def register_data_ops_routes(app: FastAPI) -> None:
    @app.get("/datasets")
    def datasets(
        datasets_root: str = "datasets",
        limit: int | None = None,
        offset: int = 0,
    ) -> dict:
        import meta_harness.api.app as root_api

        return root_api.paginate_items(
            root_api.list_dataset_versions(Path(datasets_root)),
            limit=limit,
            offset=offset,
        )

    @app.get("/datasets/{dataset_id}")
    def dataset_detail(dataset_id: str, datasets_root: str = "datasets") -> dict:
        import meta_harness.api.app as root_api

        try:
            return root_api.load_dataset_summary(Path(datasets_root), dataset_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/datasets/{dataset_id}/versions/{version}")
    def dataset_version(dataset_id: str, version: str, datasets_root: str = "datasets") -> dict:
        import meta_harness.api.app as root_api

        try:
            return root_api.load_dataset_version(Path(datasets_root), dataset_id, version)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/datasets/{dataset_id}/versions/{version}/cases")
    def dataset_cases(
        dataset_id: str,
        version: str,
        datasets_root: str = "datasets",
        limit: int | None = None,
        offset: int = 0,
    ) -> dict:
        import meta_harness.api.app as root_api

        try:
            payload = root_api.load_dataset_version(Path(datasets_root), dataset_id, version)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return root_api.paginate_items(
            list(payload.get("cases") or []),
            limit=limit,
            offset=offset,
        )

    @app.post("/annotations")
    def annotation_create(request: AnnotationCreateRequest) -> dict:
        import meta_harness.api.app as root_api

        return root_api.success_response(
            root_api.create_annotation_record(
                annotations_root=Path(request.annotations_root),
                target_type=request.target_type,
                target_ref=request.target_ref,
                label=request.label,
                value=request.value,
                notes=request.notes,
                annotator=request.annotator,
            )
        )

    @app.get("/annotations")
    def annotations(
        annotations_root: str = "annotations",
        target_type: str | None = None,
        target_ref: str | None = None,
        label: str | None = None,
        annotator: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict:
        import meta_harness.api.app as root_api

        return root_api.paginate_items(
            root_api.list_annotation_records(
                annotations_root=Path(annotations_root),
                target_type=target_type,
                target_ref=target_ref,
                label=label,
                annotator=annotator,
            ),
            limit=limit,
            offset=offset,
        )

    @app.get("/gate-policies")
    def gate_policies(
        config_root: str = "configs",
        limit: int | None = None,
        offset: int = 0,
    ) -> dict:
        import meta_harness.api.app as root_api

        return root_api.paginate_items(
            root_api.list_gate_policies(Path(config_root)),
            limit=limit,
            offset=offset,
        )

    @app.get("/gate-policies/{policy_id}")
    def gate_policy_detail(policy_id: str, config_root: str = "configs") -> dict:
        import meta_harness.api.app as root_api

        try:
            return root_api.load_gate_policy(Path(config_root), policy_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/gates/results")
    def gate_results(
        reports_root: str = "reports",
        policy_id: str | None = None,
        target_type: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict:
        import meta_harness.api.app as root_api

        return root_api.paginate_items(
            root_api.list_gate_results(
                reports_root=Path(reports_root),
                policy_id=policy_id,
                target_type=target_type,
                status=status,
            ),
            limit=limit,
            offset=offset,
        )

    @app.get("/gates/results/{gate_id}")
    def gate_result_detail(gate_id: str, reports_root: str = "reports") -> dict:
        import meta_harness.api.app as root_api

        try:
            return root_api.load_gate_result(
                reports_root=Path(reports_root),
                gate_id=gate_id,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/gates/history")
    def gate_history(
        reports_root: str = "reports",
        policy_id: str | None = None,
        target_type: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict:
        import meta_harness.api.app as root_api

        return root_api.paginate_items(
            root_api.list_gate_history(
                reports_root=Path(reports_root),
                policy_id=policy_id,
                target_type=target_type,
                status=status,
            ),
            limit=limit,
            offset=offset,
        )

    @app.post("/gate-policies/{policy_id}/evaluate")
    def gate_policy_evaluate(
        policy_id: str,
        request: GateEvaluateByPolicyRequest,
    ) -> dict:
        import meta_harness.api.app as root_api

        try:
            policy = root_api.load_gate_policy(Path(request.config_root), policy_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        policy_path = Path(request.config_root) / "gate_policies" / f"{policy_id}.json"
        return root_api.success_response(
            {
                **root_api.evaluate_gate_policy_from_paths(
                    policy_path=policy_path,
                    target_path=Path(request.target_path),
                    target_type=request.target_type,
                    target_ref=request.target_ref,
                    evidence_refs=list(request.evidence_refs),
                ),
                "policy": policy,
            }
        )

    @app.post("/datasets/extract-failures")
    def dataset_extract_failures(request: DatasetExtractFailuresRequest) -> dict:
        import meta_harness.api.app as root_api

        return root_api.submit_dataset_extract_job(
            reports_root=Path(request.reports_root),
            runs_root=Path(request.runs_root),
            output_path=Path(request.output_path),
            profile_name=request.profile,
            project_name=request.project,
            requested_by=request.requested_by,
        )

    @app.post("/datasets/build-task-set")
    def dataset_build_task_set(request: DatasetBuildTaskSetRequest) -> dict:
        import meta_harness.api.app as root_api

        return root_api.success_response(
            root_api.build_task_set_dataset_to_path(
                task_set_path=Path(request.task_set_path),
                output_path=Path(request.output_path),
                dataset_id=request.dataset_id,
                version=request.version,
            )
        )

    @app.post("/datasets/ingest-annotations")
    def dataset_ingest_annotations(request: DatasetIngestAnnotationsRequest) -> dict:
        import meta_harness.api.app as root_api

        return root_api.success_response(
            root_api.ingest_dataset_annotations_to_path(
                dataset_path=Path(request.dataset_path),
                annotations_path=Path(request.annotations_path),
                output_path=Path(request.output_path),
            )
        )

    @app.post("/datasets/derive-split")
    def dataset_derive_split(request: DatasetDeriveSplitRequest) -> dict:
        import meta_harness.api.app as root_api

        return root_api.success_response(
            root_api.derive_dataset_split_to_path(
                dataset_path=Path(request.dataset_path),
                output_path=Path(request.output_path),
                split=request.split,
                dataset_id=request.dataset_id,
                version=request.version,
            )
        )

    @app.post("/datasets/promote")
    def dataset_promote(request: DatasetPromoteRequest) -> dict:
        import meta_harness.api.app as root_api

        return root_api.success_response(
            root_api.promote_dataset_version(
                datasets_root=Path(request.datasets_root),
                dataset_id=request.dataset_id,
                version=request.version,
                split=request.split,
                promoted_by=request.promoted_by,
                reason=request.reason,
            )
        )

    @app.post("/gates/evaluate")
    def gate_evaluate(request: GateEvaluateRequest) -> dict:
        import meta_harness.api.app as root_api

        return root_api.success_response(
            root_api.evaluate_gate_policy_from_paths(
                policy_path=Path(request.policy_path),
                target_path=Path(request.target_path),
                target_type=request.target_type,
                target_ref=request.target_ref,
                evidence_refs=list(request.evidence_refs),
            )
        )
