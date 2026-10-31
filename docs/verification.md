# Compatibility and Verification

## Protocol Target

This independent Python implementation targets [Octo Runtime](https://github.com/Mininglamp-OSS/octo-runtime) Kernel IPC v1, Run contract v7 and Context envelope v3. The generated identity subset is recorded in [the client contract](protocol-contract.json) and [generation provenance](protocol-provenance.json). See [protocol design](protocol.md) for the service boundary and handwritten transport behavior.

Runtime is installed and started independently. No upstream source checkout, SDK package, protocol download or code generator is needed to build or run the library. Matching IPC versions alone does not establish full schema parity; rerun local verification when upgrading Runtime.

## Local Evidence: 2026-10-31

Platform: macOS arm64. Toolchain: Python 3.11.16, uv, Node.js 24.22.2 (verification host only).

- `.venv/bin/python -m unittest discover -s tests -v`: 11 tests passed.
- `uv build`: source distribution and wheel built locally.
- Package runtime dependencies: none; the build backend is isolated from runtime.

The independent asyncio Unix socket peer exercises fragmented responses, lost invoke ACK recovery without resubmission, terminal streams, sequence gaps, changed run/Kernel identities and non-replayed cancellation. API tests cover all four invocation signatures, Context conflicts/default replacement and preservation of the OpenClaw Gateway Agent.

## Real Codex and Existing Kernel

[Machine-readable smoke evidence](live-smoke.json) records two completed real Codex invocations, one canonical and one native, against an already-running Kernel. Both verify receipt lookup, exact full-output replay, and completion when resubscribing from the consumed terminal cursor. Canonical output contains the requested response marker.

[Example evidence](examples-verification.json) records offline text/image construction in both modes, a completed real Codex call combining Context with text and PNG image input, a completed context-aware convenience invocation, and a successful concurrent example with two independent Codex calls.

The image test verifies accepted multimodal execution and completion; it does not benchmark visual understanding. Concurrency here uses two Codex invocations. Claude Code, OpenClaw and DeepSeek Harness were not exercised live.

The smoke uses caller-owned service and Provider authentication, creates private receipts under ignored `.tmp/`, and leaves the Kernel running. Public evidence records counts and outcomes without raw Provider output, credentials or machine-specific socket paths.

## Reproduce

Follow the root README to install/start Runtime, authenticate Codex and set the actual `OCTO_KERNEL_ENDPOINT`. Then run:

```sh
uv sync --python 3.11
uv run python -m unittest discover -s tests -v
uv build
node scripts/live-smoke.mjs "$OCTO_KERNEL_ENDPOINT"
```

Use [the examples](../examples/README.md) to repeat Context, image and concurrent calls. Live checks execute your installed Provider and require its working authentication.

## Scope

Verified on this macOS arm64 machine only. Linux is a transport target but was not tested here. Windows named pipes are unsupported. Live interaction approval round trips, other Providers, service restart recovery and sustained-load behavior remain unverified. These small clients do not implement a managed invocation registry, automatic owner drain or every upstream validator.

Verification is local and explicitly invoked. No GitHub workflows, jobs, matrices, triggers, required checks or CI gates are added.
