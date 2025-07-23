import { createSolanaRpc, address } from '@solana/kit';
import { fetchPositionsForOwner } from '@orca-so/whirlpools';
import { fetchWhirlpool } from '@orca-so/whirlpools-client';
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

    for (const position of positions) {
      if (!position.isPositionBundle) {
        console.log(`------------------ Position ------------------`);
        console.log(`  Whirlpool Address: ${position.data.whirlpool}`);
        console.log(`  Position Address: ${position.address}`);
        const pool = await fetchWhirlpool(mainnetRpc, address(position.data.whirlpool));
        console.log(`  Pool Data: ${JSON.stringify(pool, (key, value) => typeof value === 'bigint' ? value.toString() : value, 2)}`);
        console.log(`  Liquidity: ${position.data.liquidity.toString()}`);
        console.log(`  Tick Range: [${position.data.tickLowerIndex}, ${position.data.tickUpperIndex}]`);
        console.log(`  Fee Owed A: ${position.data.feeOwedA.toString()}`);
        console.log(`  Fee Owed B: ${position.data.feeOwedB.toString()}`);
        console.log('--------------------------------------------\n');
      } else {
        console.log(`------------------ Position Bundle ------------------`);
        console.log(`  Bundle Address: ${position.address}`);
        console.log('  (This is a bundled position. Detailed breakdown not yet implemented.)');
        console.log('----------------------------------------------------\n');
      }
    }
  } catch (error) {
    console.error('Error fetching positions:', error);
  }
}

fetchAndLogPositions().catch((err) => {
  console.error('An unexpected error occurred:', err);
});