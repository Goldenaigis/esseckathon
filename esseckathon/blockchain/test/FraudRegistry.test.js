const { expect } = require("chai");
const { ethers } = require("hardhat");

const h = (id) => ethers.keccak256(ethers.toUtf8Bytes("sel-test:" + id));

describe("FraudRegistry", function () {
  async function setup() {
    const [admin, bank2, outsider] = await ethers.getSigners();
    const R = await ethers.getContractFactory("FraudRegistry");
    const reg = await R.deploy("BNK_01");
    await reg.addMember(bank2.address, "BNK_02");
    return { reg, admin, bank2, outsider };
  }

  it("un compte non signale n'est pas flagge", async function () {
    const { reg } = await setup();
    const [flagged, count] = await reg.isFlagged(h("ACC_000001"));
    expect(flagged).to.equal(false);
    expect(count).to.equal(0);
  });

  it("deux banques signalent le meme compte", async function () {
    const { reg, bank2 } = await setup();
    await expect(reg.reportAlert(h("ACC_000042"), 80, 0, ethers.ZeroHash)).to.emit(reg, "AlertReported");
    await reg.connect(bank2).reportAlert(h("ACC_000042"), 95, 2, ethers.ZeroHash);
    const [flagged, count, maxScore] = await reg.isFlagged(h("ACC_000042"));
    expect(flagged).to.equal(true);
    expect(count).to.equal(2);
    expect(maxScore).to.equal(95);
  });

  it("re-signaler ne double pas le compteur", async function () {
    const { reg } = await setup();
    await reg.reportAlert(h("ACC_1"), 50, 1, ethers.ZeroHash);
    await reg.reportAlert(h("ACC_1"), 70, 1, ethers.ZeroHash);
    const [, count, maxScore] = await reg.isFlagged(h("ACC_1"));
    expect(count).to.equal(1);
    expect(maxScore).to.equal(70);
  });

  it("retrait d'un faux positif", async function () {
    const { reg } = await setup();
    await reg.reportAlert(h("ACC_2"), 60, 5, ethers.ZeroHash);
    await expect(reg.retractAlert(h("ACC_2"))).to.emit(reg, "AlertRetracted");
    const [flagged] = await reg.isFlagged(h("ACC_2"));
    expect(flagged).to.equal(false);
    await expect(reg.retractAlert(h("ACC_2"))).to.be.revertedWithCustomError(reg, "NoActiveReport");
  });

  it("refuse les non-membres et les scores > 100", async function () {
    const { reg, outsider } = await setup();
    await expect(reg.connect(outsider).reportAlert(h("X"), 50, 0, ethers.ZeroHash))
      .to.be.revertedWithCustomError(reg, "NotMember");
    await expect(reg.reportAlert(h("X"), 101, 0, ethers.ZeroHash))
      .to.be.revertedWithCustomError(reg, "InvalidScore");
    await expect(reg.connect(outsider).addMember(outsider.address, "pirate"))
      .to.be.revertedWithCustomError(reg, "NotAdmin");
  });

  it("notarise un jeu de donnees", async function () {
    const { reg } = await setup();
    await expect(reg.anchorDataset(ethers.id("dataset"), "fraudnet v1.0.0")).to.emit(reg, "DatasetAnchored");
  });
});
