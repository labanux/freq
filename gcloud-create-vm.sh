#!/bin/bash
#===============================================================================
# GCloud Spot VM Creator for Freqtrade Hyperopt
# 
# This script creates a Spot VM on Google Cloud, installs Docker,
# clones your repository, and runs docker compose.
#
# Prerequisites:
#   1. Install gcloud CLI: https://cloud.google.com/sdk/docs/install
#   2. Authenticate: gcloud auth login
#   3. Set project: gcloud config set project YOUR_PROJECT_ID
#   4. Make executable: chmod +x gcloud-create-vm.sh
#
# Usage:
#   ./gcloud-create-vm.sh [INSTANCE_NAME] [MACHINE_TYPE] [ZONE]
#
# Examples:
#   ./gcloud-create-vm.sh                           # Uses defaults
#   ./gcloud-create-vm.sh hyperopt-vm               # Custom name
#   ./gcloud-create-vm.sh hyperopt-vm c2-standard-30 us-central1-a
#===============================================================================

set -e  # Exit on error

#-------------------------------------------------------------------------------
# CONFIGURATION - Modify these values as needed
#-------------------------------------------------------------------------------
INSTANCE_NAME="${1:-freqtrade-hyperopt}"
MACHINE_TYPE="${2:-c4-standard-8}"      # 8 vCPUs, 32GB RAM
ZONE="${3:-asia-southeast1-b}"
BOOT_DISK_SIZE="15GB"
BOOT_DISK_TYPE="hyperdisk-balanced"  # Required for C4 machines (pd-ssd not supported)

# GitHub repository (HTTPS format - no SSH key needed)
GIT_REPO="https://github.com/labanux/freq.git"
GIT_BRANCH="main"

#-------------------------------------------------------------------------------
# Colors for output
#-------------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  GCloud Spot VM Creator for Freqtrade${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Instance Name: ${YELLOW}${INSTANCE_NAME}${NC}"
echo -e "Machine Type:  ${YELLOW}${MACHINE_TYPE}${NC}"
echo -e "Zone:          ${YELLOW}${ZONE}${NC}"
echo -e "Disk:          ${YELLOW}${BOOT_DISK_SIZE} ${BOOT_DISK_TYPE}${NC}"
echo ""

#-------------------------------------------------------------------------------
# Check prerequisites
#-------------------------------------------------------------------------------
echo -e "${YELLOW}[1/7] Checking prerequisites...${NC}"

if ! command -v gcloud &> /dev/null; then
    echo -e "${RED}Error: gcloud CLI is not installed.${NC}"
    echo "Install from: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Check gcloud auth
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -1 > /dev/null; then
    echo -e "${RED}Error: Not logged in to gcloud. Run: gcloud auth login${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Prerequisites OK${NC}"

#-------------------------------------------------------------------------------
# Create the startup script (runs on VM boot)
#-------------------------------------------------------------------------------
STARTUP_SCRIPT=$(cat << 'STARTUP_EOF'
#!/bin/bash
set -e

LOG_FILE="/var/log/freqtrade-setup.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "========================================="
echo "Starting Freqtrade VM Setup"
echo "Time: $(date)"
echo "========================================="

# Update system
echo "[1/4] Updating system packages..."
apt-get update
apt-get upgrade -y

# Install Docker
echo "[2/4] Installing Docker..."
apt-get install -y ca-certificates curl gnupg lsb-release git

# Add Docker's official GPG key
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

# Add Docker repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
  $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Start Docker
systemctl start docker
systemctl enable docker

echo "[3/3] Docker installed successfully!"
docker --version
docker compose version

echo "========================================="
echo "Initial VM Setup Complete at $(date)"
echo "========================================="

# Create marker file to indicate setup is done
touch /tmp/setup-complete
STARTUP_EOF
)

#-------------------------------------------------------------------------------
# Create the VM
#-------------------------------------------------------------------------------
echo -e "${YELLOW}[2/6] Creating Spot VM instance...${NC}"

