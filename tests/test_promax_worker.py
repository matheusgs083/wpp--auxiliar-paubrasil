from __future__ import annotations

import base64
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from workers.promax_client import PromaxClient, normalize_status
from workers.promax_runner import (
    PromaxRunResult,
    PromaxRunner,
    PromaxRunnerConfig,
    terminate_process_tree,
)
from workers.promax_worker import PromaxWorker, _control_flag, redact_log_message
from workers.promax_worker import _promax_030206_publication_dir


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.closed = False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def close(self) -> None:
        self.closed = True


class _FakeProcess:
    def __init__(self, *, pid: int = 4321, return_code: int = 0) -> None:
        self.pid = pid
        self.return_code = return_code
        self.stdout = io.StringIO("linha stdout\n")
        self.stderr = io.StringIO("linha stderr\n")
        self._polls = 0

    def poll(self) -> int | None:
        self._polls += 1
        if self._polls < 2:
            return None
        return self.return_code

    def wait(self, timeout: float | None = None) -> int:
        return self.return_code


class PromaxClientTests(unittest.TestCase):
    def test_client_uses_worker_token_and_claim_contract(self) -> None:
        requests: list[object] = []

        def opener(request: object, *, timeout: float) -> _FakeResponse:
            requests.append(request)
            return _FakeResponse({"ok": True, "job": None})

        client = PromaxClient(
            base_url="http://127.0.0.1:8080/",
            token="secret-token",
            worker_id="worker-1",
            pid=123,
            opener=opener,
        )

        self.assertIsNone(client.claim())
        request = requests[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:8080/api/internal/promax/next-job/claim")
        self.assertEqual(request.get_header("X-promax-worker-token"), "secret-token")
        self.assertEqual(
            json.loads(request.data),
            {"worker_id": "worker-1", "pid": 123, "lease_seconds": 120},
        )

    def test_worker_requests_use_final_namespace_and_normalize_status(self) -> None:
        captured: list[tuple[str, dict[str, object]]] = []

        def opener(request: object, *, timeout: float) -> _FakeResponse:
            captured.append(
                (
                    request.full_url,
                    json.loads(request.data) if request.data is not None else {},
                )
            )
            return _FakeResponse({"ok": True})

        client = PromaxClient(
            base_url="http://localhost:8080",
            token="token",
            worker_id="worker",
            pid=321,
            opener=opener,
        )

        client.finish(
            "job-1",
            "lease-token",
            status="completed",
            result={"return_code": 0, "message": "Publicacao concluida."},
        )
        client.heartbeat_job("job-1", "lease-token")
        client.log(
            "job-1",
            "lease-token",
            "erro",
            level="error",
            data={"stream": "stderr"},
        )
        client.control("job-1")

        self.assertEqual(captured[0][1]["status"], "success")
        self.assertEqual(captured[0][1]["result"]["exit_code"], 0)
        self.assertEqual(captured[0][1]["result"]["message"], "Publicacao concluida.")
        self.assertEqual(captured[0][1]["lease_token"], "lease-token")
        self.assertEqual(captured[1][1]["lease_token"], "lease-token")
        self.assertEqual(captured[2][1]["data"]["stream"], "stderr")
        self.assertIn("/api/internal/promax/jobs/job-1/finish", captured[0][0])
        self.assertIn("/api/internal/promax/jobs/job-1/heartbeat", captured[1][0])
        self.assertIn("/api/internal/promax/jobs/job-1/log", captured[2][0])
        self.assertIn(
            "/api/internal/promax/control?worker_id=worker&job_id=job-1",
            captured[3][0],
        )

    def test_client_uploads_boleto_pdf_to_internal_import_route(self) -> None:
        captured: list[tuple[str, dict[str, object], float]] = []

        def opener(request: object, *, timeout: float) -> _FakeResponse:
            captured.append((request.full_url, json.loads(request.data), timeout))
            return _FakeResponse({"ok": True, "result": {"imported": 1}})

        client = PromaxClient(
            base_url="http://localhost:8080",
            token="token",
            worker_id="worker",
            pid=321,
            timeout_seconds=10,
            boleto_import_timeout_seconds=120,
            opener=opener,
        )

        client.import_boleto_pdf(
            job_id="job-1",
            lease_token="lease-token",
            filial="3",
            filename="03,02,06_2210003.pdf",
            pdf_bytes=b"%PDF-1.4\nconteudo",
            reference_date="2026-07-20",
        )

        self.assertEqual(captured[0][0], "http://localhost:8080/api/internal/promax/boletos/import")
        payload = captured[0][1]
        self.assertEqual(captured[0][2], 120)
        self.assertEqual(payload["worker_id"], "worker")
        self.assertEqual(payload["job_id"], "job-1")
        self.assertEqual(payload["lease_token"], "lease-token")
        self.assertEqual(payload["filial"], "3")
        self.assertEqual(payload["filename"], "03,02,06_2210003.pdf")
        self.assertEqual(base64.b64decode(payload["file_base64"]), b"%PDF-1.4\nconteudo")

    def test_control_flag_accepts_stop_job_ids_contract(self) -> None:
        payload = {
            "control": {
                "stop_job_ids": ["job-1", "job-2"],
                "cancel_requested": False,
            }
        }

        self.assertTrue(
            _control_flag(payload, key="cancel_requested", job_id="job-2")
        )
        self.assertFalse(
            _control_flag(payload, key="cancel_requested", job_id="job-3")
        )

    def test_worker_heartbeat_forwards_dynamic_catalog(self) -> None:
        captured: list[dict[str, object]] = []

        def opener(request: object, *, timeout: float) -> _FakeResponse:
            captured.append(json.loads(request.data))
            return _FakeResponse({"ok": True})

        client = PromaxClient(
            base_url="http://localhost:8080",
            token="token",
            worker_id="worker",
            pid=321,
            opener=opener,
        )

        client.heartbeat(
            details={
                "catalog": {
                    "categories": {
                        "obz": {
                            "name": "OBZ",
                            "routines": [{"id": "0512", "name": "Rotina 0512"}],
                        }
                    }
                }
            }
        )

        self.assertIn("obz", captured[0]["details"]["catalog"]["categories"])

    def test_030206_import_gate_handles_completed_status(self) -> None:
        worker = object.__new__(PromaxWorker)
        result = PromaxRunResult(status="completed", return_code=0, child_pid=123)

        worker._import_030206_boletos_if_needed(
            {"payload": {"routines": ["120601_BOT"]}},
            "job-1",
            "lease-token",
            result,
        )

    def test_030206_publication_dir_prefers_driver_metadata(self) -> None:
        source_dir = _promax_030206_publication_dir(
            {
                "metadata": {
                    "publication_mapping": {
                        r"C:\Relatorios\030206 bot": r"\\servidor\financeiro\Bot Zap\030206",
                    }
                }
            }
        )

        self.assertEqual(str(source_dir), r"\\servidor\financeiro\Bot Zap\030206")

    def test_030206_publication_dir_has_no_project_fallback(self) -> None:
        self.assertIsNone(_promax_030206_publication_dir({}))


class PromaxRunnerTests(unittest.TestCase):
    def _config(self, root: Path) -> PromaxRunnerConfig:
        driver_dir = root / "driver"
        driver_dir.mkdir()
        (driver_dir / "cli.py").write_text("", encoding="ascii")
        python_executable = root / "python.exe"
        python_executable.write_bytes(b"")
        return PromaxRunnerConfig.from_values(
            driver_dir=driver_dir,
            python_executable=python_executable,
            heartbeat_interval_seconds=1,
            control_interval_seconds=1,
        )

    def test_runner_uses_fixed_command_without_shell(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._config(Path(temp_dir))
            process = _FakeProcess()
            popen = Mock(return_value=process)
            ticks = iter([0.0, 0.0, 0.0, 2.0, 2.0, 2.0])
            runner = PromaxRunner(
                config,
                popen_factory=popen,
                monotonic=lambda: next(ticks, 3.0),
                platform="nt",
            )
            lines: list[tuple[str, str]] = []

            result = runner.run(
                {
                    "id": "job-1",
                    "job_type": "fluxo_caixa",
                    "payload": {
                        "category": "fluxo_caixa",
                        "routines": ["140506", "120606"],
                        "units": ["030117", "030118"],
                        "start_date": "2026-07-01",
                        "end_date": "2026-07-18",
                        "send_dates": True,
                        "publish": False,
                    },
                },
                on_line=lambda stream, line: lines.append((stream, line)),
                heartbeat=lambda: None,
                cancel_requested=lambda: False,
            )

        command = popen.call_args.args[0]
        self.assertEqual(
            command,
            [
                str(config.python_executable),
                str(config.cli_path),
                "relatorios",
                "--perfil",
                "fluxo_caixa",
                "--data-inicial",
                "2026-07-01",
                "--data-final",
                "2026-07-18",
                "--rotinas",
                "140506",
                "120606",
                "--unidade",
                "030117",
                "--unidade",
                "030118",
                "--somente-baixar",
                "--job-id",
                "job-1",
            ],
        )
        self.assertIs(popen.call_args.kwargs["shell"], False)
        self.assertEqual(result.status, "success")
        self.assertIn(("stdout", "linha stdout"), lines)
        self.assertIn(("stderr", "linha stderr"), lines)

    def test_runner_omits_dates_unless_send_dates_is_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._config(Path(temp_dir))
            runner = PromaxRunner(config)

            command = runner.build_command(
                {
                    "id": "job-default-dates",
                    "payload": {
                        "category": "adf",
                        "routines": ["030237"],
                        "units": [],
                        "start_date": "2026-07-01",
                        "end_date": "2026-07-18",
                        "send_dates": False,
                        "publish": True,
                    },
                }
            )

        self.assertNotIn("--data-inicial", command)
        self.assertNotIn("--data-final", command)

    def test_runner_accepts_dynamic_profile_with_safe_identifiers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._config(Path(temp_dir))
            runner = PromaxRunner(config)

            command = runner.build_command(
                {
                    "id": "job-obz",
                    "payload": {
                        "category": "obz",
                        "routines": ["0512", "150501"],
                        "units": [],
                        "publish": True,
                    },
                }
            )

        self.assertEqual(command[command.index("--perfil") + 1], "obz")
        routines_index = command.index("--rotinas")
        self.assertEqual(command[routines_index + 1 : routines_index + 3], ["0512", "150501"])

    def test_runner_builds_publication_reprocessing_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._config(Path(temp_dir))
            runner = PromaxRunner(config)

            command = runner.build_command(
                {
                    "id": "job-reprocess",
                    "job_type": "reprocess_publication",
                    "payload": {"operation": "reprocess_publication"},
                }
            )

        self.assertEqual(
            command,
            [
                str(config.python_executable),
                str(config.cli_path),
                "reprocessar-publicacao",
                "--job-id",
                "job-reprocess",
            ],
        )

    def test_runner_preserves_structured_partial_result_message(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._config(Path(temp_dir))
            process = _FakeProcess(return_code=10)
            process.stdout = io.StringIO(
                json.dumps(
                    {
                        "event": "promax_job_result",
                        "job_id": "job-reprocess",
                        "operation": "reprocessar-publicacao",
                        "status": "SUCESSO_PARCIAL",
                        "message": "2/3 publicadas; 1 permanece pendente.",
                        "failed_units": ["3610008"],
                        "exit_code": 10,
                    }
                )
                + "\n"
            )
            ticks = iter([0.0, 0.0, 0.0, 2.0, 2.0, 2.0])
            lines: list[tuple[str, str]] = []
            runner = PromaxRunner(
                config,
                popen_factory=Mock(return_value=process),
                monotonic=lambda: next(ticks, 3.0),
                platform="nt",
            )

            result = runner.run(
                {
                    "id": "job-reprocess",
                    "job_type": "reprocess_publication",
                    "payload": {"operation": "reprocess_publication"},
                },
                on_line=lambda stream, line: lines.append((stream, line)),
                heartbeat=lambda: None,
                cancel_requested=lambda: False,
            )

        self.assertEqual(result.status, "partial_success")
        self.assertEqual(result.message, "2/3 publicadas; 1 permanece pendente.")
        self.assertEqual(result.details["failed_units"], ["3610008"])
        self.assertIn(
            ("stdout", "Resumo final: 2/3 publicadas; 1 permanece pendente."),
            lines,
        )

    def test_runner_rejects_unsafe_dynamic_profile_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._config(Path(temp_dir))
            runner = PromaxRunner(config)

            with self.assertRaisesRegex(ValueError, "Invalid Promax profile identifier"):
                runner.build_command(
                    {
                        "id": "job-invalid",
                        "payload": {
                            "category": "../obz",
                            "routines": ["0512"],
                            "units": [],
                            "publish": False,
                        },
                    }
                )

    def test_runner_rejects_non_boolean_send_dates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._config(Path(temp_dir))
            runner = PromaxRunner(config)

            with self.assertRaisesRegex(ValueError, "send_dates"):
                runner.build_command(
                    {
                        "id": "job-invalid-send-dates",
                        "payload": {
                            "category": "adf",
                            "routines": ["030237"],
                            "units": [],
                            "send_dates": "true",
                            "publish": False,
                        },
                    }
                )

    def test_cancel_uses_only_the_child_pid_tree(self) -> None:
        taskkill = Mock(return_value=subprocess.CompletedProcess([], 0))

        terminate_process_tree(9876, platform="nt", run=taskkill)

        self.assertEqual(
            taskkill.call_args.args[0],
            ["taskkill", "/PID", "9876", "/T", "/F"],
        )
        self.assertIs(taskkill.call_args.kwargs["shell"], False)
        self.assertNotIn("/IM", taskkill.call_args.args[0])

    def test_cancel_requested_kills_the_running_child_pid(self) -> None:
        class RunningProcess(_FakeProcess):
            def __init__(self) -> None:
                super().__init__(pid=2468, return_code=1)
                self.terminated = False

            def poll(self) -> int | None:
                return self.return_code if self.terminated else None

        with tempfile.TemporaryDirectory() as temp_dir:
            config = self._config(Path(temp_dir))
            process = RunningProcess()
            taskkill = Mock(
                side_effect=lambda *_args, **_kwargs: setattr(process, "terminated", True)
            )
            runner = PromaxRunner(
                config,
                popen_factory=Mock(return_value=process),
                monotonic=lambda: 0.0,
                taskkill_runner=taskkill,
                platform="nt",
            )

            result = runner.run(
                {
                    "id": "job-2",
                    "job_type": "fluxo_caixa",
                    "payload": {
                        "category": "fluxo_caixa",
                        "routines": ["140506"],
                        "units": ["030117"],
                        "publish": True,
                    },
                },
                on_line=lambda _stream, _line: None,
                heartbeat=lambda: None,
                cancel_requested=lambda: True,
            )

        self.assertEqual(
            taskkill.call_args.args[0],
            ["taskkill", "/PID", "2468", "/T", "/F"],
        )
        self.assertEqual(result.status, "cancelled")


class StatusNormalizationTests(unittest.TestCase):
    def test_status_aliases_are_normalized(self) -> None:
        cases = {
            "completed": "success",
            "OK": "success",
            "partial": "partial_success",
            "failure": "failed",
            "canceled": "cancelled",
            "cancel_requested": "cancelled",
            "terminated": "stopped",
        }
        for raw_status, expected in cases.items():
            with self.subTest(raw_status=raw_status):
                self.assertEqual(normalize_status(raw_status), expected)

    def test_unknown_status_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_status("mystery")

    def test_sensitive_values_are_redacted_from_worker_logs(self) -> None:
        message = "senha=abc123 Authorization: Bearer eyJhbGciOi token:xyz"

        redacted = redact_log_message(message)

        self.assertNotIn("abc123", redacted)
        self.assertNotIn("eyJhbGciOi", redacted)
        self.assertNotIn("xyz", redacted)


if __name__ == "__main__":
    unittest.main()
