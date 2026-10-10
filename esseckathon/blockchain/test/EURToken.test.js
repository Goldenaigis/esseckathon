const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("EURToken", function () {
  async function setup() {
    const [admin, alice, bob] = await ethers.getSigners();
    const token = await (await ethers.getContractFactory("EURToken")).deploy();
    const funder = await (await ethers.getContractFactory("GasFunder")).deploy();
    return { token, funder, admin, alice, bob };
  }

  it("2 decimales et mint reserve a l'admin", async function () {
    const { token, alice } = await setup();
    expect(await token.decimals()).to.equal(2);
    await token.batchMint([alice.address], [10000]);
    expect(await token.balanceOf(alice.address)).to.equal(10000);
    await expect(token.connect(alice).batchMint([alice.address], [1]))
      .to.be.revertedWithCustomError(token, "OwnableUnauthorizedAccount");
  });

  it("pay() transfere et emet Payment avec la reference du virement", async function () {
    const { token, alice, bob } = await setup();
    await token.batchMint([alice.address], [10000]);
    const ref = ethers.encodeBytes32String("TX_0000001");
    await expect(token.connect(alice).pay(bob.address, 4865, ref, 1786406819))
      .to.emit(token, "Payment").withArgs(alice.address, bob.address, 4865, ref, 1786406819);
    expect(await token.balanceOf(bob.address)).to.equal(4865);
    await expect(token.connect(bob).pay(alice.address, 99999, ref, 0))
      .to.be.revertedWithCustomError(token, "ERC20InsufficientBalance");
  });

  it("GasFunder distribue des montants differents en une transaction", async function () {
    const { funder, alice, bob } = await setup();
    const before = await ethers.provider.getBalance(bob.address);
    await funder.fund([alice.address, bob.address], [1n, 2n], { value: 3n });
    expect(await ethers.provider.getBalance(bob.address)).to.equal(before + 2n);
    await expect(funder.fund([alice.address], [1n], { value: 2n })).to.be.revertedWithCustomError(funder, "WrongValue");
  });
});
