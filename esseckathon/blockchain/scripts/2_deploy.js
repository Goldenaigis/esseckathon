// Etape 2 : deploie EURToken, GasFunder et FraudRegistry sur la L1, depuis le wallet admin.
const fs = require("fs");
const { ethers, DEPLOYMENT_FILE, hdRoot, provider, artifact } = require("./lib");

async function deploy(signer, name, args = []) {
  const a = artifact(name);
  const c = await new ethers.ContractFactory(a.abi, a.bytecode, signer).deploy(...args);
  await c.waitForDeployment();
  const address = await c.getAddress();
  console.log(`  ${name.padEnd(14)} ${address}`);
  return address;
}

async function main() {
  const p = provider();
  const admin = new ethers.NonceManager(hdRoot().deriveChild(0).connect(p));
  const net = await p.getNetwork();
  const adminAddress = await admin.getAddress();
  const bal = await p.getBalance(adminAddress);
  console.log(`Chaine ${net.chainId} | admin ${adminAddress} | solde ${ethers.formatEther(bal)}`);
  if (bal === 0n) throw new Error("L'admin n'a pas de jeton natif : verifie l'airdrop de la L1");

  console.log("Deploiement :");
  const contracts = {
    EURToken: await deploy(admin, "EURToken"),
    GasFunder: await deploy(admin, "GasFunder"),
    FraudRegistry: await deploy(admin, "FraudRegistry", ["Admin consortium FraudNet"]),
  };
  fs.writeFileSync(DEPLOYMENT_FILE, JSON.stringify({
    chainId: Number(net.chainId), rpcUrl: process.env.L1_RPC_URL, contracts, deployedAt: new Date().toISOString(),
  }, null, 2));
  console.log("-> deployment.json");
}

main().catch((e) => { console.error(e.shortMessage || e.message); process.exit(1); });
