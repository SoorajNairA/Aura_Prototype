output "cloud_run_url" {
  value = google_cloud_run_v2_service.aura.uri
}
output "cloud_sql_connection_name" {
  value = google_sql_database_instance.aura.connection_name
}
output "database_name" {
  value = google_sql_database.aura.name
}
output "artifact_bucket_name" {
  value = google_storage_bucket.artifacts.name
}
output "runtime_service_account" {
  value = google_service_account.runtime.email
}
output "region" {
  value = var.region
}
output "artifact_registry_repository" {
  value = google_artifact_registry_repository.aura.id
}
