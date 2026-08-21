"""Same-GPU cross-machine determinism test on Modal.

Boots two concurrent SGLang servers, each on 4x H100, and proves from inside
the containers that they run on distinct physical machines with identical
setups (GPU variant, memory, driver, CUDA) before any inference money is
spent. Each machine then replays the four frozen wire payloads from
docs/crossmachine-determinism-evidence/inputs/wire/ and returns raw
responses plus content fingerprints.

This is a batch experiment, deliberately separate from the production
endpoint deployments in infra/: no web server, no proxy auth — the server
binds to 127.0.0.1 and requests are sent from inside the same container,
mirroring the SSH-only isolation of the Vast.ai protocol.

Usage:
    modal run scripts/samegpu_determinism_test.py::download_weights   # one-time, CPU only
    modal run scripts/samegpu_determinism_test.py::main               # the test session
"""

import json
import os
import subprocess
import time
from pathlib import Path

import modal

APP_NAME = "samegpu-determinism-test"
MODEL_ID = "Qwen/Qwen3.5-122B-A10B-FP8"
MODEL_REVISION = "a099dee70ccfcd8d5dda56aaa0b60cb8ecadabc9"
VOLUME_NAME = "determinism-test-qwen35-122b-weights"
COORD_NAME = "samegpu-determinism-coord"
SGLANG_IMAGE_TAG = (
    "lmsysorg/sglang:nightly-dev-cu13-20260817-d91c3682"
    "@sha256:fa8774dd128600a09fd6d46670b06fb69a55dac8a3881e50ccf0916a45eb39af"
)
GPU_SPEC = "H100!:4"
TENSOR_PARALLEL = 4
SGLANG_PORT = 30000
HF_CACHE_PATH = "/model-cache/huggingface"

EVIDENCE_DIR = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "crossmachine-determinism-evidence"
)

INPUT_ORDER = ["simple", "round19", "moderate", "long"]
BOOT1_PASSES = 2
BOOT2_PASSES = 1

SERVER_BOOT_TIMEOUT_S = 2400
REQUEST_TIMEOUT_S = 3600
DECISION_TIMEOUT_S = 1800
FINGERPRINT_TIMEOUT_S = 2700
MAX_PROVISION_ATTEMPTS = 4

app = modal.App(name=APP_NAME)

image = (
    modal.Image.from_registry(SGLANG_IMAGE_TAG)
    .entrypoint([])
    .pip_install("huggingface_hub", "hf_xet")
    .env(
        {
            "HF_HOME": HF_CACHE_PATH,
            "HF_HUB_CACHE": HF_CACHE_PATH,
            "HF_XET_HIGH_PERFORMANCE": "1",
            # Without this the server crashes at boot on this model at TP=4:
            # DeepGEMM TMA minimum-shape error. Routes the batch-invariant
            # matmul to its Triton path, which is still batch-invariant.
            "SGLANG_BATCH_INVARIANT_OPS_ENABLE_MM_DEEPGEMM": "0",
        }
    )
)

weights_volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)
coord = modal.Dict.from_name(COORD_NAME, create_if_missing=True)


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=60
        ).stdout.strip()
    except Exception as exc:
        return f"<failed: {exc}>"


def _read(path: str) -> str:
    try:
        return Path(path).read_text().strip()
    except Exception as exc:
        return f"<failed: {exc}>"


