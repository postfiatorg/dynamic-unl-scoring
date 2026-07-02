#!/usr/bin/env python3
"""Run the Phase 2 WS5 devnet withholding campaign.

The loop triggers scoring rounds, probes public surfaces during the commit
window from this workstation, runs the sidecar echo red-team probe, then records
one denominator row and a JSON evidence file per round.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import pathlib
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any


DEFAULT_BASE_URL = "https://scoring-devnet.postfiat.org"
DEFAULT_PUBLIC_VL_URL = "https://postfiat.org/devnet_vl.json"
DEFAULT_SCORING_HOST = "root@207.148.2.139"
DEFAULT_SIDECAR_HOST = "root@108.61.85.238"
DEFAULT_SCORING_DEPLOY_DIR = "/opt/dynamic-unl-scoring"
DEFAULT_SIDECAR_CONTAINER = "validator-scoring-sidecar"
DEFAULT_LOG_PATH = "docs/phase2/M2.8.1-WS5-Campaign.md"
DEFAULT_EVIDENCE_DIR = "docs/phase2/ws5-campaign"
OUTPUT_PATHS = (
    "bundle.json",
    "outputs/model_response.json",
    "outputs/validator_scores.json",
    "outputs/selected_unl.json",
    "outputs/signed_validator_list.json",
    "outputs/verification_hashes.json",
)
FINAL_PUBLIC_FIELDS = (
    "final_bundle_cid",
    "github_pages_commit_url",
    "memo_tx_hash",
)


class CampaignError(RuntimeError):
    """Raised when campaign automation cannot continue safely."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utcnow().isoformat()


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def run_command(
    args: list[str],
    *,
    input_text: str | None = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def require_success(result: subprocess.CompletedProcess[str], context: str) -> str:
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout or f"exit {result.returncode}"
        raise CampaignError(f"{context} failed: {detail}")
    return result.stdout


def ssh(host: str, remote_command: str, *, input_text: str | None = None, timeout: int = 120) -> str:
    result = run_command(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            host,
            remote_command,
        ],
        input_text=input_text,
        timeout=timeout,
    )
    return require_success(result, f"ssh {host}")


def extract_json(stdout: str) -> Any:
    for line in reversed(stdout.splitlines()):
        stripped = line.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            return json.loads(stripped)
    raise CampaignError(f"remote command did not emit JSON: {stdout[-500:]}")


def scoring_python(
    host: str,
    deploy_dir: str,
    code: str,
    *,
    env: dict[str, str] | None = None,
    timeout: int = 120,
) -> Any:
    env_args = ""
    if env:
        env_args = " ".join(
            f"-e {shlex.quote(key)}={shlex.quote(value)}"
            for key, value in sorted(env.items())
        )
    command = (
        f"cd {shlex.quote(deploy_dir)} && "
        f"docker compose exec -T {env_args} scoring python -"
    )
    return extract_json(ssh(host, command, input_text=code, timeout=timeout))


def http_get(url: str, *, timeout: int = 30) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": "ws5-campaign/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def http_json(url: str, *, timeout: int = 30) -> Any:
    status, body = http_get(url, timeout=timeout)
    if status < 200 or status >= 300:
        raise CampaignError(f"GET {url} returned HTTP {status}: {body[:200]!r}")
    return json.loads(body.decode("utf-8"))


def latest_public_round(base_url: str) -> dict[str, Any] | None:
    payload = http_json(f"{base_url.rstrip('/')}/api/scoring/rounds?limit=1")
    rounds = payload.get("rounds") or []
    return rounds[0] if rounds else None


def find_public_round(base_url: str, round_number: int) -> dict[str, Any] | None:
    payload = http_json(f"{base_url.rstrip('/')}/api/scoring/rounds?limit=100")
    for row in payload.get("rounds") or []:
        if row.get("round_number") == round_number:
            return row
    return None


def public_vl_snapshot(vl_url: str) -> dict[str, Any]:
    status, body = http_get(vl_url)
    if status != 200:
        raise CampaignError(f"GET {vl_url} returned HTTP {status}")
    sequence = None
    payload = json.loads(body.decode("utf-8"))
    if isinstance(payload, dict):
        if isinstance(payload.get("sequence"), int):
            sequence = payload["sequence"]
        elif isinstance(payload.get("blob"), str):
            sequence = _sequence_from_signed_blob(payload["blob"])
        elif payload.get("blobs_v2"):
            first = payload["blobs_v2"][0]
            if isinstance(first, dict) and isinstance(first.get("blob"), str):
                sequence = _sequence_from_signed_blob(first["blob"])
    return {
        "url": vl_url,
        "http_status": status,
        "sha256": hashlib.sha256(body).hexdigest(),
        "sequence": sequence,
        "fetched_at": iso_now(),
    }


