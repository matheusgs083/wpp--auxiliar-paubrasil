from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "exports" / "backups"
DEFAULT_ACCESS_SCHEMA = "bot_access"
VOLUME_NAMES = ("evolution_instances", "evolution_store")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gera backup operacional da stack: dump do Postgres e volumes da Evolution."
    )
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="Arquivo .env a ser lido.")
    parser.add_argument("--output-dir", default="", help="Diretorio raiz dos backups.")
    parser.add_argument("--retention-days", type=int, default=-1, help="Dias para manter backups. -1 usa .env.")
    parser.add_argument("--schema", default="", help="Schema do Postgres que sera salvo. Padrao: ACCESS_DB_SCHEMA.")
    parser.add_argument("--external-dir", default="", help="Diretorio externo para espelhar o backup pronto.")
    parser.add_argument("--include-volumes", action="store_true", help="Inclui volumes da Evolution no backup.")
    parser.add_argument("--skip-volumes", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--dry-run", action="store_true", help="So mostra o que seria feito.")
    args = parser.parse_args()

    env = load_env_file(Path(args.env_file))
    output_root = Path(args.output_dir or env.get("BACKUP_OUTPUT_DIR", "") or DEFAULT_OUTPUT_DIR).resolve()
    retention_days = args.retention_days if args.retention_days >= 0 else int(env.get("BACKUP_RETENTION_DAYS", "7"))
    schema_name = (args.schema or env.get("BACKUP_ACCESS_SCHEMA", "") or env.get("ACCESS_DB_SCHEMA", "") or DEFAULT_ACCESS_SCHEMA).strip()
    include_volumes = bool(args.include_volumes and not args.skip_volumes)
    external_root_raw = (args.external_dir or env.get("BACKUP_EXTERNAL_DIR", "")).strip()
    external_root = Path(external_root_raw).resolve() if external_root_raw else None

    required = {
        "POSTGRES_USER": env.get("POSTGRES_USER", "").strip(),
        "POSTGRES_DB": env.get("POSTGRES_DB", "").strip(),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"Variaveis obrigatorias ausentes no .env: {', '.join(missing)}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_dir = output_root / timestamp
    manifest_path = backup_dir / "manifest.json"

    plan = {
        "backup_dir": str(backup_dir),
        "schema": schema_name,
        "postgres_dump": str(backup_dir / "postgres" / f"{schema_name}.dump"),
        "volumes": [str(backup_dir / "volumes" / f"{volume}.tar.gz") for volume in VOLUME_NAMES] if include_volumes else [],
        "external_copy": str(external_root / timestamp) if external_root is not None else "",
        "retention_days": retention_days,
    }

    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "plan": plan}, ensure_ascii=True, indent=2))
        return 0

    backup_dir.mkdir(parents=True, exist_ok=True)
    postgres_dir = backup_dir / "postgres"
    postgres_dir.mkdir(parents=True, exist_ok=True)
    dump_path = postgres_dir / f"{schema_name}.dump"
    dump_postgres(
        dump_path=dump_path,
        postgres_user=required["POSTGRES_USER"],
        postgres_db=required["POSTGRES_DB"],
        schema_name=schema_name,
    )

    volume_artifacts: list[dict[str, object]] = []
    if include_volumes:
        volumes_dir = backup_dir / "volumes"
        volumes_dir.mkdir(parents=True, exist_ok=True)
        for volume_name in VOLUME_NAMES:
            artifact_path = volumes_dir / f"{volume_name}.tar.gz"
            backup_volume(volume_name=volume_name, output_path=artifact_path)
            volume_artifacts.append(
                {
                    "volume_name": volume_name,
                    "path": str(artifact_path),
                    "size_bytes": artifact_path.stat().st_size,
                }
            )

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "backup_dir": str(backup_dir),
        "schema": schema_name,
        "postgres_dump": {
            "path": str(dump_path),
            "size_bytes": dump_path.stat().st_size,
        },
        "volumes": volume_artifacts,
        "external_copy": "",
        "retention_days": retention_days,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8")

    external_copy_path = ""
    if external_root is not None:
        external_backup_dir = external_root / timestamp
        mirror_backup(source_dir=backup_dir, destination_dir=external_backup_dir)
        external_copy_path = str(external_backup_dir)
        manifest["external_copy"] = external_copy_path
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8")
        external_manifest_path = external_backup_dir / "manifest.json"
        external_manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8")

    removed = prune_old_backups(output_root=output_root, retention_days=retention_days)
    removed_external = prune_old_backups(output_root=external_root, retention_days=retention_days) if external_root is not None else []
    result = {
        "ok": True,
        "backup_dir": str(backup_dir),
        "manifest": str(manifest_path),
        "removed_old_backups": removed,
        "external_copy": external_copy_path,
        "removed_old_external_backups": removed_external,
    }
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


def load_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        env[key.strip()] = strip_wrapping_quotes(value.strip())
    return env


def strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def dump_postgres(*, dump_path: Path, postgres_user: str, postgres_db: str, schema_name: str) -> None:
    last_error = ""
    for attempt in range(1, 4):
        if dump_path.exists():
            dump_path.unlink()
        try:
            with dump_path.open("wb") as handle:
                run_command(
                    [
                        "docker",
                        "exec",
                        "evolution-postgres",
                        "pg_dump",
                        "-U",
                        postgres_user,
                        "-d",
                        postgres_db,
                        "-n",
                        schema_name,
                        "-Fc",
                        "--no-owner",
                        "--no-privileges",
                    ],
                    stdout=handle,
                )
            return
        except RuntimeError as exc:
            last_error = str(exc)
            if attempt >= 3:
                break
            time.sleep(min(attempt * 2, 5))
    raise RuntimeError(f"Falha ao gerar pg_dump apos 3 tentativas.\n{last_error}")


def backup_volume(*, volume_name: str, output_path: Path) -> None:
    output_dir = output_path.parent.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{volume_name}:/source:ro",
            "-v",
            f"{output_dir}:/backup",
            "alpine:3.20",
            "sh",
            "-c",
            f"tar -czf /backup/{output_path.name} -C /source .",
        ]
    )


def prune_old_backups(*, output_root: Path, retention_days: int) -> list[str]:
    if retention_days <= 0 or output_root is None or not output_root.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    removed: list[str] = []
    for child in output_root.iterdir():
        if not child.is_dir():
            continue
        modified = datetime.fromtimestamp(child.stat().st_mtime, tz=timezone.utc)
        if modified >= cutoff:
            continue
        shutil.rmtree(child, ignore_errors=True)
        removed.append(str(child))
    return removed


def mirror_backup(*, source_dir: Path, destination_dir: Path) -> None:
    if destination_dir.exists():
        shutil.rmtree(destination_dir, ignore_errors=True)
    destination_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, destination_dir)


def run_command(command: Iterable[str], *, stdout: object | None = None) -> None:
    completed = subprocess.run(
        list(command),
        cwd=PROJECT_ROOT,
        check=False,
        stdout=stdout,
        stderr=subprocess.PIPE,
        text=stdout is None,
    )
    if completed.returncode != 0:
        stderr_raw = completed.stderr or b""
        if isinstance(stderr_raw, bytes):
            stderr = stderr_raw.decode("utf-8", errors="replace").strip()
        else:
            stderr = str(stderr_raw).strip()
        raise RuntimeError(f"Comando falhou ({completed.returncode}): {' '.join(command)}\n{stderr}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True, indent=2), file=sys.stderr)
        raise
