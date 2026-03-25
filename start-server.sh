#!/bin/bash
# Flask Price Alerter - Startup Script
# This script starts the Flask server on port 8081

echo "=========================================="
echo "Starting AI Price Alert Server"
echo "=========================================="

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Check if port 8081 is already in use
if lsof -i :8081 > /dev/null 2>&1; then
    echo "⚠️  Port 8081 is already in use!"
    echo "   Trying to find the process..."
    PID=$(lsof -t -i :8081)
    echo "   Process ID: $PID"
    read -p "   Kill this process and restart? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        kill $PID 2>/dev/null
        echo "   Process killed. Starting fresh..."
        sleep 1
    else
        echo "   Aborting. Server might already be running."
        exit 1
    fi
fi

# Initialize database
echo "📦 Initializing database..."
python3 -c "from app import init_db; init_db()" 2>/dev/null

# Start the server
echo "🚀 Starting server on http://localhost:8081"
echo ""
echo "Available routes:"
echo "  /signup     - Sign up for an account"
echo "  /login      - Login to your account"
echo "  /dashboard  - View your price trackers"
echo ""
echo "Press Ctrl+C to stop the server"
echo "=========================================="

# Start Flask server
python3 app.py

