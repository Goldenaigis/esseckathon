// Redeploie uniquement FraudRegistry (ex. apres une correction du contrat) et y reinscrit les banques.
// EURToken, les soldes et les virements deja on-chain ne sont pas touches.
const fs = require("fs");
const {
  ethers, WALLETS_FILE, DEPLOYMENT_FILE, hdRoot, provider, artifact, readJson, sendAndWait,
} = require("./lib");

async function main() {
  const p = provider();
  const admin = hdRoot().deriveChild(0);
  const W = readJson(WALLETS_FILE, "lance 'npm run wallets'");
  const D = readJson(DEPLOYMENT_FILE, "lance 'npm run deploy'");
  const a = artifact("FraudRegistry");

  const deployTx = await new ethers.ContractFactory(a.abi, a.bytecode).getDeployTransaction("Admin consortium FraudNet");
  const receipt = await sendAndWait(p, admin, deployTx);
  const address = ethers.getAddress(receipt.contractAddress);
  console.log(`FraudRegistry redeploye : ${address} (ancien : ${D.contracts.FraudRegistry})`);

  const registry = new ethers.Contract(address, a.abi, p);
  for (const [id, b] of Object.entries(W.banks)) {
    await sendAndWait(p, admin, await registry.addMember.populateTransaction(b.address, `${id} ${b.name}`));
  }
  console.log(`${Object.keys(W.banks).length} banques inscrites`);

  D.previousRegistries = [...(D.previousRegistries || []), D.contracts.FraudRegistry];
  D.contracts.FraudRegistry = address;
  fs.writeFileSync(DEPLOYMENT_FILE, JSON.stringify(D, null, 2));
  console.log("-> deployment.json mis a jour");
}

main().catch((e) => { console.error(e.shortMessage || e.message); process.exit(1); });
