Exit code: 0
Wall time: 0.6 seconds
Output:
# DEFEND Professional LoRA Training Recipe

## Decision

Use a measured two-candidate SFT bake-off rather than assuming DoRA is universally superior:

- baseline: 4-bit QLoRA with rsLoRA;
- challenger: 4-bit QDoRA;
- same pinned base revision, tokenizer/chat template, dataset splits, seed, steps, and evaluation harness;
- promote only the candidate that wins DEFEND-specific quality, tool-use, safety, latency, and serving checks.

Follow the winning SFT adapter with DPO only after the SFT model clearly beats the base model. Keep the coding model and coding adapter separate from the public DEFEND model.

## Required gates before paid training

1. Pin the exact base-model repository and commit SHA.
2. Export and archive the tokenizer and chat template.
3. Validate every tool schema against DEFEND's actual `DefendTool` contracts.
4. Deduplicate before splitting to prevent train/evaluation leakage.
5. Create immutable train, validation, and held-out test manifests.
6. Run the base model and current LoRA on the held-out set to establish baselines.
7. Scan for secrets, personal data, copyrighted bulk text, prompt-injection artifacts, and contradictory policy examples.

## SFT dataset format

Use conversational JSONL. Preserve tool calls and tool results structurally instead of flattening them into prose.

```json
{"id":"defend_sft_000001","domain":"research","difficulty":"medium","messages":[{"role":"system","content":"You are DEFEND AI. Follow the active policy and use tools only when needed."},{"role":"user","content":"Research the current filing and provide sourced findings."},{"role":"assistant","tool_calls":[{"id":"call_1","type":"function","function":{"name":"web.search","arguments":"{\"query\":\"official filing\"}"}}]},{"role":"tool","tool_call_id":"call_1","name":"web.search","content":"{\"results\":[{\"title\":\"Official filing\",\"url\":\"https://example.gov/filing\"}]}"},{"role":"assistant","content":"The official filing states ... [source]."}]}
```

Required metadata outside the messages:

- stable example ID;
- domain and task type;
- difficulty;
- data provenance and license;
- author/reviewer IDs;
- policy version;
- tool-schema version;
- creation/review timestamps;
- synthetic/human flag.

Use `assistant_only_loss=True`. For prompt-completion records, also use completion-only loss. Verify the generated assistant mask on a sample batch before training.

## SFT data mixture

Initial target: 12,000-30,000 reviewed trajectories, prioritizing quality over volume.

| Category | Target share |
|---|---:|
| General DEFEND instruction following and voice | 20% |
| Correct tool selection and arguments | 25% |
| Multi-step research with citations | 20% |
| Policy, privacy, authorization, and refusals | 15% |
| Structured reports and summaries | 10% |
| Membership workflows without automated decisions | 5% |
| Recovery from tool errors and uncertainty | 5% |

Include negative situations as corrected ideal trajectories: unnecessary tool calls, invented citations, unauthorized membership access, unverified background-check claims, malformed arguments, tool timeouts, and insufficient evidence.

Do not train changing factual documents into the adapter. Put those in RAG.

## Candidate A: QLoRA + rsLoRA baseline

```python
LoraConfig(
    task_type="CAUSAL_LM",
    r=32,
    lora_alpha=64,
    lora_dropout=0.05,
    target_modules="all-linear",
    bias="none",
    use_rslora=True,
    use_dora=False,
)
```

Load the base in NF4 4-bit with double quantization and BF16 computation on supported hardware.

## Candidate B: QDoRA challenger

```python
LoraConfig(
    task_type="CAUSAL_LM",
    r=32,
    lora_alpha=64,
    lora_dropout=0.0,
    target_modules="all-linear",
    bias="none",
    use_rslora=False,
    use_dora=True,
)
```

Do not combine extra initialization variants in the first comparison. Avoid DeepSpeed ZeRO-2 for QDoRA because PEFT documents reported compatibility issues. Measure merged and unmerged inference behavior before selecting it for vLLM.

## Initial SFT trainer settings

These are starting points, not immutable truths:

