// Outils communs aux scripts FraudNet on-chain.
const fs = require("fs");
const path = require("path");
const { ethers } = require("ethers");

const ROOT = path.join(__dirname, "..");
require("dotenv").config({ path: path.join(ROOT, ".env") });

const DATA_DIR = process.env.FRAUDNET_DATA || path.join(ROOT, "..", "fraudnet", "data");
const WALLETS_FILE = path.join(ROOT, "wallets.json");
const DEPLOYMENT_FILE = path.join(ROOT, "deployment.json");

// Index de derivation : 0 = admin (banque centrale), 1..N = comptes, BANK_INDEX_BASE + k = banques
const BANK_INDEX_BASE = 1_000_000;
const HD_BASE_PATH = "m/44'/60'/0'/0";

function readCsv(file) {
  const [header, ...lines] = fs.readFileSync(file, "utf8").trim().split(/\r?\n/);
  const cols = header.split(",");
  // Les colonnes utiles sont avant les champs texte libres eventuels : on ne parse
  // que les fichiers sans virgule entre guillemets (accounts, banks, transactions).
  return lines.map((l) => {
    const v = l.split(",");
    return Object.fromEntries(cols.map((c, i) => [c, v[i]]));
  });
}

function hdRoot() {
  const phrase = process.env.MNEMONIC;
  if (!phrase) throw new Error("MNEMONIC absent de .env : lance d'abord 'npm run wallets'");
  return ethers.HDNodeWallet.fromPhrase(phrase, "", HD_BASE_PATH);
}

function provider() {
  const url = process.env.L1_RPC_URL;
  if (!url) throw new Error("L1_RPC_URL absent de .env (URL RPC donnee par 'avalanche blockchain deploy')");
  return new ethers.JsonRpcProvider(url, undefined, { batchMaxCount: 50 });
}

function artifact(name) {
  const p = path.join(ROOT, "artifacts", "contracts", `${name}.sol`, `${name}.json`);
  if (!fs.existsSync(p)) throw new Error("Contrats non compiles : lance 'npx hardhat compile'");
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

function readJson(file, hint) {
  if (!fs.existsSync(file)) throw new Error(`${path.basename(file)} introuvable : ${hint}`);
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

const toCents = (eur) => BigInt(Math.round(Number(eur) * 100));

// Envoi robuste : nonce explicite, suivi du recu toutes les 500 ms, renvoi si la transaction
// disparait de la file (sinon ethers attend indefiniment).
async function sendAndWait(p, wallet, req, { rebroadcastMs = 15000, timeoutMs = 180000 } = {}) {
  const [nonce, fee, net] = await Promise.all([
    p.getTransactionCount(wallet.address, "pending"), p.getFeeData(), p.getNetwork(),
  ]);
  const gasLimit = req.gasLimit || ((await p.estimateGas({ ...req, from: wallet.address })) * 12n) / 10n;
  const raw = await wallet.signTransaction({
    ...req, nonce, gasLimit, chainId: net.chainId, type: 2,
    maxFeePerGas: fee.maxFeePerGas * 2n, maxPriorityFeePerGas: fee.maxPriorityFeePerGas || 0n,
  });
  const hash = ethers.keccak256(raw);
  const t0 = Date.now();
  let lastSend = 0;
  for (;;) {
    if (Date.now() - lastSend > rebroadcastMs) {
      try { await p.send("eth_sendRawTransaction", [raw]); } catch (e) {
        if (!/already known|nonce too low/i.test(e.error?.message || e.message)) throw e;
      }
      lastSend = Date.now();
    }
    const r = await p.send("eth_getTransactionReceipt", [hash]);
    if (r) {
      if (r.status !== "0x1") throw new Error(`Transaction rejetee : ${hash}`);
      return r;
    }
    if (Date.now() - t0 > timeoutMs) throw new Error(`Pas de confirmation apres ${timeoutMs / 1000} s : ${hash}`);
    await new Promise((res) => setTimeout(res, 500));
  }
}

module.exports = {
  ethers, ROOT, DATA_DIR, WALLETS_FILE, DEPLOYMENT_FILE, BANK_INDEX_BASE,
  readCsv, hdRoot, provider, artifact, readJson, toCents, sendAndWait,
};
