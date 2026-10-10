// Etape 3 : donne du gas a chaque wallet, mint les soldes initiaux en EURF, inscrit les banques au registre.
const path = require("path");
const {
  ethers, DATA_DIR, WALLETS_FILE, DEPLOYMENT_FILE, hdRoot, provider, artifact, readCsv, readJson, toCents, sendAndWait,
} = require("./lib");

const CHUNK = 100; // ~3,6 M gas par lot, sous la limite de bloc d une L1 Avalanche
const GAS_PER_PAY = 100_000n; // marge au-dessus du cout reel d'un pay()

// Solde initial = solde final reconstruit, rehausse pour qu'aucun compte ne passe en negatif pendant le rejeu
function initialBalances(accounts, txs) {
  const net = new Map();
  for (const t of txs) {
    const c = toCents(t.amount);
    net.set(t.src_account, (net.get(t.src_account) || 0n) - c);
    net.set(t.dst_account, (net.get(t.dst_account) || 0n) + c);
  }
  const bal = new Map();
  for (const a of accounts) {
    let b = toCents(a.balance) - (net.get(a.account_id) || 0n);
    bal.set(a.account_id, b < 0n ? 0n : b);
  }
  const running = new Map(bal);
  const deficit = new Map();
  for (const t of txs) {
    const c = toCents(t.amount);
    const r = running.get(t.src_account) - c;
    running.set(t.src_account, r);
    running.set(t.dst_account, running.get(t.dst_account) + c);
    if (r < -(deficit.get(t.src_account) || 0n)) deficit.set(t.src_account, -r);
  }
  for (const [id, d] of deficit) bal.set(id, bal.get(id) + d);
  return { bal, nAdjusted: deficit.size };
}

async function main() {
  const p = provider();
  const admin = hdRoot().deriveChild(0);
  const W = readJson(WALLETS_FILE, "lance 'npm run wallets'");
  const D = readJson(DEPLOYMENT_FILE, "lance 'npm run deploy'");
  const token = new ethers.Contract(D.contracts.EURToken, artifact("EURToken").abi, p);
  const funder = new ethers.Contract(D.contracts.GasFunder, artifact("GasFunder").abi, p);
  const registry = new ethers.Contract(D.contracts.FraudRegistry, artifact("FraudRegistry").abi, p);

  const accounts = readCsv(path.join(DATA_DIR, "accounts.csv"));
  const txs = readCsv(path.join(DATA_DIR, "transactions.csv"))
    .filter((t) => t.status === "completed")
    .sort((a, b) => (a.ts === b.ts ? (a.tx_id < b.tx_id ? -1 : 1) : a.ts < b.ts ? -1 : 1));

  // --- gas natif : proportionnel au nombre de virements emis
  const fee = await p.getFeeData();
  const gasPrice = (fee.maxFeePerGas || fee.gasPrice) * 2n;
  const sends = new Map();
  for (const t of txs) sends.set(t.src_account, (sends.get(t.src_account) || 0) + 1);
  const gasTargets = [];
  for (const [id, n] of sends) gasTargets.push([W.accounts[id].address, BigInt(n + 5) * GAS_PER_PAY * gasPrice]);
  for (const b of Object.values(W.banks)) gasTargets.push([b.address, 1000n * GAS_PER_PAY * gasPrice]);

  const already = await Promise.all(gasTargets.map(([a]) => p.getBalance(a)));
  const todoGas = gasTargets.filter((_, k) => already[k] === 0n);
  console.log(`Gas : ${gasTargets.length - todoGas.length} wallets deja finances, ${todoGas.length} a faire`);

  const totalGas = todoGas.reduce((s, [, v]) => s + v, 0n);
  const adminBal = await p.getBalance(admin.address);
  console.log(`Gas a distribuer : ${ethers.formatEther(totalGas)} (solde admin ${ethers.formatEther(adminBal)})`);
  if (totalGas > adminBal) throw new Error("Solde admin insuffisant : augmente l'airdrop de la L1");

  for (let i = 0; i < todoGas.length; i += CHUNK) {
    const part = todoGas.slice(i, i + CHUNK);
    const value = part.reduce((s, [, v]) => s + v, 0n);
    const req = await funder.fund.populateTransaction(part.map(([a]) => a), part.map(([, v]) => v), { value });
    await sendAndWait(p, admin, req);
    process.stdout.write(`\r  gas : ${Math.min(i + CHUNK, todoGas.length)}/${todoGas.length}`);
  }
  console.log();

  // --- soldes initiaux EURF
  const { bal, nAdjusted } = initialBalances(accounts, txs);
  const candidates = [...bal].filter(([, v]) => v > 0n);
  const minted = await Promise.all(candidates.map(([id]) => token.balanceOf(W.accounts[id].address)));
  const mints = candidates.filter((_, k) => minted[k] === 0n);
  console.log(`EURF : ${candidates.length - mints.length} soldes deja crees, ${mints.length} a faire`);
  for (let i = 0; i < mints.length; i += CHUNK) {
    const part = mints.slice(i, i + CHUNK);
    const req = await token.batchMint.populateTransaction(part.map(([id]) => W.accounts[id].address), part.map(([, v]) => v));
    await sendAndWait(p, admin, req);
    process.stdout.write(`\r  EURF : ${Math.min(i + CHUNK, mints.length)}/${mints.length}`);
  }
  const supply = await token.totalSupply();
  console.log(`\n  masse monetaire : ${ethers.formatUnits(supply, 2)} EURF (${nAdjusted} soldes rehausses anti-decouvert)`);

  // --- banques membres du registre d'alertes
  for (const [id, b] of Object.entries(W.banks)) {
    if (!(await registry.isMember(b.address))) {
      await sendAndWait(p, admin, await registry.addMember.populateTransaction(b.address, `${id} ${b.name}`));
    }
  }
  console.log(`  ${Object.keys(W.banks).length} banques inscrites au FraudRegistry`);
}

main().catch((e) => { console.error(e.shortMessage || e.message); if (process.env.DEBUG) console.error(e.stack); process.exit(1); });