def collect_fingerprint(label: str) -> dict:
    gpu_csv = _run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,memory.total,driver_version,uuid,serial,pci.bus_id,vbios_version",
            "--format=csv,noheader",
        ]
    )
    gpus = []
    for line in gpu_csv.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 8:
            gpus.append(
                {
                    "index": parts[0],
                    "name": parts[1],
                    "memory_total": parts[2],
                    "driver_version": parts[3],
                    "uuid": parts[4],
                    "serial": parts[5],
                    "pci_bus_id": parts[6],
                    "vbios_version": parts[7],
                }
            )

    import re

    smi_header = _run(["nvidia-smi"])
    cuda_match = re.search(r"CUDA Version:\s*([\d.]+)", smi_header)
    cuda_version = cuda_match.group(1) if cuda_match else ""
    smi_query = _run(["nvidia-smi", "-q"])
    module_ids = [
        line.split(":")[1].strip()
        for line in smi_query.splitlines()
        if "Module ID" in line
    ]

    cpu_model = ""
    for line in _read("/proc/cpuinfo").splitlines():
        if line.startswith("model name"):
            cpu_model = line.split(":", 1)[1].strip()
            break
    btime = ""
    for line in _read("/proc/stat").splitlines():
        if line.startswith("btime"):
            btime = line.split()[1]
            break

    return {
        "label": label,
        "gpus": gpus,
        "gpu_count": len(gpus),
        "cuda_version": cuda_version,
        "module_ids": module_ids,
        "uptime": _read("/proc/uptime"),
        "boot_id": _read("/proc/sys/kernel/random/boot_id"),
        "btime": btime,
        "hostname": _run(["hostname"]),
        "kernel": _run(["uname", "-a"]),
        "cpu_model": cpu_model,
        "nproc": _run(["nproc"]),
        "mem_total": next(
            (
                line
                for line in _read("/proc/meminfo").splitlines()
                if line.startswith("MemTotal")
            ),
            "",
        ),
        "captured_at": time.time(),
    }


def launch_server(model_path: str, log_path: str) -> subprocess.Popen:
    cmd = [
        "python", "-m", "sglang.launch_server",
        "--model-path", model_path,
        "--served-model-name", MODEL_ID,
        "--host", "127.0.0.1",
        "--port", str(SGLANG_PORT),
        "--tp", str(TENSOR_PARALLEL),
        "--enable-deterministic-inference",
        "--attention-backend", "fa3",
        "--disable-radix-cache",
        "--mem-fraction-static", "0.85",
        "--chunked-prefill-size", "4096",
        "--max-running-requests", "1",
        "--trust-remote-code",
    ]
    log_file = open(log_path, "w")
    return subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)


def wait_for_server(process: subprocess.Popen, log_path: str, timeout: int) -> None:
    import requests

    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            tail = "\n".join(_read(log_path).splitlines()[-120:])
            raise RuntimeError(
                f"SGLang server exited with code {process.returncode} during boot:\n{tail}"
            )
        try:
            resp = requests.get(
                f"http://127.0.0.1:{SGLANG_PORT}/health", timeout=5
            )
            if resp.status_code == 200:
                return
        except requests.exceptions.RequestException:
            pass
        time.sleep(5)
    raise TimeoutError(f"SGLang server not ready within {timeout}s")


def stop_server(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=120)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=60)


def run_one(payload: dict, input_label: str, phase: str, pass_idx: int) -> dict:
    import hashlib

    import requests

    record = {"input": input_label, "phase": phase, "pass": pass_idx}
    start = time.time()
    try:
        resp = requests.post(
            f"http://127.0.0.1:{SGLANG_PORT}/v1/chat/completions",
            json=payload,
            timeout=REQUEST_TIMEOUT_S,
        )
        record["latency_s"] = round(time.time() - start, 1)
        record["status_code"] = resp.status_code
        if resp.status_code == 200:
            body = resp.json()
            content = body["choices"][0]["message"]["content"]
            record["content_sha256"] = hashlib.sha256(
                content.encode()
            ).hexdigest()
            record["content_chars"] = len(content)
            record["finish_reason"] = body["choices"][0].get("finish_reason")
            record["usage"] = body.get("usage", {})
            record["raw_response"] = resp.text
        else:
            record["error"] = resp.text[:2000]
    except Exception as exc:
        record["latency_s"] = round(time.time() - start, 1)
        record["error"] = f"{type(exc).__name__}: {exc}"
    return record


@app.function(image=image, volumes={HF_CACHE_PATH: weights_volume}, timeout=3 * 3600)
def download_weights() -> str:
    from huggingface_hub import snapshot_download

    path = snapshot_download(MODEL_ID, revision=MODEL_REVISION)
    weights_volume.commit()
    print(f"Snapshot ready at {path}")
    return str(path)


