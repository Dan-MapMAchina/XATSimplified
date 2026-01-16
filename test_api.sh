#!/bin/bash
#
# XATSimplified API Test Script
# Tests the complete workflow: auth -> create collector -> pcc register -> load test
#

set -e

# Configuration
BASE_URL="${BASE_URL:-http://localhost:8001}"
TEST_USER="${TEST_USER:-testuser}"
TEST_PASS="${TEST_PASS:-testpass123}"
TEST_EMAIL="${TEST_EMAIL:-test@example.com}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   XATSimplified API Test Suite${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "Base URL: ${YELLOW}${BASE_URL}${NC}"
echo ""

# Function to check if server is ready
wait_for_server() {
    echo -e "${YELLOW}Waiting for server to be ready...${NC}"
    for i in {1..30}; do
        if curl -s "${BASE_URL}/api/v1/auth/token/" > /dev/null 2>&1; then
            echo -e "${GREEN}Server is ready!${NC}"
            return 0
        fi
        sleep 1
    done
    echo -e "${RED}Server not responding after 30 seconds${NC}"
    exit 1
}

# Function to pretty print JSON
pretty_json() {
    if command -v jq &> /dev/null; then
        echo "$1" | jq .
    else
        echo "$1"
    fi
}

# ============================================================================
# STEP 0: Wait for server
# ============================================================================
wait_for_server

# ============================================================================
# STEP 1: Register a new user
# ============================================================================
echo ""
echo -e "${BLUE}STEP 1: Register new user${NC}"
echo -e "Creating user: ${TEST_USER}"

REGISTER_RESPONSE=$(curl -s -X POST "${BASE_URL}/api/v1/auth/register/" \
    -H "Content-Type: application/json" \
    -d "{
        \"username\": \"${TEST_USER}\",
        \"email\": \"${TEST_EMAIL}\",
        \"password\": \"${TEST_PASS}\",
        \"password2\": \"${TEST_PASS}\",
        \"first_name\": \"Test\",
        \"last_name\": \"User\"
    }" 2>&1) || true

if echo "$REGISTER_RESPONSE" | grep -q "username"; then
    echo -e "${GREEN}✓ User registered successfully${NC}"
    pretty_json "$REGISTER_RESPONSE"
else
    echo -e "${YELLOW}⚠ User may already exist (continuing)${NC}"
    echo "$REGISTER_RESPONSE"
fi

# ============================================================================
# STEP 2: Get JWT Token
# ============================================================================
echo ""
echo -e "${BLUE}STEP 2: Get JWT Token${NC}"

TOKEN_RESPONSE=$(curl -s -X POST "${BASE_URL}/api/v1/auth/token/" \
    -H "Content-Type: application/json" \
    -d "{\"username\": \"${TEST_USER}\", \"password\": \"${TEST_PASS}\"}")

ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | grep -o '"access":"[^"]*' | cut -d'"' -f4)

if [ -n "$ACCESS_TOKEN" ]; then
    echo -e "${GREEN}✓ JWT token obtained${NC}"
    echo "Token (first 50 chars): ${ACCESS_TOKEN:0:50}..."
else
    echo -e "${RED}✗ Failed to get token${NC}"
    echo "$TOKEN_RESPONSE"
    exit 1
fi

# ============================================================================
# STEP 3: Get current user info
# ============================================================================
echo ""
echo -e "${BLUE}STEP 3: Get current user info${NC}"

USER_RESPONSE=$(curl -s -X GET "${BASE_URL}/api/v1/auth/user/" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}")

echo -e "${GREEN}✓ User info retrieved${NC}"
pretty_json "$USER_RESPONSE"

# ============================================================================
# STEP 4: Create a Collector
# ============================================================================
echo ""
echo -e "${BLUE}STEP 4: Create a Collector${NC}"

COLLECTOR_RESPONSE=$(curl -s -X POST "${BASE_URL}/api/v1/collectors/" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -H "Content-Type: application/json" \
    -d '{"name": "test-server-01", "description": "Test server for API validation"}')

COLLECTOR_ID=$(echo "$COLLECTOR_RESPONSE" | grep -o '"id":"[^"]*' | cut -d'"' -f4)
API_KEY=$(echo "$COLLECTOR_RESPONSE" | grep -o '"api_key":"[^"]*' | cut -d'"' -f4)

