# Elastic IP attached to the VM. The A record below points the demo domain at
# this address, so a recreated instance keeps the same public URL.

resource "aws_eip" "demo" {
  instance = aws_instance.demo.id
  domain   = "vpc"

  tags = { Name = "${local.name_prefix}-vm" }
}