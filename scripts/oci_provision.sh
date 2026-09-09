#!/usr/bin/env bash
# Provisions the Always-Free OCI resources for this project:
#   - VCN + public subnet + internet gateway + security list (22, 8080)
#   - Autonomous Database, Always Free, Data Warehouse workload
#   - Compute instance, VM.Standard.A1.Flex (Ampere ARM, Always Free eligible)
#
# Prereqs: `oci setup config` already run (needs an OCI account + API signing key).
# Fill in the variables below, then: bash scripts/oci_provision.sh
set -euo pipefail

# ---- fill these in ----
COMPARTMENT_ID="ocid1.tenancy.oc1..xxxxxxxx"   # or a sub-compartment OCID
REGION="us-ashburn-1"
SSH_PUBLIC_KEY_FILE="$HOME/.ssh/id_rsa.pub"
DB_ADMIN_PASSWORD="ChangeMe123#"                # 12-30 chars, upper+lower+digit, no dictionary word
APP_NAME="recowarehouse"
# ------------------------

echo "== Availability domain =="
AD=$(oci iam availability-domain list --compartment-id "$COMPARTMENT_ID" \
     --query "data[0].name" --raw-output)
echo "$AD"

echo "== Network: VCN =="
VCN_ID=$(oci network vcn create --compartment-id "$COMPARTMENT_ID" \
  --display-name "${APP_NAME}-vcn" --cidr-block "10.0.0.0/16" \
  --query "data.id" --raw-output --wait-for-state AVAILABLE)

echo "== Network: Internet Gateway =="
IG_ID=$(oci network internet-gateway create --compartment-id "$COMPARTMENT_ID" \
  --vcn-id "$VCN_ID" --display-name "${APP_NAME}-ig" --is-enabled true \
  --query "data.id" --raw-output --wait-for-state AVAILABLE)

echo "== Network: route table =="
RT_ID=$(oci network route-table list --compartment-id "$COMPARTMENT_ID" --vcn-id "$VCN_ID" \
  --query "data[0].id" --raw-output)
oci network route-table update --rt-id "$RT_ID" --force \
  --route-rules "[{\"destination\":\"0.0.0.0/0\",\"destinationType\":\"CIDR_BLOCK\",\"networkEntityId\":\"$IG_ID\"}]" >/dev/null

echo "== Network: security list (22, 8080 ingress) =="
SL_ID=$(oci network security-list list --compartment-id "$COMPARTMENT_ID" --vcn-id "$VCN_ID" \
  --query "data[0].id" --raw-output)
oci network security-list update --security-list-id "$SL_ID" --force \
  --ingress-security-rules '[
    {"source":"0.0.0.0/0","protocol":"6","tcpOptions":{"destinationPortRange":{"min":22,"max":22}}},
    {"source":"0.0.0.0/0","protocol":"6","tcpOptions":{"destinationPortRange":{"min":8080,"max":8080}}}
  ]' \
  --egress-security-rules '[{"destination":"0.0.0.0/0","protocol":"all"}]' >/dev/null

echo "== Network: public subnet =="
SUBNET_ID=$(oci network subnet create --compartment-id "$COMPARTMENT_ID" --vcn-id "$VCN_ID" \
  --display-name "${APP_NAME}-subnet" --cidr-block "10.0.1.0/24" \
  --route-table-id "$RT_ID" --security-list-ids "[\"$SL_ID\"]" \
  --prohibit-public-ip-on-vnic false \
  --query "data.id" --raw-output --wait-for-state AVAILABLE)

echo "== Autonomous Database (Always Free, DW workload) =="
oci db autonomous-database create --compartment-id "$COMPARTMENT_ID" \
  --db-name "${APP_NAME}" --display-name "${APP_NAME}" \
  --cpu-core-count 1 --data-storage-size-in-tbs 1 \
  --admin-password "$DB_ADMIN_PASSWORD" \
  --db-workload DW --is-free-tier true --license-model LICENSE_INCLUDED \
  --wait-for-state AVAILABLE

echo "== Compute image lookup (Ubuntu 22.04, ARM) =="
IMAGE_ID=$(oci compute image list --compartment-id "$COMPARTMENT_ID" \
  --operating-system "Canonical Ubuntu" --operating-system-version "22.04" \
  --shape "VM.Standard.A1.Flex" --sort-by TIMECREATED --sort-order DESC \
  --query "data[0].id" --raw-output)
echo "$IMAGE_ID"

echo "== Compute instance (VM.Standard.A1.Flex, 4 OCPU / 24GB, Always Free) =="
oci compute instance launch --compartment-id "$COMPARTMENT_ID" \
  --availability-domain "$AD" --shape "VM.Standard.A1.Flex" \
  --shape-config '{"ocpus":4,"memoryInGBs":24}' \
  --display-name "${APP_NAME}-vm" --image-id "$IMAGE_ID" \
  --subnet-id "$SUBNET_ID" --assign-public-ip true \
  --metadata "{\"ssh_authorized_keys\":\"$(cat "$SSH_PUBLIC_KEY_FILE")\"}" \
  --user-data-file scripts/cloud-init.yaml \
  --wait-for-state RUNNING

echo "== Public IP =="
oci compute instance list-vnics --compartment-id "$COMPARTMENT_ID" \
  --query "data[?contains(\"display-name\",'${APP_NAME}-vm')] | [0]['public-ip']" --raw-output

echo
echo "Done. Next: download the ADB wallet or TLS connect string from the console"
echo "(Autonomous Database > DB Connection), ssh into the VM, then follow the"
echo "'Deploy the app' steps in README.md."
