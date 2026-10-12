# Lo que cambia de un job a otro. Todo lo demás es igual para todos y vive en main.tf.

variable "nombre" {
  description = "Nombre corto del job, por ejemplo gleif-bronze. El job se llama refhub-<nombre>-<ambiente> y su rol refhub-glue-<nombre>-<ambiente>."
  type        = string
}

variable "environment" {
  description = "Ambiente (dev): va al final de los nombres."
  type        = string
}

variable "script_location" {
  description = "Dónde está el script en S3: el que publicó el CI para la versión en uso."
  type        = string
}

variable "argumentos" {
  description = "Los parámetros del job (--DATA_BUCKET, --conf, ...): los comunes del hub más los suyos."
  type        = map(string)
}

variable "permisos_json" {
  description = "La política del job: los permisos base de glue_comun.tf más los propios, como JSON."
  type        = string
}

variable "timeout" {
  description = "Minutos: si el job tarda más, Glue lo corta y deja de cobrar."
  type        = number
  default     = 60
}
