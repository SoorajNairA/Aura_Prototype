param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,
    [string]$Region = "asia-south1",
    [ValidateSet(0, 1)][int]$MinInstances = 0,
    [string]$Tag = "latest"
)
$ErrorActionPreference = "Stop"
if ((gcloud config get-value project).Trim() -ne $ProjectId) {
    throw "Active gcloud project must be $ProjectId"
}
if (-not (Get-Command terraform -ErrorAction SilentlyContinue)) {
    throw "Terraform >=1.7 must be installed and available on PATH"
}
$infra = Join-Path $PSScriptRoot "../infra/gcp"
$image = "${Region}-docker.pkg.dev/$ProjectId/aura/workspace:$Tag"
Push-Location $infra
try {
    terraform init
    terraform apply -target=google_project_service.required -target=google_artifact_registry_repository.aura -var="image=$image" -auto-approve
    gcloud builds submit (Resolve-Path "$PSScriptRoot/..") --project $ProjectId --tag $image
    $digest = (gcloud artifacts docker images describe $image --project $ProjectId --format='value(image_summary.digest)').Trim()
    if (-not $digest.StartsWith("sha256:")) { throw "Could not resolve immutable image digest for $image" }
    $deployedImage = "${Region}-docker.pkg.dev/$ProjectId/aura/workspace@$digest"
    terraform apply -var="image=$deployedImage" -var="min_instances=$MinInstances" -auto-approve
    terraform output
} finally {
    Pop-Location
}
