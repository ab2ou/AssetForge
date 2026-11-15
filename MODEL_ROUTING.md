# Model and effort routing (user rule, 2026-10-21)

When the user gives an order, the coordinating assistant splits it into tasks and gives each task to the cheapest
model and effort that can do it well. Goal: fewer tokens without lower quality.

## Who does what

| task type | examples | model | effort |
|---|---|---|---|
| no model at all | running stages, bakes, renders, queues | `run_forge.bat` / `forge_orch.py` on the PC | — |
| mechanical checks | watch a queue, read logs, `decision.json`, md5 checks, copy/stage files, collect numbers into a table | haiku | low |
| routine work with a clear recipe | write a queue for known steps, update CHANGELOG / TEST_RESULTS from reports, small code edits with a test already defined | sonnet | medium |
| judgement | visual review of images at a REVIEW gate, choosing between versions, decisions with the user, new algorithms, debugging an unknown failure, summarising a ChatGPT discussion | opus | high |
| very hard, rare | only if opus failed twice on the same problem, and the user agrees | fable | high |

## Rules

1. The coordinator keeps the conversation with the user, splits the order, writes a precise brief for each helper
   (paths, expected output, what counts as done), and checks every result before telling the user anything
   (evidence first: a helper's claim is not evidence until its output files or numbers are checked).
2. Do not delegate tiny tasks: a helper starts with no context and must re-read files. A task shorter than its brief
   is done by the coordinator directly.
3. Independent tasks run in parallel; dependent tasks wait for their input.
4. Never delegate: code changes to production during a running queue, approvals of REVIEW gates, anything the user
   must decide, publishing, downloads, PowerShell, paid services (CONTRIBUTING rules apply to helpers too).
5. Each delegation is logged in the reply to the user in one line: task → model / effort → result.
