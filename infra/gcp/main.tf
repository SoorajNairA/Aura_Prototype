locals {
  runtime_name = "aura-runner"
  db_name      = "aura"
  db_user      = "aura"
  apis = toset([
    "aiplatform.googleapis.com", "artifactregistry.googleapis.com", "run.googleapis.com",
    "sqladmin.googleapis.com", "secretmanager.googleapis.com", "storage.googleapis.com",
    "servicenetworking.googleapis.com", "compute.googleapis.com", "cloudbuild.googleapis.com"
  ])
}

resource "google_project_service" "required" {
  for_each           = local.apis
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "aura" {
  location      = var.region
  repository_id = "aura"
  format        = "DOCKER"
  depends_on    = [google_project_service.required]
}

resource "google_service_account" "runtime" {
  account_id   = local.runtime_name
  display_name = "AURA Cloud Run runtime"
}

resource "google_project_iam_member" "runtime_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}
resource "google_project_iam_member" "runtime_sql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_compute_global_address" "private_services" {
  name          = "aura-private-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = "default"
  depends_on    = [google_project_service.required]
}
resource "google_service_networking_connection" "private_services" {
  network                 = "default"
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]
}

resource "google_sql_database_instance" "aura" {
  name                = "aura-postgres"
  region              = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = var.database_deletion_protection
  settings {
    tier              = var.database_tier
    edition           = "ENTERPRISE"
    availability_type = "ZONAL"
    disk_type         = "PD_SSD"
    disk_size         = var.database_disk_gb
    disk_autoresize   = false
    backup_configuration { enabled = false }
    ip_configuration {
      ipv4_enabled                                  = false
      private_network                               = "projects/${var.project_id}/global/networks/default"
      enable_private_path_for_google_cloud_services = true
    }
  }
  depends_on = [google_service_networking_connection.private_services]
}
resource "google_sql_database" "aura" {
  name     = local.db_name
  instance = google_sql_database_instance.aura.name
}
resource "random_password" "database" {
  length  = 32
  special = false
}
resource "google_sql_user" "aura" {
  name     = local.db_user
  instance = google_sql_database_instance.aura.name
  password = random_password.database.result
}
resource "google_secret_manager_secret" "db_password" {
  secret_id = "aura-db-password"
  replication {
    auto {}
  }
  depends_on = [google_project_service.required]
}
resource "google_secret_manager_secret_version" "db_password" {
  secret      = google_secret_manager_secret.db_password.id
  secret_data = random_password.database.result
}
resource "google_secret_manager_secret_iam_member" "runtime" {
  secret_id = google_secret_manager_secret.db_password.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_storage_bucket" "artifacts" {
  name                        = "${var.project_id}-aura-artifacts"
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.artifact_force_destroy
  soft_delete_policy { retention_duration_seconds = 604800 }
}
resource "google_storage_bucket_iam_member" "runtime" {
  bucket = google_storage_bucket.artifacts.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_cloud_run_v2_service" "aura" {
  name                = var.service_name
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"
  lifecycle {
    ignore_changes = [scaling]
  }
  template {
    service_account                  = google_service_account.runtime.email
    timeout                          = "3600s"
    max_instance_request_concurrency = 20
    scaling {
      min_instance_count = var.min_instances == 0 ? null : 1
      max_instance_count = 1
    }
    vpc_access {
      network_interfaces {
        network    = "default"
        subnetwork = "default"
      }
      egress = "PRIVATE_RANGES_ONLY"
    }
    volumes {
      name = "cloudsql"
      cloud_sql_instance { instances = [google_sql_database_instance.aura.connection_name] }
    }
    containers {
      image = var.image
      resources {
        limits   = { cpu = "1", memory = "1Gi" }
        cpu_idle = true
      }
      ports { container_port = 8080 }
      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
      env {
        name  = "AURA_CLOUD_MODE"
        value = "true"
      }
      env {
        name  = "AURA_LLM_PROVIDER"
        value = "vertex"
      }
      env {
        name  = "AURA_GCP_PROJECT"
        value = var.project_id
      }
      env {
        name  = "AURA_GCP_LOCATION"
        value = "global"
      }
      env {
        name  = "AURA_VERTEX_MODEL"
        value = "gemini-3.1-flash-lite"
      }
      env {
        name  = "AURA_VERTEX_TIMEOUT_SECONDS"
        value = "20"
      }
      env {
        name  = "AURA_WORKSPACE_STORAGE_MODE"
        value = "postgres"
      }
      env {
        name  = "AURA_ARTIFACT_STORAGE_MODE"
        value = "gcs"
      }
      env {
        name  = "AURA_GCS_BUCKET"
        value = google_storage_bucket.artifacts.name
      }
      env {
        name  = "AURA_DB_HOST"
        value = "/cloudsql/${google_sql_database_instance.aura.connection_name}"
      }
      env {
        name  = "AURA_DB_NAME"
        value = local.db_name
      }
      env {
        name  = "AURA_DB_USER"
        value = local.db_user
      }
      env {
        name  = "AURA_DB_POOL_SIZE"
        value = "3"
      }
      env {
        name  = "AURA_DB_MAX_OVERFLOW"
        value = "1"
      }
      env {
        name  = "AURA_DB_POOL_TIMEOUT"
        value = "5"
      }
      env {
        name = "AURA_DB_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.db_password.secret_id
            version = "latest"
          }
        }
      }
      startup_probe {
        http_get { path = "/health/live" }
        initial_delay_seconds = 2
        timeout_seconds       = 2
        period_seconds        = 3
        failure_threshold     = 30
      }
      liveness_probe {
        http_get { path = "/health/live" }
        timeout_seconds   = 2
        period_seconds    = 30
        failure_threshold = 3
      }
    }
  }
  depends_on = [google_project_service.required, google_secret_manager_secret_iam_member.runtime,
    google_project_iam_member.runtime_sql, google_project_iam_member.runtime_vertex,
  google_storage_bucket_iam_member.runtime]
}
