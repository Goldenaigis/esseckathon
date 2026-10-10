// Etape 1 : cree 1 wallet par compte FraudNet (+ 1 admin + 1 par banque), derives d'une phrase secrete.
const fs = require("fs");
const path = require("path");
const { ethers, ROOT, DATA_DIR, WALLETS_FILE, BANK_INDEX_BASE, readCsv } = require("./lib");

const envFile = path.join(ROOT, ".env");
let env = fs.existsSync(envFile) ? fs.readFileSync(envFile, "utf8") : "";
if (!/^MNEMONIC=/m.test(env)) {
  const phrase = ethers.Wallet.createRandom().mnemonic.phrase;
  env += `${env && !env.endsWith("\n") ? "\n" : ""}MNEMONIC="${phrase}"\n`;
  fs.writeFileSync(envFile, env, { mode: 0o600 });
  console.log("Nouvelle phrase secrete generee et enregistree dans .env (MNEMONIC)");
}
require("dotenv").config({ path: envFile, override: true });
const root = ethers.HDNodeWallet.fromPhrase(process.env.MNEMONIC, "", "m/44'/60'/0'/0");

const accounts = readCsv(path.join(DATA_DIR, "accounts.csv"));
const banks = readCsv(path.join(DATA_DIR, "banks.csv"));

const out = {
  admin: { index: 0, address: root.deriveChild(0).address },
  banks: {},
  accounts: {},
};
banks.forEach((b, k) => {
  const index = BANK_INDEX_BASE + k;
  out.banks[b.bank_id] = { index, address: root.deriveChild(index).address, name: b.bank_name };
});
accounts.forEach((a, i) => {
  const index = i + 1;
  out.accounts[a.account_id] = { index, address: root.deriveChild(index).address, bank_id: a.bank_id };
});

fs.writeFileSync(WALLETS_FILE, JSON.stringify(out, null, 1));
console.log(`${accounts.length} wallets de comptes + ${banks.length} wallets de banques -> wallets.json`);
console.log(`\nAdresse ADMIN (a mettre dans l'airdrop de la L1) :\n  ${out.admin.address}`);
