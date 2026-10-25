// 部署 AscCatSamuraiV2：npm run deploy:amoy（測試網）或 npm run deploy:polygon（主網）
// 部署後用部署者錢包設定：配件選項、轉蛋獎池、舊 0~30 號配件、價格、販售開關；最後把 owner 轉給 NFT_OWNER
const { ethers, network } = require("hardhat");
const { LEGACY, optionArgs, gachaArgs } = require("./traits");
require("dotenv").config();

const U = (n) => ethers.parseUnits(String(n || 0), 6);

async function main() {
    const env = process.env;
    const [deployer] = await ethers.getSigners();
    const main = network.name === "polygon";
    console.log(`網路：${network.name}｜部署者：${deployer.address}`);

    let usdt = env.USDT_ADDRESS;
    let oldNft = env.OLD_NFT;
    if (!main) {
        const t = await (await ethers.getContractFactory("MockUSDT")).deploy();
        await t.waitForDeployment();
        usdt = await t.getAddress();
        const o = await (await ethers.getContractFactory("MockOldNFT")).deploy();
        await o.waitForDeployment();
        oldNft = await o.getAddress();
        console.log(`測試網：tUSDT ${usdt}（任何人可 mint）｜舊 NFT ${oldNft}（任何人可 mint(地址, 編號)）`);
    }
    const treasury = env.TREASURY ? ethers.getAddress(env.TREASURY.trim()) : deployer.address;
    const max = Number(env.MAX_SUPPLY || 500);

    const nft = await (await ethers.getContractFactory("AscCatSamuraiV2")).deploy(
        deployer.address, usdt, treasury, oldNft, LEGACY.length, max, env.BASE_URI || ""
    );
    await nft.waitForDeployment();
    const address = await nft.getAddress();
    console.log(`\n已部署 AscCatSamuraiV2：${address}`);

    const send = async (label, p) => {
        await (await p).wait();
        console.log(`  ✓ ${label}`);
    };
    const opts = optionArgs();
    for (let c = 0; c < opts.length; c++) await send(`配件第 ${c} 類（${opts[c].weights.length} 個）`, nft.setOptions(c, opts[c].weights, opts[c].rare));
    const g = gachaArgs();
    await send(`轉蛋獎池（${g.cats.length} 個獎項）`, nft.setGachaPool(g.cats, g.idxs, g.weights, g.miss));
    await send(`舊 0~${LEGACY.length - 1} 號配件`, nft.setLegacyTraits(LEGACY.map((_, i) => i), LEGACY));
    await send("鎖定舊配件", nft.lockLegacy());
    await send(
        `價格 隨機 ${env.PRICE_RANDOM || 0}／自訂 ${env.PRICE_CUSTOM}／換裝 ${env.PRICE_CHANGE}／VIP ${env.PRICE_VIP}／轉蛋 ${env.PRICE_GACHA} USDT`,
        nft.setPrices(U(env.PRICE_RANDOM), U(env.PRICE_CUSTOM), U(env.PRICE_CHANGE), U(env.PRICE_VIP), U(env.PRICE_GACHA))
    );
    await send(`販售 ${env.SALE_OPEN === "true" ? "開啟" : "關閉"}，隨機每人上限 ${env.MAX_RANDOM_PER_WALLET || 0}`, nft.setSale(env.SALE_OPEN === "true", Number(env.MAX_RANDOM_PER_WALLET || 0)));

    if (env.NFT_OWNER && ethers.getAddress(env.NFT_OWNER.trim()) !== deployer.address) {
        const o = ethers.getAddress(env.NFT_OWNER.trim());
        await send(`owner 轉移第一步 → ${o}（請用該錢包／Safe 按 acceptOwnership）`, nft.transferOwnership(o));
    }
    console.log("\n下一步：");
    console.log(`  1. 驗證原始碼：npx hardhat verify --network ${network.name} ${address} ${deployer.address} ${usdt} ${treasury} ${oldNft} ${LEGACY.length} ${max} "${env.BASE_URI || ""}"`);
    console.log(`  2. 2026_asc_web3_ipfs 的 GitHub Secrets／config 填 NFT_V2_ADDRESS=${address}`);
    console.log(`  3. 網站 config.js 填 nftV2: "${address}"`);
}

main().catch((e) => {
    console.error(e);
    process.exitCode = 1;
});
