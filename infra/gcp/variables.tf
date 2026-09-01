variable "project_id" {
  type        = string
  description = "Google Cloud project ID used for the AURA deployment."
}
variable "region" {
  type    = string
  default = "asia-south1"
}
variable "service_name" {
  type    = string
  default = "aura-workspace"
}
variable "image" {
  type        = string
  description = "Immutable or tagged Artifact Registry image URL."
}
variable "min_instances" {
  type    = number
  default = 0
  validation {
    condition     = contains([0, 1], var.min_instances)
    error_message = "min_instances must be 0 or 1."
  }
}
variable "database_tier" {
  type    = string
  default = "db-f1-micro"
}
variable "database_disk_gb" {
  type    = number
  default = 10
}
variable "database_deletion_protection" {
  type    = bool
  default = true
}
variable "artifact_force_destroy" {
  type    = bool
  default = false
}
