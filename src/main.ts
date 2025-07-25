import { address, createSolanaRpc, mainnet } from "@solana/kit";
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
import { Sequelize, DataTypes } from "sequelize";
import { SOLANA_RPC_ENDPOINT, WALLET_TO_CHECK, HELIUS_RPC_URL } from "./config";
import { Connection, PublicKey, ParsedTransactionWithMeta } from "@solana/web3.js";

// Initialize Sequelize with SQLite
const sequelize = new Sequelize({
  dialect: "sqlite",
  storage: "./database.sqlite",
  logging: false, // Disable logging of SQL queries
});

// Define the Position model
const Position = sequelize.define("Position", {
  position_address: {
    type: DataTypes.STRING,
    primaryKey: true,
  },
  pool_address: {
    type: DataTypes.STRING,
    allowNull: false,
  },
  initial_a: {
    type: DataTypes.DECIMAL,
    allowNull: false,
  },
  initial_b: {
    type: DataTypes.DECIMAL,
    allowNull: false,
  },
  price_range_lower: {
    type: DataTypes.DECIMAL,
    allowNull: false,
  },
  price_range_upper: {
    type: DataTypes.DECIMAL,
    allowNull: false,
  },
  pending_yield_a: {
    type: DataTypes.DECIMAL,
    allowNull: false,
  },
  pending_yield_b: {
    type: DataTypes.DECIMAL,
    allowNull: false,
  },
  creation_date: {
    type: DataTypes.DATE,
    allowNull: true,
  },
  last_updated: {
    type: DataTypes.DATE,
    allowNull: false,
  },
  metadata: {
    type: DataTypes.JSON,
    allowNull: true,
  },
}, {
  timestamps: false, // Disable automatic timestamps
});

// Helper to convert a BN-like object to a Decimal with the correct number of decimals
function toDecimal(amount: { toString: () => string }, decimals: number): Decimal {
  return new Decimal(amount.toString()).div(new Decimal(10).pow(decimals));
}

interface Event {
  type: 'deposit' | 'withdrawal' | 'feeClaim';
  tokenA: Decimal;
  tokenB: Decimal;
  date: Date;
  tx: string;
}