@app.function(
    image=image,
    gpu=GPU_SPEC,
    volumes={HF_CACHE_PATH: weights_volume},
    timeout=4 * 3600,
)
def run_machine(label: str, payloads: dict) -> dict:
    from huggingface_hub import snapshot_download

    fingerprint = collect_fingerprint(label)
    compact = {k: v for k, v in fingerprint.items() if k != "kernel"}
    coord[f"fp:{label}"] = compact
    print(f"[{label}] fingerprint published, waiting for pair decision")

    decision = None
    deadline = time.time() + DECISION_TIMEOUT_S
    while time.time() < deadline:
        decision = coord.get(f"decision:{label}")
        if decision in ("go", "abort"):
            break
        time.sleep(5)
    if decision != "go":
        print(f"[{label}] decision={decision!r} — exiting without inference")
        return {"label": label, "fingerprint": fingerprint, "aborted": True}

    model_path = snapshot_download(MODEL_ID, revision=MODEL_REVISION)
    runs = []
    log_tails = {}

    for boot_idx, passes in ((1, BOOT1_PASSES), (2, BOOT2_PASSES)):
        phase = f"boot{boot_idx}"
        log_path = f"/tmp/sglang-{label}-{phase}.log"
        print(f"[{label}] {phase}: launching server")
        boot_start = time.time()
        process = launch_server(model_path, log_path)
        try:
            wait_for_server(process, log_path, SERVER_BOOT_TIMEOUT_S)
            print(
                f"[{label}] {phase}: healthy in {time.time() - boot_start:.0f}s"
            )
            for pass_idx in range(1, passes + 1):
                for input_label in INPUT_ORDER:
                    record = run_one(
                        payloads[input_label], input_label, phase, pass_idx
                    )
                    runs.append(record)
                    print(
                        f"[{label}] {phase} pass{pass_idx} {input_label}: "
                        f"{record.get('content_sha256', record.get('error', '?'))[:16]} "
                        f"({record.get('latency_s')}s, "
                        f"finish={record.get('finish_reason')})"
                    )
        finally:
            stop_server(process)
            log_tails[phase] = "\n".join(_read(log_path).splitlines()[-80:])
        time.sleep(5)

    return {
        "label": label,
        "fingerprint": fingerprint,
        "model_path": model_path,
        "aborted": False,
        "runs": runs,
        "server_log_tails": log_tails,
    }


def _pair_verdict(fp_a: dict, fp_b: dict) -> tuple[bool, list[str]]:
    """Return (is_valid_pair, reasons). Valid = identical setup, distinct machines."""
    reasons = []

    def gpu_field(fp, field):
        return sorted({g[field] for g in fp["gpus"]})

    for field in ("name", "memory_total", "driver_version"):
        a, b = gpu_field(fp_a, field), gpu_field(fp_b, field)
        if len(a) != 1 or len(b) != 1:
            reasons.append(f"mixed {field} within one machine: {a} / {b}")
        elif a != b:
            reasons.append(f"{field} mismatch: {a[0]} vs {b[0]}")
    if fp_a["cuda_version"] != fp_b["cuda_version"]:
        reasons.append(
            f"cuda mismatch: {fp_a['cuda_version']} vs {fp_b['cuda_version']}"
        )
    if fp_a["gpu_count"] != 4 or fp_b["gpu_count"] != 4:
        reasons.append(
            f"gpu count not 4: {fp_a['gpu_count']} / {fp_b['gpu_count']}"
        )

    uuids_a, uuids_b = set(gpu_field(fp_a, "uuid")), set(gpu_field(fp_b, "uuid"))
    serials_a, serials_b = set(gpu_field(fp_a, "serial")), set(
        gpu_field(fp_b, "serial")
    )
    if uuids_a & uuids_b:
        reasons.append("overlapping GPU UUIDs — same GPUs")
    if serials_a & serials_b:
        reasons.append("overlapping GPU serials — same GPUs")
    if fp_a["boot_id"] == fp_b["boot_id"]:
        reasons.append("identical boot_id — likely same host")

    try:
        uptime_a = float(fp_a["uptime"].split()[0]) - (
            time.time() - fp_a["captured_at"]
        )
        uptime_b = float(fp_b["uptime"].split()[0]) - (
            time.time() - fp_b["captured_at"]
        )
        if abs(uptime_a - uptime_b) < 90:
            modules_a, modules_b = set(fp_a["module_ids"]), set(fp_b["module_ids"])
            if modules_a and modules_b and not (modules_a & modules_b):
                reasons.append(
                    "near-identical host uptime with complementary GPU module IDs"
                    " — suspected same physical host"
                )
    except (ValueError, IndexError):
        pass

    return (not reasons, reasons)


