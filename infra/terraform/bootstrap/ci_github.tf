# Los roles con los que el CI de GitHub entra a AWS, sin claves guardadas (OIDC).
# Viven en bootstrap y no en el hub: el CI aplica el hub, así que no puede tocar los roles con
# los que entra. Este archivo lo aplicás vos, desde tu máquina, igual que el bucket del state.

variable "github_sub_prefix" {
  description = "Cómo se presenta tu repo en el token de GitHub (gh api repos/<dueño>/<repo>/actions/oidc/customization/sub)."
  type        = string
  default     = "repo:LuisRodriguezzz@131310791/third-party-reference-data-hub@1391569587"
}

data "aws_region" "actual" {}

locals {
  account_id = data.aws_caller_identity.actual.account_id
  region     = data.aws_region.actual.region

  # Los buckets de datos del hub se llaman refhub-data-<cuenta>-<ambiente>.
  data_buckets = "arn:aws:s3:::refhub-data-${local.account_id}-*"
}

# El proveedor OIDC de GitHub ya está registrado en la cuenta (se crea una vez por cuenta y
# puede haber uno solo por URL). "data" lo lee: Terraform no lo crea, no lo cambia ni lo borra.
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

# ---------------------------------------------------------------- 1. Lo que comparten los dos

# ReadOnlyAccess deja leer el contenido de CUALQUIER bucket de la cuenta. Este Deny lo recorta:
# solo el state y los artefactos del hub. Un Deny gana siempre sobre cualquier Allow.
data "aws_iam_policy_document" "ci_comun" {
  statement {
    sid     = "NoLeerDatos"
    effect  = "Deny"
    actions = ["s3:GetObject", "s3:GetObjectVersion"]
    not_resources = [
      "${aws_s3_bucket.state.arn}/*",      # el state y su candado
      "${local.data_buckets}/artifacts/*", # el .whl, el zip de la Lambda y los scripts de Glue
    ]
  }
}

# ---------------------------------------------------------------- 2. Rol de plan (pull requests)

# QUIÉN: un workflow de TU repo, corriendo por un pull request. Nadie más.
data "aws_iam_policy_document" "ci_plan_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"] # entrar con un token de GitHub, no con claves

    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"] # el token se pidió para AWS
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${var.github_sub_prefix}:pull_request"] # tu repo, en un pull request
    }
  }
}

resource "aws_iam_role" "ci_plan" {
  name                 = "refhub-github-plan"
  description          = "CI de GitHub: terraform plan en los pull requests (solo lectura)."
  assume_role_policy   = data.aws_iam_policy_document.ci_plan_assume.json
  max_session_duration = 3600 # las credenciales vencen en una hora
}

# QUÉ puede hacer, parte 1: leer (describir) todo, que es lo que necesita un plan.
resource "aws_iam_role_policy_attachment" "ci_plan_lectura" {
  role       = aws_iam_role.ci_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess" # política administrada por AWS
}

