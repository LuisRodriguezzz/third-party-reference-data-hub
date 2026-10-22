output "data_bucket" {
  value = aws_s3_bucket.data.bucket
}

output "gleif_lambda_name" {
  value = aws_lambda_function.gleif.function_name
}

output "pipeline_state_machine_arn" {
  value = aws_sfn_state_machine.pipeline.arn
}

output "dbt_codebuild_project" {
  value = aws_codebuild_project.dbt.name
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

output "glue_gleif_isin_lei_job" {
  value = module.glue_gleif_isin_lei.job_name
}

output "glue_sec_job" {
  value = module.glue_sec.job_name
}

output "glue_gleif_relaciones_job" {
  value = module.glue_gleif_relaciones.job_name
}