def _summarize_fp(fp: dict) -> str:
    gpus = fp["gpus"]
    name = gpus[0]["name"] if gpus else "?"
    driver = gpus[0]["driver_version"] if gpus else "?"
    mem = gpus[0]["memory_total"] if gpus else "?"
    serials = ",".join(g["serial"][-6:] for g in gpus)
    return (
        f"{fp['gpu_count']}x {name} ({mem}), driver {driver}, "
        f"CUDA {fp['cuda_version']}, serials …{serials}, "
        f"boot_id {fp['boot_id'][:8]}…, uptime {fp['uptime'].split()[0]}s"
    )


@app.local_entrypoint()
def main():
    from datetime import datetime, timezone

    wire_dir = EVIDENCE_DIR / "inputs" / "wire"
    payloads = {
        label: json.loads((wire_dir / f"{label}.json").read_bytes())
        for label in INPUT_ORDER
    }
    manifest = json.loads((wire_dir / "manifest.json").read_bytes())
    print("Frozen inputs:")
    for label in INPUT_ORDER:
        print(f"  {label}: sha256 {manifest[label]['sha256'][:16]}…")

    session = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = EVIDENCE_DIR / "results" / f"session-{session}"
    out_dir.mkdir(parents=True)

    for key in list(coord.keys()):
        del coord[key]

    calls: dict[str, object] = {}
    next_idx = 1

    def spawn() -> str:
        nonlocal next_idx
        label = f"m{next_idx}"
        next_idx += 1
        calls[label] = run_machine.spawn(label, payloads)
        print(f"Spawned {label}")
        return label

    active = [spawn(), spawn()]
    attempts = 2
    pair = None

    while pair is None:
        fps = {}
        deadline = time.time() + FINGERPRINT_TIMEOUT_S
        while len(fps) < 2 and time.time() < deadline:
            for label in active:
                if label not in fps:
                    fp = coord.get(f"fp:{label}")
                    if fp:
                        fps[label] = fp
                        print(f"{label}: {_summarize_fp(fp)}")
            if len(fps) < 2:
                time.sleep(10)
        if len(fps) < 2:
            raise TimeoutError(
                f"fingerprints not received from {active} within "
                f"{FINGERPRINT_TIMEOUT_S}s"
            )

        a, b = active
        ok, reasons = _pair_verdict(fps[a], fps[b])
        (out_dir / f"fingerprints-attempt-{attempts}.json").write_text(
            json.dumps({a: fps[a], b: fps[b], "verdict": reasons or "ok"}, indent=2)
        )
        if ok:
            print(f"Pair {a}/{b} VALID: identical setup, distinct machines. GO.")
            pair = (a, b)
            coord[f"decision:{a}"] = "go"
            coord[f"decision:{b}"] = "go"
        else:
            print(f"Pair {a}/{b} INVALID: {reasons}")
            if attempts >= MAX_PROVISION_ATTEMPTS:
                coord[f"decision:{a}"] = "abort"
                coord[f"decision:{b}"] = "abort"
                raise RuntimeError(
                    f"no valid machine pair after {attempts} provision attempts; "
                    f"fingerprints saved under {out_dir}"
                )
            coord[f"decision:{b}"] = "abort"
            print(f"Aborting {b}, provisioning a replacement")
            active = [a, spawn()]
            attempts += 1

    results = {}
    for label in pair:
        print(f"Waiting for {label} battery…")
        results[label] = calls[label].get()
        (out_dir / f"machine-{label}.json").write_text(
            json.dumps(results[label], indent=2)
        )
        print(f"{label} battery complete, saved")

    print("\n=== VERDICT ===")
    comparison = {"session": session, "inputs": {}, "machines": list(pair)}
    for input_label in INPUT_ORDER:
        per_machine = {}
        for label in pair:
            hashes = [
                r.get("content_sha256", f"ERROR:{r.get('error', '?')[:40]}")
                for r in results[label]["runs"]
                if r["input"] == input_label
            ]
            per_machine[label] = hashes
        all_hashes = [h for hs in per_machine.values() for h in hs]
        stable = all(len(set(hs)) == 1 for hs in per_machine.values())
        converged = len(set(all_hashes)) == 1
        comparison["inputs"][input_label] = {
            "per_machine": per_machine,
            "per_machine_stable": stable,
            "cross_machine_identical": converged,
        }
        status = (
            "PASS" if converged
            else ("DIVERGENT-CROSS-MACHINE" if stable else "UNSTABLE")
        )
        print(f"{input_label}: {status}")
        for label, hashes in per_machine.items():
            print(f"  {label}: {[h[:16] for h in hashes]}")

    (out_dir / "comparison.json").write_text(json.dumps(comparison, indent=2))
    print(f"\nAll artifacts saved under {out_dir}")


