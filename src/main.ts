// src/main.ts

import { createSolanaRpc, address } from '@solana/kit';
import { fetchPositionsForOwner } from '@orca-so/whirlpools';
import { SOLANA_RPC_ENDPOINT, WALLET_TO_CHECK } from './config';

async function fetchAndLogPositions() {
  console.log(`Fetching liquidity positions for wallet: ${WALLET_TO_CHECK}`);
  console.log(`Using RPC endpoint: ${SOLANA_RPC_ENDPOINT}\n`);

  try {
    const mainnetRpc = createSolanaRpc(SOLANA_RPC_ENDPOINT);
    const wallet = address(WALLET_TO_CHECK);

    const positions = await fetchPositionsForOwner(mainnetRpc, wallet);

    if (positions.length === 0) {
      console.log('No liquidity positions found for the specified wallet.');
      return;
    }

    console.log(`Found ${positions.length} positions:\n`);

    positions.forEach((position, index) => {
      // Type guard to ensure we are dealing with a single Position, not a PositionBundle
      if (!position.isPositionBundle) {
        console.log(`------------------ Position ${index + 1} ------------------`);
        console.log(`  Whirlpool Address: ${position.data.whirlpool}`);
        console.log(`  Position Address: ${position.address}`);
        console.log(`  Liquidity: ${position.data.liquidity.toString()}`);
        console.log(`  Tick Range: [${position.data.tickLowerIndex}, ${position.data.tickUpperIndex}]`);
        console.log(`  Fee Owed A: ${position.data.feeOwedA.toString()}`);
        console.log(`  Fee Owed B: ${position.data.feeOwedB.toString()}`);
        console.log('----------------------------------------------------\n');
      } else {
        console.log(`------------------ Position Bundle ${index + 1} ------------------`);
        console.log(`  Bundle Address: ${position.address}`);
        console.log('  (This is a bundled position. Detailed breakdown not yet implemented.)');
        console.log('----------------------------------------------------\n');
      }
    });

  } catch (error) {
    console.error('Error fetching positions:', error);
  }
}

fetchAndLogPositions().catch((err) => {
  console.error('An unexpected error occurred:', err);
});
