#!/usr/bin/env python3
"""
Shadow DEX Position Tracker with Accurate Reward and Balance Calculation.

This script provides a comprehensive view of concentrated liquidity positions on
Shadow DEX. It now includes tracking for the initial state of each position
(balances and price at creation) by using a local JSON file for caching,
which makes subsequent runs much faster.

This updated version includes:
- Impermanent Loss (IL) calculation: Projects the IL in USD and percentage
  terms if the price reaches the upper or lower bound of the position.
- Days to Breakeven: Estimates the time required for fee rewards (at the
  current APR) to offset the projected impermanent loss.
- Breakeven Analysis: Shows time elapsed, time remaining to breakeven, and
  the dollar difference between accrued fees and projected IL.
- Hybrid V2/V3 pool price fetching for Shadow DEX

Features:
- All active positions for a given wallet.
- Current and initial underlying token balances for each position.
- Current and initial USD value and price of the position.
- Accurately fetched emission rewards (xSHADOW, etc.).
- The creation date of each position.
- Projected Impermanent Loss and time to breakeven.
"""

from dotenv import load_dotenv
load_dotenv()
import json
from web3 import Web3
import requests
from decimal import Decimal, getcontext
from datetime import datetime, timedelta # Import timedelta
import traceback
import os # Import os for environment variable
import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in the environment")
engine = create_engine(DATABASE_URL)

# Set precision for Decimal calculations
getcontext().prec = 50

# --- CONFIGURATION ---
# Sonic RPC endpoint
RPC_URL = os.environ.get("RPC_URL", "https://rpc.soniclabs.com") # Get from env or fallback
# File to cache initial position data
DATABASE_FILENAME = "positions.db" # <-- REPLACE CACHE_FILENAME
CACHE_FILENAME = "position_initial_data.json"
# Time in seconds to cache prices (e.g., 5 minutes = 300 seconds)
PRICE_CACHE_DURATION = 60 # 1 minute TTL for pool prices
# Global in-memory cache for prices
_price_cache = {}
_price_cache_timestamp = datetime.min


# --- WEB3 SETUP ---
web3 = Web3(Web3.HTTPProvider(RPC_URL))

# --- CONTRACT ADDRESSES ---
NFT_MANAGER_CONTRACT = "0x12E66C8F215DdD5d48d150c8f46aD0c6fB0F4406"
VOTER_CONTRACT = "0x9f59398d0a397b2eeb8a6123a6c7295cb0b0062d"

# --- SHADOW DEX POOL ADDRESSES ---
SHADOW_USDC_POOL = "0xAca297ecC8cbAF15Bd78Cd0757Ee93D6ef82c6b7"  # V2 style pool
WBTC_USDC_POOL = "0x8BC2f9e725cbB07c338df4e77c82190119ddd823"     # V3 style pool

# --- KNOWN ADDRESSES FOR EFFICIENCY ---
# Known pool addresses to avoid extra lookups
KNOWN_POOLS = {
    ('0x0555E30da8f98308EdB960aa94C0Db47230d2B9c', '0x29219dd400f2Bf60E5a23d13Be72B486D4038894'): WBTC_USDC_POOL, # WBTC/USDC
    ('0x3333b97138D4b086720b5aE8A7844b1345a33333', '0x29219dd400f2Bf60E5a23d13Be72B486D4038894'): SHADOW_USDC_POOL # SHADOW/USDC
}

# Known token information to reduce RPC calls
KNOWN_TOKENS = {
    '0x0555E30da8f98308EdB960aa94C0Db47230d2B9c': {'symbol': 'WBTC', 'decimals': 8},
    '0x29219dd400f2Bf60E5a23d13Be72B486D4038894': {'symbol': 'USDC', 'decimals': 6},
    '0x3333b97138D4b086720b5aE8A7844b1345a33333': {'symbol': 'SHADOW', 'decimals': 18},
    '0x5050bc082FF4A74Fb6B0B04385dEfdDB114b2424': {'symbol': 'xSHADOW', 'decimals': 18}, # xSHADOW price is tracked via SHADOW
}

# --- ABIs ---
NFT_MANAGER_ABI = [{"inputs":[],"name":"name","outputs":[{"internalType":"string","name":"","type":"string"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"address","name":"owner","type":"address"}],"name":"balanceOf","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"address","name":"owner","type":"address"},{"internalType":"uint256","name":"index","type":"uint256"}],"name":"tokenOfOwnerByIndex","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"uint256","name":"tokenId","type":"uint256"}],"name":"positions","outputs":[{"internalType":"address","name":"token0","type":"address"},{"internalType":"address","name":"token1","type":"address"},{"internalType":"int24","name":"tickSpacing","type":"int24"},{"internalType":"int24","name":"tickLower","type":"int24"},{"internalType":"int24","name":"tickUpper","type":"int24"},{"internalType":"uint128","name":"liquidity","type":"uint128"},{"internalType":"uint256","name":"feeGrowthInside0LastX128","type":"uint256"},{"internalType":"uint256","name":"feeGrowthInside1LastX128","type":"uint256"},{"internalType":"uint128","name":"tokensOwed0","type":"uint128"},{"internalType":"uint128","name":"tokensOwed1","type":"uint128"}],"stateMutability":"view","type":"function"},{"anonymous":False,"inputs":[{"indexed":True,"internalType":"address","name":"from","type":"address"},{"indexed":True,"internalType":"address","name":"to","type":"address"},{"indexed":True,"internalType":"uint256","name":"tokenId","type":"uint256"}],"name":"Transfer","type":"event"}]

