# Lo que el resto del hub necesita saber del job (Step Functions lo arranca por nombre).

output "job_name" {
  value = aws_glue_job.this.name
}

output "job_arn" {
  value = aws_glue_job.this.arn
}
