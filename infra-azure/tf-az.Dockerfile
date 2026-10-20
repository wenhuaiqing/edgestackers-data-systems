# Terraform and the Azure CLI in one image.
#
# terraform.exe will not execute on a managed Windows laptop: application
# control blocks a large unsigned binary in the user profile ("Access is
# denied" with full ACLs). Inside the Linux VM it has no reach. Authenticate
# with a service principal through ARM_* variables; a container cannot borrow
# the host's az session.
#
# Build once:
#   docker build -f infra-azure/tf-az.Dockerfile -t tf-az:local infra-azure
# Run (PowerShell, not Git Bash - Git Bash rewrites -w /work into a Windows path):
#   docker run --rm -v "<repo>\infra-azure:/work" -w /work -e ARM_CLIENT_ID=... `
#     -e ARM_CLIENT_SECRET=... -e ARM_TENANT_ID=... -e ARM_SUBSCRIPTION_ID=... tf-az:local plan -out=tfplan

FROM hashicorp/terraform:latest AS tf

FROM mcr.microsoft.com/azure-cli:latest
COPY --from=tf /bin/terraform /usr/local/bin/terraform
WORKDIR /work
ENTRYPOINT ["terraform"]
