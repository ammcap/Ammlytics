# app.py

from flask import Flask, jsonify, send_from_directory, request
from web3 import Web3
from decimal import Decimal
import os

# Import your liquidity_positions.py functions
# --- THIS SECTION IS UPDATED ---
from liquidity_positions import (
    find_and_display_positions, RPC_URL,
    NFT_MANAGER_CONTRACT, VOTER_CONTRACT,
    KNOWN_POOLS, KNOWN_TOKENS, NFT_MANAGER_ABI, POOL_ABI,
    VOTER_ABI, GAUGE_V3_ABI, ERC20_ABI, # <-- CACHE_FILENAME removed
    # load_cache, save_cache have been removed as they are no longer used
    get_position_creation_info,
    format_amount, get_token_info,
    tick_to_price, calculate_token_amounts, get_pool_info,
    get_emissions_rewards, calculate_il_percentage, format_timedelta
)

app = Flask(__name__)

# Helper to convert Decimal objects to strings for JSON serialization
def convert_decimals_to_str(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/style.css')
def style_css():
    return send_from_directory('.', 'style.css')

@app.route('/script.js')
def script_js():
    return send_from_directory('.', 'script.js')

@app.route('/api/data')
def get_data():
    wallet_address = request.args.get('wallet_address')
    if not wallet_address:
        return jsonify({"error": "Wallet address is required."}), 400

    try:
        # The Web3 instance is already created in liquidity_positions.py
        # You can call the main function directly.
        data = find_and_display_positions(wallet_address)
        return jsonify(data), 200, {'Content-Type': 'application/json'}
    except Exception as e:
        return jsonify({"error": f"An unexpected error occurred: {e}"}), 500

if __name__ == '__main__':
    app.run()