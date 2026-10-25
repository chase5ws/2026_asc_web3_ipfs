const { expect } = require("chai");
const { ethers } = require("hardhat");
const { loadFixture } = require("@nomicfoundation/hardhat-toolbox/network-helpers");
const { TRAITS, LEGACY, optionArgs, gachaArgs } = require("../scripts/traits");

const U = (n) => ethers.parseUnits(String(n), 6);
const coder = ethers.AbiCoder.defaultAbiCoder();
const unpack = (p) => [0, 1, 2, 3, 4].map((c) => Number((BigInt(p) >> BigInt(8 * c)) & 0xffn));
const pack = (t) => t.reduce((a, v, c) => a | (BigInt(v) << BigInt(8 * c)), 0n);
const idx = (cat, name) => TRAITS.categories[cat].options.findIndex((o) => o.name === name);
const firstNormal = (cat, skip = 0) => TRAITS.categories[cat].options.map((o, i) => [o, i]).filter(([o]) => o.tier === "normal")[skip][1];
const normalCombo = (k = 0) => [firstNormal(0, k), firstNormal(1, k), firstNormal(2, k), firstNormal(3, k), firstNormal(4, k)];

/** 跟合約一樣：用 seed 算出隨機配件 */
function rollCombo(seed) {
    const opts = optionArgs();
    return opts.map((o, c) => {
        const total = o.weights.reduce((a, b) => a + b, 0);
        const roll = BigInt(ethers.keccak256(coder.encode(["bytes32", "uint256"], [seed, c]))) % BigInt(total);
        let acc = 0n;
        for (let i = 0; i < o.weights.length; i++) {
            acc += BigInt(o.weights[i]);
            if (roll < acc) return i;
        }
    });
}

async function events(tx, nft, name) {
    const rc = await tx.wait();
    return rc.logs.map((l) => { try { return nft.interface.parseLog(l); } catch { return null; } }).filter((e) => e && e.name === name);
}

async function deploy() {
    const [owner, treasury, alice, bob, carol] = await ethers.getSigners();
    const usdt = await (await ethers.getContractFactory("MockUSDT")).deploy();
    const old = await (await ethers.getContractFactory("MockOldNFT")).deploy();
    const nft = await (await ethers.getContractFactory("AscCatSamuraiV2")).deploy(
        owner.address, await usdt.getAddress(), treasury.address, await old.getAddress(), LEGACY.length, 500, "https://x.io/v2/metadata/"
    );
    const opts = optionArgs();
    for (let c = 0; c < 5; c++) await nft.setOptions(c, opts[c].weights, opts[c].rare);
    const g = gachaArgs();
    await nft.setGachaPool(g.cats, g.idxs, g.weights, g.miss);
    await nft.setLegacyTraits(LEGACY.map((_, i) => i), LEGACY);
    await nft.lockLegacy();
    await nft.setPrices(0, U(5), U(2), U(20), U(1));
    await nft.setSale(true, 3);
    for (const u of [alice, bob, carol]) {
        await usdt.mint(u.address, U(1000));
        await usdt.connect(u).approve(await nft.getAddress(), ethers.MaxUint256);
    }
    await old.mint(alice.address, 0);
    await old.mint(alice.address, 1);
    await old.mint(bob.address, 2);
    return { nft, usdt, old, owner, treasury, alice, bob, carol };
}

