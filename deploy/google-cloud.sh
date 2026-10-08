#!/usr/bin/env bash
# Deploy Academic Weapon to Google Cloud Run. Run this in Google Cloud Shell:
#   bash deploy/google-cloud.sh
# Run it again any time to update the app with the latest code.
set -euo pipefail

SERVICE="academic-weapon"
REGION="${REGION:-us-central1}"

bold() { printf "\n\033[1m%s\033[0m\n" "$1"; }

PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
if [[ -z "$PROJECT" ]]; then
  echo "No Google Cloud project selected."
  echo "Pick one at the top of the Cloud console, or run:  gcloud config set project YOUR_PROJECT_ID"
  exit 1
fi
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
APP_URL="https://${SERVICE}-${PROJECT_NUMBER}.${REGION}.run.app"

bold "Project: $PROJECT   Region: $REGION"
echo "Your app will live at: $APP_URL"

# Updating an existing deployment only needs the new code; settings are kept.
if gcloud run services describe "$SERVICE" --region "$REGION" >/dev/null 2>&1; then
  read -r -p "The app is already deployed. Update it with the latest code? [Y/n] " answer
  if [[ ! "$answer" =~ ^[Nn] ]]; then
    gcloud run deploy "$SERVICE" --source . --region "$REGION" --quiet
    bold "Updated: $APP_URL"
    exit 0
  fi
fi

bold "Turning on the Google services the app needs (takes a minute the first time)…"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  drive.googleapis.com --quiet

# Newer projects need this so Cloud Build can build from source with the default account
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/run.builder" --condition=None --quiet >/dev/null

bold "Google sign-in setup (one time, in the console)"
cat <<STEPS
Open https://console.cloud.google.com/auth/overview?project=${PROJECT} and:
  1. Click "Get started". App name: Academic Weapon. Use your Gmail for the emails.
     Audience: External. Finish and click Create.
  2. Audience -> Test users -> Add users -> your Gmail -> Save.
  3. Data Access -> Add or remove scopes -> tick ".../auth/drive.appdata" -> Update -> Save.
  4. Clients -> Create client -> Application type: Web application.
     Under "Authorized redirect URIs" click Add URI and paste exactly:

         ${APP_URL}/oauth2callback

     Click Create, then copy the Client ID and Client secret.
STEPS
read -r -p "Press Enter when you have the Client ID and secret… " _

bold "Your settings (typed values are not shown for secrets)"
read -r -p "Google Client ID: " GOOGLE_CLIENT_ID
read -r -s -p "Google Client secret: " GOOGLE_CLIENT_SECRET; echo
read -r -p "Your Gmail address (the only account allowed in): " ALLOWED_EMAIL
read -r -s -p "Anthropic API key (sk-ant-…): " ANTHROPIC_API_KEY; echo
COOKIE_SECRET="$(openssl rand -hex 32)"

for v in GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET ALLOWED_EMAIL ANTHROPIC_API_KEY; do
  if [[ -z "${!v}" ]]; then echo "$v can't be empty. Run the script again."; exit 1; fi
done

ENV_FILE="$(mktemp)"
trap 'rm -f "$ENV_FILE"' EXIT
# YAML single-quoted strings: double any single quote
yaml() { printf "%s: '%s'\n" "$1" "${2//\'/\'\'}"; }
{
  yaml APP_URL "$APP_URL"
  yaml GOOGLE_CLIENT_ID "$GOOGLE_CLIENT_ID"
  yaml GOOGLE_CLIENT_SECRET "$GOOGLE_CLIENT_SECRET"
  yaml COOKIE_SECRET "$COOKIE_SECRET"
  yaml ALLOWED_EMAIL "$ALLOWED_EMAIL"
  yaml ANTHROPIC_API_KEY "$ANTHROPIC_API_KEY"
} > "$ENV_FILE"

bold "Building and deploying (about 3-5 minutes)…"
# One instance only: the app keeps one working copy of your data and saves it to Drive.
gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --max-instances 1 \
  --session-affinity \
  --memory 1Gi \
  --timeout 3600 \
  --env-vars-file "$ENV_FILE" \
  --quiet

bold "Done! Open your app: $APP_URL"
echo "Sign in with $ALLOWED_EMAIL. Google will say the app isn't verified: click Continue."
