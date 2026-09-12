## Subagent dispatch requires multi-agent support

Add to your Codex config (`~/.codex/config.toml`):

```toml
[features]
multi_agent = true
```

This enables the host's subagent dispatch and wait operations for skills like `review-gate` and `subagent-fanout-delivery`. Use only tool names actually exposed by the current host. If the host cannot resume an agent, dispatch each fix round as a fresh implementer carrying the brief, report, and findings. Parallel implementation may fall back to serial work; an independent Review may not fall back to self-review.

## Environment Detection

Skills that create worktrees or finish branches should detect their
environment with read-only git commands before proceeding:

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
BRANCH=$(git branch --show-current)
```

- `GIT_DIR != GIT_COMMON` → already in a linked worktree (skip creation)
- `BRANCH` empty → detached HEAD (cannot branch/push/PR from sandbox)

See `finishing-a-development-branch`（`references/worktree-setup.md`）
for how each skill uses these signals.

## Codex App Finishing

When the sandbox blocks branch or push operations in an externally managed
worktree, preserve the verified working tree and ask the user which supported
integration path to use. Do not commit, push, or create a branch without task authorization.

- **"Create branch"** — names the branch, then commit/push/PR via App UI
- **"Hand off to local"** — transfers work to the user's local checkout

The agent can still run tests and output suggested branch names, commit messages,
and PR descriptions. Staging also requires the task's normal authorization boundary.
