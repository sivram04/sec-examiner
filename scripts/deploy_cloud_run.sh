#!/usr/bin/env bash
# Deploy the public SEC Examiner demo to Google Cloud Run.
#
#   bash scripts/deploy_cloud_run.sh
#
# Needs: a gcloud profile logged in to a project with billing (default: the docintel-lk profile,
# project docintel-demo-lk, which has a $5 budget alert), and SEC_USER_AGENT in .env.
# Cost guards: scales to zero, 1 instance max (also keeps the in-memory quota exact),
# 2 examinations per visitor IP per day, 300 per day site-wide.
set -euo pipefail
cd "$(dirname "$0")/.."
export CLOUDSDK_ACTIVE_CONFIG_NAME=${GCLOUD_PROFILE:-docintel-lk}
PROJECT=${PROJECT:-docintel-demo-lk}
REGION=${REGION:-us-central1}
SERVICE=sec-examiner
set -a; . ./.env; set +a

echo "== stage the public letters and the champion model only"
CHAMP=$(python -c "import json;print(json.load(open('data/examiner/models/registry.json'))['champion'])")
rm -rf deploy/models && mkdir -p "deploy/models/$CHAMP"
cp data/examiner/models/registry.json data/examiner/models/audit.jsonl deploy/models/
cp data/examiner/letters.jsonl deploy/
cp "data/examiner/models/$CHAMP/model.joblib" "data/examiner/models/$CHAMP/meta.json" "deploy/models/$CHAMP/"

echo "== services"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  --project "$PROJECT"
gcloud artifacts repositories describe sec-examiner --location "$REGION" --project "$PROJECT" \
  >/dev/null 2>&1 || gcloud artifacts repositories create sec-examiner --repository-format docker \
  --location "$REGION" --project "$PROJECT"

IMAGE="$REGION-docker.pkg.dev/$PROJECT/sec-examiner/app:$(git rev-parse --short HEAD)"
echo "== build $IMAGE"
gcloud builds submit --config cloudbuild.yaml --substitutions "_IMAGE=$IMAGE" --project "$PROJECT" .

echo "== deploy"
gcloud run deploy "$SERVICE" --image "$IMAGE" --project "$PROJECT" --region "$REGION" \
  --port 8080 --cpu 1 --memory 1Gi --min-instances 0 --max-instances 1 --concurrency 20 \
  --timeout 120 --no-invoker-iam-check \
  --set-env-vars "EXAMINER_PUBLIC=1,EXAMINER_PER_IP_DAILY=2,EXAMINER_GLOBAL_DAILY=300,TRUST_PROXY=1,SEC_USER_AGENT=${SEC_USER_AGENT}" \
  --quiet
gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format "value(status.url)"
