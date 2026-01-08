#!/bin/bash
#===============================================================================
# GCloud VM Manager for Freqtrade
# 
# Quick commands to manage your Spot VM
#
# Usage:
#   ./gcloud-manage-vm.sh [command] [options]
#
# Commands:
#   ssh      - Connect to VM
#   run      - Run hyperopt (supports passing hyperopt options)
#   update   - Pull latest code
#   start    - Start stopped VM
#   stop     - Stop VM (saves costs)
#   delete   - Delete VM
#   status   - Show VM status
#   logs     - View setup logs
#   copy     - Copy hyperopt results from VM
#
# Examples:
#   ./gcloud-manage-vm.sh run
#   ./gcloud-manage-vm.sh run --epochs 500 --strategy SekkaLong
#   ./gcloud-manage-vm.sh run --instance my-vm --zone us-west1-a --epochs 1000
#===============================================================================

# Default configuration
INSTANCE_NAME="hyperopt-vm"
ZONE="asia-southeast1-b"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Get the command
COMMAND="$1"
shift 2>/dev/null || true

# Parse --instance and --zone from remaining args, collect hyperopt args
HYPEROPT_ARGS=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --instance)
            INSTANCE_NAME="$2"
            shift 2
            ;;
        --zone)
            ZONE="$2"
            shift 2
            ;;
        *)
            # Collect all other args for hyperopt
            HYPEROPT_ARGS="$HYPEROPT_ARGS $1"
            shift
            ;;
    esac
done

show_help() {
    echo "GCloud VM Manager for Freqtrade"
    echo ""
    echo "Usage: ./gcloud-manage-vm.sh [command] [options]"
    echo ""
    echo "Commands:"
    echo "  ssh      Connect to VM"
    echo "  run      Run hyperopt (foreground)"
    echo "  run-bg   Run hyperopt in background"
    echo "  check    Check if hyperopt is running"
    echo "  output   View hyperopt output log"
    echo "  best     Show current best hyperopt results"
    echo "  kill     Stop running hyperopt"
    echo "  download Download market data on VM"
    echo "  update   Update code on VM"
    echo "  start    Start stopped VM"
    echo "  stop     Stop VM (saves costs)"
    echo "  delete   Delete VM"
    echo "  status   Show VM status"
    echo "  logs     View setup logs"
    echo "  copy     Copy hyperopt results from VM"
    echo ""
    echo "Global Options:"
    echo "  --instance NAME    VM instance name (default: freqtrade-hyperopt)"
    echo "  --zone ZONE        GCloud zone (default: asia-southeast1-b)"
    echo ""
    echo "Run Command Options (passed to run-hyperopt.sh):"
    echo "  --strategy, -s     Strategy name"
    echo "  --epochs, -e       Number of epochs"
    echo "  --timerange, -t    Time range"
    echo "  --spaces           Optimization spaces"
    echo "  --jobs, -j         Parallel jobs"
    echo ""
    echo "Examples:"
    echo "  ./gcloud-manage-vm.sh ssh"
    echo "  ./gcloud-manage-vm.sh run"
    echo "  ./gcloud-manage-vm.sh run --epochs 500"
    echo "  ./gcloud-manage-vm.sh download"
    echo "  ./gcloud-manage-vm.sh download --timeframes '1h 4h 1d'"
    echo "  ./gcloud-manage-vm.sh stop"
}

