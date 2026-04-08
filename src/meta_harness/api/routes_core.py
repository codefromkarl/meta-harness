from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException


def register_core_routes(app: FastAPI) -> None:
    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/profiles")
    def profiles(
        config_root: str = "configs",
        limit: int | None = None,
        offset: int = 0,
    ) -> dict:
        import meta_harness.api.app as root_api

        return root_api.paginate_items(
            root_api.list_profile_names(Path(config_root)),
            limit=limit,
            offset=offset,
        )

    @app.get("/projects")
    def projects(
        config_root: str = "configs",
        limit: int | None = None,
        offset: int = 0,
    ) -> dict:
        import meta_harness.api.app as root_api

        return root_api.paginate_items(
            root_api.list_project_names(Path(config_root)),
            limit=limit,
            offset=offset,
        )

    @app.get("/proposals")
    def proposals(
        proposals_root: str = "proposals",
        profile: str | None = None,
        project: str | None = None,
        status: str | None = None,
        proposer_kind: str | None = None,
        strategy: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict:
        import meta_harness.api.app as root_api

        return root_api.paginate_items(
            root_api.list_proposals_payload(
                proposals_root=Path(proposals_root),
                profile_name=profile,
                project_name=project,
                status=status,
                proposer_kind=proposer_kind,
                strategy=strategy,
            ),
            limit=limit,
            offset=offset,
        )

    @app.get("/proposals/{proposal_id}")
    def proposal_detail(proposal_id: str, proposals_root: str = "proposals") -> dict:
        import meta_harness.api.app as root_api

        try:
            return root_api.load_proposal_payload(
                proposals_root=Path(proposals_root),
                proposal_id=proposal_id,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runs")
    def runs(
        runs_root: str = "runs",
        profile: str | None = None,
        project: str | None = None,
        candidate_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict:
        import meta_harness.api.app as root_api

        return root_api.paginate_items(
            root_api.list_run_summaries(
                Path(runs_root),
                profile=profile,
                project=project,
                candidate_id=candidate_id,
            ),
            limit=limit,
            offset=offset,
        )

    @app.get("/runs/{run_id}")
    def run_detail(run_id: str, runs_root: str = "runs") -> dict:
        import meta_harness.api.app as root_api

        return root_api.load_run_summary(Path(runs_root), run_id)

    @app.get("/runs/{run_id}/tasks")
    def run_tasks(
        run_id: str,
        runs_root: str = "runs",
        task_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict:
        import meta_harness.api.app as root_api

        return root_api.paginate_items(
            root_api.list_task_results(
                Path(runs_root),
                run_id,
                task_id=task_id,
                status=status,
            ),
            limit=limit,
            offset=offset,
        )

    @app.get("/runs/{run_id}/tasks/{task_id}")
    def run_task_detail(run_id: str, task_id: str, runs_root: str = "runs") -> dict:
        import meta_harness.api.app as root_api

        try:
            return root_api.load_task_result(Path(runs_root), run_id, task_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runs/{run_id}/trace")
    def run_trace(
        run_id: str,
        runs_root: str = "runs",
        task_id: str | None = None,
        phase: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict:
        import meta_harness.api.app as root_api

        return root_api.paginate_items(
            root_api.list_trace_events(
                Path(runs_root),
                run_id,
                task_id=task_id,
                phase=phase,
                status=status,
            ),
            limit=limit,
            offset=offset,
        )

    @app.get("/runs/{run_id}/trace/grade")
    def run_trace_grade(run_id: str, runs_root: str = "runs") -> dict:
        import meta_harness.api.app as root_api

        return root_api.grade_trace_events(
            run_id=run_id,
            events=root_api.list_trace_events(Path(runs_root), run_id),
        )

    @app.get("/runs/{run_id}/evaluators")
    def run_evaluators(run_id: str, runs_root: str = "runs") -> dict[str, list[dict]]:
        import meta_harness.api.app as root_api

        return {"items": root_api.list_evaluator_reports(Path(runs_root), run_id)}

    @app.get("/runs/{run_id}/evaluators/{evaluator_name}")
    def run_evaluator_detail(
        run_id: str,
        evaluator_name: str,
        runs_root: str = "runs",
    ) -> dict:
        import meta_harness.api.app as root_api

        try:
            return root_api.load_evaluator_report(Path(runs_root), run_id, evaluator_name)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/jobs")
    def jobs(
        reports_root: str = "reports",
        repo_root: str | None = None,
        status: str | None = None,
        job_type: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict:
        import meta_harness.api.app as root_api

        return root_api.paginate_items(
            root_api.list_job_views(
                reports_root=Path(reports_root),
                repo_root=Path(repo_root) if repo_root is not None else None,
                status=status,
                job_type=job_type,
            ),
            limit=limit,
            offset=offset,
        )

    @app.get("/jobs/{job_id}")
    def job_detail(
        job_id: str,
        reports_root: str = "reports",
        repo_root: str | None = None,
    ) -> dict:
        import meta_harness.api.app as root_api

        return root_api.load_job_view(
            reports_root=Path(reports_root),
            job_id=job_id,
            repo_root=Path(repo_root) if repo_root is not None else None,
        )

    @app.post("/jobs/{job_id}/cancel")
    def job_cancel(job_id: str, reports_root: str = "reports") -> dict:
        import meta_harness.api.app as root_api

        return root_api.success_response(
            root_api.cancel_job_record(reports_root=Path(reports_root), job_id=job_id)
        )

    @app.post("/jobs/{job_id}/retry")
    def job_retry(job_id: str, reports_root: str = "reports") -> dict:
        import meta_harness.api.app as root_api

        try:
            return root_api.retry_job(reports_root=Path(reports_root), job_id=job_id)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/jobs/{job_id}/result")
    def job_result(
        job_id: str,
        reports_root: str = "reports",
        repo_root: str | None = None,
    ) -> dict:
        import meta_harness.api.app as root_api

        try:
            return root_api.load_job_result(
                reports_root=Path(reports_root),
                job_id=job_id,
                repo_root=Path(repo_root) if repo_root is not None else None,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/candidates/current")
    def candidates_current(
        candidates_root: str = "candidates",
        runs_root: str | None = None,
    ) -> dict:
        import meta_harness.api.app as root_api

        resolved_runs_root = Path(runs_root) if runs_root is not None else None
        return root_api.candidate_current_view_payload(
            candidates_root=Path(candidates_root),
            runs_root=resolved_runs_root,
        )

    @app.get("/champions")
    def champions(candidates_root: str = "candidates") -> dict[str, dict[str, str]]:
        import meta_harness.api.app as root_api

        return {"items": root_api.list_champions(Path(candidates_root))}
