#!/usr/bin/env bash
set -euo pipefail

failed=false
for plugin in plugins/quetz_*; do
  echo "::group::Testing plugin ${plugin}"
  if ! pixi run -e dev quetz plugin install "$plugin" || \
     ! pixi run -e dev pytest -v "$plugin"; then
    failed=true
  fi
  echo '::endgroup::'
done
if [ "$failed" = true ]; then
  exit 1
fi
