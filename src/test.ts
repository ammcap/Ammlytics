import { Connection } from "@solana/web3.js";

// TODO: Replace with your actual Helius RPC URL
const HELIUS_RPC_URL = "https://mainnet.helius-rpc.com/?api-key=658b3ac5-e16c-4046-bb70-5f837ef9400a";

const testTransaction = async () => {
  try {
    const connection = new Connection(HELIUS_RPC_URL, "confirmed");
    const tx = await connection.getParsedTransaction("5BFTW7E2LoVVPVhNuA8t7vcB5pjYA3AZVQFzc9fZcCmtfCfaGYZ6SWgMs7pTJZajYJSiFqrRm8vX3Pz6v4JkX23w", { maxSupportedTransactionVersion: 0 });
    console.log(JSON.stringify(tx, null, 2));
  } catch (error) {
    console.error("An error occurred:", error);
  }
};

testTransaction();
