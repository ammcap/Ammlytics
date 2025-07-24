import dotenv from 'dotenv';

dotenv.config();

function getEnvVariable(key: string): string {
  const value = process.env[key];
  if (!value) {
    throw new Error(`Missing environment variable: ${key}`);
  }
  return value;
}

export const SOLANA_RPC_ENDPOINT = getEnvVariable("SOLANA_RPC_ENDPOINT");
export const WALLET_TO_CHECK = getEnvVariable("WALLET_TO_CHECK");
export const HELIUS_RPC_URL = getEnvVariable("HELIUS_RPC_URL");