async function getPositionEvents(
  connection: Connection,
  positionAddress: string,
  owner: string,
  vaultA: PublicKey,
  vaultB: PublicKey,
  decimalsA: number,
  decimalsB: number
): Promise<Event[]> {
  try {
    const signatures = await connection.getSignaturesForAddress(new PublicKey(positionAddress), { limit: 1000 });
    if (signatures.length === 0) {
      return [];
    }

    const events: Event[] = [];

    for (const sig of signatures) {
      const tx = await connection.getParsedTransaction(sig.signature, { maxSupportedTransactionVersion: 0 });
      if (!tx || !tx.blockTime) continue;

      const date = new Date(tx.blockTime * 1000);
      const txId = sig.signature;

      let eventType: Event['type'] | null = null;

      // Check logMessages for instruction type
      if (tx.meta && tx.meta.logMessages) {
        for (const log of tx.meta.logMessages) {
          if (log.includes("Instruction: IncreaseLiquidity")) {
            eventType = 'deposit';
          } else if (log.includes("Instruction: DecreaseLiquidity")) {
            eventType = 'withdrawal';
          } else if (log.includes("Instruction: CollectFees")) {
            eventType = 'feeClaim';
          }
          if (eventType) break;
        }
      }

      if (!eventType) continue;

      // Sum transfers for amounts
      let amountA = new Decimal(0);
      let amountB = new Decimal(0);

      // Parse outer instructions
      for (const ix of tx.transaction.message.instructions) {
        if ("parsed" in ix && ix.program === "spl-token" && ix.parsed.type === "transfer") {
          const info = ix.parsed.info;
          const amountDec = new Decimal(info.amount);
          if (eventType === 'deposit') {
            if (info.destination === vaultA.toBase58()) {
              amountA = amountA.add(amountDec.div(new Decimal(10).pow(decimalsA)));
            } else if (info.destination === vaultB.toBase58()) {
              amountB = amountB.add(amountDec.div(new Decimal(10).pow(decimalsB)));
            }
          } else {
            if (info.source === vaultA.toBase58()) {
              amountA = amountA.add(amountDec.div(new Decimal(10).pow(decimalsA)));
            } else if (info.source === vaultB.toBase58()) {
              amountB = amountB.add(amountDec.div(new Decimal(10).pow(decimalsB)));
            }
          }
        }
      }

      // Parse inner instructions
      if (tx.meta?.innerInstructions) {
        for (const innerSet of tx.meta.innerInstructions) {
          for (const ix of innerSet.instructions) {
            if ("parsed" in ix && ix.program === "spl-token" && ix.parsed.type === "transfer") {
              const info = ix.parsed.info;
              const amountDec = new Decimal(info.amount);
              if (eventType === 'deposit') {
                if (info.destination === vaultA.toBase58()) {
                  amountA = amountA.add(amountDec.div(new Decimal(10).pow(decimalsA)));
                } else if (info.destination === vaultB.toBase58()) {
                  amountB = amountB.add(amountDec.div(new Decimal(10).pow(decimalsB)));
                }
              } else {
                if (info.source === vaultA.toBase58()) {
                  amountA = amountA.add(amountDec.div(new Decimal(10).pow(decimalsA)));
                } else if (info.source === vaultB.toBase58()) {
                  amountB = amountB.add(amountDec.div(new Decimal(10).pow(decimalsB)));
                }
              }
            }
          }
        }
      }

      if (amountA.gt(0) || amountB.gt(0)) {
        events.push({
          type: eventType,
          tokenA: amountA,
          tokenB: amountB,
          date,
          tx: txId,
        });
      }
    }

    return events.sort((a, b) => a.date.getTime() - b.date.getTime()); // Chronological
  } catch (error) {
    console.error(`Error fetching events for position ${positionAddress}:`, error);
    return [];
  }
}

async function getPositionCreationInfo(
  connection: Connection,
  mintAddress: PublicKey,
  vaultA: PublicKey,
  vaultB: PublicKey,
  decimalsA: number,
  decimalsB: number
): Promise<{ date: Date | null; initialA: Decimal; initialB: Decimal }> {
  let initialA = new Decimal(0);
  let initialB = new Decimal(0);

  try {
    const signatures = await connection.getSignaturesForAddress(mintAddress);
    if (signatures.length === 0) {
      return { date: null, initialA, initialB };
    }

    const earliestSignature = signatures[signatures.length - 1];
    const tx: ParsedTransactionWithMeta | null = await connection.getParsedTransaction(earliestSignature.signature, {
      maxSupportedTransactionVersion: 0,
    });

    if (!tx || !tx.blockTime) {
      return { date: null, initialA, initialB };
    }

    const date = new Date(tx.blockTime * 1000);

    // Parse outer instructions for SPL transfers
    for (const ix of tx.transaction.message.instructions) {
      if ("parsed" in ix && ix.program === "spl-token" && ix.parsed.type === "transfer") {
        const info = ix.parsed.info;
        const dest = info.destination;
        let amountDec: Decimal;
        if (dest === vaultA.toBase58()) {
          amountDec = new Decimal(info.amount).div(new Decimal(10).pow(decimalsA));
          initialA = initialA.add(amountDec);
        } else if (dest === vaultB.toBase58()) {
          amountDec = new Decimal(info.amount).div(new Decimal(10).pow(decimalsB));
          initialB = initialB.add(amountDec);
        }
      }
    }

    // Parse inner instructions for SPL transfers (in case of nested)
    if (tx.meta?.innerInstructions) {
      for (const innerSet of tx.meta.innerInstructions) {
        for (const ix of innerSet.instructions) {
          if ("parsed" in ix && ix.program === "spl-token" && ix.parsed.type === "transfer") {
            const info = ix.parsed.info;
            const dest = info.destination;
            let amountDec: Decimal;
            if (dest === vaultA.toBase58()) {
              amountDec = new Decimal(info.amount).div(new Decimal(10).pow(decimalsA));
              initialA = initialA.add(amountDec);
            } else if (dest === vaultB.toBase58()) {
              amountDec = new Decimal(info.amount).div(new Decimal(10).pow(decimalsB));
              initialB = initialB.add(amountDec);
            }
          }
        }
      }
    }

    return { date, initialA, initialB };
  } catch (error) {
    console.error(`Error fetching creation info for mint ${mintAddress.toBase58()}:`, error);
    return { date: null, initialA, initialB };
  }
}