def _sequence_from_signed_blob(blob: str) -> int | None:
    padded = blob + "=" * (-len(blob) % 4)
    decoded = base64.b64decode(padded).decode("utf-8")
    payload = json.loads(decoded)
    sequence = payload.get("sequence")
    return sequence if isinstance(sequence, int) else None


def trigger_round(host: str, deploy_dir: str) -> dict[str, Any]:
    command = (
        f"cd {shlex.quote(deploy_dir)} && "
        "key=$(awk -F= '$1==\"ADMIN_API_KEY\" {"
        "print substr($0,index($0,\"=\")+1); exit}' .env) && "
        "curl -fsS -X POST http://127.0.0.1:8000/api/scoring/trigger "
        "-H \"X-API-Key: ${key}\""
    )
    stdout = ssh(host, command, timeout=30)
    return json.loads(stdout)


def get_round_record(host: str, deploy_dir: str, round_number: int) -> dict[str, Any] | None:
    code = r'''
import json
import os
from datetime import datetime

from scoring_service.database import get_db

round_number = int(os.environ["ROUND_NUMBER"])
conn = get_db()
try:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT r.id, r.round_number, r.status, r.vl_sequence,
               r.final_bundle_cid, r.github_pages_commit_url, r.memo_tx_hash,
               r.announcement_tx_hash, r.output_publication_commit_closes_at,
               r.output_publication_due_at, r.output_publication_not_tracked,
               r.input_package_cid, r.input_package_hash, r.input_frozen_at,
               r.override_type, r.completed_at,
               a.tx_hash, a.commit_opens_at, a.commit_closes_at,
               a.reveal_opens_at, a.reveal_closes_at
        FROM scoring_rounds r
        LEFT JOIN round_announcements a ON a.round_number = r.round_number
        WHERE r.round_number = %s
        """,
        (round_number,),
    )
    row = cur.fetchone()
finally:
    conn.close()

def enc(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value

if row is None:
    print("null")
else:
    keys = [
        "id", "round_number", "status", "vl_sequence", "final_bundle_cid",
        "github_pages_commit_url", "memo_tx_hash", "announcement_tx_hash",
        "output_publication_commit_closes_at", "output_publication_due_at",
        "output_publication_not_tracked", "input_package_cid",
        "input_package_hash", "input_frozen_at", "override_type",
        "completed_at", "ingested_announcement_tx_hash", "commit_opens_at",
        "commit_closes_at", "reveal_opens_at", "reveal_closes_at",
    ]
    print(json.dumps({key: enc(value) for key, value in zip(keys, row)}, sort_keys=True))
'''
    return scoring_python(
        host,
        deploy_dir,
        code,
        env={"ROUND_NUMBER": str(round_number)},
    )


def latest_round_record_after(
    host: str,
    deploy_dir: str,
    before_round: int,
) -> dict[str, Any] | None:
    code = r'''
import json
import os
from datetime import datetime

from scoring_service.database import get_db

before_round = int(os.environ["BEFORE_ROUND"])
conn = get_db()
try:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT round_number
        FROM scoring_rounds
        WHERE round_number > %s
          AND override_type IS NULL
        ORDER BY round_number ASC
        LIMIT 1
        """,
        (before_round,),
    )
    row = cur.fetchone()
finally:
    conn.close()

print(json.dumps({"round_number": row[0] if row else None}))
'''
    payload = scoring_python(
        host,
        deploy_dir,
        code,
        env={"BEFORE_ROUND": str(before_round)},
    )
    round_number = payload.get("round_number")
    if round_number is None:
        return None
    return get_round_record(host, deploy_dir, int(round_number))


