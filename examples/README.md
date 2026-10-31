# Python Examples

Run these commands from the repository root after following the root README's build/install instructions. Execution examples use an already-running [Octo Runtime](https://github.com/Mininglamp-OSS/octo-runtime) and an authenticated Codex Provider.

```sh
export OCTO_KERNEL_ENDPOINT="$HOME/.octo-runtime/sockets/octo-runtime-executor-kernel.sock"
uv run python examples/with_context.py
uv run python examples/inputs.py --dry-run
uv run python examples/inputs.py --image /path/to/image.png --dry-run
uv run python examples/inputs.py --image /path/to/image.png
uv run python examples/inputs.py --native
uv run python examples/multi_harness.py codex codex
```

`--dry-run` prints the constructed Input without connecting to Runtime. Omit it to submit. `--native` selects the explicit native protocol mode; canonical is the default. For live image calls use a PNG, JPEG or WebP supported by your Provider/model.

## Import Context and Construct Input

```python
from omni_agent_invoke import Client, Context, build_input, image_input

business: Context = {"schema": "octo.context-envelope/v3", "items": []}
```

Context carries execution/background items. It is not the prompt, message history or a local cancellation token. See the complete [Context example](with_context.py) and [Input example](inputs.py) for executable construction, error handling, full-frame consumption and terminal-state checks. Both context-free and context-aware invocation methods have explicit native variants.

Text Input starts with an ordered text part. To make a multimodal Input, append an image part to the same `inputs` array:

```python
from pathlib import Path

input = build_input("codex", "Describe this image.", "canonical")
input["inputs"].append(
    image_input(Path("/path/to/image.png").read_bytes(), "image/png")
)
```

The full Input example imports Context, adds inline background material and a run timeout, constructs text, and optionally appends an image. The helpers accept explicit bytes and MIME type and compute `data` (base64), `byteSize` and lowercase `sha256`. They validate format names and the 1-byte to 2-MiB size range; decoding image contents remains the Provider's responsibility. They never fetch an image URL or silently replace images with text.

## Example Index

| Example | Purpose |
| --- | --- |
| [Context](with_context.py) | Import the public Context type and invoke with explicit background material |
| [Inputs](inputs.py) | Text-only, text + image, canonical/native and offline construction |
| [Concurrent](multi_harness.py) | Await independent harness invocations and report individual failures |
| [Context JSON](context.json) | Pass background and execution limits using playboard `--context` |
| [OpenClaw request](openclaw-request.json) | Select an existing Gateway Agent with `provider_agent_id` |
| [Protocol design](../docs/protocol.md) | Framing, identity, modes, recovery and lifecycle |

Use Adapter IDs `codex`, `claude-code`, `openclaw` and `dsh` to select Codex, Claude Code, OpenClaw and DeepSeek Harness respectively. Each must be installed/configured for your Runtime; capabilities depend on the selected Adapter. The concurrent example provides the necessary OpenClaw Context for Gateway Agent `main`; change it for your deployment.

All examples preserve complete HostFrames. A control frame with `completed`, `failed`, `cancelled` or `lost` determines the execution outcome. Breaking a loop or closing observation does not cancel an accepted run. Persist a receipt with the playboard or lower-level submit API when recovery is required.
