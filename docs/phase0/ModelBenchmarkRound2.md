# Model Benchmark Round 2

Round 1 selected Qwen3-235B-A22B (thinking mode) as the primary candidate. All three Round 1 finalists (qwen3-235b-thinking, minimax-m2.5, qwen3-235b-instruct) are 229-235B MoE models requiring ~115-118GB VRAM at 4-bit quantization. They load fine, but OOM during SGLang's Marlin kernel repacking step on every GPU available on Modal (H200, B200, A100-80G). The repacking temporarily doubles memory usage, pushing past even the H200's 141GB.

Deterministic inference requires TP=1 (single GPU), so multi-GPU workarounds are off the table. We need smaller models that actually fit through the full load-and-serve pipeline on one H200 or B200.

---

## Model Selection: Next Tier from LiveBench

Starting from where Round 1's rankings left off (after Qwen3-235B-A22B Instruct at rank 10), the next tier of open-weight models on LiveBench reasoning:

| Rank | Model | Reasoning Avg | Total Params | Architecture | 4-bit VRAM | Fits H200? |
|------|-------|--------------|-------------|--------------|------------|-----------|
| 11 | Qwen3-Next-80B-A3B Thinking | 58.16 | 80B | MoE, 3B active | ~40 GB | Yes |
| 12 | Qwen3-Next-80B-A3B Instruct | 54.75 | 80B | MoE, 3B active | ~40 GB | Yes |
| 13 | Qwen3-32B | 48.25 | 32B | Dense | ~16 GB | Yes |
| — | DeepSeek V3.2 Exp (685B) | — | 685B | MoE | ~343 GB | No |
| — | DeepSeek V3.2 (685B) | — | 685B | MoE | ~343 GB | No |
| — | Kimi K2 Instruct (1T) | — | ~1,000B | MoE | ~500 GB | No |
| 14 | GPT-OSS-120B | 39.21 | 117B | MoE, 5.1B active | ~58 GB | Yes |

The three excluded models (DeepSeek V3.2 variants, Kimi K2) require 343-500GB at 4-bit — well beyond any single GPU.

---

## Selected Models

| # | Model | Reasoning Avg | 4-bit VRAM | Rationale |
|---|-------|--------------|------------|-----------|
| 1 | **Qwen3-Next-80B-A3B (Thinking)** | 58.16 | ~40 GB | Highest reasoning in the tier. Same thinking-mode approach as Round 1 winner. Extreme VRAM headroom (~100GB free for KV cache). |
| 2 | **Qwen3-Next-80B-A3B (Instruct)** | 54.75 | ~40 GB | Same weights, non-thinking mode. Tests whether chain-of-thought helps at this smaller scale. |
| 3 | **Qwen3-32B** | 48.25 | ~16 GB | Dense 32B model. Smallest candidate — if it scores well enough, it simplifies deployment significantly. |
| 4 | **GPT-OSS-120B** | 39.21 | ~58 GB | OpenAI's first open MoE release. Lower reasoning score but different architecture lineage worth testing. |

All four fit comfortably on a single H200 (141GB) or B200 (192GB) with substantial VRAM headroom for Marlin repacking and KV cache.

### Why Qwen3-Next-80B Gets Both Modes

Same rationale as Round 1's Qwen3-235B dual testing: the thinking variant may produce better scoring quality through chain-of-thought reasoning, while the instruct variant may produce more reliable JSON output. Testing both tells us whether the thinking trace is worth the overhead at 80B scale.

### Reasoning Score Drop-off

The step down from Round 1 is notable. Round 1 candidates scored 58-59 on LiveBench reasoning. This tier ranges from 58 (Qwen3-Next thinking) down to 39 (GPT-OSS). Whether that gap matters for our specific validator-scoring task is exactly what the benchmark will determine — LiveBench reasoning and "score 42 validators with a rubric" are different problems.

---

## Benchmark Methodology

Identical to Round 1. See [ModelBenchmarkRound1.md](ModelBenchmarkRound1.md) for full details.

- Same scoring prompt (`prompts/scoring_v1.txt`)
- Same testnet snapshot (`data/testnet_snapshot.json`)
- Same evaluation criteria: JSON compliance, score differentiation, reasoning quality, diversity awareness, consistency across runs
- Same infrastructure: OpenRouter API, `temperature=0`, 5 runs per model
- Script: `benchmarks/round2.py`

### Model-Specific Configuration

| Model | OpenRouter ID | Thinking Mode | Response Format |
|-------|---------------|---------------|-----------------|
| qwen3-next-80b-thinking | `qwen/qwen3-next-80b-a3b-thinking` | `reasoning.effort = "high"` | None (text + JSON) |
| qwen3-next-80b-instruct | `qwen/qwen3-next-80b-a3b-instruct` | Off | `json_object` |
| qwen3-32b | `qwen/qwen3-32b` | Off | `json_object` |
| gpt-oss-120b | `openai/gpt-oss-120b` | Off | `json_object` |

---

## Results

Benchmark completed. See [Round2Analysis.md](Round2Analysis.md) for full results, cross-run consistency metrics, penalty calibration, and the final model recommendation.
