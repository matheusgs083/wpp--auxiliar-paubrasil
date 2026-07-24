from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from workers.promax_client import PromaxClient, normalize_status
from workers.promax_runner import (
    PromaxRunResult,
    PromaxRunner,
    PromaxRunnerConfig,
    terminate_process_tree,
)
from workers.promax_worker import (
    PromaxVisualAutomationLock,
    PromaxWorker,
    WorkerConfig,
    _control_flag,
    redact_log_message,
)
from workers.promax_worker import _promax_030206_publication_dir


class _FakeVisualLock:
    def __init__(self, acquire_result: bool = True) -> None:
        self.acquire_result = acquire_result
        self.acquire_calls: list[dict[str, object]] = []
        self.release_calls = 0

    def acquire(self, metadata: object = None) -> bool:
        self.acquire_calls.append(dict(metadata or {}))
        return self.acquire_result

    def release(self) -> None:
        self.release_calls += 1


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

    def test_client_uploads_inadimplencia_csvs_to_internal_import_route(self) -> None:
        captured: list[tuple[str, dict[str, object], float]] = []

        def opener(request: object, *, timeout: float) -> _FakeResponse:
            captured.append((request.full_url, json.loads(request.data), timeout))
            return _FakeResponse({"ok": True, "result": {"file_count": 2}})

        client = PromaxClient(
            base_url="http://localhost:8080",
            token="token",
            worker_id="worker",
            pid=321,
            timeout_seconds=10,
            boleto_import_timeout_seconds=120,
            opener=opener,
        )

        client.import_inadimplencia_csvs(
            job_id="job-1",
            lease_token="lease-token",
            files={
                "2026-07 Sousa.csv": b"Cliente;Valor\n1;10\n",
                "2026-07 Patos.csv": b"Cliente;Valor\n2;20\n",
            },
            reference_date="2026-07-20",
        )

        self.assertEqual(captured[0][0], "http://localhost:8080/api/internal/promax/inadimplencia/import")
        payload = captured[0][1]
        self.assertEqual(captured[0][2], 120)
        self.assertEqual(payload["worker_id"], "worker")
        self.assertEqual(payload["job_id"], "job-1")
        self.assertEqual(payload["lease_token"], "lease-token")
        self.assertEqual(payload["reference_date"], "2026-07-20")
        self.assertEqual([item["filename"] for item in payload["files"]], ["2026-07 Sousa.csv", "2026-07 Patos.csv"])
        self.assertEqual(base64.b64decode(payload["files"][0]["file_base64"]), b"Cliente;Valor\n1;10\n")

    def test_client_uploads_comodatos_csvs_to_internal_import_route(self) -> None:
        captured: list[tuple[str, dict[str, object], float]] = []

        def opener(request: object, *, timeout: float) -> _FakeResponse:
            captured.append((request.full_url, json.loads(request.data), timeout))
            return _FakeResponse({"ok": True, "result": {"file_count": 1}})

        client = PromaxClient(
            base_url="http://localhost:8080",
            token="token",
            worker_id="worker",
            pid=321,
            boleto_import_timeout_seconds=120,
            opener=opener,
        )

        client.import_comodatos_csvs(
            job_id="job-1",
            lease_token="lease-token",
            files={"020220 bot - Sousa.csv": b"Cliente;Valor\n1;10\n"},
        )

        self.assertEqual(captured[0][0], "http://localhost:8080/api/internal/promax/comodatos/import")
        self.assertEqual(captured[0][2], 120)
        self.assertEqual(captured[0][1]["files"][0]["filename"], "020220 bot - Sousa.csv")

    def test_client_uploads_dclientes_csv_to_internal_import_route(self) -> None:
        captured: list[tuple[str, dict[str, object], float]] = []

        def opener(request: object, *, timeout: float) -> _FakeResponse:
            captured.append((request.full_url, json.loads(request.data), timeout))
            return _FakeResponse({"ok": True, "result": {"rows": 10}})

        client = PromaxClient(
            base_url="http://localhost:8080",
            token="token",
            worker_id="worker",
            pid=321,
            boleto_import_timeout_seconds=120,
            opener=opener,
        )

        client.import_dclientes_csv(
            job_id="job-1",
            lease_token="lease-token",
            filename="0105070402 bot - dClientes.csv",
            csv_bytes=b"Cliente;Valor\n1;10\n",
        )

        self.assertEqual(captured[0][0], "http://localhost:8080/api/internal/promax/dclientes/import")
        self.assertEqual(captured[0][2], 120)
        self.assertEqual(captured[0][1]["files"][0]["filename"], "0105070402 bot - dClientes.csv")

    def test_client_uploads_critica_csvs_to_internal_import_route(self) -> None:
        captured: list[tuple[str, dict[str, object], float]] = []

        def opener(request: object, *, timeout: float) -> _FakeResponse:
            captured.append((request.full_url, json.loads(request.data), timeout))
            return _FakeResponse({"ok": True, "result": {"file_count": 1, "rows": 2}})

        client = PromaxClient(
            base_url="http://localhost:8080",
            token="token",
            worker_id="worker",
            pid=321,
            boleto_import_timeout_seconds=120,
            opener=opener,
        )

        client.import_critica_csvs(
            job_id="job-1",
            lease_token="lease-token",
            files={"030111 bot - Patos.csv": b"Filial Origem;Valor\n3;10\n"},
            reference_date="2026-07-20",
        )

        self.assertEqual(captured[0][0], "http://localhost:8080/api/internal/promax/critica/import")
        self.assertEqual(captured[0][2], 120)
        payload = captured[0][1]
        self.assertEqual(payload["worker_id"], "worker")
        self.assertEqual(payload["job_id"], "job-1")
        self.assertEqual(payload["lease_token"], "lease-token")
        self.assertEqual(payload["reference_date"], "2026-07-20")
        self.assertEqual(payload["files"][0]["filename"], "030111 bot - Patos.csv")
        self.assertEqual(base64.b64decode(payload["files"][0]["file_base64"]), b"Filial Origem;Valor\n3;10\n")

    def test_client_uploads_020304_csv_to_internal_import_route(self) -> None:
        captured: list[tuple[str, dict[str, object], float]] = []

        def opener(request: object, *, timeout: float) -> _FakeResponse:
            captured.append((request.full_url, json.loads(request.data), timeout))
            return _FakeResponse({"ok": True, "result": {"rows": 2, "pdf_bytes": 100}})

        client = PromaxClient(
            base_url="http://localhost:8080",
            token="token",
            worker_id="worker",
            pid=321,
            boleto_import_timeout_seconds=120,
            opener=opener,
        )

        client.import_estoque_020304_csv(
            job_id="job-1",
            lease_token="lease-token",
            filial="3",
            filename="02,03,04_2210003.csv",
            csv_bytes=b"Grade;Cod;Descricao\n1;2;Produto\n",
            reference_date="2026-07-23",
        )

        self.assertEqual(captured[0][0], "http://localhost:8080/api/internal/promax/estoque/import")
        self.assertEqual(captured[0][2], 120)
        payload = captured[0][1]
        self.assertEqual(payload["filial"], "3")
        self.assertEqual(payload["filename"], "02,03,04_2210003.csv")
        self.assertEqual(payload["reference_date"], "2026-07-23")
        self.assertEqual(base64.b64decode(payload["file_base64"]), b"Grade;Cod;Descricao\n1;2;Produto\n")

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

    def test_worker_does_not_claim_job_when_visual_lock_is_busy(self) -> None:
        lock = _FakeVisualLock(acquire_result=False)
        client = Mock()
        worker = PromaxWorker(
            config=WorkerConfig(
                api_url="http://localhost:8080",
                token="token",
                worker_id="worker",
                driver_dir="C:/driver",
                python_executable="C:/driver/venv/Scripts/python.exe",
            ),
            client=client,
            runner=Mock(),
            visual_lock=lock,
        )

        self.assertFalse(worker.run_once())
        client.claim.assert_not_called()
        client.heartbeat.assert_called_once()
        heartbeat_details = client.heartbeat.call_args.kwargs["details"]
        self.assertEqual(heartbeat_details["visual_lock"]["state"], "busy")
        self.assertEqual(lock.release_calls, 0)

    def test_worker_releases_visual_lock_after_claimed_job(self) -> None:
        lock = _FakeVisualLock(acquire_result=True)
        client = Mock()
        client.claim.return_value = {
            "id": "job-1",
            "lease_token": "lease-token",
            "job_type": "fluxo_caixa",
            "payload": {"category": "fluxo_caixa", "routines": ["140506"]},
        }
        runner = Mock()
        runner.run.return_value = PromaxRunResult(status="success", return_code=0, child_pid=123)
        worker = PromaxWorker(
            config=WorkerConfig(
                api_url="http://localhost:8080",
                token="token",
                worker_id="worker",
                driver_dir="C:/driver",
                python_executable="C:/driver/venv/Scripts/python.exe",
            ),
            client=client,
            runner=runner,
            visual_lock=lock,
        )

        self.assertTrue(worker.run_once())
        self.assertEqual(lock.release_calls, 1)
        runner.run.assert_called_once()
        client.finish.assert_called_once()

    def test_visual_automation_lock_blocks_second_holder_until_release(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = str(Path(temp_dir) / "promax_visual.lock")
            first = PromaxVisualAutomationLock(path=lock_path)
            second = PromaxVisualAutomationLock(path=lock_path)

            self.assertTrue(first.acquire({"worker_id": "worker-1"}))
            self.assertFalse(second.acquire({"worker_id": "worker-2"}))
            first.release()
            self.assertTrue(second.acquire({"worker_id": "worker-2"}))
            second.release()

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

    def test_worker_config_extends_lease_for_boleto_import_timeout(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PROMAX_WORKER_TOKEN": "token",
                "PROMAX_WORKER_LEASE_SECONDS": "120",
                "PROMAX_WORKER_BOLETO_IMPORT_TIMEOUT_SECONDS": "300",
            },
        ):
            config = WorkerConfig.from_env()

        self.assertEqual(config.boleto_import_timeout_seconds, 300)
        self.assertEqual(config.lease_seconds, 360)

    def test_030206_import_renews_job_lease_around_each_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir)
            for unit in ("0640001", "0640002"):
                (source_dir / f"03,02,06_{unit}.pdf").write_bytes(b"%PDF-1.4\nconteudo")
            client = Mock()
            client.import_boleto_pdf.return_value = {"ok": True, "result": {"imported": 1}}
            worker = PromaxWorker(
                config=WorkerConfig(
                    api_url="http://localhost:8080",
                    token="token",
                    worker_id="worker",
                    driver_dir=str(source_dir),
                    python_executable=str(source_dir / "python.exe"),
                    lease_seconds=360,
                    boleto_import_timeout_seconds=300,
                ),
                client=client,
                runner=Mock(),
                catalog_provider=None,
            )

            worker._import_030206_boletos_if_needed(
                {
                    "payload": {
                        "routines": ["030206_BOT"],
                        "units": ["0640001", "0640002"],
                        "end_date": "2026-07-21",
                    }
                },
                "job-1",
                "lease-token",
                PromaxRunResult(
                    status="success",
                    return_code=0,
                    child_pid=123,
                    details={
                        "metadata": {
                            "publication_mapping": {
                                str(source_dir.parent / "030206 bot"): str(source_dir),
                            }
                        }
                    },
                ),
            )

        self.assertEqual(client.import_boleto_pdf.call_count, 2)
        self.assertEqual(client.heartbeat_job.call_count, 4)

    def test_120601_bot_imports_all_csvs_in_one_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir)
            (source_dir / "2026-07 Sousa.csv").write_bytes(b"Cliente;Valor\n1;10\n")
            (source_dir / "2026-07 Patos.csv").write_bytes(b"Cliente;Valor\n2;20\n")
            client = Mock()
            client.import_inadimplencia_csvs.return_value = {
                "ok": True,
                "result": {"file_count": 2, "rows": 2, "batch_id": 42},
            }
            worker = PromaxWorker(
                config=WorkerConfig(
                    api_url="http://localhost:8080",
                    token="token",
                    worker_id="worker",
                    driver_dir=str(source_dir),
                    python_executable=str(source_dir / "python.exe"),
                    lease_seconds=360,
                    boleto_import_timeout_seconds=300,
                ),
                client=client,
                runner=Mock(),
                catalog_provider=None,
            )

            worker._import_120601_inadimplencia_if_needed(
                {
                    "payload": {
                        "routines": ["120601_BOT"],
                        "units": ["0640001", "2210003"],
                        "end_date": "2026-07-21",
                    }
                },
                "job-1",
                "lease-token",
                PromaxRunResult(
                    status="success",
                    return_code=0,
                    child_pid=123,
                    details={
                        "metadata": {
                            "publication_mapping": {
                                str(source_dir.parent / "120601 bot"): str(source_dir),
                            }
                        }
                    },
                ),
            )

        client.import_inadimplencia_csvs.assert_called_once()
        call_kwargs = client.import_inadimplencia_csvs.call_args.kwargs
        self.assertEqual(call_kwargs["reference_date"], "2026-07-21")
        self.assertEqual(sorted(call_kwargs["files"]), ["2026-07 Patos.csv", "2026-07 Sousa.csv"])
        self.assertEqual(client.heartbeat_job.call_count, 2)

    def test_020304_bot_imports_stock_csvs_by_unit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir)
            (source_dir / "02,03,04_2210003.csv").write_bytes(b"Grade;Cod;Descricao\n1;2;Produto\n")
            (source_dir / "02,03,04_2210004.csv").write_bytes(b"Grade;Cod;Descricao\n1;3;Produto\n")
            client = Mock()
            client.import_estoque_020304_csv.return_value = {
                "ok": True,
                "result": {"rows": 2, "pdf_bytes": 100, "batch_id": 46},
            }
            worker = PromaxWorker(
                config=WorkerConfig(
                    api_url="http://localhost:8080",
                    token="token",
                    worker_id="worker",
                    driver_dir=str(source_dir),
                    python_executable=str(source_dir / "python.exe"),
                    lease_seconds=360,
                    boleto_import_timeout_seconds=300,
                ),
                client=client,
                runner=Mock(),
                catalog_provider=None,
            )

            worker._import_020304_estoque_if_needed(
                {
                    "payload": {
                        "routines": ["020304_BOT"],
                        "units": ["2210003", "2210004"],
                        "end_date": "2026-07-23",
                    }
                },
                "job-1",
                "lease-token",
                PromaxRunResult(
                    status="success",
                    return_code=0,
                    child_pid=123,
                    details={
                        "metadata": {
                            "publication_mapping": {str(source_dir.parent / "020304 bot"): str(source_dir)}
                        }
                    },
                ),
            )

        self.assertEqual(client.import_estoque_020304_csv.call_count, 2)
        call_kwargs = client.import_estoque_020304_csv.call_args_list[0].kwargs
        self.assertEqual(call_kwargs["filial"], "3")
        self.assertEqual(call_kwargs["reference_date"], "2026-07-23")
        self.assertEqual(client.heartbeat_job.call_count, 4)

    def test_020220_bot_imports_comodatos_csvs_in_one_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir)
            (source_dir / "020220 bot - Sousa.csv").write_bytes(b"Cliente;Valor\n1;10\n")
            client = Mock()
            client.import_comodatos_csvs.return_value = {
                "ok": True,
                "result": {"file_count": 1, "rows": 5, "batch_id": 43},
            }
            worker = PromaxWorker(
                config=WorkerConfig(
                    api_url="http://localhost:8080",
                    token="token",
                    worker_id="worker",
                    driver_dir=str(source_dir),
                    python_executable=str(source_dir / "python.exe"),
                    lease_seconds=360,
                    boleto_import_timeout_seconds=300,
                ),
                client=client,
                runner=Mock(),
                catalog_provider=None,
            )

            worker._import_020220_comodatos_if_needed(
                {"payload": {"routines": ["020220_BOT"], "end_date": "2026-07-21"}},
                "job-1",
                "lease-token",
                PromaxRunResult(
                    status="success",
                    return_code=0,
                    child_pid=123,
                    details={"metadata": {"publication_mapping": {str(source_dir.parent / "020220 bot"): str(source_dir)}}},
                ),
            )

        client.import_comodatos_csvs.assert_called_once()
        self.assertEqual(client.heartbeat_job.call_count, 2)

    def test_0105070402_bot_imports_latest_dclientes_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir)
            old_path = source_dir / "0105070402 bot - velho.csv"
            new_path = source_dir / "0105070402 bot - novo.csv"
            old_path.write_bytes(b"Cliente;Valor\n1;10\n")
            new_path.write_bytes(b"Cliente;Valor\n2;20\n")
            os.utime(old_path, (1, 1))
            os.utime(new_path, (2, 2))
            client = Mock()
            client.import_dclientes_csv.return_value = {
                "ok": True,
                "result": {"rows": 500, "batch_id": 44},
            }
            worker = PromaxWorker(
                config=WorkerConfig(
                    api_url="http://localhost:8080",
                    token="token",
                    worker_id="worker",
                    driver_dir=str(source_dir),
                    python_executable=str(source_dir / "python.exe"),
                    lease_seconds=360,
                    boleto_import_timeout_seconds=300,
                ),
                client=client,
                runner=Mock(),
                catalog_provider=None,
            )

            worker._import_0105070402_dclientes_if_needed(
                {"payload": {"routines": ["0105070402_BOT"], "end_date": "2026-07-21"}},
                "job-1",
                "lease-token",
                PromaxRunResult(
                    status="success",
                    return_code=0,
                    child_pid=123,
                    details={
                        "metadata": {
                            "publication_mapping": {str(source_dir.parent / "0105070402 bot"): str(source_dir)}
                        }
                    },
                ),
            )

        client.import_dclientes_csv.assert_called_once()
        self.assertEqual(client.import_dclientes_csv.call_args.kwargs["filename"], "0105070402 bot - novo.csv")
        self.assertEqual(client.heartbeat_job.call_count, 2)

    def test_030111_bot_imports_critica_csvs_in_one_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir)
            (source_dir / "030111 bot - Patos.csv").write_bytes(b"Filial Origem;Valor\n3;10\n")
            (source_dir / "030111 bot - Sume.csv").write_bytes(b"Filial Origem;Valor\n4;20\n")
            client = Mock()
            client.import_critica_csvs.return_value = {
                "ok": True,
                "result": {"file_count": 2, "rows": 4, "batch_id": 45},
            }
            worker = PromaxWorker(
                config=WorkerConfig(
                    api_url="http://localhost:8080",
                    token="token",
                    worker_id="worker",
                    driver_dir=str(source_dir),
                    python_executable=str(source_dir / "python.exe"),
                    lease_seconds=360,
                    boleto_import_timeout_seconds=300,
                ),
                client=client,
                runner=Mock(),
                catalog_provider=None,
            )

            worker._import_030111_critica_if_needed(
                {"payload": {"routines": ["030111_BOT"], "end_date": "2026-07-21"}},
                "job-1",
                "lease-token",
                PromaxRunResult(
                    status="success",
                    return_code=0,
                    child_pid=123,
                    details={
                        "metadata": {
                            "publication_mapping": {str(source_dir.parent / "030111 bot"): str(source_dir)}
                        }
                    },
                ),
            )

        client.import_critica_csvs.assert_called_once()
        call_kwargs = client.import_critica_csvs.call_args.kwargs
        self.assertEqual(call_kwargs["reference_date"], "2026-07-21")
        self.assertEqual(sorted(call_kwargs["files"]), ["030111 bot - Patos.csv", "030111 bot - Sume.csv"])
        self.assertEqual(client.heartbeat_job.call_count, 2)


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
