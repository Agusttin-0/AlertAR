#!/bin/sh
# Publica el panel en Cloudflare Pages (proyecto "alertar" -> https://alertar.pages.dev).
# Copia los archivos fijos del panel, genera la página pública y sube todo junto con _worker.js.
# Uso, desde la raíz del repositorio:  sh deploy/cloudflare/publicar.sh
# Requiere Node (npx) y una sesión de Cloudflare con acceso al proyecto: npx wrangler login
set -e
AQUI="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$AQUI/../../backend"
rm -rf "$AQUI/public/static"
cp -r "$BACKEND/static" "$AQUI/public/static"
# La página "/" sin sesión es igual para todos: se genera con Flask y se sirve desde Cloudflare.
python - "$BACKEND" "$AQUI/public/index.html" <<'PY'
import os, sys, tempfile
backend, destino = sys.argv[1], sys.argv[2]
sys.path.insert(0, backend)
os.environ.update(ALERTAR_REQUIRE_AUTH="1", ALERTAR_API_KEY="x" * 32,
                  ALERTAR_DATABASE=os.path.join(tempfile.mkdtemp(), "vacia.sqlite3"))
from app import create_app
r = create_app({"TESTING": True}).test_client().get("/")
assert r.status_code == 200 and 'data-admin="0"' in r.text, "La página pública no se generó bien"
open(destino, "w", encoding="utf-8", newline="\n").write(r.text)
print("index.html:", len(r.text), "bytes")
PY
cat > "$AQUI/public/_headers" <<'H'
/*
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Referrer-Policy: same-origin
  Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'
/
  Cache-Control: no-cache
H
npx wrangler pages deploy "$AQUI/public" --project-name alertar --branch main --commit-dirty=true
