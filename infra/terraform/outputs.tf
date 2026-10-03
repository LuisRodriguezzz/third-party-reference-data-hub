output "data_bucket" {
  value = aws_s3_bucket.data.bucket
}

output "gleif_lambda_name" {
  value = aws_lambda_function.gleif.function_name
}

output "gleif_state_machine_arn" {
  value = aws_sfn_state_machine.gleif.arn
}