def wait_for_announced_round(
    host: str,
    deploy_dir: str,
    before_round: int,
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_seen: dict[str, Any] | None = None
    while time.time() < deadline:
        row = latest_round_record_after(host, deploy_dir, before_round)
        if row:
            last_seen = row
            if row.get("commit_opens_at") and row.get("commit_closes_at"):
                return row
        time.sleep(10)
    raise CampaignError(f"timed out waiting for announced round after {before_round}; last={last_seen}")


def wait_for_round_status(
    host: str,
    deploy_dir: str,
    round_number: int,
    status: str,
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_seen: dict[str, Any] | None = None
    while time.time() < deadline:
        row = get_round_record(host, deploy_dir, round_number)
        last_seen = row
        if row.get("status") == status:
            return row
        time.sleep(10)
    raise CampaignError(
        f"timed out waiting for round {round_number} to reach {status}; last={last_seen}"
    )


def wait_until(label: str, target: datetime) -> None:
    while True:
        remaining = (target - utcnow()).total_seconds()
        if remaining <= 0:
            return
        sleep_for = min(remaining, 30)
        print(f"{iso_now()} waiting {int(remaining)}s for {label}", flush=True)
        time.sleep(sleep_for)


def probe_output_paths(base_url: str, round_number: int) -> list[dict[str, Any]]:
    rows = []
    for path in OUTPUT_PATHS:
        url = f"{base_url.rstrip('/')}/api/scoring/rounds/{round_number}/{path}"
        status, body = http_get(url)
        rows.append(
            {
                "path": path,
                "url": url,
                "http_status": status,
                "timestamp": iso_now(),
                "body_sha256": hashlib.sha256(body).hexdigest() if body else None,
            }
        )
    return rows


def check_public_round_fields(base_url: str, round_number: int) -> dict[str, Any]:
    row = find_public_round(base_url, round_number)
    if row is None:
        return {"round_number": round_number, "found": False, "timestamp": iso_now()}
    return {
        "round_number": round_number,
        "found": True,
        "timestamp": iso_now(),
        "status": row.get("status"),
        "fields": {field: row.get(field) for field in FINAL_PUBLIC_FIELDS},
    }


def find_final_memos_on_chain(host: str, deploy_dir: str, round_number: int) -> list[dict[str, Any]]:
    code = r'''
import json
import os

from xrpl.utils import hex_to_str

from scoring_service.clients.pftl import PFTLClient
from scoring_service.config import settings

round_number = int(os.environ["ROUND_NUMBER"])
client = PFTLClient()
result = client.account_tx(client.publisher_address, limit=80, forward=False)
matches = []
for entry in result.get("transactions") or []:
    tx = entry.get("tx") or entry.get("tx_json") or {}
    tx_hash = entry.get("hash") or tx.get("hash")
    for memo_entry in tx.get("Memos") or []:
        memo = memo_entry.get("Memo") if isinstance(memo_entry, dict) else None
        if not isinstance(memo, dict):
            continue
        try:
            memo_type = hex_to_str(memo.get("MemoType") or "")
            memo_data = json.loads(hex_to_str(memo.get("MemoData") or ""))
        except Exception:
            continue
        if memo_type != settings.scoring_memo_type:
            continue
        if memo_data.get("round_number") == round_number:
            matches.append({
                "tx_hash": tx_hash,
                "ledger_index": entry.get("ledger_index") or tx.get("ledger_index"),
                "vl_sequence": memo_data.get("vl_sequence"),
                "final_bundle_cid": memo_data.get("final_bundle_cid"),
            })
print(json.dumps(matches, sort_keys=True))
'''
    payload = scoring_python(
        host,
        deploy_dir,
        code,
        env={"ROUND_NUMBER": str(round_number)},
    )
    if not isinstance(payload, list):
        raise CampaignError(f"unexpected on-chain memo payload: {payload!r}")
    return payload


def restart_scoring_service(
    host: str,
    deploy_dir: str,
    round_number: int,
    *,
    round_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started_at = iso_now()
    command = f"cd {shlex.quote(deploy_dir)} && docker compose restart scoring >/dev/null"
    ssh(host, command, timeout=180)
    event = {
        "round_number": round_number,
        "action": "docker compose restart scoring",
        "started_at": started_at,
        "completed_at": iso_now(),
    }
    if round_record:
        event["status_before_restart"] = round_record.get("status")
        event["output_publication_commit_closes_at"] = round_record.get(
            "output_publication_commit_closes_at"
        )
        event["output_publication_due_at"] = round_record.get("output_publication_due_at")
    return event


def get_foundation_publisher_address(host: str, deploy_dir: str) -> str:
    code = r'''
import json

from scoring_service.clients.pftl import PFTLClient

print(json.dumps({"publisher_address": PFTLClient().publisher_address}))
'''
    payload = scoring_python(host, deploy_dir, code)
    address = payload.get("publisher_address") if isinstance(payload, dict) else None
    if not isinstance(address, str) or not address:
        raise CampaignError(f"could not resolve foundation publisher address: {payload!r}")
    return address


def wrong_hash_for(input_hash: str) -> str:
    replacement = "0" if input_hash[0] != "0" else "1"
    return replacement + input_hash[1:]


def submit_announcement_mismatch_commit(
    *,
    sidecar_host: str,
    sidecar_container: str,
    network: str,
    foundation_publisher_address: str,
    round_record: dict[str, Any],
) -> dict[str, Any]:
    wrong_input_hash = wrong_hash_for(round_record["input_package_hash"])
    code = r'''
import json
import os
from datetime import datetime

from xrpl.core import keypairs
from xrpl.core.addresscodec import encode_node_public_key

from validator_scoring_sidecar.chain import XrplPftlRpcClient
from validator_scoring_sidecar.config import load_config
from validator_scoring_sidecar.scoring import commit_reveal

network = os.environ["NETWORK"]
round_number = int(os.environ["ROUND_NUMBER"])
foundation = os.environ["FOUNDATION_PUBLISHER_ADDRESS"]
wrong_input_hash = os.environ["WRONG_INPUT_HASH"]
commit_opens_at = datetime.fromisoformat(os.environ["COMMIT_OPENS_AT"])
commit_closes_at = datetime.fromisoformat(os.environ["COMMIT_CLOSES_AT"])

config = load_config(network=network)
if not config.validator_wallet_seed:
    raise RuntimeError("sidecar validator wallet seed is not configured")

rpc = XrplPftlRpcClient(config.pftl_rpc_url)
close_time = rpc.latest_validated_ledger_close_time()
if close_time < commit_opens_at:
    raise RuntimeError(f"commit window is not open: {close_time.isoformat()}")
if close_time >= commit_closes_at:
    raise RuntimeError(f"commit window is closed: {close_time.isoformat()}")

seed = keypairs.generate_seed()
public_key, private_key = keypairs.derive_keypair(seed)
master_key = encode_node_public_key(bytes.fromhex(public_key))
output_hashes = commit_reveal.OutputHashes(
    model_response_hash="1" * 64,
    validator_scores_hash="2" * 64,
    selected_unl_hash="3" * 64,
)
salt = "a" * 64
commitment_hash = commit_reveal.compute_commitment_hash(
    protocol_version=commit_reveal.PROTOCOL_VERSION,
    network=network,
    round_number=round_number,
    validator_master_key=master_key,
    input_package_hash=wrong_input_hash,
    output_hashes=output_hashes,
    salt=salt,
)
signing_bytes = commit_reveal.build_commit_signing_bytes(
    protocol_version=commit_reveal.PROTOCOL_VERSION,
    network=network,
    round_number=round_number,
    validator_master_key=master_key,
    input_package_hash=wrong_input_hash,
    commitment_hash=commitment_hash,
)
signature = keypairs.sign(signing_bytes, private_key)
payload = commit_reveal.build_commit_payload(
    protocol_version=commit_reveal.PROTOCOL_VERSION,
    network=network,
    round_number=round_number,
    validator_master_key=master_key,
    input_package_hash=wrong_input_hash,
    commitment_hash=commitment_hash,
    signature=signature,
)
memo_data = commit_reveal.canonical_json_bytes(payload).decode("utf-8")
tx_hash = rpc.submit_memo(
    wallet_seed=config.validator_wallet_seed,
    destination=foundation,
    memo_type=commit_reveal.VALIDATOR_COMMIT_TYPE,
    memo_data=memo_data,
)
print(json.dumps({
    "tx_hash": tx_hash,
    "validator_master_key": master_key,
    "wrong_input_package_hash": wrong_input_hash,
    "commitment_hash": commitment_hash,
    "ledger_close_time": close_time.isoformat(),
}, sort_keys=True))
'''
    command = (
        "docker exec -i "
        f"-e NETWORK={shlex.quote(network)} "
        f"-e ROUND_NUMBER={int(round_record['round_number'])} "
        f"-e FOUNDATION_PUBLISHER_ADDRESS={shlex.quote(foundation_publisher_address)} "
        f"-e WRONG_INPUT_HASH={shlex.quote(wrong_input_hash)} "
        f"-e COMMIT_OPENS_AT={shlex.quote(round_record['commit_opens_at'])} "
        f"-e COMMIT_CLOSES_AT={shlex.quote(round_record['commit_closes_at'])} "
        f"{shlex.quote(sidecar_container)} python -"
    )
    result = ssh(sidecar_host, command, input_text=code, timeout=180)
    payload = extract_json(result)
    if not isinstance(payload, dict):
        raise CampaignError(f"unexpected mismatch injection response: {payload!r}")
    return {
        "timestamp": iso_now(),
        "expected_outcome": "announcement_mismatch",
        **payload,
    }


def run_echo_probe(
    *,
    sidecar_host: str,
    sidecar_container: str,
    sidecar_script: pathlib.Path,
    base_url: str,
    network: str,
    round_number: int,
    foundation_publisher_address: str | None,
) -> dict[str, Any]:
    if not sidecar_script.exists():
        raise CampaignError(f"echo probe script not found: {sidecar_script}")
    remote_tmp = f"/tmp/ws5_echo_red_team_probe_{os.getpid()}.py"
    scp_result = run_command(
        [
            "scp",
            "-q",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            str(sidecar_script),
            f"{sidecar_host}:{remote_tmp}",
        ],
        timeout=60,
    )
    require_success(scp_result, "copy echo probe to sidecar host")
    command = (
        f"docker cp {shlex.quote(remote_tmp)} "
        f"{shlex.quote(sidecar_container)}:/tmp/echo_red_team_probe.py >/dev/null && "
        f"rm -f {shlex.quote(remote_tmp)} && "
        f"docker exec {shlex.quote(sidecar_container)} python "
        "/tmp/echo_red_team_probe.py "
        f"--round-number {round_number} "
        f"--network {shlex.quote(network)} "
        f"--base-url {shlex.quote(base_url)} "
        + (
            f"--foundation-publisher-address {shlex.quote(foundation_publisher_address)} "
            if foundation_publisher_address
            else ""
        )
        +
        "--submit-commit"
    )
    result = run_command(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            sidecar_host,
            command,
        ],
        timeout=180,
    )
    return {
        "timestamp": iso_now(),
        "exit_code": result.returncode,
        "stdout_summary": sanitize_probe_output(result.stdout),
        "stderr_summary": sanitize_probe_output(result.stderr),
    }


def run_echo_probe_until_ready(
    *,
    commit_closes_at: datetime,
    retry_seconds: int,
    **kwargs: Any,
) -> dict[str, Any]:
    attempts = []
    while True:
        attempt = run_echo_probe(**kwargs)
        attempts.append(dict(attempt))
        if attempt["exit_code"] in {0, 1}:
            return {**attempt, "attempts": attempts}
        if (commit_closes_at - utcnow()).total_seconds() <= retry_seconds:
            return {**attempt, "attempts": attempts}
        print(
            f"{iso_now()} echo probe returned {attempt['exit_code']}; "
            f"retrying in {retry_seconds}s",
            flush=True,
        )
        time.sleep(retry_seconds)


def sanitize_probe_output(output: str) -> list[str]:
    sanitized = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.endswith("_hash=") or "_hash=" in stripped:
            continue
        sanitized.append(stripped)
    return sanitized[-8:]


def wait_for_public_completion(
    base_url: str,
    round_number: int,
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last = None
    while time.time() < deadline:
        row = find_public_round(base_url, round_number)
        if row:
            last = row
            if row.get("status") in {"COMPLETE", "VL_PUBLISHED_MEMO_FAILED"}:
                return row
        time.sleep(15)
    raise CampaignError(f"round {round_number} did not complete in time; last={last}")


def wait_for_convergence(
    base_url: str,
    round_number: int,
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last = None
    while time.time() < deadline:
        view = http_json(f"{base_url.rstrip('/')}/api/scoring/rounds/{round_number}/convergence")
        last = view
        if view.get("finalized") is True and view.get("anchor_tx_hash"):
            return view
        time.sleep(20)
    raise CampaignError(f"round {round_number} convergence did not seal in time; last={last}")


def summarize_convergence(view: dict[str, Any]) -> dict[str, Any]:
    report = view.get("report") if isinstance(view.get("report"), dict) else {}
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    participants = report.get("participants") if isinstance(report.get("participants"), list) else []
    return {
        "phase": view.get("phase"),
        "finalized": view.get("finalized"),
        "convergence_bundle_cid": view.get("convergence_bundle_cid"),
        "anchor_tx_hash": view.get("anchor_tx_hash"),
        "committers": summary.get("committers"),
        "outcomes": summary.get("outcomes"),
        "levels_matched": summary.get("levels_matched"),
        "divergence_categories": summary.get("divergence_categories"),
        "participants": [
            {
                "validator_master_key": item.get("validator_master_key"),
                "outcome": item.get("outcome"),
                "accepted_commit_tx": item.get("accepted_commit_tx"),
                "accepted_reveal_tx": item.get("accepted_reveal_tx"),
                "comparison_levels_matched": item.get("comparison_levels_matched"),
            }
            for item in participants
        ],
    }


def disposition(evidence: dict[str, Any]) -> str:
    if evidence.get("error"):
        return f"failed:{evidence.get('error_stage', 'campaign-error')}"

    probe_sets = evidence.get("mid_window_probes") or []
    output_statuses = [
        item.get("http_status")
        for probe in probe_sets
        for item in probe.get("output_paths", [])
    ]
    fields = [
        value
        for probe in probe_sets
        for value in (probe.get("public_round_fields") or {}).get("fields", {}).values()
    ]
    vl_ok = all(
        (probe.get("public_vl") or {}).get("sequence")
        == (evidence.get("baseline_public_vl") or {}).get("sequence")
        for probe in probe_sets
    )
    no_memos = all(not probe.get("onchain_final_memos") for probe in probe_sets)
    echo_ok = all((probe.get("echo_probe") or {}).get("exit_code") == 0 for probe in probe_sets)
    convergence = evidence.get("convergence_summary") or {}
    outcomes = convergence.get("outcomes") or {}
    valid_count = outcomes.get("valid") or outcomes.get("VALID") or 0
    expected = evidence.get("expected_outcomes") or {}

    if any(status == 200 for status in output_statuses):
        return "failed:mid-window-output-leak"
    if any(value for value in fields):
        return "failed:public-final-field-mid-window"
    if not vl_ok:
        return "failed:vl-advanced-mid-window"
    if not no_memos:
        return "failed:final-memo-mid-window"
    if not echo_ok:
        return "failed:echo-probe"
    if convergence.get("finalized") is not True:
        return "failed:convergence-not-finalized"
    if expected.get("announcement_mismatch"):
        mismatch_count = outcomes.get("announcement_mismatch") or 0
        if mismatch_count != 1:
            return "failed:announcement-mismatch-injection"
        if convergence.get("divergence_categories"):
            return "failed:divergence"
        if convergence.get("committers") != 4 or valid_count != 3:
            return "injection_observed:announcement_mismatch_sidecar_gap"
        return "tracked_injection:announcement_mismatch"
    if convergence.get("committers") != 3 or valid_count != 3:
        return "failed:convergence-not-3-valid"
    if convergence.get("divergence_categories"):
        return "failed:divergence"
    return "tracked"


def write_evidence(path: pathlib.Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_log_row(log_path: pathlib.Path, evidence: dict[str, Any], evidence_path: pathlib.Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if not log_path.exists():
        log_path.write_text(initial_log_text(), encoding="utf-8")

    round_number = evidence["round_number"]
    convergence = evidence.get("convergence_summary") or {}
    output_codes = sorted(
        {
            str(item.get("http_status"))
            for probe in evidence.get("mid_window_probes") or []
            for item in probe.get("output_paths", [])
        }
    )
    fields_ok = all(
        not value
        for probe in evidence.get("mid_window_probes") or []
        for value in (probe.get("public_round_fields") or {}).get("fields", {}).values()
    )
    vl_sequence = (evidence.get("baseline_public_vl") or {}).get("sequence")
    public_row = evidence.get("public_completion") or {}
    outcomes = convergence.get("outcomes") or {}
    levels = convergence.get("levels_matched") or {}
    injection = evidence.get("announcement_mismatch_injection")
    injection_text = ""
    if injection:
        injection_text = (
            f"; injected_announcement_mismatch={injection.get('tx_hash', 'n/a')}"
        )
    evidence_link = os.path.relpath(evidence_path, start=log_path.parent)
    row = (
        f"| {round_number} | {evidence.get('started_at')} | "
        f"{evidence.get('disposition')} | "
        f"{convergence.get('committers')} committers; outcomes={compact_json(outcomes)} | "
        f"levels={compact_json(levels)} | "
        f"output_http={','.join(output_codes) or 'n/a'}; fields_clear={str(fields_ok).lower()}; "
        f"vl_seq_mid={vl_sequence}; echo={echo_exit_codes(evidence)}{injection_text} | "
        f"{public_row.get('final_bundle_cid') or 'n/a'} | "
        f"{public_row.get('memo_tx_hash') or 'n/a'} | "
        f"[json]({pathlib.Path(evidence_link).as_posix()}) |\n"
    )

    content = log_path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    prefix = f"| {round_number} |"
    replaced = False
    for idx, line in enumerate(lines):
        if line.startswith(prefix):
            lines[idx] = row
            replaced = True
            break
    if not replaced:
        lines.append(row)
    log_path.write_text("".join(lines), encoding="utf-8")


def initial_log_text() -> str:
    return """# M2.8.1 WS5 Devnet Campaign As-Run

Scope: Dynamic UNL Phase 2 post-hardening withholding campaign on devnet.
This is an internal readiness record only; it is not a public announcement.

## Denominator

Every round in the campaign window gets one row, including failures and
not-tracked rounds.

| Round | Started UTC | Disposition | Participation | Matched Levels | Mid-Window Checks | Final Bundle CID | Memo Tx | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
"""


def compact_json(value: Any) -> str:
    return json.dumps(value or {}, sort_keys=True, separators=(",", ":"))


def echo_exit_codes(evidence: dict[str, Any]) -> str:
    codes = [
        str((probe.get("echo_probe") or {}).get("exit_code"))
        for probe in evidence.get("mid_window_probes") or []
    ]
    return ",".join(codes) if codes else "n/a"


def run_round(args: argparse.Namespace, *, before_round: int | None = None) -> dict[str, Any]:
    latest = latest_public_round(args.base_url)
    if latest is None:
        raise CampaignError("public rounds endpoint returned no rounds")
    previous_round = before_round if before_round is not None else int(latest["round_number"])
    baseline_vl = public_vl_snapshot(args.public_vl_url)

    print(f"{iso_now()} triggering round after {previous_round}", flush=True)
    trigger_result = trigger_round(args.scoring_host, args.scoring_deploy_dir)
    print(f"{iso_now()} trigger accepted: {trigger_result}", flush=True)

    record = wait_for_announced_round(
        args.scoring_host,
        args.scoring_deploy_dir,
        previous_round,
        timeout_seconds=args.announce_timeout_seconds,
    )
    round_number = int(record["round_number"])
    print(f"{iso_now()} round {round_number} announced", flush=True)

    commit_opens = parse_ts(record["commit_opens_at"])
    commit_closes = parse_ts(record["commit_closes_at"])
    reveal_closes = parse_ts(record["reveal_closes_at"])
    restart_event = None
    if args.restart_scoring_during_hold:
        record = wait_for_round_status(
            args.scoring_host,
            args.scoring_deploy_dir,
            round_number,
            "AWAITING_COMMIT_CLOSE",
            timeout_seconds=args.hold_status_timeout_seconds,
        )
        restart_event = restart_scoring_service(
            args.scoring_host,
            args.scoring_deploy_dir,
            round_number,
            round_record=record,
        )
    midpoint = commit_opens + (commit_closes - commit_opens) / 2
    probe_at = max(commit_opens, midpoint)
    if utcnow() >= commit_closes:
        raise CampaignError(f"round {round_number} commit window already closed")
    wait_until(f"round {round_number} mid-window probe", probe_at)

    publisher_address = args.foundation_publisher_address or get_foundation_publisher_address(
        args.scoring_host,
        args.scoring_deploy_dir,
    )
    mismatch_injection = None
    probe = {
        "timestamp": iso_now(),
        "output_paths": probe_output_paths(args.base_url, round_number),
        "public_round_fields": check_public_round_fields(args.base_url, round_number),
        "public_vl": public_vl_snapshot(args.public_vl_url),
        "onchain_final_memos": find_final_memos_on_chain(
            args.scoring_host,
            args.scoring_deploy_dir,
            round_number,
        ),
        "echo_probe": run_echo_probe_until_ready(
            commit_closes_at=commit_closes,
            retry_seconds=30,
            sidecar_host=args.sidecar_host,
            sidecar_container=args.sidecar_container,
            sidecar_script=args.echo_probe_script,
            base_url=args.base_url,
            network=args.network,
            round_number=round_number,
            foundation_publisher_address=publisher_address,
        ),
    }
    if args.announcement_mismatch_injection:
        mismatch_injection = submit_announcement_mismatch_commit(
            sidecar_host=args.sidecar_host,
            sidecar_container=args.sidecar_container,
            network=args.network,
            foundation_publisher_address=publisher_address,
            round_record=record,
        )
    checkpoint = {
        "round_number": round_number,
        "started_at": record.get("input_frozen_at") or record.get("commit_opens_at"),
        "record": record,
        "baseline_public_vl": baseline_vl,
        "mid_window_probes": [probe],
        "restart_event": restart_event,
        "announcement_mismatch_injection": mismatch_injection,
        "expected_outcomes": (
            {"valid": 3, "announcement_mismatch": 1}
            if mismatch_injection
            else {"valid": 3}
        ),
        "campaign_record_status": "pending_convergence_seal",
        "recorded_at": iso_now(),
    }
    write_evidence(args.evidence_dir / f"round-{round_number}.json", checkpoint)

    try:
        wait_until(f"round {round_number} reveal close", reveal_closes)
        public_completion = wait_for_public_completion(
            args.base_url,
            round_number,
            timeout_seconds=args.completion_timeout_seconds,
        )
        convergence = wait_for_convergence(
            args.base_url,
            round_number,
            timeout_seconds=args.convergence_timeout_seconds,
        )
        final_record = get_round_record(args.scoring_host, args.scoring_deploy_dir, round_number)
        error = None
    except Exception as exc:
        public_completion = find_public_round(args.base_url, round_number) or {}
        try:
            convergence = http_json(
                f"{args.base_url.rstrip('/')}/api/scoring/rounds/{round_number}/convergence"
            )
        except Exception:
            convergence = {}
        final_record = get_round_record(args.scoring_host, args.scoring_deploy_dir, round_number)
        error = {
            "stage": "post-probe-completion",
            "type": type(exc).__name__,
            "message": str(exc),
        }

    evidence = {
        "round_number": round_number,
        "started_at": record.get("input_frozen_at") or record.get("commit_opens_at"),
        "record": record,
        "final_record": final_record,
        "baseline_public_vl": baseline_vl,
        "mid_window_probes": [probe],
        "restart_event": restart_event,
        "announcement_mismatch_injection": mismatch_injection,
        "expected_outcomes": (
            {"valid": 3, "announcement_mismatch": 1}
            if mismatch_injection
            else {"valid": 3}
        ),
        "public_completion": public_completion,
        "convergence_summary": summarize_convergence(convergence),
        "campaign_record_status": "sealed",
        "recorded_at": iso_now(),
    }
    if error:
        evidence["campaign_record_status"] = "failed_after_mid_window_probe"
        evidence["error"] = error
        evidence["error_stage"] = error["stage"]
    evidence["disposition"] = disposition(evidence)
    return evidence


def default_echo_script() -> pathlib.Path:
    repos_dir = pathlib.Path(__file__).resolve().parents[2]
    return repos_dir / "validator-scoring-sidecar/scripts/echo_red_team_probe.py"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--network", default="devnet", choices=("devnet", "testnet"))
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--public-vl-url", default=DEFAULT_PUBLIC_VL_URL)
    parser.add_argument("--scoring-host", default=DEFAULT_SCORING_HOST)
    parser.add_argument("--sidecar-host", default=DEFAULT_SIDECAR_HOST)
    parser.add_argument("--scoring-deploy-dir", default=DEFAULT_SCORING_DEPLOY_DIR)
    parser.add_argument("--sidecar-container", default=DEFAULT_SIDECAR_CONTAINER)
    parser.add_argument("--foundation-publisher-address")
    parser.add_argument(
        "--announcement-mismatch-injection",
        action="store_true",
        help="Submit one wrong-input-hash commit from a generated test identity.",
    )
    parser.add_argument(
        "--restart-scoring-during-hold",
        action="store_true",
        help="Restart the scoring service after the round enters the hold window.",
    )
    parser.add_argument("--log-path", type=pathlib.Path, default=pathlib.Path(DEFAULT_LOG_PATH))
    parser.add_argument(
        "--evidence-dir",
        type=pathlib.Path,
        default=pathlib.Path(DEFAULT_EVIDENCE_DIR),
    )
    parser.add_argument("--echo-probe-script", type=pathlib.Path, default=default_echo_script())
    parser.add_argument("--announce-timeout-seconds", type=int, default=900)
    parser.add_argument("--completion-timeout-seconds", type=int, default=900)
    parser.add_argument("--convergence-timeout-seconds", type=int, default=1200)
    parser.add_argument("--hold-status-timeout-seconds", type=int, default=900)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.rounds < 1:
        raise CampaignError("--rounds must be >= 1")

    previous_round = None
    for _ in range(args.rounds):
        evidence = run_round(args, before_round=previous_round)
        evidence_path = args.evidence_dir / f"round-{evidence['round_number']}.json"
        write_evidence(evidence_path, evidence)
        append_log_row(args.log_path, evidence, evidence_path)
        previous_round = evidence["round_number"]
        print(
            f"{iso_now()} recorded round {previous_round}: "
            f"{evidence['disposition']} -> {evidence_path}",
            flush=True,
        )
        if not str(evidence["disposition"]).startswith("tracked"):
            return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CampaignError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
