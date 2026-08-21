# ReproAgent

| Experiment | Byte-identical | Different | Interpretation |
|---|---:|---:|---|
| Original vs replay | TBD | TBD | Pipeline/environment variance |
| Agent run 1 vs run 2 | TBD | TBD | Agent plus pipeline variance |

ReproAgent selects an nf-core pipeline from a small auditable registry, runs it with `-profile test,docker`, captures a versioned provenance manifest, replays without an agent, and compares output trees.

## Commands

```console
reproagent run "call variants on this sample against the test reference" --outdir r1
reproagent replay r1/manifest.json --outdir r1_replay
reproagent diff r1 r1_replay --report reports/replay_diff.md
```

Pass local data with repeatable `--input` options; ReproAgent copies it into the run bundle so replay needs only that bundle. Use the deterministic planner by default, or select an OpenAI-compatible model with `--model MODEL` and `OPENAI_API_KEY` (override the endpoint with `REPROAGENT_LLM_URL`).

Install with `pip install -e .` on Python 3.11 with Nextflow, Java, and Docker available. Provenance that cannot be observed is stored as `null` and logged as a warning; it is never guessed.

The JSON manifest records the requested release and resolved commit SHA, parameters, bundled input hashes, container digests where observable, reference, seeds, complete decision trace, model settings and host versions. Diff reports contain both Markdown and machine-readable JSON. Replay fails rather than silently continuing when a bundled input is missing or changed.
