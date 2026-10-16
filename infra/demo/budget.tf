# AWS monthly cost budget + email alerts (PRD v2 Phase 1a DEMO-FR-65).
#
# Defaults to a $100/month budget. When budget_alert_email is set, alerts fire
# at 80% of actual spend and 100% of forecasted spend.

data "aws_caller_identity" "current" {}

locals {
  budget_notifications = var.budget_alert_email == "" ? [] : [
    {
      type           = "ACTUAL"
      operator       = "GREATER_THAN"
      threshold      = 80
      threshold_type = "PERCENTAGE"
    },
    {
      type           = "FORECASTED"
      operator       = "GREATER_THAN"
      threshold      = 100
      threshold_type = "PERCENTAGE"
    },
  ]
}

resource "aws_budgets_budget" "demo" {
  account_id   = data.aws_caller_identity.current.account_id
  name         = "${local.name_prefix}-monthly"
  budget_type  = "COST"
  time_unit    = "MONTHLY"
  limit_amount = tostring(var.budget_limit_usd)
  limit_unit   = "USD"

  dynamic "notification" {
    for_each = local.budget_notifications
    content {
      comparison_operator        = notification.value.operator
      threshold                  = notification.value.threshold
      threshold_type             = notification.value.threshold_type
      notification_type          = notification.value.type
      subscriber_email_addresses = [var.budget_alert_email]
    }
  }
}
