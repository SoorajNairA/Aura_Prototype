# Google Cloud deployment

AURA's Google Cloud topology uses one private Cloud Run service, a zonal PostgreSQL 16 Cloud SQL instance, and a private regional Standard Cloud Storage bucket. Vertex remains global. Cloud Run is limited to one instance because live WebSocket fan-out is process-local; durable PostgreSQL replay remains authoritative.

## Cost profile

Cloud Run defaults to zero minimum instances and request-based billing, so idle cost is near zero. Cloud SQL is the persistent baseline: approximately US$13.14/month compute plus roughly US$2/month storage. Storage and Artifact Registry cost cents at the expected demo volume. Vertex is usage-based. Prices vary by billing currency; verify them in Google's calculator before applying.

## Initial deployment and redeploy

Prerequisites are `gcloud`, Terraform 1.7+, an authenticated deployer with infrastructure permissions, and an attached billing account. No service-account keys are used.

```powershell
gcloud config set project your-gcp-project-id
./scripts/deploy-gcp.ps1 -ProjectId your-gcp-project-id
```

The script enables only declared APIs, creates Artifact Registry first, submits the multi-stage build to Google Cloud Build, then applies the complete private deployment. Normal redeploy uses the same command and a distinct tag if desired. The final container runs Python 3.12 as a non-root user, serves the Vite production build from FastAPI, and retains only Node plus pinned tscircuit runtime dependencies.

The service is private by default. A signed-in authorized user can use `gcloud run services proxy aura-workspace --region asia-south1`. Public access requires an explicit security decision, then only this narrow binding:

```powershell
gcloud run services add-iam-policy-binding aura-workspace --region asia-south1 --member=allUsers --role=roles/run.invoker
```

## Demo warm mode and spending controls

Set `-MinInstances 1` during a live demo and return to `-MinInstances 0` afterward. This does not delete data:

```powershell
./scripts/deploy-gcp.ps1 -ProjectId your-gcp-project-id -MinInstances 1
./scripts/deploy-gcp.ps1 -ProjectId your-gcp-project-id -MinInstances 0
```

Cloud SQL still accrues its baseline while Cloud Run is at zero. To stop all database compute without deleting it, use the Cloud SQL activation policy deliberately and restore it before a demo. This is operational state outside Terraform and can be reset by the next apply.

## Explicit local-to-cloud migration

Configure the PostgreSQL/GCS environment used by Cloud Run, then inspect before copying:

```powershell
aura-migrate-storage --from sqlite --to postgres --dry-run
aura-migrate-storage --from sqlite --to postgres
```

The importer preserves revisions, structured patches, verification data, event IDs/order, representation metadata, artifact keys, and SHA-256 hashes. It refuses target project conflicts and never deletes the SQLite source.

## Validation and teardown

Paid integration tests are opt-in: `AURA_RUN_GCP_LIVE=1 pytest -m gcp_live`. Normal pytest skips them.

Terraform protects the database and non-empty bucket by default. Normal redeploy never destroys either. Intentional data destruction requires both explicit overrides and confirmation:

```powershell
terraform -chdir=infra/gcp apply -var='image=IMAGE' -var='database_deletion_protection=false' -var='artifact_force_destroy=true'
terraform -chdir=infra/gcp destroy -var='image=IMAGE' -var='database_deletion_protection=false' -var='artifact_force_destroy=true'
```

This permanently destroys persisted cloud data. Keep Cloud Run at zero instead when the goal is only to minimize demo spending.
