#!/bin/bash
# Get Your Public IP Address for Render Whitelisting
#
# This script helps you find your public IP address to whitelist in Render

echo "=========================================="
echo "Finding Your Public IP Address"
echo "=========================================="
echo ""

# Try multiple methods to get public IP
IP=""

# Method 1: ipify
if command -v curl &> /dev/null; then
    IP=$(curl -s https://api.ipify.org 2>/dev/null)
    if [ -n "$IP" ] && [ "$IP" != "Could not determine IP" ]; then
        echo "✅ Found via ipify: $IP"
        echo ""
        echo "Add this IP to Render Database Whitelist:"
        echo "  1. Go to: https://dashboard.render.com"
        echo "  2. Navigate to: shopify-analytics-db"
        echo "  3. Go to: Network Access (or Connections)"
        echo "  4. Add IP: $IP"
        echo ""
        exit 0
    fi
fi

# Method 2: ifconfig.me
if command -v curl &> /dev/null; then
    IP=$(curl -s https://ifconfig.me 2>/dev/null)
    if [ -n "$IP" ] && [[ "$IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo "✅ Found via ifconfig.me: $IP"
        echo ""
        echo "Add this IP to Render Database Whitelist:"
        echo "  1. Go to: https://dashboard.render.com"
        echo "  2. Navigate to: shopify-analytics-db"
        echo "  3. Go to: Network Access (or Connections)"
        echo "  4. Add IP: $IP"
        echo ""
        exit 0
    fi
fi

# Method 3: icanhazip
if command -v curl &> /dev/null; then
    IP=$(curl -s https://icanhazip.com 2>/dev/null)
    if [ -n "$IP" ] && [[ "$IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo "✅ Found via icanhazip: $IP"
        echo ""
        echo "Add this IP to Render Database Whitelist:"
        echo "  1. Go to: https://dashboard.render.com"
        echo "  2. Navigate to: shopify-analytics-db"
        echo "  3. Go to: Network Access (or Connections)"
        echo "  4. Add IP: $IP"
        echo ""
        exit 0
    fi
fi

# Method 4: DNS lookup
if command -v dig &> /dev/null; then
    IP=$(dig +short myip.opendns.com @resolver1.opendns.com 2>/dev/null)
    if [ -n "$IP" ] && [[ "$IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo "✅ Found via DNS: $IP"
        echo ""
        echo "Add this IP to Render Database Whitelist:"
        echo "  1. Go to: https://dashboard.render.com"
        echo "  2. Navigate to: shopify-analytics-db"
        echo "  3. Go to: Network Access (or Connections)"
        echo "  4. Add IP: $IP"
        echo ""
        exit 0
    fi
fi

# If all methods failed
echo "⚠️  Could not automatically determine your IP address"
echo ""
echo "Manual Methods:"
echo ""
echo "Option 1: Visit in browser:"
echo "  https://api.ipify.org"
echo "  https://ifconfig.me"
echo "  https://icanhazip.com"
echo ""
echo "Option 2: Use command:"
echo "  curl https://api.ipify.org"
echo ""
echo "Option 3: Check your router/admin panel"
echo ""
echo "Once you have your IP, add it to Render:"
echo "  1. Go to: https://dashboard.render.com"
echo "  2. Navigate to: shopify-analytics-db"
echo "  3. Go to: Network Access (or Connections)"
echo "  4. Add your IP address"
echo ""