async function fetchAndLogPositions() {
  console.log(`Fetching liquidity positions for wallet: ${WALLET_TO_CHECK}`);
  console.log(`Using RPC endpoint: ${HELIUS_RPC_URL}\n`);

  try {
    // Sync the model with the database (add { force: true } once if recreating table)
    await sequelize.sync();

    const rpc = createSolanaRpc(mainnet(HELIUS_RPC_URL));
    const connection = new Connection(HELIUS_RPC_URL, "confirmed");
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

      const creationInfo = await getPositionCreationInfo(
        connection,
        new PublicKey(positionData.positionMint),
        new PublicKey(whirlpool.tokenVaultA),
        new PublicKey(whirlpool.tokenVaultB),
        tokenDecimalsA,
        tokenDecimalsB
      );

      const creationDate = creationInfo.date;
      const initialA = creationInfo.initialA;
      const initialB = creationInfo.initialB;

      const events = await getPositionEvents(
        connection,
        position.address,
        WALLET_TO_CHECK,
        new PublicKey(whirlpool.tokenVaultA),
        new PublicKey(whirlpool.tokenVaultB),
        tokenDecimalsA,
        tokenDecimalsB
      );

      // Upsert position data into the database
      await Position.upsert({
        position_address: position.address,
        pool_address: positionData.whirlpool.toString(),
        initial_a: initialA.toString(),
        initial_b: initialB.toString(),
        price_range_lower: priceLower,
        price_range_upper: priceUpper,
        pending_yield_a: feeA,
        pending_yield_b: feeB,
        creation_date: creationDate,
        last_updated: new Date(),
        metadata: { events },
      });

      console.log(`------------------ Position ------------------`);
      console.log(`  Pool: ${whirlpool.tokenMintA.toString().substring(0,4)}.../${whirlpool.tokenMintB.toString().substring(0,4)}...`);
      console.log(`  Position Address: ${position.address}`);
      console.log(`  Creation Date: ${creationDate ? creationDate.toISOString() : 'Not found'}`);
      console.log(`  Initial (Token A): ${initialA.toFixed(tokenDecimalsA)}`);
      console.log(`  Initial (Token B): ${initialB.toFixed(tokenDecimalsB)}`);
      console.log(`  Liquidity (Token A): ${amountA.toFixed(tokenDecimalsA)}`);
      console.log(`  Liquidity (Token B): ${amountB.toFixed(tokenDecimalsB)}`);
      console.log(`  Price Range: [${priceLower.toFixed(tokenDecimalsB)} - ${priceUpper.toFixed(tokenDecimalsB)}]`);
      console.log(`  Pending Yield A: ${feeA.toFixed(tokenDecimalsA)}`);
      console.log(`  Pending Yield B: ${feeB.toFixed(tokenDecimalsB)}`);

      if (events.length > 0) {
        console.log(`  Events:`);
        for (const event of events) {
          console.log(`    - ${event.type} on ${event.date.toISOString()}: Token A = ${event.tokenA.toFixed(tokenDecimalsA)}, Token B = ${event.tokenB.toFixed(tokenDecimalsB)} (tx: ${event.tx.substring(0, 10)}...)`);
        }
      } else {
        console.log(`  No events found.`);
      }
      console.log('--------------------------------------------\n');
    }
  } catch (error) {
    console.error("Error fetching positions:", error);
  }
}

fetchAndLogPositions().catch((err) => {
  console.error("An unexpected error occurred:", err);
});