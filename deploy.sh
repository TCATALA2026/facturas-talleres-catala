#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

: "${GITHUB_TOKEN:?Falta GITHUB_TOKEN}"
: "${RENDER_API_KEY:?Falta RENDER_API_KEY}"

REPO_NAME="${REPO_NAME:-facturas-talleres-catala}"

GITHUB_USER=$(curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
  https://api.github.com/user | python3 -c "import sys,json; print(json.load(sys.stdin)['login'])")

echo "→ Usuario GitHub: $GITHUB_USER"

if [ ! -d .git ]; then
  git init
  git branch -M main
fi

git add -A
git diff --cached --quiet || git commit -m "Deploy facturas Talleres Catala"

if ! curl -sf -H "Authorization: Bearer $GITHUB_TOKEN" \
  "https://api.github.com/repos/$GITHUB_USER/$REPO_NAME" >/dev/null; then
  curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
    -d "{\"name\":\"$REPO_NAME\",\"private\":true}" \
    https://api.github.com/user/repos >/dev/null
  echo "→ Repo creado"
fi

git remote remove origin 2>/dev/null || true
git remote add origin "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_USER}/${REPO_NAME}.git"
git push -u origin main --force
echo "→ Código en GitHub"

OWNER_ID=$(curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  https://api.render.com/v1/owners | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data[0]['owner']['id'] if data else '')
")

SERVICE_ID=$(curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/services?limit=50" | python3 -c "
import sys, json
for item in json.load(sys.stdin):
    s = item.get('service', {})
    if s.get('name') == '$REPO_NAME':
        print(s['id']); break
")

if [ -z "$SERVICE_ID" ]; then
  RESPONSE=$(curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
    -H "Content-Type: application/json" \
    -d "{
      \"type\": \"web_service\",
      \"name\": \"$REPO_NAME\",
      \"ownerId\": \"$OWNER_ID\",
      \"repo\": \"https://github.com/$GITHUB_USER/$REPO_NAME\",
      \"branch\": \"main\",
      \"autoDeploy\": \"yes\",
      \"serviceDetails\": {
        \"env\": \"docker\",
        \"plan\": \"free\",
        \"region\": \"frankfurt\",
        \"envSpecificDetails\": {\"dockerfilePath\": \"Dockerfile\"}
      }
    }" \
    https://api.render.com/v1/services)
  SERVICE_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))")
fi

set -a; source .env 2>/dev/null; set +a

set_env() {
  curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"envVar\":{\"key\":\"$1\",\"value\":\"$2\"}}" \
    "https://api.render.com/v1/services/$SERVICE_ID/env-vars" >/dev/null
}

set_env EMAIL_ACCOUNTS "${EMAIL_ACCOUNTS:-}"
set_env RECIPIENT_NAME "${RECIPIENT_NAME:-Talleres Catala Automotive SL}"
set_env IMAP_SERVER "${IMAP_SERVER:-imap.servidor-correo.net}"
set_env IMAP_PORT "${IMAP_PORT:-993}"
set_env AUTO_SYNC_HOURS "${AUTO_SYNC_HOURS:-4}"
set_env CRON_SECRET "${CRON_SECRET:-deploy-secret-$(date +%s)}"

echo ""
echo "✅ Desplegado: https://${REPO_NAME}.onrender.com"
echo "   Añade a pantalla de inicio en Safari"
