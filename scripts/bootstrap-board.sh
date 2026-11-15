#!/usr/bin/env bash
# One-time repo setup (about 10 minutes, run by the lead): labels, the Message Board issue, pin it.
# Requires: gh authenticated with write access to this repo.
set -euo pipefail

gh label create "stream:A-brain" --color 1f6feb --description "Brain and proof" --force
gh label create "stream:B-body"  --color 2da44e --description "Body and physics" --force
gh label create "stream:C-world" --color bf8700 --description "World, capture and UI" --force

if gh issue view 1 --json title -q .title 2>/dev/null | grep -qx "Message Board"; then
  echo "Issue #1 already is the Message Board."
else
  gh issue create --title "Message Board" --body "Agents post here. Format and rules: AGENTS.md ('The board')." --label "stream:A-brain"
fi
gh issue pin 1 || echo "(pin failed or already pinned)"
echo "Done. Next: add the two teammates as collaborators and replace HANDLE_1..3 in AGENTS.md and .github/CODEOWNERS."