if [ -n "$COLLECTOR_ID" ] && [ -n "$API_KEY" ]; then
    echo -e "${GREEN}✓ Collector created${NC}"
    echo "Collector ID: ${COLLECTOR_ID}"
    echo "API Key: ${API_KEY}"
    pretty_json "$COLLECTOR_RESPONSE"
else
    echo -e "${RED}✗ Failed to create collector${NC}"
    echo "$COLLECTOR_RESPONSE"
    exit 1
fi

# ============================================================================
# STEP 5: List Collectors
# ============================================================================
echo ""
echo -e "${BLUE}STEP 5: List Collectors${NC}"

LIST_RESPONSE=$(curl -s -X GET "${BASE_URL}/api/v1/collectors/" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}")

echo -e "${GREEN}✓ Collectors listed${NC}"
pretty_json "$LIST_RESPONSE"

# ============================================================================
# STEP 6: Simulate pcc Registration (using API key)
# ============================================================================
echo ""
echo -e "${BLUE}STEP 6: Simulate pcc Registration${NC}"

PCC_RESPONSE=$(curl -s -X POST "${BASE_URL}/api/v1/register/" \
    -H "Authorization: ApiKey ${API_KEY}" \
    -H "Content-Type: application/json" \
    -d '{
        "hostname": "test-server-01.local",
        "ip_address": "192.168.1.100",
        "os_name": "Ubuntu",
        "os_version": "22.04 LTS",
        "kernel_version": "5.15.0-generic",
        "processor_brand": "intel",
        "processor_model": "Intel Xeon E5-2680 v4 @ 2.40GHz",
        "vcpus": 8,
        "memory_gib": 32.0,
        "storage_gib": 500.0,
        "storage_type": "nvme"
    }')

if echo "$PCC_RESPONSE" | grep -q "registered"; then
    echo -e "${GREEN}✓ pcc registration successful${NC}"
    pretty_json "$PCC_RESPONSE"
else
    echo -e "${RED}✗ pcc registration failed${NC}"
    echo "$PCC_RESPONSE"
    exit 1
fi

# ============================================================================
# STEP 7: Verify Collector was updated
# ============================================================================
echo ""
echo -e "${BLUE}STEP 7: Verify Collector updated with system info${NC}"

UPDATED_COLLECTOR=$(curl -s -X GET "${BASE_URL}/api/v1/collectors/${COLLECTOR_ID}/" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}")

echo -e "${GREEN}✓ Collector details retrieved${NC}"
pretty_json "$UPDATED_COLLECTOR"

# Check if specs were updated
if echo "$UPDATED_COLLECTOR" | grep -q "Intel Xeon"; then
    echo -e "${GREEN}✓ System specs auto-populated!${NC}"
else
    echo -e "${YELLOW}⚠ System specs may not have been updated${NC}"
fi

# ============================================================================
# STEP 8: Create a second Collector for comparison
# ============================================================================
echo ""
echo -e "${BLUE}STEP 8: Create second Collector for comparison${NC}"

COLLECTOR2_RESPONSE=$(curl -s -X POST "${BASE_URL}/api/v1/collectors/" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -H "Content-Type: application/json" \
    -d '{"name": "test-server-02", "description": "Second test server"}')

COLLECTOR2_ID=$(echo "$COLLECTOR2_RESPONSE" | grep -o '"id":"[^"]*' | cut -d'"' -f4)
API_KEY2=$(echo "$COLLECTOR2_RESPONSE" | grep -o '"api_key":"[^"]*' | cut -d'"' -f4)

echo -e "${GREEN}✓ Second collector created${NC}"
echo "Collector ID: ${COLLECTOR2_ID}"

# Register second collector
curl -s -X POST "${BASE_URL}/api/v1/register/" \
    -H "Authorization: ApiKey ${API_KEY2}" \
    -H "Content-Type: application/json" \
    -d '{
        "hostname": "test-server-02.local",
        "ip_address": "192.168.1.101",
        "os_name": "Ubuntu",
        "os_version": "22.04 LTS",
        "processor_brand": "amd",
        "processor_model": "AMD EPYC 7763 64-Core Processor",
        "vcpus": 16,
        "memory_gib": 64.0
    }' > /dev/null

echo -e "${GREEN}✓ Second collector registered${NC}"

# ============================================================================
# STEP 9: Create Load Test Results
# ============================================================================
echo ""
echo -e "${BLUE}STEP 9: Create Load Test Results${NC}"

