#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

: "${GITHUB_TOKEN:?Falta GITHUB_TOKEN}"
: "${RENDER_API_KEY:?Falta RENDER_API_KEY}"

REPO_NAME="${REPO_NAME:-facturas-talleres-catala}"
GITHUB_USER="${GITHUB_USER:-}"

if [ -z "$GITHUB_USER" ]; then
  GITHUB_USER=$(curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
    https://api.github.com/user | python3 -c "import sys,json; print(json.load(sys.stdin)['login'])")
fi

echo "→ Usuario GitHub: $GITHUB_USER"

# Inicializar git si hace falta
if [ ! -d .git ]; then
  git init
  git branch -M main
fi

git add -A
git diff --cached --quiet && echo "Sin cambios" || git commit -m "Deploy facturas Talleres Catala"

# Crear repo si no existe
if ! curl -sf -H "Authorization: Bearer $GITHUB_TOKEN" \
  "https://api.github.com/repos/$GITHUB_USER/$REPO_NAME" >/dev/null; then
  curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
    -d "{\"name\":\"$REPO_NAME\",\"private\":true}" \
    https://api.github.com/user/repos >/dev/null
  echo "→ Repo creado: $GITHUB_USER/$REPO_NAME"
fi

git remote remove origin 2>/dev/null || true
git remote add origin "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_USER}/${REPO_NAME}.git"
git push -u origin main --force

echo "→ Código subido a GitHub"

# Obtener owner ID de Render
OWNER_ID=$(curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  https://api.render.com/v1/owners | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data[0]['owner']['id'] if data else '')
")

if [ -z "$OWNER_ID" ]; then
  echo "Error: no se pudo obtener owner ID de Render"
  exit 1
fi

# Leer variables de .env
source .env 2>/dev/null || true

# Comprobar si el servicio ya existe
SERVICE_ID=$(curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/services?limit=50" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for item in data:
    s = item.get('service', {})
    if s.get('name') == '$REPO_NAME':
        print(s['id'])
        break
")

if [ -z "$SERVICE_ID" ]; then
  echo "→ Creando servicio en Render..."
  RESPONSE=$(curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
    -H "Content-Type: application/json" \
    -d "{
      \"type\": \"web_service\",
      \"name\": \"$REPO_NAME\",
      \"ownerId\": \"$OWNER_ID\",
      \"repo\": \"https://github.com/$GITHUB_USER/$REPO_NAME\",
      \"branch\": \"main\",
      \"rootDir\": \"\",
      \"autoDeploy\": \"yes\",
      \"serviceDetails\": {
        \"env\": \"docker\",
        \"plan\": \"free\",
        \"region\": \"frankfurt\",
        \"envSpecificDetails\": {
          \"dockerfilePath\": \"Dockerfile\"
        }
      }
    }" \
    https://api.render.com/v1/services)

  SERVICE_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id',''))")
  SERVICE_URL=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('serviceDetails',{}).get('url',''))")
else
  echo "→ Servicio ya existe: $SERVICE_ID"
  SERVICE_URL=$(curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
    "https://api.render.com/v1/services/$SERVICE_ID" | python3 -c "
import sys,json; d=json.load(sys.stdin); print(d.get('serviceDetails',{}).get('url',''))
")
fi

# Configurar variables de entorno
set_env() {
  local key=$1 val=$2
  curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"envVar\":{\"key\":\"$key\",\"value\":\"$val\"}}" \
    "https://api.render.com/v1/services/$SERVICE_ID/env-vars" >/dev/null
}

set_env "EMAIL_ACCOUNTS" "${EMAIL_ACCOUNTS:-}"
set_env "RECIPIENT_NAME" "${RECIPIENT_NAME:-Talleres Catala Automotive SL}"
set_env "IMAP_SERVER" "${IMAP_SERVER:-imap.servidor-correo.net}"
set_env "IMAP_PORT" "${IMAP_PORT:-993}"
set_env "AUTO_SYNC_HOURS" "${AUTO_SYNC_HOURS:-4}"
set_env "CRON_SECRET" "${CRON_SECRET:-$(openssl rand -hex 16)}"

echo ""
echo "========================================="
echo "  DESPLIEGUE COMPLETADO"
echo "========================================="
echo "  URL: https://${SERVICE_URL:-$REPO_NAME.onrender.com}"
echo ""
echo "  En tu iPhone:"
echo "  1. Abre la URL en Safari"
echo "  2. Compartir → Añadir a pantalla de inicio"
echo "========================================="
