# Customizing the in-app tour

The first-run sidebar tour ships with sensible defaults but can be
re-skinned for a specific deployment without rebuilding the extension.
Point the `NBI_TOUR_CONFIG_PATH` environment variable (or the
`NotebookIntelligence.tour_config_path` traitlet) at a YAML or JSON file
and Notebook Intelligence will overlay your copy on the built-in steps.

## Where to put the file

Anywhere readable by the Jupyter server process. A common pattern on
JupyterHub:

```bash
# In the Hub spawner / pod env:
export NBI_TOUR_CONFIG_PATH=/srv/jupyterhub/nbi-tour.yaml
```

A missing file is the steady state and produces no logs. An unreadable,
oversized, or malformed file produces a single warning and the tour
falls back to the built-in copy.

## Starting from the defaults

The built-in defaults ship in
[`src/tour/tour-defaults.json`](../src/tour/tour-defaults.json), which
uses exactly the schema documented below. The fastest way to customize
the tour is to copy that file, rename it to `.yaml` (YAML is a superset
of JSON, so the same content parses unchanged), then trim it to only
the keys you want to change. Anything you remove falls back to the
built-in copy.

## Schema

The file is a single mapping with up to three top-level keys: `steps`,
`ui`, and `command`. All are optional; only fields you set are
overridden.

```yaml
# Optional. Each key matches a built-in step id. Steps not listed keep
# their default copy.
steps:
  welcome:
    title: 'Welcome to ACME AI'
    description: |
      The next minute walks you through the gear, attachments, and
      modes so you can drive it. Press Esc to skip.

  drag-and-drop:
    enabled: false # drop this step entirely

  launcher-tiles:
    title: 'Run an agent in a terminal'
    # Special: templates for the only step whose copy is built at
    # runtime from the list of installed CLI tools. `{launchers}` is
    # substituted with the comma-joined list. Singular fires when one
    # CLI is installed; plural when two or more. Unset templates fall
    # back to the built-in copy.
    description_singular: '{launchers} opens a CLI session in a terminal.'
    description_plural: 'Each of {launchers} opens a CLI session in a terminal.'

# Optional. Rewrites the overlay's button labels.
ui:
  skip: 'Skip'
  next: 'Next'
  back: 'Back'
  done: 'Done'

# Optional. Rewrites the JupyterLab command palette label users see
# when replaying the tour.
command:
  label: 'Replay ACME walkthrough'
```

### Recognized step ids

| Step id          | What it covers                                    |
| ---------------- | ------------------------------------------------- |
| `welcome`        | Opening modal                                     |
| `new-chat`       | New-chat icon (Claude mode only)                  |
| `claude-history` | Resume-session icon (Claude mode + CLI installed) |
| `settings-gear`  | Settings cog                                      |
| `slash-commands` | Slash button                                      |
| `add-context`    | Workspace file picker button                      |
| `upload-file`    | Upload from computer button                       |
| `drag-and-drop`  | Prompt area drop affordance                       |
| `chat-mode`      | Mode picker (non-Claude mode only)                |
| `launcher-tiles` | JupyterLab Launcher "Coding Agent" tiles          |
| `done`           | Closing modal                                     |

### Recognized step-level keys

| Key                    | Type    | Notes                                                                                                        |
| ---------------------- | ------- | ------------------------------------------------------------------------------------------------------------ |
| `title`                | string  | Replaces the step's title. Capped at 80 chars.                                                               |
| `description`          | string  | Replaces the step's description. Capped at 400 chars. Ignored on `launcher-tiles` (use the templates below). |
| `enabled`              | boolean | `false` drops the step entirely. Default `true`.                                                             |
| `description_singular` | string  | `launcher-tiles` only. Template with `{launchers}` placeholder for the single-CLI case.                      |
| `description_plural`   | string  | `launcher-tiles` only. Template for the multi-CLI case.                                                      |

### Recognized UI keys

| Key    | Default     | Cap      |
| ------ | ----------- | -------- |
| `skip` | "Skip tour" | 24 chars |
| `next` | "Next"      | 24 chars |
| `back` | "Back"      | 24 chars |
| `done` | "Done"      | 24 chars |

### Recognized command keys

| Key     | Default         | Cap      |
| ------- | --------------- | -------- |
| `label` | "Show NBI tour" | 40 chars |

## What you can't do

- **Add new steps or reorder existing ones.** A new step needs a DOM
  anchor inside the sidebar and capability gating; that's a code change.
  The override file can only modify the copy of steps the extension
  already knows about.
- **Bypass the built-in capability gates.** Steps that target
  affordances which aren't visible on the current machine (e.g. the
  Claude history icon when the CLI isn't installed) are still skipped.
  Override copy is a layer on top of the same gating, not a way around
  it.
- **Ship a file larger than 32 KB.** The loader rejects oversized files
  with a warning; tour copy doesn't need anywhere near that much room
  and oversizing is almost always a deployment mistake.

## Failure modes

The loader logs WARN and falls back to defaults for:

- File missing or unreadable (the typical no-customization case is
  silent; only stat/read failures of an actual file log).
- File exceeds the 32 KB cap.
- YAML/JSON parse error.
- Top-level value is not a mapping.
- Unknown top-level key (`steps`, `ui` are the only recognized ones).
- Unknown step id under `steps`.
- Unknown field under a step (e.g. `placement: top`).
- Type mismatch (`enabled: "true"` as a string, `title: 42` as an int).
- Per-field length cap exceeded — the field is truncated rather than
  dropped, and a single warning records the truncation.

None of these conditions block the rest of the file. If `steps.welcome`
has a valid title and an invalid description, the title applies and
the description falls back. The principle is "apply what you can,
warn about the rest, never crash the sidebar."

## Worked example

A locked-down deployment that:

- Renames the product
- Drops the drag-and-drop step (the workspace is locked, no local files)
- Tightens the launcher-tile copy
- Renames the dismiss button

```yaml
steps:
  welcome:
    title: 'Welcome to the AcmeLab assistant'
    description: |
      This sidebar opens an AI assistant for your notebooks. A quick
      walkthrough so you know where the gear and the modes are.
      Press Esc to skip; replay from the command palette later.
  drag-and-drop:
    enabled: false
  launcher-tiles:
    description_singular: '{launchers} runs in a Jupyter terminal here.'
    description_plural: '{launchers} each run in a Jupyter terminal here.'
  done:
    title: 'All set'
    description: |
      Ask a question or attach a notebook to get going.
ui:
  skip: 'Dismiss'
```
