# ReproAgent

| Experiment | Byte-identical | Different | Interpretation |
|---|---:|---:|---|
| Original vs replay | not yet measured | not yet measured | End-to-end run of `nf-core/sarek` 3.5.1 `-profile test,docker` did not finish within the session it was started in; the table stays empty rather than guessed |
| Agent run 1 vs run 2 | not yet measured | not yet measured | Same reason |

ReproAgent selects an nf-core pipeline from a small auditable registry, runs it with `-profile test,docker`, captures a versioned provenance manifest, replays without an agent, and compares output trees.

## Commands

```console
reproagent run "call variants on this sample against the test reference" --outdir r1
reproagent replay r1/manifest.json --outdir r1_replay
reproagent report r1 r1_replay --output reports/replay_diff.md
```

Pass local data with repeatable `--input` options; ReproAgent copies it into the run bundle so replay needs only that bundle. Extra Nextflow config can be passed with repeatable `--config` options; each file is copied into `configs/` and its SHA-256 goes into the manifest, so replay reapplies exactly the same config without the file. On a host smaller than the nf-core profiles assume, use the bundled [`configs/constrained-host.config`](configs/constrained-host.config), which lowers CPU/memory offers only and leaves the scientific parameters alone.

Use the deterministic planner by default, or select an OpenAI-compatible model with `--model MODEL` and `OPENAI_API_KEY` (override the endpoint with `REPROAGENT_LLM_URL`).

Install with `pip install -e .` on Python 3.11 with Nextflow, Java, and Docker available. Provenance that cannot be observed is stored as `null` and logged as a warning; it is never guessed.

The JSON manifest records the requested release and resolved commit SHA, parameters, bundled input hashes, container digests where observable, reference, seeds, complete decision trace, model settings and host versions. Diff reports contain both Markdown and machine-readable JSON. Replay fails rather than silently continuing when a bundled input is missing or changed.
