import { address, createSolanaRpc, mainnet, assertAccountExists } from "@solana/kit";
import { fetchPositionsForOwner } from "@orca-so/whirlpools";
import {
  fetchMaybeWhirlpool,
  fetchAllTickArray,
  getTickArrayAddress,
} from "@orca-so/whirlpools-client";
import {
  tickIndexToPrice,
  decreaseLiquidityQuote,
  collectFeesQuote,
  getTickArrayStartTickIndex,
  getTickIndexInArray,
} from "@orca-so/whirlpools-core";
import { getMintDecoder } from "@solana-program/token";
import { Buffer } from "buffer";
import { Decimal } from "decimal.js";
import { SOLANA_RPC_ENDPOINT, WALLET_TO_CHECK, HELIUS_RPC_URL } from "./config";

// Helper to convert a BN-like object to a Decimal with the correct number of decimals
function toDecimal(amount: { toString: () => string }, decimals: number): Decimal {
  return new Decimal(amount.toString()).div(new Decimal(10).pow(decimals));
}

async function fetchAndLogPositions() {
  console.log(`Fetching liquidity positions for wallet: ${WALLET_TO_CHECK}`);
  console.log(`Using RPC endpoint: ${HELIUS_RPC_URL}\n`);

  try {
    const rpc = createSolanaRpc(mainnet(HELIUS_RPC_URL));
    const owner = address(WALLET_TO_CHECK);

    const positions = await fetchPositionsForOwner(rpc, owner);

    if (positions.length === 0) {
      console.log("No liquidity positions found for the specified wallet.");
      return;
    }

    console.log(`Found ${positions.length} position accounts (may include bundles):\n`);

    const mintDecoder = getMintDecoder();

    for (const position of positions) {
      if (position.isPositionBundle) {
        console.log(`------------------ Position Bundle ------------------`);
        console.log(`  Bundle Address: ${position.address}`);
        console.log(`  This bundle contains ${position.positions.length} individual positions.`);
        console.log('----------------------------------------------------\n');
        continue;
      }

      const positionData = position.data;
      if (positionData.liquidity === 0n) {
        // Skip positions with no liquidity
        continue;
      }

      const whirlpoolAccount = await fetchMaybeWhirlpool(rpc, positionData.whirlpool);

      if (!whirlpoolAccount.exists) {
        console.log(`Could not find whirlpool for position: ${position.address}`);
        continue;
      }
      const whirlpool = whirlpoolAccount.data;

      // Fetch token mints to get decimals
      const getMintsResult = await rpc
        .getMultipleAccounts([whirlpool.tokenMintA, whirlpool.tokenMintB])
        .send();
      const [tokenMintAAccount, tokenMintBAccount] = getMintsResult.value;

      if (!tokenMintAAccount || !tokenMintBAccount) {
        console.log(`Could not find mint accounts for whirlpool: ${whirlpoolAccount.address}`);
        continue;
      }

      const tokenMintA = mintDecoder.decode(Buffer.from(tokenMintAAccount.data[0], "base64"));
      const tokenMintB = mintDecoder.decode(Buffer.from(tokenMintBAccount.data[0], "base64"));

      const tokenDecimalsA = tokenMintA.decimals;
      const tokenDecimalsB = tokenMintB.decimals;

      const priceLower = tickIndexToPrice(positionData.tickLowerIndex, tokenDecimalsA, tokenDecimalsB);
      const priceUpper = tickIndexToPrice(positionData.tickUpperIndex, tokenDecimalsA, tokenDecimalsB);

      // To get the latest fees, we need to fetch the tick arrays
      const lowerTickArrayStartIndex = getTickArrayStartTickIndex(
        positionData.tickLowerIndex,
        whirlpool.tickSpacing
      );
      const upperTickArrayStartIndex = getTickArrayStartTickIndex(
        positionData.tickUpperIndex,
        whirlpool.tickSpacing
      );

      const [lowerTickArrayAddress] = await getTickArrayAddress(
        positionData.whirlpool,
        lowerTickArrayStartIndex
      );
      const [upperTickArrayAddress] = await getTickArrayAddress(
        positionData.whirlpool,
        upperTickArrayStartIndex
      );

      const [lowerTickArray, upperTickArray] = await fetchAllTickArray(rpc, [
        lowerTickArrayAddress,
        upperTickArrayAddress,
      ]);

      const lowerTick = lowerTickArray.data.ticks[getTickIndexInArray(
          positionData.tickLowerIndex,
          lowerTickArrayStartIndex,
          whirlpool.tickSpacing
      )];
      const upperTick = upperTickArray.data.ticks[getTickIndexInArray(
          positionData.tickUpperIndex,
          upperTickArrayStartIndex,
          whirlpool.tickSpacing
      )];

      const feesQuote = collectFeesQuote(whirlpool, positionData, lowerTick, upperTick);

      const quote = decreaseLiquidityQuote(
        positionData.liquidity,
        0, // slippage tolerance bps - 0 for read-only
        whirlpool.sqrtPrice,
        positionData.tickLowerIndex,
        positionData.tickUpperIndex
      );

      const feeA = toDecimal(feesQuote.feeOwedA, tokenDecimalsA);
      const feeB = toDecimal(feesQuote.feeOwedB, tokenDecimalsB);

      const amountA = toDecimal(quote.tokenEstA, tokenDecimalsA);
      const amountB = toDecimal(quote.tokenEstB, tokenDecimalsB);

      console.log(`------------------ Position ------------------`);
      console.log(`  Pool: ${whirlpool.tokenMintA.toString().substring(0,4)}.../${whirlpool.tokenMintB.toString().substring(0,4)}...`);
      console.log(`  Position Address: ${position.address}`);
      console.log(`  Liquidity (Token A): ${amountA.toFixed(tokenDecimalsA)}`);
      console.log(`  Liquidity (Token B): ${amountB.toFixed(tokenDecimalsB)}`);
      console.log(`  Price Range: [${priceLower.toFixed(tokenDecimalsB)} - ${priceUpper.toFixed(tokenDecimalsB)}]`);
      console.log(`  Pending Yield A: ${feeA.toFixed(tokenDecimalsA)}`);
      console.log(`  Pending Yield B: ${feeB.toFixed(tokenDecimalsB)}`);
      console.log('--------------------------------------------\n');
    }
  } catch (error) {
    console.error("Error fetching positions:", error);
  }
}

fetchAndLogPositions().catch((err) => {
  console.error("An unexpected error occurred:", err);
});