@app.local_entrypoint()
def probe_third():
    """Third concurrent machine for the pigeonhole guarantee.

    Launched while m1/m2 still hold their GPUs: three concurrent 4-GPU
    allocations pin 12 distinct H100s at once, which cannot fit on one
    8-GPU host — so at least two distinct physical machines are involved
    even though Modal's sandbox masks host identity.
    """
    wire_dir = EVIDENCE_DIR / "inputs" / "wire"
    payloads = {
        label: json.loads((wire_dir / f"{label}.json").read_bytes())
        for label in INPUT_ORDER
    }
    session_dirs = sorted((EVIDENCE_DIR / "results").glob("session-*"))
    out_dir = session_dirs[-1]
    print(f"Attaching to {out_dir.name}")
    pair_fps = json.loads(
        sorted(out_dir.glob("fingerprints-attempt-*.json"))[-1].read_bytes()
    )
    ref = pair_fps["m1"]
    taken_serials = {
        g["serial"] for m in ("m1", "m2") for g in pair_fps[m]["gpus"]
    }

    label_idx = 3
    while label_idx <= 5:
        label = f"m{label_idx}"
        call = run_machine.spawn(label, payloads)
        print(f"Spawned {label}")
        fp = None
        deadline = time.time() + FINGERPRINT_TIMEOUT_S
        while fp is None and time.time() < deadline:
            fp = coord.get(f"fp:{label}")
            if fp is None:
                time.sleep(10)
        if fp is None:
            coord[f"decision:{label}"] = "abort"
            raise TimeoutError(f"no fingerprint from {label}")
        print(f"{label}: {_summarize_fp(fp)}")

        ok, reasons = _pair_verdict(ref, fp)
        serials = {g["serial"] for g in fp["gpus"]}
        if serials & taken_serials:
            ok = False
            reasons.append("serial overlap with m1/m2 — GPUs reused, no pigeonhole")
        (out_dir / f"fingerprint-{label}.json").write_text(
            json.dumps({label: fp, "verdict": reasons or "ok"}, indent=2)
        )
        if ok:
            print(f"{label} VALID vs m1/m2 setup, all serials disjoint. GO.")
            coord[f"decision:{label}"] = "go"
            result = call.get()
            (out_dir / f"machine-{label}.json").write_text(
                json.dumps(result, indent=2)
            )
            print(f"{label} battery complete, saved")
            return
        print(f"{label} INVALID: {reasons} — aborting, retrying")
        coord[f"decision:{label}"] = "abort"
        label_idx += 1

    raise RuntimeError("no valid third machine within attempts m3-m5")