# QUÉ puede hacer, parte 2: poner y sacar el candado del state, y nada más.
data "aws_iam_policy_document" "ci_plan" {
  source_policy_documents = [data.aws_iam_policy_document.ci_comun.json] # el Deny de arriba

  statement {
    sid       = "CandadoDelState" # el archivo .tflock que crea use_lockfile
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.state.arn}/hub/*.tflock"]
  }
}

resource "aws_iam_role_policy" "ci_plan" {
  name   = "candado-del-state"
  role   = aws_iam_role.ci_plan.id
  policy = data.aws_iam_policy_document.ci_plan.json
}

# ---------------------------------------------------------------- 3. Rol de apply (main)

# QUIÉN: un workflow de TU repo, corriendo en la rama main (o sea, después de un merge).
data "aws_iam_policy_document" "ci_apply_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${var.github_sub_prefix}:ref:refs/heads/main"] # tu repo, rama main
    }
  }
}

resource "aws_iam_role" "ci_apply" {
  name                 = "refhub-github-apply"
  description          = "CI de GitHub: terraform apply del hub al mergear a main."
  assume_role_policy   = data.aws_iam_policy_document.ci_apply_assume.json
  max_session_duration = 3600
}

resource "aws_iam_role_policy_attachment" "ci_apply_lectura" {
  role       = aws_iam_role.ci_apply.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess" # el apply también hace un plan antes
}

# QUÉ puede cambiar: solo lo que se llama refhub-* (o refhub_* en el catálogo de Glue).
data "aws_iam_policy_document" "ci_apply" {
  source_policy_documents = [data.aws_iam_policy_document.ci_comun.json]

  statement {
    sid       = "StateDelHub" # escribir el state y su candado (leerlo ya puede)
    actions   = ["s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.state.arn}/hub/*"]
  }

  statement {
    sid = "BucketDeDatos" # crear y configurar el bucket (acciones de bucket, no de objetos)
    actions = [
      "s3:CreateBucket", "s3:DeleteBucket", "s3:PutBucket*",
      "s3:PutLifecycleConfiguration", "s3:PutEncryptionConfiguration",
    ]
    resources = [local.data_buckets]
  }

  statement {
    sid       = "Artefactos" # los objetos que maneja Terraform o publica el CI: solo artifacts/
    actions   = ["s3:PutObject", "s3:PutObjectTagging", "s3:DeleteObject"]
    resources = ["${local.data_buckets}/artifacts/*"]
  }

  statement {
    # Crear y cambiar los roles de la Lambda, Glue, Step Functions... con políticas escritas en
    # el rol, como las del hub. Sin AttachRolePolicy: no puede pegarle AdministratorAccess a nadie.
    sid = "RolesDelHub"
    actions = [
      "iam:CreateRole", "iam:DeleteRole", "iam:UpdateRole", "iam:UpdateRoleDescription",
      "iam:UpdateAssumeRolePolicy", "iam:TagRole", "iam:UntagRole",
      "iam:PutRolePolicy", "iam:DeleteRolePolicy",
    ]
    resources = ["arn:aws:iam::${local.account_id}:role/refhub-*"]
  }

  statement {
    sid       = "PasarRolesASusServicios" # "darle" un rol a la Lambda, a Glue, etc. al crearlos
    actions   = ["iam:PassRole"]
    resources = ["arn:aws:iam::${local.account_id}:role/refhub-*"]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values = [
        "lambda.amazonaws.com", "glue.amazonaws.com",
        "states.amazonaws.com", "scheduler.amazonaws.com",
      ]
    }
  }

  statement {
    sid    = "NoTocarLosRolesDelCI" # ni este rol ni el de plan, aunque empiecen con refhub-
    effect = "Deny"
    actions = [
      "iam:Attach*", "iam:Create*", "iam:Delete*", "iam:Detach*", "iam:PassRole",
      "iam:Put*", "iam:Tag*", "iam:Untag*", "iam:Update*",
    ]
    resources = ["arn:aws:iam::${local.account_id}:role/refhub-github-*"]
  }

  statement {
    sid     = "ServiciosDelHub" # todo, pero solo sobre lo que se llama refhub-*
    actions = ["lambda:*", "logs:*", "states:*", "scheduler:*", "glue:*", "athena:*", "budgets:*"]
    resources = [
      "arn:aws:lambda:${local.region}:${local.account_id}:function:refhub-*",
      "arn:aws:logs:${local.region}:${local.account_id}:log-group:/aws/lambda/refhub-*",
      "arn:aws:logs:${local.region}:${local.account_id}:log-group:/aws-glue/refhub-*",
      "arn:aws:states:${local.region}:${local.account_id}:stateMachine:refhub-*",
      "arn:aws:scheduler:${local.region}:${local.account_id}:schedule/default/refhub-*",
      "arn:aws:glue:${local.region}:${local.account_id}:job/refhub-*",
      "arn:aws:athena:${local.region}:${local.account_id}:workgroup/refhub-*",
      "arn:aws:budgets::${local.account_id}:budget/refhub-*",
    ]
  }

  statement {
    sid = "CatalogoDelHub" # las bases refhub_* del catálogo de Glue (4B y 4C) y sus tablas
    actions = [
      "glue:CreateDatabase", "glue:UpdateDatabase", "glue:DeleteDatabase",
      "glue:DeleteTable", "glue:BatchDeleteTable", "glue:TagResource", "glue:UntagResource",
    ]
    resources = [
      "arn:aws:glue:${local.region}:${local.account_id}:catalog",
      "arn:aws:glue:${local.region}:${local.account_id}:database/refhub_*",
      "arn:aws:glue:${local.region}:${local.account_id}:table/refhub_*/*",
    ]
  }
}

resource "aws_iam_role_policy" "ci_apply" {
  name   = "aplicar-el-hub"
  role   = aws_iam_role.ci_apply.id
  policy = data.aws_iam_policy_document.ci_apply.json
}

# ---------------------------------------------------------------- 4. Para cargar en GitHub

output "ci_plan_role_arn" {
  value = aws_iam_role.ci_plan.arn
}

output "ci_apply_role_arn" {
  value = aws_iam_role.ci_apply.arn
}