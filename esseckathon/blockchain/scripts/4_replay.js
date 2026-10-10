// Etape 4 : rejoue les virements FraudNet sur la L1, chacun signe par le wallet du compte emetteur.
//
//   node scripts/4_replay.js            -> tous les virements "completed" (reprend ou il s'est arrete)
//   node scripts/4_replay.js --limit 2000
//   node scripts/4_replay.js --reset    -> repart du debut (sur une chaine neuve)
//
// Les virements sont envoyes par lots en parallele. Un virement n'entre dans le lot courant que si
// son emetteur n'a rien recu plus tot dans ce lot : l'ordre chronologique des soldes est donc respecte.
const fs = require("fs");
const path = require("path");
const {
  ethers, ROOT, DATA_DIR, WALLETS_FILE, DEPLOYMENT_FILE, hdRoot, provider, artifact, readCsv, readJson, toCents,
} = require("./lib");

const PROGRESS_FILE = path.join(ROOT, "replay_progress.json");
const MAX_BATCH = 400;
const GAS_LIMIT = 100_000n;
const POLL_MS = 300;
const REBROADCAST_MS = 15_000;
const BATCH_TIMEOUT_MS = 300_000;

const args = process.argv.slice(2);
const limitArg = args.indexOf("--limit");
const LIMIT = limitArg >= 0 ? Number(args[limitArg + 1]) : Infinity;
if (args.includes("--reset") && fs.existsSync(PROGRESS_FILE)) fs.unlinkSync(PROGRESS_FILE);

async function main() {
  const p = provider();
  const root = hdRoot();
  const W = readJson(WALLETS_FILE, "lance 'npm run wallets'");
  const D = readJson(DEPLOYMENT_FILE, "lance 'npm run deploy'");
  const iface = new ethers.Interface(artifact("EURToken").abi);
  const chainId = (await p.getNetwork()).chainId;

  const txs = readCsv(path.join(DATA_DIR, "transactions.csv"))
    .filter((t) => t.status === "completed")
    .sort((a, b) => (a.ts === b.ts ? (a.tx_id < b.tx_id ? -1 : 1) : a.ts < b.ts ? -1 : 1));

  const progress = fs.existsSync(PROGRESS_FILE) ? JSON.parse(fs.readFileSync(PROGRESS_FILE, "utf8")) : { done: 0 };
  const end = Math.min(txs.length, progress.done + LIMIT);
  console.log(`Rejeu des virements ${progress.done + 1} a ${end} sur ${txs.length}`);

  // Nonce deterministe : le k-ieme virement d'un compte porte le nonce k (ces wallets ne font rien d'autre).
  // Relancer le script ne peut donc jamais rejouer deux fois le meme virement.
  const counter = new Map();
  const nonceOf = txs.map((t) => {
    const k = counter.get(t.src_account) || 0;
    counter.set(t.src_account, k + 1);
    return k;
  });
  const signers = new Map();
  const signerOf = (id) => {
    if (!signers.has(id)) signers.set(id, root.deriveChild(W.accounts[id].index));
    return signers.get(id);
  };

  const t0 = Date.now();
  let i = progress.done;
  while (i < end) {
    // constitution du lot
    const batch = [];
    const received = new Set();
    while (i < end && batch.length < MAX_BATCH && !received.has(txs[i].src_account)) {
      batch.push({ ...txs[i], nonce: nonceOf[i] });
      received.add(txs[i].dst_account);
      i++;
    }

    const fee = await p.getFeeData();
    const signed = await Promise.all(batch.map((t) => {
      const data = iface.encodeFunctionData("pay", [
        W.accounts[t.dst_account].address,
        toCents(t.amount),
        ethers.encodeBytes32String(t.tx_id),
        Math.floor(Date.parse(t.ts + "Z") / 1000),
      ]);
      return signerOf(t.src_account).signTransaction({
        to: D.contracts.EURToken, data, nonce: t.nonce, chainId, type: 2, gasLimit: GAS_LIMIT,
        maxFeePerGas: fee.maxFeePerGas * 3n, maxPriorityFeePerGas: fee.maxPriorityFeePerGas || 0n,
      });
    }));
    const ALREADY = { status: "0x1" }; // nonce deja consomme = virement deja on-chain (reprise)
    const receipts = new Array(signed.length).fill(null);
    const hashes = await Promise.all(signed.map(async (raw, k) => {
      try {
        return await p.send("eth_sendRawTransaction", [raw]);
      } catch (e) {
        if (/nonce too low|already known/i.test(e.error?.message || e.message)) {
          receipts[k] = ALREADY;
          return null;
        }
        throw e;
      }
    }));

    // attente groupee des recus
    let lastSend = Date.now();
    const tBatch = Date.now();
    while (receipts.some((r) => r === null)) {
      await new Promise((r) => setTimeout(r, POLL_MS));
      await Promise.all(hashes.map(async (h, k) => {
        if (receipts[k] === null) receipts[k] = await p.send("eth_getTransactionReceipt", [h]);
      }));
      // renvoi des transactions disparues de la file (deja connues ou deja minees : ignore)
      if (Date.now() - lastSend > REBROADCAST_MS) {
        await Promise.all(signed.map(async (raw, k) => {
          if (receipts[k] !== null) return;
          try { await p.send("eth_sendRawTransaction", [raw]); } catch (e) {
            if (/nonce too low/i.test(e.error?.message || e.message)) receipts[k] = ALREADY;
          }
        }));
        lastSend = Date.now();
      }
      if (Date.now() - tBatch > BATCH_TIMEOUT_MS) throw new Error("Lot non confirme apres 5 min : relance 'npm run replay'");
    }
    const failed = receipts.findIndex((r) => r.status !== "0x1");
    if (failed >= 0) throw new Error(`Virement ${batch[failed].tx_id} rejete on-chain (${hashes[failed]})`);

    fs.writeFileSync(PROGRESS_FILE, JSON.stringify({ done: i }));
    const rate = ((i - progress.done) / ((Date.now() - t0) / 1000)).toFixed(0);
    process.stdout.write(`\r  ${i}/${txs.length} virements on-chain (${rate} tx/s, lot de ${batch.length})   `);
  }
  console.log(`\nTermine. Dernier bloc : ${await p.getBlockNumber()}`);
}

main().catch((e) => { console.error("\n" + (e.shortMessage || e.message), e.error?.message || ""); process.exit(1); });