gcloud compute instances create "$INSTANCE_NAME" \
    --machine-type="$MACHINE_TYPE" \
    --zone="$ZONE" \
    --provisioning-model=SPOT \
    --instance-termination-action=STOP \
    --boot-disk-size="$BOOT_DISK_SIZE" \
    --boot-disk-type="$BOOT_DISK_TYPE" \
    --image-family=debian-12 \
    --image-project=debian-cloud \
    --metadata=startup-script="$STARTUP_SCRIPT" \
    --scopes=default

echo -e "${GREEN}✓ VM created!${NC}"

#-------------------------------------------------------------------------------
# Wait for VM to be ready
#-------------------------------------------------------------------------------
echo -e "${YELLOW}[3/6] Waiting for VM to be ready...${NC}"
sleep 20

# Wait for SSH to be available
for i in {1..20}; do
    if gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE" --command="echo 'SSH Ready'" 2>/dev/null; then
        echo -e "${GREEN}✓ SSH is ready!${NC}"
        break
    fi
    echo "  Waiting for SSH... (attempt $i/20)"
    sleep 10
done

#-------------------------------------------------------------------------------
# Wait for Docker setup to complete
#-------------------------------------------------------------------------------
echo -e "${YELLOW}[4/6] Waiting for Docker installation...${NC}"
for i in {1..30}; do
    if gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE" --command="test -f /tmp/setup-complete" 2>/dev/null; then
        echo -e "${GREEN}✓ Docker setup complete!${NC}"
        break
    fi
    echo "  Setup in progress... (attempt $i/30)"
    sleep 15
done

#-------------------------------------------------------------------------------
# Clone repository
#-------------------------------------------------------------------------------
echo -e "${YELLOW}[5/6] Cloning repository...${NC}"
gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE" --command="
    sudo mkdir -p /opt/freqtrade
    cd /opt/freqtrade
    sudo git clone ${GIT_REPO} . 2>/dev/null || sudo git pull origin ${GIT_BRANCH}
    sudo chown -R root:root /opt/freqtrade
    echo 'Repository ready at /opt/freqtrade'
"
echo -e "${GREEN}✓ Repository cloned!${NC}"

#-------------------------------------------------------------------------------
# Make scripts executable
#-------------------------------------------------------------------------------
echo -e "${YELLOW}[6/6] Setting up scripts...${NC}"
gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE" --command="
    cd /opt/freqtrade
    sudo chmod +x *.sh 2>/dev/null || true
    echo 'Scripts ready!'
"
echo -e "${GREEN}✓ Scripts ready!${NC}"

#-------------------------------------------------------------------------------
# Summary
#-------------------------------------------------------------------------------
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  ✓ VM Setup Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${BLUE}Quick Commands:${NC}"
echo ""
echo -e "  ${YELLOW}Connect to VM:${NC}"
echo "  gcloud compute ssh ${INSTANCE_NAME} --zone=${ZONE}"
echo ""
echo -e "  ${YELLOW}Run Hyperopt:${NC}"
echo "  gcloud compute ssh ${INSTANCE_NAME} --zone=${ZONE} --command='cd /opt/freqtrade && sudo ./run-hyperopt.sh'"
echo ""
echo -e "  ${YELLOW}Update & Run:${NC}"
echo "  gcloud compute ssh ${INSTANCE_NAME} --zone=${ZONE} --command='cd /opt/freqtrade && sudo ./update-and-run.sh'"
echo ""
echo -e "  ${YELLOW}Stop VM (saves costs):${NC}"
echo "  gcloud compute instances stop ${INSTANCE_NAME} --zone=${ZONE}"
echo ""
echo -e "  ${YELLOW}Start VM again:${NC}"
echo "  gcloud compute instances start ${INSTANCE_NAME} --zone=${ZONE}"
echo ""
echo -e "  ${YELLOW}Delete VM:${NC}"
echo "  gcloud compute instances delete ${INSTANCE_NAME} --zone=${ZONE}"
echo ""
echo -e "  ${YELLOW}View setup logs:${NC}"
echo "  gcloud compute ssh ${INSTANCE_NAME} --zone=${ZONE} --command='cat /var/log/freqtrade-setup.log'"
echo ""
