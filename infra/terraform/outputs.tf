output "data_bucket" {
  value = aws_s3_bucket.data.bucket
}

output "gleif_lambda_name" {
  value = aws_lambda_function.gleif.function_name
}

output "gleif_state_machine_arn" {
  value = aws_sfn_state_machine.gleif.arn
}

output "glue_gleif_full_job" {
  value = module.glue_gleif_full.job_name
}

output "glue_gleif_bronze_job" {
  value = module.glue_gleif_bronze.job_name
}

output "athena_workgroup" {
  value = aws_athena_workgroup.hub.name
}

output "glue_gleif_silver_job" {
  value = module.glue_gleif_silver.job_name
}
