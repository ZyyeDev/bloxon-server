#!/bin/bash

echo "=== Game Master Server Deployment ==="

# is this bad? TODO: Please rethink this
# nah i dont think it is bad
git fetch origin main
git reset --hard origin/main

echo "Starting Xvfb display server..."
Xvfb :99 -screen 0 1024x768x24 +extension GLX &
XVFB_PID=$!
export DISPLAY=:99

sleep 2

source .env

echo "Starting Python server..."
python3 main.py

kill $XVFB_PID 2>/dev/null