case "$COMMAND" in
    ssh)
        echo -e "${YELLOW}Connecting to ${INSTANCE_NAME}...${NC}"
        gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE"
        ;;
    
    run)
        echo -e "${YELLOW}Running hyperopt on ${INSTANCE_NAME}...${NC}"
        if [ -n "$HYPEROPT_ARGS" ]; then
            echo -e "Options: ${YELLOW}${HYPEROPT_ARGS}${NC}"
        fi
        gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE" -- \
            "cd /opt/freqtrade && sudo ./run-hyperopt.sh $HYPEROPT_ARGS"
        ;;
    
    run-bg)
        echo -e "${YELLOW}Starting hyperopt in background on ${INSTANCE_NAME}...${NC}"
        echo -e "${YELLOW}VM will auto-stop when hyperopt completes.${NC}"
        if [ -n "$HYPEROPT_ARGS" ]; then
            echo -e "Options: ${YELLOW}${HYPEROPT_ARGS}${NC}"
        fi
        # Use screen for reliable background execution that survives SSH disconnect
        gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE" -- "
            # Install screen if not present
            which screen > /dev/null || sudo apt-get install -y screen > /dev/null 2>&1
            # Kill any existing hyperopt screen session
            sudo screen -S hyperopt -X quit 2>/dev/null || true
            # Start new screen session
            cd /opt/freqtrade
            sudo screen -dmS hyperopt bash -c './run-hyperopt.sh --auto-stop $HYPEROPT_ARGS 2>&1 | tee /opt/freqtrade/hyperopt.log'
            sleep 2
            # Verify it started
            if sudo screen -list | grep -q hyperopt; then
                echo 'Screen session started successfully'
            else
                echo 'ERROR: Failed to start screen session'
            fi
        "
        echo -e "${GREEN}✓ Hyperopt started in background!${NC}"
        echo ""
        echo -e "Commands to monitor:"
        echo -e "  ${YELLOW}./gcloud-manage-vm.sh check${NC}   - Check if running"
        echo -e "  ${YELLOW}./gcloud-manage-vm.sh output${NC}  - View output log"
        echo -e "  ${YELLOW}./gcloud-manage-vm.sh status${NC}  - Check VM status"
        echo ""
        echo -e "${GREEN}Note: VM will automatically stop after hyperopt completes.${NC}"
        ;;
    
    check)
        echo -e "${YELLOW}Checking hyperopt status on ${INSTANCE_NAME}...${NC}"
        gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE" -- '
            echo "=== Docker Containers ==="
            docker ps 2>/dev/null || echo "Docker not running"
            echo ""
            echo "=== Hyperopt Script Process ==="
            PROC=$(pgrep -af "run-hyperopt" 2>/dev/null | grep -v grep || true)
            if [ -n "$PROC" ]; then
                echo "✓ run-hyperopt.sh is RUNNING"
                echo "$PROC"
            else
                echo "✗ run-hyperopt.sh is NOT running"
            fi
            echo ""
            echo "=== Log File ==="
            if [ -f /opt/freqtrade/hyperopt.log ]; then
                ls -la /opt/freqtrade/hyperopt.log
                echo ""
                echo "=== Last 10 Log Lines ==="
                tail -10 /opt/freqtrade/hyperopt.log
            else
                echo "No log file found"
            fi
        '
        ;;
    
    output)
        echo -e "${YELLOW}Last 50 lines of hyperopt log:${NC}"
        gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE" -- \
            "tail -50 /opt/freqtrade/hyperopt.log 2>/dev/null || echo 'No log file found'"
        ;;
    
    best)
        echo -e "${YELLOW}Current best hyperopt results on ${INSTANCE_NAME}:${NC}"
        gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE" -- '
            cd /opt/freqtrade
            docker compose run --rm freqtrade hyperopt-list --best -n 5 --config user_data/config-long.json 2>/dev/null
            echo ""
            echo "=== Best Parameters ==="
            docker compose run --rm freqtrade hyperopt-show --best --config user_data/config-long.json 2>/dev/null | tail -40
        '
        ;;
    
    kill)
        echo -e "${YELLOW}Stopping hyperopt on ${INSTANCE_NAME}...${NC}"
        gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE" -- '
            # Kill screen session
            sudo screen -S hyperopt -X quit 2>/dev/null || true
            # Stop all freqtrade containers
            docker stop $(docker ps -q --filter "ancestor=freqtradeorg/freqtrade:stable_plot") 2>/dev/null || true
            cd /opt/freqtrade
            docker compose down 2>/dev/null || true
            # Kill any remaining processes
            sudo pkill -f "run-hyperopt" 2>/dev/null || true
            echo "✓ Hyperopt stopped"
        '
        echo -e "${GREEN}✓ Hyperopt stopped!${NC}"
        ;;
    download)
        echo -e "${YELLOW}Downloading data on ${INSTANCE_NAME}...${NC}"
        if [ -n "$HYPEROPT_ARGS" ]; then
            echo -e "Options: ${YELLOW}${HYPEROPT_ARGS}${NC}"
        fi
        gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE" -- \
            "cd /opt/freqtrade && sudo ./download-data.sh $HYPEROPT_ARGS"
        ;;
    
    init)
        echo -e "${YELLOW}Initializing repository on ${INSTANCE_NAME}...${NC}"
        GIT_REPO="https://github.com/labanux/freq.git"
        gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE" -- "
            sudo rm -rf /opt/freqtrade
            sudo mkdir -p /opt/freqtrade
            cd /opt/freqtrade
            sudo git clone ${GIT_REPO} .
            sudo chmod +x *.sh 2>/dev/null || true
            echo 'Repository initialized!'
        "
        echo -e "${GREEN}✓ Repository cloned!${NC}"
        ;;
    
    update)
        echo -e "${YELLOW}Updating code on ${INSTANCE_NAME}...${NC}"
        gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE" -- \
            "cd /opt/freqtrade && sudo git fetch origin main && sudo git reset --hard origin/main && sudo chmod +x *.sh"
        echo -e "${GREEN}✓ Code updated!${NC}"
        ;;
    
    start)
        echo -e "${YELLOW}Starting ${INSTANCE_NAME}...${NC}"
        gcloud compute instances start "$INSTANCE_NAME" --zone="$ZONE"
        echo -e "${GREEN}✓ VM started!${NC}"
        ;;
    
    stop)
        echo -e "${YELLOW}Stopping ${INSTANCE_NAME}...${NC}"
        gcloud compute instances stop "$INSTANCE_NAME" --zone="$ZONE"
        echo -e "${GREEN}✓ VM stopped! (no charges while stopped)${NC}"
        ;;
    
    delete)
        echo -e "${RED}WARNING: This will permanently delete ${INSTANCE_NAME}!${NC}"
        read -p "Are you sure? (yes/no): " confirm
        if [ "$confirm" = "yes" ]; then
            gcloud compute instances delete "$INSTANCE_NAME" --zone="$ZONE"
            echo -e "${GREEN}✓ VM deleted!${NC}"
        else
            echo "Cancelled."
        fi
        ;;
    
    status)
        echo -e "${YELLOW}Status of ${INSTANCE_NAME}:${NC}"
        gcloud compute instances describe "$INSTANCE_NAME" --zone="$ZONE" \
            --format="table(name,status,machineType.basename(),scheduling.provisioningModel)"
        ;;
    
    logs)
        echo -e "${YELLOW}Setup logs from ${INSTANCE_NAME}:${NC}"
        gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE" -- \
            "cat /var/log/freqtrade-setup.log"
        ;;
    
    copy)
        echo -e "${YELLOW}Exporting best hyperopt result as JSON...${NC}"
        TIMESTAMP=$(date +%Y%m%d_%H%M%S)
        OUTPUT_FILE="hyperopt_result_${TIMESTAMP}.json"
        
        # Export best result as JSON on VM, then copy
        gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE" -- \
            "cd /opt/freqtrade && docker compose run --rm freqtrade hyperopt-show --best --export-json /freqtrade/user_data/${OUTPUT_FILE} --config user_data/config-long.json"
        
        # Copy the JSON file
        gcloud compute scp \
            "$INSTANCE_NAME:/opt/freqtrade/user_data/${OUTPUT_FILE}" \
            "./user_data/${OUTPUT_FILE}" \
            --zone="$ZONE"
        
        echo -e "${GREEN}✓ Result saved to ./user_data/${OUTPUT_FILE}${NC}"
        ;;
    
    *)
        show_help
        ;;
esac