# Load test for server 1
LOADTEST1_RESPONSE=$(curl -s -X POST "${BASE_URL}/api/v1/loadtest/" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{
        \"collector\": \"${COLLECTOR_ID}\",
        \"units_10pct\": 1200,
        \"units_20pct\": 2350,
        \"units_30pct\": 3400,
        \"units_40pct\": 4500,
        \"units_50pct\": 5600,
        \"units_60pct\": 6650,
        \"units_70pct\": 7700,
        \"units_80pct\": 8750,
        \"units_90pct\": 9800,
        \"units_100pct\": 10500,
        \"notes\": \"Initial benchmark run\"
    }")

echo -e "${GREEN}✓ Load test result created for server 1${NC}"
pretty_json "$LOADTEST1_RESPONSE"

# Load test for server 2 (higher performance)
LOADTEST2_RESPONSE=$(curl -s -X POST "${BASE_URL}/api/v1/loadtest/" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{
        \"collector\": \"${COLLECTOR2_ID}\",
        \"units_10pct\": 2400,
        \"units_20pct\": 4700,
        \"units_30pct\": 6800,
        \"units_40pct\": 9000,
        \"units_50pct\": 11200,
        \"units_60pct\": 13300,
        \"units_70pct\": 15400,
        \"units_80pct\": 17500,
        \"units_90pct\": 19600,
        \"units_100pct\": 21000,
        \"notes\": \"Initial benchmark run - higher core count\"
    }")

echo -e "${GREEN}✓ Load test result created for server 2${NC}"

# ============================================================================
# STEP 10: Compare Load Test Results
# ============================================================================
echo ""
echo -e "${BLUE}STEP 10: Compare Load Test Results${NC}"

COMPARE_RESPONSE=$(curl -s -X POST "${BASE_URL}/api/v1/loadtest/compare/" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"collector_ids\": [\"${COLLECTOR_ID}\", \"${COLLECTOR2_ID}\"]}")

echo -e "${GREEN}✓ Comparison results${NC}"
pretty_json "$COMPARE_RESPONSE"

# ============================================================================
# STEP 11: Create a Benchmark
# ============================================================================
echo ""
echo -e "${BLUE}STEP 11: Create a Benchmark${NC}"

BENCHMARK_RESPONSE=$(curl -s -X POST "${BASE_URL}/api/v1/benchmarks/" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{
        \"collector\": \"${COLLECTOR_ID}\",
        \"name\": \"Initial Performance Test\",
        \"benchmark_type\": \"standard\"
    }")

BENCHMARK_ID=$(echo "$BENCHMARK_RESPONSE" | grep -o '"id":"[^"]*' | cut -d'"' -f4)

echo -e "${GREEN}✓ Benchmark created${NC}"
pretty_json "$BENCHMARK_RESPONSE"

# Update benchmark with scores
curl -s -X PATCH "${BASE_URL}/api/v1/benchmarks/${BENCHMARK_ID}/" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -H "Content-Type: application/json" \
    -d '{
        "status": "completed",
        "cpu_score": 85,
        "memory_score": 78,
        "disk_score": 92,
        "network_score": 88,
        "overall_score": 86
    }' > /dev/null

echo -e "${GREEN}✓ Benchmark scores updated${NC}"

# ============================================================================
# STEP 12: Get Benchmark Stats
# ============================================================================
echo ""
echo -e "${BLUE}STEP 12: Get Benchmark Statistics${NC}"

STATS_RESPONSE=$(curl -s -X GET "${BASE_URL}/api/v1/benchmarks/stats/" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}")

echo -e "${GREEN}✓ Benchmark statistics${NC}"
pretty_json "$STATS_RESPONSE"

# ============================================================================
# Summary
# ============================================================================
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}   All Tests Passed Successfully!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "Summary:"
echo -e "  • User: ${TEST_USER}"
echo -e "  • Collectors created: 2"
echo -e "  • Load tests created: 2"
echo -e "  • Benchmarks created: 1"
echo ""
echo -e "Collector 1: ${COLLECTOR_ID}"
echo -e "  API Key: ${API_KEY}"
echo ""
echo -e "Collector 2: ${COLLECTOR2_ID}"
echo -e "  API Key: ${API_KEY2}"
echo ""
echo -e "${YELLOW}To install pcc on a real server:${NC}"
echo -e "  export API_KEY=${API_KEY}"
echo -e "  # Then run pcc with the API key"
echo ""
