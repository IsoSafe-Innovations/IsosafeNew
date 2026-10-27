# Demo VM security group. PRD DEMO-FR-60.
#
# Inbound:
#   80, 443 -> the whole internet (nginx HTTP->HTTPS redirect, HTTPS app front door)
#   22      -> developer/owner IPs ONLY (var.ssh_allowed_cidrs)
# Deliberately NO public 5432 (postgres), 6379 (redis), or 8000 (backend API):
# those containers are reachable only inside the Docker bridge network and never
# published to the VM host.
#
# Outbound: all — the VM needs it for apt/containers, Docker Hub pulls, and S3
# presigned URLs. The site-facing connectivity is outbound-only by design.

resource "aws_security_group" "demo" {
  name        = "${local.name_prefix}-vm"
  description = "Iso Safe demo VM: 80/443 from internet, SSH from owner IPs only"
  vpc_id      = aws_vpc.demo.id

  tags = { Name = "${local.name_prefix}-vm" }
}

resource "aws_security_group_rule" "http_in" {
  type              = "ingress"
  security_group_id = aws_security_group.demo.id
  description       = "HTTP to nginx (redirect to HTTPS)"
  from_port         = 80
  to_port           = 80
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
}

resource "aws_security_group_rule" "https_in" {
  type              = "ingress"
  security_group_id = aws_security_group.demo.id
  description       = "HTTPS to nginx (app front door, also /api and WSS)"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
}

resource "aws_security_group_rule" "ssh_in" {
  type              = "ingress"
  security_group_id = aws_security_group.demo.id
  description       = "SSH from developer/owner IPs only"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  cidr_blocks       = var.ssh_allowed_cidrs
}

resource "aws_security_group_rule" "egress_all" {
  type              = "egress"
  security_group_id = aws_security_group.demo.id
  description       = "Outbound (apt, containers, Docker Hub, S3)"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"]
}