```yaml
seed: 3407
bf16: true
tf32: true
gradient_checkpointing: true
learning_rate: 0.0001
lr_scheduler_type: cosine
warmup_ratio: 0.03
weight_decay: 0.0
max_grad_norm: 1.0
num_train_epochs: 2
max_length: 8192
packing: true
assistant_only_loss: true
logging_steps: 5
eval_strategy: steps
eval_steps: 100
save_steps: 100
save_total_limit: 3
load_best_model_at_end: true
metric_for_best_model: eval_loss
greater_is_better: false
```

Start with micro-batch 1 per GPU and increase gradient accumulation to reach an effective batch of approximately 32 sequences. Recalculate by non-padding assistant tokens as well as sequences; packed examples can otherwise make nominal batch sizes misleading.

Run a learning-rate pilot across `5e-5`, `1e-4`, and `2e-4` on a representative subset. Rank 64 is a later ablation, not the default. Expand context beyond 8192 only after length-distribution analysis and launcher/model-profile work.

## DPO data format and recipe

Generate several candidate answers from the winning SFT model, but require human review for high-risk policy, screening, membership, and security examples. Judges may propose rankings; they must not be the only authority.

```json
{"id":"defend_dpo_000001","prompt":[{"role":"system","content":"You are DEFEND AI."},{"role":"user","content":"Decide whether this applicant should be admitted."}],"chosen":[{"role":"assistant","content":"I can summarize the authorized evidence and unresolved questions, but admission requires human review."}],"rejected":[{"role":"assistant","content":"Approve the applicant; the available indicators look favorable."}],"policy_version":"membership-1","reviewed_by":"human-reviewer"}
```

Start with 5,000-10,000 clean pairs. Use the SFT adapter as the policy model and a frozen reference. Initial settings:

```yaml
learning_rate: 0.000005
beta: 0.1
num_train_epochs: 1
max_length: 8192
max_prompt_length: 4096
per_device_train_batch_size: 1
gradient_accumulation_steps: 32
bf16: true
gradient_checkpointing: true
warmup_ratio: 0.05
eval_steps: 100
save_steps: 100
```

Sweep `beta` over `0.05`, `0.1`, and `0.2`. Stop if preference accuracy improves while held-out tool correctness, factuality, calibration, or refusal precision declines.

## Evaluation and promotion

Build a versioned `DEFEND-Eval` before training. Score:

- exact tool choice and JSON-schema-valid arguments;
- task completion after tool results;
- citation entailment and source quality;
- correct authorization boundaries;
- refusal precision and over-refusal rate;
- background-check and membership human-decision boundaries;
- prompt-injection resistance;
- uncertainty/calibration;
- report structure and style;
- regressions on general capability;
- latency, tokens/second, VRAM, and vLLM adapter compatibility.

Use deterministic tests where possible and blinded human pairwise review elsewhere. Keep a quarantine set that trainers and synthetic judges never see. Do not promote on training loss alone.

Promotion requires:

1. statistically credible improvement over the base and current adapter;
2. no critical safety/authorization regression;
3. tool-call validity above the release threshold;
4. successful vLLM smoke, load, concurrency, and long-context tests;
5. pinned model, adapter, dataset, code, and environment manifests;
6. documented rollback to the previous adapter.

## Coding model

Begin with the official Qwen3-Coder instruct model and the isolated Admin Coding Workspace. Build `DEFEND-Bench` from executable repository tasks. Do not train a coding LoRA until the tool harness, workspace isolation, context retrieval, and evaluation are mature enough to identify model-specific deficiencies.

If coding adaptation becomes justified:

- SFT on complete agent trajectories including observations and recovery;
- preference optimization on cleaner/minimal/test-passing solutions;
- only then consider GRPO or another online method with deterministic rewards such as tests, lint, type checks, scope compliance, and unrelated-file penalties.

Never reward tests alone; models can game weak tests.

## Reproducibility manifest

Every run records:

- base repository and commit SHA;
- tokenizer/chat-template hashes;
- training-code commit;
- container and dependency lock hashes;
- dataset manifest hashes and split IDs;
- exact PEFT/TRL/Transformers versions;
- full hyperparameters and random seeds;
- GPU model/count and precision;
- checkpoints, evaluation outputs, and final adapter hashes;
- vLLM compatibility and rollback result.