# V3 Pool ABI (for concentrated liquidity pools like WBTC/USDC)
POOL_V3_ABI = [
    {"inputs":[],"name":"slot0","outputs":[{"internalType":"uint160","name":"sqrtPriceX96","type":"uint160"},{"internalType":"int24","name":"tick","type":"int24"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"token0","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"token1","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"fee","outputs":[{"internalType":"uint24","name":"","type":"uint24"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"feeGrowthGlobal0X128","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"feeGrowthGlobal1X128","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"internalType":"int24","name":"tick","type":"int24"}],"name":"ticks","outputs":[{"internalType":"uint256","name":"feeGrowthOutside0X128","type":"uint256"},{"internalType":"uint256","name":"feeGrowthOutside1X128","type":"uint256"}],"stateMutability":"view","type":"function"}
]

# V2 Pool ABI (for standard AMM pools like SHADOW/USDC)
POOL_V2_ABI = [
    {"inputs":[],"name":"getReserves","outputs":[{"type":"uint112","name":"reserve0"},{"type":"uint112","name":"reserve1"},{"type":"uint32","name":"blockTimestampLast"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"token0","outputs":[{"type":"address","name":""}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"token1","outputs":[{"type":"address","name":""}],"stateMutability":"view","type":"function"}
]

# Use V3 ABI for the main POOL_ABI (for concentrated liquidity positions)
POOL_ABI = POOL_V3_ABI

VOTER_ABI = [{"inputs":[{"internalType":"address","name":"pool","type":"address"}],"name":"gaugeForPool","outputs":[{"internalType":"address","name":"gauge","type":"address"}],"stateMutability":"view","type":"function"}]
GAUGE_V3_ABI = [{"inputs":[],"name":"getRewardTokens","outputs":[{"internalType":"address[]","name":"","type":"address[]"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"address","name":"token","type":"address"},{"internalType":"uint256","name":"tokenId","type":"uint256"}],"name":"earned","outputs":[{"internalType":"uint256","name":"reward","type":"uint256"}],"stateMutability":"view","type":"function"}]
ERC20_ABI = [{"inputs":[],"name":"symbol","outputs":[{"internalType":"string","name":"","type":"string"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"decimals","outputs":[{"internalType":"uint8","name":"","type":"uint8"}],"stateMutability":"view","type":"function"}]


# --- CACHE FUNCTIONS ---
# def load_cache():
#     """Loads the initial position data cache from a JSON file."""
#     try:
#         with open(CACHE_FILENAME, 'r') as f:
#             return json.load(f)
#     except (FileNotFoundError, json.JSONDecodeError):
#         return {}

# def save_cache(data):
#     """Saves the cache data to a JSON file."""
#     with open(CACHE_FILENAME, 'w') as f:
#         json.dump(data, f, indent=4)

# ADD THESE NEW FUNCTIONS to liquidity_positions.py

def db_load_initial_positions():
    """Loads all initial position data from the PostgreSQL database."""
    initial_data = {}
    select_sql = text("SELECT * FROM initial_positions")
    try:
        with engine.connect() as conn:
            rows = conn.execute(select_sql).fetchall()
            for row in rows:
                token_id, date, block, amount0, amount1, price = row
                initial_data[token_id] = {
                    'date': date, 'block': block, 'amount0': int(amount0),
                    'amount1': int(amount1), 'price': price
                }
    except Exception as e:
        print(f"Database error while loading positions: {e}")
    return initial_data

def db_save_initial_position(token_id, data):
    """Saves a single position to PostgreSQL. If it exists, it's updated."""
    upsert_sql = text("""
        INSERT INTO initial_positions (token_id, creation_date, block_number, amount0, amount1, price)
        VALUES (:token_id, :date, :block, :amount0, :amount1, :price)
        ON CONFLICT (token_id) DO UPDATE SET
            creation_date = EXCLUDED.creation_date,
            block_number = EXCLUDED.block_number,
            amount0 = EXCLUDED.amount0,
            amount1 = EXCLUDED.amount1,
            price = EXCLUDED.price;
    """)
    try:
        with engine.connect() as conn:
            conn.execute(upsert_sql, {
                "token_id": token_id, "date": data['date'], "block": data['block'],
                "amount0": str(data['amount0']), "amount1": str(data['amount1']),
                "price": data['price']
            })
            conn.commit()
    except Exception as e:
        print(f"Database error while saving position {token_id}: {e}")

# --- HELPER FUNCTIONS ---

def get_position_creation_info(web3, nft_address, token_id, owner_address):
    """
    Fetches the creation block and timestamp for a given NFT position (token_id)
    by looking for the ERC721 Transfer event from the zero address to the owner.
    This method is adapted from app.py for more efficient log fetching.
    """
    print(f"   Fetching creation info for token ID: {token_id} from manager {nft_address}")

    try:
        latest_block = web3.eth.block_number
        # Query the last 2,000,000 blocks. This is a heuristic to avoid full chain scans
        # that might timeout on public RPCs, while being broad enough for recent positions.
        from_block = max(0, latest_block - 2000000)

        # FIX: Hardcode the event signature hash to ensure correct formatting with a 0x prefix.
        event_signature_hash = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        zero_address_padded = '0x0000000000000000000000000000000000000000000000000000000000000000'
        owner_address_padded = '0x' + owner_address[2:].lower().zfill(64)
        token_id_padded = '0x' + hex(token_id)[2:].zfill(64)

        mint_filter_params = {
            'fromBlock': hex(from_block),
            'toBlock': 'latest',
            'address': web3.to_checksum_address(nft_address),
            'topics': [
                event_signature_hash,
                zero_address_padded,
                owner_address_padded, # Use specific owner address instead of wildcard
                token_id_padded
            ]
        }

        # LOGGING: Added detailed logging to show the exact filter being sent to the RPC node.
        print(f"   [DEBUG] Filter parameters for get_logs call:\n{json.dumps(mint_filter_params, indent=4)}")

        logs = web3.eth.get_logs(mint_filter_params)

        if not logs:
            print(f"   No creation event found for token ID {token_id} within the last {latest_block - from_block:,} blocks.")
            return None

        # The first log found is assumed to be the mint event.
        mint_event = logs[0]

        if mint_event.get('transactionHash') is None or mint_event.get('blockNumber') is None:
            print(f"   Event data incomplete for token ID {token_id}.")
            return None

        block_number = mint_event['blockNumber']
        block_info = web3.eth.get_block(block_number)
        timestamp = block_info['timestamp']

        print(f"   Found creation event in block {block_number} at timestamp {timestamp}")
        return {'block_number': block_number, 'timestamp': timestamp}

    except Exception as e:
        # LOGGING: Added more detailed error logging
        print(f"   [ERROR] An exception occurred in get_position_creation_info for token {token_id}:")
        print(f"   - Exception Type: {type(e).__name__}")
        print(f"   - Exception Details: {e}")
        return None

def format_amount(amount, decimals):
    """Formats a raw token amount into a human-readable string."""
    if amount == 0: return "0"
    adjusted = Decimal(amount) / Decimal(10 ** decimals)
    if adjusted == 0: return "0"
    if adjusted < 0.0001: return f"{adjusted:.8f}"
    if adjusted < 1: return f"{adjusted:.4f}"
    return f"{adjusted:,.2f}"

def calculate_price_from_sqrt_price_x96(sqrt_price_x96, token0_decimals, token1_decimals):
    """Convert sqrtPriceX96 to actual token price"""
    Q96 = Decimal(2**96)
    price_ratio = (Decimal(sqrt_price_x96) / Q96) ** 2
    decimal_adjustment = (Decimal(10) ** token0_decimals) / (Decimal(10) ** token1_decimals)
    adjusted_price = price_ratio * decimal_adjustment
    return adjusted_price

def get_token_info(token_address, cache):
    """Gets token symbol and decimals, using a cache to avoid redundant calls."""
    checksum_address = web3.to_checksum_address(token_address)
    if checksum_address in cache: return cache[checksum_address]
    if checksum_address in KNOWN_TOKENS:
        cache[checksum_address] = KNOWN_TOKENS[checksum_address]
        return cache[checksum_address]

    token_contract = web3.eth.contract(address=checksum_address, abi=ERC20_ABI)
    try: symbol = token_contract.functions.symbol().call()
    except Exception: symbol = f"Unknown ({checksum_address[:6]}...)"
    try: decimals = token_contract.functions.decimals().call()
    except Exception: decimals = 18
    info = {'symbol': symbol, 'decimals': decimals}
    cache[checksum_address] = info
    return info

def get_v3_pool_price(pool_address):
    """Get price from V3-style concentrated liquidity pool"""
    try:
        pool_contract = web3.eth.contract(address=web3.to_checksum_address(pool_address), abi=POOL_V3_ABI)
        slot0 = pool_contract.functions.slot0().call()
        sqrt_price_x96 = slot0[0]

        token0_address = pool_contract.functions.token0().call()
        token1_address = pool_contract.functions.token1().call()

        token_info_cache = {}
        token0_info = get_token_info(token0_address, token_info_cache)
        token1_info = get_token_info(token1_address, token_info_cache)

        price = calculate_price_from_sqrt_price_x96(sqrt_price_x96, token0_info['decimals'], token1_info['decimals'])

        # Determine USD price based on which token is USDC
        if token1_info['symbol'] in ['USDC', 'USDC.e']:
            return price  # Price is token0 per USDC
        elif token0_info['symbol'] in ['USDC', 'USDC.e']:
            return Decimal(1) / price  # Price is token1 per USDC
        else:
            print(f"   Warning: Neither token in V3 pool {pool_address} is USDC. Cannot determine USD price.")
            return None
            
    except Exception as e:
        # Not a V3 pool, return None to try V2
        return None

def get_v2_pool_price(pool_address):
    """Get price from V2-style pool using reserves"""
    try:
        pool_contract = web3.eth.contract(address=web3.to_checksum_address(pool_address), abi=POOL_V2_ABI)
        
        reserves = pool_contract.functions.getReserves().call()
        token0_address = pool_contract.functions.token0().call()
        token1_address = pool_contract.functions.token1().call()
        
        token_info_cache = {}
        token0_info = get_token_info(token0_address, token_info_cache)
        token1_info = get_token_info(token1_address, token_info_cache)
        
        reserve0 = Decimal(reserves[0])
        reserve1 = Decimal(reserves[1])
        
        # Adjust for decimals
        reserve0_adjusted = reserve0 / Decimal(10**token0_info['decimals'])
        reserve1_adjusted = reserve1 / Decimal(10**token1_info['decimals'])
        
        # Price = reserve1/reserve0 (token1 per token0)
        if reserve0_adjusted > 0:
            price = reserve1_adjusted / reserve0_adjusted
            
            # Determine USD price based on which token is USDC
            if token1_info['symbol'] in ['USDC', 'USDC.e']:
                return price  # token0 price in USD
            elif token0_info['symbol'] in ['USDC', 'USDC.e']:
                return Decimal(1) / price  # token1 price in USD
            else:
                print(f"   Warning: Neither token in V2 pool {pool_address} is USDC. Cannot determine USD price.")
                return None
                
        return None
        
    except Exception as e:
        # Not a V2 pool either
        return None

def get_pool_price(pool_address):
    """
    Fetches the current USD price for a given Shadow DEX pool.
    Automatically detects V2 vs V3 style and uses appropriate method.
    """
    global _price_cache, _price_cache_timestamp
    current_time = datetime.now()

    # Check cache first
    if current_time - _price_cache_timestamp < timedelta(seconds=PRICE_CACHE_DURATION):
        if pool_address in _price_cache:
            return _price_cache[pool_address]
    else:
        _price_cache = {}
        print(f"   Price cache expired. Refreshing...")

    try:
        # First try V3-style (concentrated liquidity)
        v3_price = get_v3_pool_price(pool_address)
        if v3_price is not None:
            _price_cache[pool_address] = v3_price
            _price_cache_timestamp = current_time
            print(f"   Successfully fetched V3 price for {pool_address}: ${v3_price:,.2f}")
            return v3_price
            
        # If V3 fails, try V2-style (reserves)
        v2_price = get_v2_pool_price(pool_address)
        if v2_price is not None:
            _price_cache[pool_address] = v2_price
            _price_cache_timestamp = current_time
            print(f"   Successfully fetched V2 price for {pool_address}: ${v2_price:,.2f}")
            return v2_price
            
        print(f"   Warning: Could not determine pool type for {pool_address}")
        return None
        
    except Exception as e:
        print(f"   Warning: Could not fetch price for pool {pool_address}: {e}")
        return None

def get_coingecko_price(api_id):
    """
    This function is now a placeholder. Prices are fetched from Shadow DEX pools.
    It will return prices for WBTC and SHADOW from their respective pools.
    For other tokens, it will attempt to fetch from CoinGecko (if api_id is provided).
    """
    if api_id == 'wrapped-bitcoin':
        return get_pool_price(WBTC_USDC_POOL)
    elif api_id == 'shadow-2':
        return get_pool_price(SHADOW_USDC_POOL)
    else:
        # Fallback for other tokens not on Shadow DEX, if needed
        print(f"   Attempting to fetch price for {api_id} from CoinGecko (fallback)...")
        try:
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={api_id}&vs_currencies=usd"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            price = Decimal(data[api_id]['usd'])
            return price
        except Exception as e:
            print(f"   Warning: Could not fetch price for {api_id} from CoinGecko: {e}")
            return None

def tick_to_price(tick, decimals0, decimals1):
    """Converts a tick to a human-readable price."""
    price_ratio = Decimal(1.0001) ** Decimal(tick)
    price_adjustment = Decimal(10) ** (decimals0 - decimals1)
    return price_ratio * price_adjustment

def calculate_token_amounts(liquidity, current_sqrt_price, lower_tick, upper_tick):
    """Calculates the underlying token amounts from liquidity and price range."""
    liquidity = Decimal(liquidity)
    sqrt_price_lower = Decimal(1.0001) ** (Decimal(lower_tick) / 2)
    sqrt_price_upper = Decimal(1.0001) ** (Decimal(upper_tick) / 2)

    amount0, amount1 = 0, 0
    if current_sqrt_price <= sqrt_price_lower:
        amount0 = liquidity * ((sqrt_price_upper - sqrt_price_lower) / (sqrt_price_lower * sqrt_price_upper))
    elif current_sqrt_price >= sqrt_price_upper:
        amount1 = liquidity * (sqrt_price_upper - sqrt_price_lower)
    else: # In range
        amount0 = liquidity * ((sqrt_price_upper - current_sqrt_price) / (current_sqrt_price * sqrt_price_upper))
        amount1 = liquidity * (current_sqrt_price - sqrt_price_lower)

    return int(amount0), int(amount1)

def get_pool_info(web3, token0, token1, block_identifier='latest'):
    """Gets pool address and state for a pair of tokens at a specific block."""
    token0_cs = web3.to_checksum_address(token0)
    token1_cs = web3.to_checksum_address(token1)

    pool_address = KNOWN_POOLS.get((token0_cs, token1_cs)) or KNOWN_POOLS.get((token1_cs, token0_cs))
    if not pool_address: return None

    try:
        pool_contract = web3.eth.contract(address=web3.to_checksum_address(pool_address), abi=POOL_ABI)
        slot0 = pool_contract.functions.slot0().call(block_identifier=block_identifier)
        sqrt_price_x96 = slot0[0]
        current_tick = slot0[1]
        sqrt_price = Decimal(sqrt_price_x96) / Decimal(2**96)

        return {
            'pool_address': pool_address,
            'sqrt_price': sqrt_price,
            'current_tick': current_tick,
        }
    except Exception as e:
        print(f"   Error getting pool info for {pool_address} at block {block_identifier}: {e}")
        return None

def get_emissions_rewards(web3, token_id, pool_address):
    """Fetches emission rewards from the associated GaugeV3 contract."""
    rewards = {}
    try:
        voter_contract = web3.eth.contract(address=web3.to_checksum_address(VOTER_CONTRACT), abi=VOTER_ABI)
        gauge_address = voter_contract.functions.gaugeForPool(web3.to_checksum_address(pool_address)).call()

        if gauge_address == '0x0000000000000000000000000000000000000000': return rewards

        gauge_contract = web3.eth.contract(address=web3.to_checksum_address(gauge_address), abi=GAUGE_V3_ABI)
        reward_tokens = gauge_contract.functions.getRewardTokens().call()

        for token_address in reward_tokens:
            earned = gauge_contract.functions.earned(web3.to_checksum_address(token_address), token_id).call()
            if earned > 0:
                rewards[token_address] = earned
        return rewards
    except Exception as e:
        print(f"   Warning: Could not fetch emissions for pool {pool_address}: {e}")
        return rewards

def calculate_il_percentage(entry_price, target_price, lower_price, upper_price):
    """
    Calculates the impermanent loss as a percentage based on price movements.
    This logic is ported from the provided calculations.js file.
    """
    p_entry = Decimal(entry_price)
    p_target = Decimal(target_price)
    p_lower = Decimal(lower_price)
    p_upper = Decimal(upper_price)

    if p_target == p_entry or p_lower >= p_upper:
        return Decimal(0)

    sqrt_entry = p_entry.sqrt()
    sqrt_target = p_target.sqrt()
    sqrt_lower = p_lower.sqrt()
    sqrt_upper = p_upper.sqrt()

    # Use L=1 for a normalized calculation of asset amounts
    L = Decimal(1)

    # Calculate hypothetical initial token amounts at entry_price
    if p_entry <= p_lower:
        amount0_entry = L * (sqrt_upper - sqrt_lower) / (sqrt_lower * sqrt_upper)
        amount1_entry = Decimal(0)
    elif p_entry >= p_upper:
        amount0_entry = Decimal(0)
        amount1_entry = L * (sqrt_upper - sqrt_lower)
    else:
        amount0_entry = L * (sqrt_upper - sqrt_entry) / (sqrt_entry * sqrt_upper)
        amount1_entry = L * (sqrt_entry - sqrt_lower)

    # Calculate token amounts at the target_price
    if p_target <= p_lower:
        amount0_target = L * (sqrt_upper - sqrt_lower) / (sqrt_lower * sqrt_upper)
        amount1_target = Decimal(0)
    elif p_target >= p_upper:
        amount0_target = Decimal(0)
        amount1_target = L * (sqrt_upper - sqrt_lower)
    else:
        amount0_target = L * (sqrt_upper - sqrt_target) / (sqrt_target * sqrt_upper)
        amount1_target = L * (sqrt_target - sqrt_lower)

    # Value of initial assets if they were held (HODL value)
    hodl_value = amount0_entry * p_target + amount1_entry
    # Value of the assets in the LP position
    lp_value = amount0_target * p_target + amount1_target

    if hodl_value == 0:
        return Decimal(0)

    # IL is the relative difference between LP value and HODL value
    il = (lp_value / hodl_value) - 1
    return abs(il)

def format_timedelta(days):
    """Formats a decimal number of days into a human-readable string (up to 3 levels of units, no seconds)."""
    if days is None or not isinstance(days, Decimal) or not days.is_finite():
        return "N/A"

    if days < 0:
        return "Met"

    total_minutes = int(days * 24 * 60)

    if total_minutes == 0:
        return "<1m"

    parts = []

    # Calculate all components from total_minutes
    years = total_minutes // (365 * 24 * 60)
    total_minutes %= (365 * 24 * 60)

    months = total_minutes // (30 * 24 * 60) # Approximate month
    total_minutes %= (30 * 24 * 60)

    weeks = total_minutes // (7 * 24 * 60)
    total_minutes %= (7 * 24 * 60)

    days_part = total_minutes // (24 * 60)
    total_minutes %= (24 * 60)

    hours_part = total_minutes // 60
    minutes_part = total_minutes % 60

    time_components_ordered = []
    if years > 0: time_components_ordered.append((years, 'y'))
    if months > 0: time_components_ordered.append((months, 'mo'))
    if weeks > 0: time_components_ordered.append((weeks, 'w'))
    if days_part > 0: time_components_ordered.append((days_part, 'd'))
    if hours_part > 0: time_components_ordered.append((hours_part, 'h'))
    if minutes_part > 0: time_components_ordered.append((minutes_part, 'm'))

    display_parts = []
    for value, unit in time_components_ordered:
        display_parts.append(f"{value}{unit}")
        if len(display_parts) == 3:
            break

    return " ".join(display_parts) if display_parts else "N/A"


# --- MAIN LOGIC ---
def find_and_display_positions(wallet_address):
        """The main function to find, calculate, and display position details."""
        if not web3.is_connected():
            return {"error": f"Failed to connect to Sonic RPC at {RPC_URL}"}

        initial_data_cache = db_load_initial_positions()

        # Pre-fetch prices for known tokens using the new cached function
        price_cache = {}
        for token_address, token_info in KNOWN_TOKENS.items():
            if token_info['symbol'] == 'USDC':
                price_cache[token_info['symbol']] = Decimal('1.0') # Hardcode USDC price to $1
            elif token_info['symbol'] == 'WBTC':
                price = get_pool_price(WBTC_USDC_POOL)
                if price:
                    price_cache[token_info['symbol']] = price
            elif token_info['symbol'] == 'SHADOW' or token_info['symbol'] == 'xSHADOW':
                price = get_pool_price(SHADOW_USDC_POOL)
                if price:
                    price_cache[token_info['symbol']] = price

        nft_contract = web3.eth.contract(address=web3.to_checksum_address(NFT_MANAGER_CONTRACT), abi=NFT_MANAGER_ABI)
        try:
            balance = nft_contract.functions.balanceOf(wallet_address).call()
        except Exception as e:
            return {"error": f"Error getting wallet balance: {e}"}

        if balance == 0:
            return {"message": "No positions found for this wallet."}

        active_positions = []
        consecutive_closed = 0
        for i in range(balance - 1, -1, -1):
            try:
                token_id = nft_contract.functions.tokenOfOwnerByIndex(wallet_address, i).call()
                pos_data = nft_contract.functions.positions(token_id).call()
                if pos_data[5] > 0: # Check for liquidity
                    consecutive_closed = 0
                    active_positions.append({'token_id': token_id, 'data': pos_data})
                else:
                    consecutive_closed += 1

                if consecutive_closed >= 5:
                    break
            except Exception as e:
                # print(f"   Warning: Skipping token {nft_contract.functions.tokenOfOwnerByIndex.w3.eth.checksum_address(wallet_address), i} due to error: {e}")
                pass # Silently skip positions that cause errors

        active_positions.reverse()

        if not active_positions:
            return {"message": "No active positions found."}

        all_positions_data = []
        token_info_cache = {}
        total_portfolio_value = Decimal(0)
        # cache_updated = False

        for i, pos_container in enumerate(active_positions):
            pos = pos_container['data']
            token_id = pos_container['token_id']
            token_id_str = str(token_id)

            token0_addr, token1_addr, _, tickLower, tickUpper, liquidity, *_ = pos
            token0_info = get_token_info(token0_addr, token_info_cache)
            token1_info = get_token_info(token1_addr, token_info_cache)

            current_pool_info = get_pool_info(web3, token0_addr, token1_addr)
            if not current_pool_info:
                # If pool info cannot be fetched, skip this position as it's critical
                continue

            current_sqrt_price = current_pool_info['sqrt_price']
            current_tick = current_pool_info['current_tick']
            amount0, amount1 = calculate_token_amounts(liquidity, current_sqrt_price, tickLower, tickUpper)
            current_price = tick_to_price(current_tick, token0_info['decimals'], token1_info['decimals'])

            if token_id_str not in initial_data_cache:
                # cache_updated = True
                creation_info = get_position_creation_info(web3, NFT_MANAGER_CONTRACT, token_id, wallet_address)
                if creation_info:
                    hist_pool_info = get_pool_info(web3, token0_addr, token1_addr, creation_info['block_number'])
                    if hist_pool_info:
                        initial_amount0, initial_amount1 = calculate_token_amounts(liquidity, hist_pool_info['sqrt_price'], tickLower, tickUpper)
                        initial_price = tick_to_price(hist_pool_info['current_tick'], token0_info['decimals'], token1_info['decimals'])

                        initial_data_cache[token_id_str] = {
                            'date': datetime.fromtimestamp(creation_info['timestamp']).strftime('%a %Y-%m-%d %H:%M:%S'),
                            'block': creation_info['block_number'],
                            'amount0': initial_amount0,
                            'amount1': initial_amount1,
                            'price': str(initial_price)
                        }
                else:
                    # Fallback for new positions if creation info not found
                    initial_data_cache[token_id_str] = {
                        'date': datetime.now().strftime('%a %Y-%m-%d %H:%M:%S') + " (Current)",
                        'block': 'N/A',
                        'amount0': amount0,
                        'amount1': amount1,
                        'price': str(current_price)
                    }

            db_save_initial_position(token_id_str, initial_data_cache[token_id_str])

            position_usd_value = Decimal(0)
            price0 = price_cache.get(token0_info['symbol'])
            price1 = price_cache.get(token1_info['symbol'])

            if price0:
                position_usd_value += (Decimal(amount0) / Decimal(10**token0_info['decimals'])) * price0
            if price1:
                position_usd_value += (Decimal(amount1) / Decimal(10**token1_info['decimals'])) * price1

            # Handle cases where one token might be USDC
            if position_usd_value == 0:
                if token1_info['symbol'] == 'USDC' and price0:
                    position_usd_value = (Decimal(amount0) / Decimal(10**token0_info['decimals']) * price0) + (Decimal(amount1) / Decimal(10**token1_info['decimals']))
                elif token0_info['symbol'] == 'USDC' and price1:
                    position_usd_value = (Decimal(amount1) / Decimal(10**token1_info['decimals']) * price1) + (Decimal(amount0) / Decimal(10**token0_info['decimals']))
                else:
                    position_usd_value = Decimal(0) # Ensure it's Decimal 0 if no value could be computed

            total_portfolio_value += position_usd_value

            position_status = "IN RANGE" if tickLower <= current_tick <= tickUpper else "OUT OF RANGE"

            price_lower = tick_to_price(tickLower, token0_info['decimals'], token1_info['decimals'])
            price_upper = tick_to_price(tickUpper, token0_info['decimals'], token1_info['decimals'])

            initial_info = initial_data_cache.get(token_id_str, {})
            initial_usd_value = Decimal(0)
            initial_price_val = Decimal(0) # Initialize with Decimal 0
            if 'price' in initial_info and initial_info['price'] != 'N/A':
                try:
                    initial_price_val = Decimal(initial_info['price'])
                except Exception:
                    initial_price_val = Decimal(0) # Default to 0 if conversion fails


            if initial_info and initial_price_val > 0: # Check if initial_price_val is valid
                initial_amount0_adj = Decimal(initial_info.get('amount0', 0)) / Decimal(10**token0_info['decimals'])
                initial_amount1_adj = Decimal(initial_info.get('amount1', 0)) / Decimal(10**token1_info['decimals'])

                if token1_info['symbol'] == 'USDC':
                    initial_usd_value = (initial_amount0_adj * initial_price_val) + initial_amount1_adj
                elif token0_info['symbol'] == 'USDC':
                    initial_usd_value = (initial_amount1_adj * (1/initial_price_val)) + initial_amount0_adj
                elif price0 and price1: # Fallback for non-USDC pairs, use current prices
                     initial_usd_value = (initial_amount0_adj * price0) + (initial_amount1_adj * price1)
                else:
                    initial_usd_value = Decimal(0) # Ensure it's Decimal 0 if no value could be computed


            emissions = get_emissions_rewards(web3, token_id, current_pool_info['pool_address'])
            rewards_data = []
            total_rewards_usd = Decimal(0)
            if emissions:
                for token_addr, amount in emissions.items():
                    reward_token_info = get_token_info(token_addr, token_info_cache)
                    display_amount = format_amount(amount, reward_token_info['decimals'])
                    usd_value = Decimal(0)
                    reward_price = price_cache.get(reward_token_info['symbol'])
                    if reward_price:
                        raw_amount = Decimal(amount) / Decimal(10**reward_token_info['decimals'])
                        usd_value = raw_amount * reward_price
                        if reward_token_info['symbol'] == 'xSHADOW':
                            total_rewards_usd += (usd_value / 2)
                        else:
                            total_rewards_usd += usd_value

                    rewards_data.append({
                        "amount": display_amount,
                        "symbol": reward_token_info['symbol'],
                        "usd_value": f"{usd_value / 2 if reward_token_info['symbol'] == 'xSHADOW' else usd_value:,.2f}",
                    })

            annualized_apr = Decimal(0)
            days_active = Decimal(0)
            daily_projected_usd_earnings = Decimal(0)
            annual_projected_usd_earnings = Decimal(0)

            if initial_info and 'date' in initial_info and " (Current)" not in initial_info['date']:
                try:
                    creation_date_str = initial_info['date']
                    creation_datetime = datetime.strptime(creation_date_str, '%a %Y-%m-%d %H:%M:%S')
                    time_difference = datetime.now() - creation_datetime
                    days_active = Decimal(time_difference.total_seconds()) / Decimal(86400)

                    if position_usd_value > 0 and days_active > 0: # Ensure no division by zero
                        annualized_apr = (total_rewards_usd / position_usd_value) / (days_active / Decimal(365)) * Decimal(100)
                        annual_projected_usd_earnings = position_usd_value * (annualized_apr / Decimal(100))
                        daily_projected_usd_earnings = annual_projected_usd_earnings / Decimal(365)
                except Exception as e:
                    print(f"   [ERROR] APR calculation failed for token ID {token_id}: {e}")
                    annualized_apr = Decimal(0) # Ensure it's 0 on error

            il_data = {} # Initialize empty to ensure it's always a dict
            if initial_info and initial_price_val > 0 and position_usd_value > 0 and days_active > 0: # Proceed only if basic info is valid
                try:
                    initial_price = initial_price_val # Use the already converted Decimal

                    il_perc_lower = calculate_il_percentage(initial_price, price_lower, price_lower, price_upper)
                    il_perc_upper = calculate_il_percentage(initial_price, price_upper, price_lower, price_upper)

                    initial_amount0_adj = Decimal(initial_info['amount0']) / Decimal(10**token0_info['decimals'])
                    initial_amount1_adj = Decimal(initial_info['amount1']) / Decimal(10**token1_info['decimals'])

                    hodl_val_at_lower = initial_amount0_adj * price_lower + initial_amount1_adj
                    il_usd_lower = il_perc_lower * hodl_val_at_lower

                    hodl_val_at_upper = initial_amount0_adj * price_upper + initial_amount1_adj
                    il_usd_upper = il_perc_upper * hodl_val_at_upper

                    # Initialize these to default values
                    days_to_breakeven_lower = Decimal(0)
                    days_to_breakeven_upper = Decimal(0)
                    daily_rewards_usd = Decimal(0)

                    if annualized_apr > 0: # Only calculate if APR is positive
                        daily_rewards_usd = (position_usd_value * (annualized_apr / Decimal(100))) / Decimal(365)
                        if daily_rewards_usd > 0: # Avoid division by zero
                            days_to_breakeven_lower = il_usd_lower / daily_rewards_usd if il_usd_lower > 0 else Decimal(0)
                            days_to_breakeven_upper = il_usd_upper / daily_rewards_usd if il_usd_upper > 0 else Decimal(0)

                    time_remaining_lower = days_to_breakeven_lower - days_active
                    fee_il_diff_lower = total_rewards_usd - il_usd_lower

                    time_remaining_upper = days_to_breakeven_upper - days_active
                    fee_il_diff_upper = total_rewards_usd - il_usd_upper

                    il_perc_current = calculate_il_percentage(initial_price, current_price, price_lower, price_upper)
                    hodl_val_at_current = (initial_amount0_adj * current_price) + initial_amount1_adj
                    il_usd_current = il_perc_current * hodl_val_at_current
                    net_gain_loss = total_rewards_usd - il_usd_current

                    breakeven_lower_str = "N/A"
                    breakeven_upper_str = "N/A"

                    # Only format if breakeven time is meaningful (not 0 or None)
                    if days_to_breakeven_lower > 0:
                        total_time_str = format_timedelta(days_to_breakeven_lower)
                        remaining_time_str = format_timedelta(time_remaining_lower)
                        breakeven_lower_str = f"{total_time_str} ({remaining_time_str} left)" if remaining_time_str != "Met" else f"{total_time_str} (Met)"

                    if days_to_breakeven_upper > 0:
                        total_time_str = format_timedelta(days_to_breakeven_upper)
                        remaining_time_str = format_timedelta(time_remaining_upper)
                        breakeven_upper_str = f"{total_time_str} ({remaining_time_str} left)" if remaining_time_str != "Met" else f"{total_time_str} (Met)"


                    time_remaining_perc_lower = 0
                    if days_to_breakeven_lower > 0:
                        time_remaining_perc_lower = (time_remaining_lower / days_to_breakeven_lower) * 100 if time_remaining_lower.is_finite() else -1

                    time_remaining_perc_upper = 0
                    if days_to_breakeven_upper > 0:
                        time_remaining_perc_upper = (time_remaining_upper / days_to_breakeven_upper) * 100 if time_remaining_upper.is_finite() else -1

                    perc_to_lower = Decimal(0)
                    perc_to_lower_str = ""
                    if current_price > 0:
                        perc_to_lower = ((current_price - price_lower) / current_price) * 100
                        perc_to_lower_str = f"{perc_to_lower:,.2f}% down"

                    perc_to_upper = Decimal(0)
                    perc_to_upper_str = ""
                    if current_price > 0:
                        perc_to_upper = ((price_upper - current_price) / current_price) * 100
                        perc_to_upper_str = f"{perc_to_upper:,.2f}% up"

                    il_data = {
                        "lower_bound": {
                            "price": f"{price_lower:,.0f}",
                            "il_usd": f"{il_usd_lower:,.2f}",
                            "il_perc": f"{il_perc_lower:.2%}",
                            "breakeven_time": breakeven_lower_str,
                            "breakeven_time_perc": time_remaining_perc_lower,
                            "fees_vs_il": f"{fee_il_diff_lower:,.2f}"
                        },
                        "upper_bound": {
                            "price": f"{price_upper:,.0f}",
                            "il_usd": f"{il_usd_upper:,.2f}",
                            "il_perc": f"{il_perc_upper:.2%}",
                            "breakeven_time": breakeven_upper_str,
                            "breakeven_time_perc": time_remaining_perc_upper,
                            "fees_vs_il": f"{fee_il_diff_upper:,.2f}"
                        },
                        "current": {
                            "il_usd": f"{il_usd_current:,.2f}",
                            "il_perc": f"{il_perc_current:.2%}",
                            "net_gain_loss": f"{net_gain_loss:,.2f}"
                        },
                        "position_age": format_timedelta(days_active)
                    }
                except Exception as e:
                    print(f"   [ERROR] Error during IL calculation for token ID {token_id}: {e}")
                    # traceback.print_exc() # Uncomment for more detailed trace in development
                    il_data = {} # Ensure il_data is empty or default on error

            price_range_percentage = 0
            if (price_upper - price_lower) > 0:
                price_range_percentage = (current_price - price_lower) / (price_upper - price_lower) * 100

            all_positions_data.append({
                "token_id": token_id,
                "pair": f"{token0_info['symbol']}/{token1_info['symbol']}",
                "status": position_status,
                "estimated_value_usd": f"{position_usd_value:,.2f}",
                "price_range": f"{price_lower:,.0f} - {price_upper:,.0f}",
                "price_range_lower": f"{price_lower:,.0f}",
                "price_range_upper": f"{price_upper:,.0f}",
                "price_range_percentage": price_range_percentage,
                "perc_to_lower": f"{perc_to_lower:,.2f}%",
                "perc_to_upper": f"{perc_to_upper:,.2f}%",
                "current_price": f"{current_price:,.0f} {token1_info['symbol']}/{token0_info['symbol']}",
                "initial_state": {
                    "date": initial_info.get('date', 'N/A'),
                    "balances": f"{format_amount(initial_info.get('amount0', 0), token0_info['decimals'])} {token0_info['symbol']} & {format_amount(initial_info.get('amount1', 0), token1_info['decimals'])} {token1_info['symbol']}",
                    "price": f"{initial_price_val:,.0f} {token1_info['symbol']}/{token0_info['symbol']}", # Use initial_price_val here
                    "usd_value": f"{initial_usd_value:,.2f}"
                },
                "current_balances": f"{format_amount(amount0, token0_info['decimals'])} {token0_info['symbol']} & {format_amount(amount1, token1_info['decimals'])} {token1_info['symbol']}",
                "rewards": rewards_data,
                "total_rewards_usd": f"{total_rewards_usd:,.2f}",
                "annualized_apr": f"{annualized_apr:,.2f}%",
                "daily_projected_usd_earnings": f"{daily_projected_usd_earnings:,.2f}",
                "annual_projected_usd_earnings": f"{annual_projected_usd_earnings:,.2f}",
                "impermanent_loss_data": il_data
            })

        # if cache_updated:
            # save_cache(initial_data_cache)

        total_daily_projected_usd_earnings = Decimal(0)
        total_annual_projected_usd_earnings = Decimal(0)
        for pos_data in all_positions_data:
            total_daily_projected_usd_earnings += Decimal(pos_data["daily_projected_usd_earnings"].replace(",", ""))
            total_annual_projected_usd_earnings += Decimal(pos_data["annual_projected_usd_earnings"].replace(",", ""))

        total_annual_yield = Decimal(0)
        if total_portfolio_value > 0:
            total_annual_yield = (total_annual_projected_usd_earnings / total_portfolio_value) * Decimal(100)

        return {
            "total_portfolio_value": f"{total_portfolio_value:,.2f}",
            "num_active_positions": len(active_positions),
            "total_daily_projected_usd_earnings": f"{total_daily_projected_usd_earnings:,.2f}",
            "total_annual_projected_usd_earnings": f"{total_annual_projected_usd_earnings:,.2f}",
            "total_annual_yield": f"{total_annual_yield:,.2f}%",
            "positions": all_positions_data
        }