describe("AscCatSamuraiV2", function () {
    describe("舊 NFT 領回", function () {
        it("持有者免費領回同編號、同配件", async function () {
            const { nft, alice } = await loadFixture(deploy);
            await expect(nft.connect(alice).claim([0, 1])).to.emit(nft, "Minted");
            expect(await nft.ownerOf(0)).to.equal(alice.address);
            expect((await nft.traitsOf(1)).map(Number)).to.deep.equal(LEGACY[1]);
            expect(await nft.totalSupply()).to.equal(2);
            expect(await nft.nextId()).to.equal(LEGACY.length);
        });
        it("不是舊持有者、重複領、超過 30 號都會被擋", async function () {
            const { nft, alice, bob } = await loadFixture(deploy);
            await expect(nft.connect(bob).claim([0])).to.be.revertedWithCustomError(nft, "NotOldOwner");
            await nft.connect(alice).claim([0]);
            await expect(nft.connect(alice).claim([0])).to.be.revertedWithCustomError(nft, "ERC721InvalidSender");
            await expect(nft.connect(alice).claim([31])).to.be.revertedWithCustomError(nft, "NotLegacy");
        });
        it("鎖定後不能再改舊配件", async function () {
            const { nft } = await loadFixture(deploy);
            await expect(nft.setLegacyTraits([3], [LEGACY[3]])).to.be.revertedWithCustomError(nft, "IsLocked");
        });
    });

    describe("隨機鑄造", function () {
        it("從 31 號開始，配件可由 RandomSeed 事件驗算", async function () {
            const { nft, alice } = await loadFixture(deploy);
            const tx = await nft.connect(alice).randomMint();
            const [seedEv] = await events(tx, nft, "RandomSeed");
            const [mint] = await events(tx, nft, "Minted");
            expect(mint.args.tokenId).to.equal(31n);
            const a = seedEv.args;
            const rc = await tx.wait();
            const prev = await ethers.provider.getBlock(rc.blockNumber - 1);
            expect(a.prevBlockHash).to.equal(prev.hash);
            const seed = ethers.keccak256(coder.encode(["bytes32", "uint256", "address", "uint256"], [a.prevBlockHash, a.prevrandao, alice.address, a.nonce]));
            expect(a.seed).to.equal(seed);
            expect(unpack(mint.args.traits)).to.deep.equal(rollCombo(seed));
            expect((await nft.traitsOf(31)).map(Number)).to.deep.equal(rollCombo(seed));
        });
        it("每個錢包上限、販售關閉、收費", async function () {
            const { nft, usdt, alice, treasury } = await loadFixture(deploy);
            for (let i = 0; i < 3; i++) await nft.connect(alice).randomMint();
            await expect(nft.connect(alice).randomMint()).to.be.revertedWithCustomError(nft, "WalletLimit");
            await nft.setSale(false, 0);
            await expect(nft.connect(alice).randomMint()).to.be.revertedWithCustomError(nft, "SaleClosed");
            await nft.setSale(true, 0);
            await nft.setPrices(U(1), U(5), U(2), U(20), U(1));
            await expect(nft.connect(alice).randomMint()).to.changeTokenBalances(usdt, [alice, treasury], [-U(1), U(1)]);
        });
        it("鑄出來的組合都不重複", async function () {
            const { nft, alice } = await loadFixture(deploy);
            await nft.setSale(true, 0);
            const seen = new Set(LEGACY.map((t) => pack(t).toString()));
            for (let i = 0; i < 40; i++) {
                const tx = await nft.connect(alice).randomMint();
                const [m] = await events(tx, nft, "Minted");
                const k = m.args.traits.toString();
                expect(seen.has(k)).to.equal(false);
                seen.add(k);
            }
        });
        it("賣完、上限只能調高", async function () {
            const { nft, alice } = await loadFixture(deploy);
            await expect(nft.setMaxSupply(10)).to.be.revertedWithCustomError(nft, "CannotShrink");
            const [owner, treasury] = await ethers.getSigners();
            const small = await (await ethers.getContractFactory("AscCatSamuraiV2")).deploy(
                owner.address, await nft.usdt(), treasury.address, await nft.oldNft(), LEGACY.length, LEGACY.length + 1, ""
            );
            const opts = optionArgs();
            for (let c = 0; c < 5; c++) await small.setOptions(c, opts[c].weights, opts[c].rare);
            await small.setSale(true, 0);
            await small.connect(alice).randomMint();
            await expect(small.connect(alice).randomMint()).to.be.revertedWithCustomError(small, "SoldOut");
            await small.setMaxSupply(LEGACY.length + 2);
            await small.connect(alice).randomMint();
        });
    });

    describe("VIP、自訂、換裝", function () {
        it("VIP 付費一次，不能重複買", async function () {
            const { nft, usdt, alice, treasury } = await loadFixture(deploy);
            await expect(nft.connect(alice).buyVip()).to.changeTokenBalances(usdt, [alice, treasury], [-U(20), U(20)]);
            expect(await nft.isVip(alice.address)).to.equal(true);
            await expect(nft.connect(alice).buyVip()).to.be.revertedWithCustomError(nft, "AlreadyVip");
            expect(await nft.totalPaid(alice.address)).to.equal(U(20));
        });
        it("自訂：非 VIP 擋、每次收費、組合不能重複", async function () {
            const { nft, usdt, alice, bob, treasury } = await loadFixture(deploy);
            const t = normalCombo(0);
            await expect(nft.connect(alice).customMint(t)).to.be.revertedWithCustomError(nft, "NotVip");
            await nft.connect(alice).buyVip();
            await expect(nft.connect(alice).customMint(t)).to.changeTokenBalances(usdt, [alice, treasury], [-U(5), U(5)]);
            expect((await nft.traitsOf(31)).map(Number)).to.deep.equal(t);
            expect(await nft.comboOwner(t)).to.equal(31n);
            await nft.connect(bob).buyVip();
            await expect(nft.connect(bob).customMint(t)).to.be.revertedWithCustomError(nft, "ComboTaken").withArgs(31);
            await expect(nft.connect(bob).customMint([99, 0, 0, 0, 0])).to.be.revertedWithCustomError(nft, "BadTrait");
        });
        it("自訂：稀有配件要消耗背包道具", async function () {
            const { nft, alice } = await loadFixture(deploy);
            await nft.connect(alice).buyVip();
            const t = normalCombo(0);
            t[2] = idx(2, "Armor1"); // 黃金鎧甲（超稀有）
            await expect(nft.connect(alice).customMint(t)).to.be.revertedWithCustomError(nft, "NoItem");
            await nft.giveItems(alice.address, 2, t[2], 1);
            await nft.connect(alice).customMint(t);
            expect(await nft.itemBalance(alice.address, 2, t[2])).to.equal(0n);
        });
        it("換裝：換下的稀有配件退回背包，舊組合釋放給別人用", async function () {
            const { nft, usdt, alice, bob, treasury } = await loadFixture(deploy);
            await nft.connect(alice).buyVip();
            const t = normalCombo(0);
            t[3] = idx(3, "Common99"); // 金色閃電眼
            await nft.giveItems(alice.address, 3, t[3], 1);
            await nft.connect(alice).customMint(t);
            const t2 = [...t];
            t2[3] = firstNormal(3, 1);
            await expect(nft.connect(alice).changeTraits(31, t2)).to.changeTokenBalances(usdt, [alice, treasury], [-U(2), U(2)]);
            expect(await nft.itemBalance(alice.address, 3, t[3])).to.equal(1n); // 退回
            expect((await nft.traitsOf(31)).map(Number)).to.deep.equal(t2);
            expect(await nft.comboOwner(t)).to.equal(ethers.MaxUint256);
            // 再換回去會消耗道具
            await nft.connect(alice).changeTraits(31, t);
            expect(await nft.itemBalance(alice.address, 3, t[3])).to.equal(0n);
            // 別人不能換、沒變不能換
            await nft.connect(bob).buyVip();
            await expect(nft.connect(bob).changeTraits(31, t2)).to.be.revertedWithCustomError(nft, "NotTokenOwner");
            await expect(nft.connect(alice).changeTraits(31, t)).to.be.revertedWithCustomError(nft, "NoChange");
        });
        it("舊 NFT 也能換裝，原本的稀有配件退回背包", async function () {
            const { nft, alice } = await loadFixture(deploy);
            await nft.connect(alice).claim([0]); // 0 號 Body = Original1（稀有）
            await nft.connect(alice).buyVip();
            const t = (await nft.traitsOf(0)).map(Number);
            expect(t[1]).to.equal(idx(1, "Original1"));
            const t2 = [...t];
            t2[1] = firstNormal(1, 5);
            await nft.connect(alice).changeTraits(0, t2);
            expect(await nft.itemBalance(alice.address, 1, t[1])).to.equal(1n);
        });
    });

    describe("轉蛋", function () {
        it("只有 VIP、一次 1~10 抽、收費、結果可驗算", async function () {
            const { nft, usdt, alice, treasury } = await loadFixture(deploy);
            await expect(nft.connect(alice).gacha(1)).to.be.revertedWithCustomError(nft, "NotVip");
            await nft.connect(alice).buyVip();
            await expect(nft.connect(alice).gacha(0)).to.be.revertedWithCustomError(nft, "BadAmount");
            await expect(nft.connect(alice).gacha(11)).to.be.revertedWithCustomError(nft, "BadAmount");
            const g = gachaArgs();
            const total = BigInt(g.miss + g.weights.reduce((a, b) => a + b, 0));
            let hits = 0;
            for (let round = 0; round < 5; round++) {
                const before = await usdt.balanceOf(treasury.address);
                const tx = await nft.connect(alice).gacha(10);
                expect((await usdt.balanceOf(treasury.address)) - before).to.equal(U(10));
                const pulls = await events(tx, nft, "GachaPull");
                const seeds = await events(tx, nft, "RandomSeed");
                expect(pulls.length).to.equal(10);
                for (let i = 0; i < 10; i++) {
                    const p = pulls[i].args;
                    expect(p.seed).to.equal(seeds[i].args.seed);
                    expect(p.totalWeight).to.equal(total);
                    expect(p.roll).to.equal(BigInt(p.seed) % total);
                    // 依獎池順序判斷
                    let acc = 0n, want = null;
                    for (let k = 0; k < g.cats.length; k++) {
                        acc += BigInt(g.weights[k]);
                        if (p.roll < acc) { want = [g.cats[k], g.idxs[k]]; break; }
                    }
                    expect(p.hit).to.equal(want !== null);
                    if (want) { expect([Number(p.cat), Number(p.idx)]).to.deep.equal(want); hits++; }
                }
            }
            // 背包總數 = 抽中次數
            const bp = await nft.backpack(alice.address);
            const sum = bp.flat().reduce((a, b) => a + Number(b), 0);
            expect(sum).to.equal(hits);
        });
    });

    describe("owner 與其他", function () {
        it("owner 功能非 owner 不能用", async function () {
            const { nft, alice } = await loadFixture(deploy);
            await expect(nft.connect(alice).setPrices(0, 0, 0, 0, 0)).to.be.revertedWithCustomError(nft, "OwnableUnauthorizedAccount");
            await expect(nft.connect(alice).giveItems(alice.address, 0, 0, 1)).to.be.revertedWithCustomError(nft, "OwnableUnauthorizedAccount");
            await expect(nft.connect(alice).setVip(alice.address, true)).to.be.revertedWithCustomError(nft, "OwnableUnauthorizedAccount");
        });
        it("選項只能增加不能減少", async function () {
            const { nft } = await loadFixture(deploy);
            await expect(nft.setOptions(0, [1], [false])).to.be.revertedWithCustomError(nft, "CannotShrink");
            const o = optionArgs()[0];
            await nft.setOptions(0, [...o.weights, 50], [...o.rare, false]);
            expect((await nft.options(0)).weights.length).to.equal(o.weights.length + 1);
        });
        it("暫停後全部擋下", async function () {
            const { nft, alice } = await loadFixture(deploy);
            await nft.pause();
            await expect(nft.connect(alice).randomMint()).to.be.revertedWithCustomError(nft, "EnforcedPause");
            await expect(nft.connect(alice).claim([0])).to.be.revertedWithCustomError(nft, "EnforcedPause");
        });
        it("tokenURI、ERC-4906、gift、兩步驟轉移 owner", async function () {
            const { nft, alice, bob } = await loadFixture(deploy);
            await nft.gift(bob.address, normalCombo(1));
            expect(await nft.tokenURI(31)).to.equal("https://x.io/v2/metadata/31.json");
            expect(await nft.supportsInterface("0x49064906")).to.equal(true);
            await nft.transferOwnership(alice.address);
            await nft.connect(alice).acceptOwnership();
            expect(await nft.owner()).to.equal(alice.address);
        });
        it("traitsRange 給出圖程式用", async function () {
            const { nft, alice } = await loadFixture(deploy);
            await nft.connect(alice).claim([0]);
            await nft.connect(alice).randomMint();
            const [ex, tr] = await nft.traitsRange(0, 1000);
            expect(ex.length).to.equal(32);
            expect(ex[0]).to.equal(true);
            expect(ex[1]).to.equal(false);
            expect(ex[31]).to.equal(true);
            expect(unpack(tr[0])).to.deep.equal(LEGACY[0]);
        });
    });
});
