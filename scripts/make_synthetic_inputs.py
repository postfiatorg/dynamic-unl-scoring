"""Generate the frozen wire payloads for the same-GPU determinism test.

Run once. The four files written to
docs/crossmachine-determinism-evidence/inputs/wire/ are frozen from that
point on: every battery run on every machine replays these exact bytes.
Randomness is seeded so the script itself is reproducible provenance, but
the committed files — not this script — are the test inputs.

Payloads are in wire format: what actually goes over HTTP to SGLang's
/v1/chat/completions. For the round 19 anchor this means the frozen
model_request.json with extra_body hoisted to top level, the internal
"method" key dropped, and the model field swapped — verified byte-identical
to the payload the Vast Stage 1 machines received.
"""

import hashlib
import json
import random
from pathlib import Path

EVIDENCE_DIR = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "crossmachine-determinism-evidence"
)
WIRE_DIR = EVIDENCE_DIR / "inputs" / "wire"

MODEL = "Qwen/Qwen3.5-122B-A10B-FP8"
SEED = 20260821

REGIONS = ["north", "south", "east", "west", "central", "coastal", "alpine", "desert"]
STATUSES = ["nominal", "nominal", "nominal", "degraded", "offline", "maintenance"]


def station_records(rng: random.Random, count: int) -> str:
    lines = []
    for i in range(count):
        region = rng.choice(REGIONS)
        temp = round(rng.uniform(-25.0, 45.0), 1)
        humidity = rng.randint(5, 100)
        wind = round(rng.uniform(0.0, 160.0), 1)
        status = rng.choice(STATUSES)
        lines.append(
            f"Station {region}-{i:05d}: temperature {temp} C, "
            f"humidity {humidity}%, wind {wind} km/h, status {status}."
        )
    return "\n".join(lines)


def wire_payload(prompt: str, max_tokens: int) -> dict:
    return {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }


def build_simple() -> dict:
    prompt = (
        "Explain in one short paragraph why the sky appears blue during the day "
        "and reddish at sunset."
    )
    return wire_payload(prompt, max_tokens=512)


def build_moderate(rng: random.Random) -> dict:
    records = station_records(rng, 200)
    prompt = (
        "You are a data analyst. Below is a dataset of weather station records.\n\n"
        f"{records}\n\n"
        "Using only the records above, report: the total number of records, "
        "the minimum and maximum temperature with their station ids, the mean "
        "temperature rounded to two decimals, the five stations with the highest "
        "wind speed, and the count of records per status."
    )
    return wire_payload(prompt, max_tokens=2048)


def build_long(rng: random.Random) -> dict:
    records = station_records(rng, 1150)
    prompt = (
        "You are a data analyst. Below is a dataset of weather station records.\n\n"
        f"{records}\n\n"
        "Using only the records above, produce a detailed structured report with "
        "these sections: (1) total number of records; (2) per-region record count "
        "and minimum, maximum, and mean temperature; (3) the ten stations with the "
        "highest wind speed, with their full records; (4) every station with "
        "status offline, listed by id; (5) the count of records per status; "
        "(6) a closing paragraph summarizing notable patterns."
    )
    return wire_payload(prompt, max_tokens=8192)


def build_round19() -> dict:
    frozen = json.loads(
        (EVIDENCE_DIR / "inputs" / "round19_model_request.json").read_bytes()
    )
    wire = {k: v for k, v in frozen.items() if k not in ("method", "extra_body")}
    wire.update(frozen["extra_body"])
    wire["model"] = MODEL
    return wire


def main() -> None:
    WIRE_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    payloads = {
        "simple": build_simple(),
        "moderate": build_moderate(rng),
        "long": build_long(rng),
        "round19": build_round19(),
    }
    manifest = {}
    for label, payload in payloads.items():
        raw = json.dumps(payload, indent=2, ensure_ascii=False).encode()
        (WIRE_DIR / f"{label}.json").write_bytes(raw)
        manifest[label] = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "prompt_chars": sum(len(m["content"]) for m in payload["messages"]),
            "max_tokens": payload["max_tokens"],
        }
    (WIRE_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
