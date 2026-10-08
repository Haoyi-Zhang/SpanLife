#!/bin/sh
# Read-only availability check. No emulated analyzer is used.
set +e
printf 'UTC: '; date -u
printf '\nTracetest executable: '; command -v tracetest
printf '\nDocker executable: '; command -v docker
printf '\nGo executable: '; command -v go
printf '\nBounded public source retrieval attempt:\n'
timeout 12 git ls-remote https://github.com/kubeshop/tracetest.git HEAD
printf '\nretrieval_exit=%s\n' "$?"
