# DNS: demo.<domain_root> -> Elastic IP (PRD DEMO-FR-60).
# Uses the existing hosted zone named by domain_root, unless 'hosted_zone_id'
# is set explicitly.

data "aws_route53_zone" "demo" {
  count        = var.hosted_zone_id == "" ? 1 : 0
  name         = var.domain_root
  private_zone = false
}

resource "aws_route53_record" "demo" {
  zone_id = var.hosted_zone_id != "" ? var.hosted_zone_id : data.aws_route53_zone.demo[0].zone_id
  name    = local.full_domain
  type    = "A"
  ttl     = 300
  records = [aws_eip.demo.public_ip]
}
