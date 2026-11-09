#!/usr/bin/env bash
# Genera definicion_proyecto.pdf desde el HTML con Chrome headless.
set -euo pipefail
cd "$(dirname "$0")"
google-chrome --headless=new --disable-gpu --no-pdf-header-footer \
  --print-to-pdf="$PWD/definicion_proyecto.pdf" "file://$PWD/definicion_proyecto.html" 2>/dev/null
echo "PDF: $PWD/definicion_proyecto.pdf"
