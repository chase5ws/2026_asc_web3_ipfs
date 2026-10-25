// 部署 AscCatSamuraiV2：npm run deploy:amoy（測試網）或 npm run deploy:polygon（主網）
// 部署後用部署者錢包設定：配件選項、轉蛋獎池、價格、販售開關；（選填）空投給舊系列持有者；最後把 owner 轉給 NFT_OWNER
const { ethers, network } = require("hardhat");
const { optionArgs, gachaArgs } = require("./traits");
require("dotenv").config();

const U = (n) => ethers.parseUnits(String(n || 0), 6);

/** 鏈下讀舊系列每一顆的持有者（合約本身不記錄任何舊資料） */
async function oldHolders(address) {
    const old = new ethers.Contract(address, ["function totalSupply() view returns (uint256)", "function tokenByIndex(uint256) view returns (uint256)", "function ownerOf(uint256) view returns (address)"], ethers.provider);
    const n = Number(await old.totalSupply());
    const out = [];
    for (let i = 0; i < n; i++) {
        const id = await old.tokenByIndex(i);
        out.push({ id: Number(id), owner: await old.ownerOf(id) });
    }
    return out;
}

async function main() {
    const env = process.env;
    const [deployer] = await ethers.getSigners();
    console.log(`網路：${network.name}｜部署者：${deployer.address}`);

    let usdt = env.USDT_ADDRESS;
    if (network.name !== "polygon") {
        const t = await (await ethers.getContractFactory("MockUSDT")).deploy();
        await t.waitForDeployment();
        usdt = await t.getAddress();
        console.log(`測試網：tUSDT ${usdt}（任何人都能 mint(地址, 數量)，6 位小數）`);
    }
    const treasury = env.TREASURY ? ethers.getAddress(env.TREASURY.trim()) : deployer.address;
    const max = Number(env.MAX_SUPPLY || 500);

    const nft = await (await ethers.getContractFactory("AscCatSamuraiV2")).deploy(deployer.address, usdt, treasury, max, env.BASE_URI || "");
    await nft.waitForDeployment();
    const address = await nft.getAddress();
    const block = (await nft.deploymentTransaction().wait()).blockNumber;
    console.log(`\n已部署 AscCatSamuraiV2：${address}（區塊 ${block}）`);

    const send = async (label, p) => {
        await (await p).wait();
        console.log(`  ✓ ${label}`);
    };
    const opts = optionArgs();
    for (let c = 0; c < opts.length; c++) await send(`配件第 ${c} 類（${opts[c].weights.length} 個）`, nft.setOptions(c, opts[c].weights, opts[c].rare));
    const g = gachaArgs();
    await send(`轉蛋獎池（${g.cats.length} 個獎項）`, nft.setGachaPool(g.cats, g.idxs, g.weights, g.miss));
    await send(
        `價格 隨機 ${env.PRICE_RANDOM || 0}／自訂 ${env.PRICE_CUSTOM}／換裝 ${env.PRICE_CHANGE}／VIP ${env.PRICE_VIP}／轉蛋 ${env.PRICE_GACHA} USDT`,
        nft.setPrices(U(env.PRICE_RANDOM), U(env.PRICE_CUSTOM), U(env.PRICE_CHANGE), U(env.PRICE_VIP), U(env.PRICE_GACHA))
    );

    // 空投給舊系列持有者：每持有一顆舊的，就發一顆隨機配件的 V2
    if (env.AIRDROP_FROM && env.AIRDROP_FROM.trim() && network.name !== "polygon") {
        console.log("  （測試網略過空投：AIRDROP_FROM 是主網合約；要測空投請用 owner 呼叫 airdrop([你的地址])）");
    } else if (env.AIRDROP_FROM && env.AIRDROP_FROM.trim()) {
        const list = await oldHolders(env.AIRDROP_FROM.trim());
        console.log(`  舊系列 ${env.AIRDROP_FROM} 共 ${list.length} 顆，持有者 ${new Set(list.map((x) => x.owner)).size} 個錢包`);
        const to = list.map((x) => x.owner);
        for (let i = 0; i < to.length; i += 100) await send(`空投 ${Math.min(i + 100, to.length)}/${to.length}`, nft.airdrop(to.slice(i, i + 100)));
    }

    await send(`販售 ${env.SALE_OPEN === "true" ? "開啟" : "關閉"}，隨機每人上限 ${env.MAX_RANDOM_PER_WALLET || 0}`, nft.setSale(env.SALE_OPEN === "true", Number(env.MAX_RANDOM_PER_WALLET || 0)));

    if (env.NFT_OWNER && ethers.getAddress(env.NFT_OWNER.trim()) !== deployer.address) {
        const o = ethers.getAddress(env.NFT_OWNER.trim());
        await send(`owner 轉移第一步 → ${o}（請用該錢包／Safe 按 acceptOwnership）`, nft.transferOwnership(o));
    }
    console.log("\n下一步：");
    console.log(`  1. 驗證原始碼：npx hardhat verify --network ${network.name} ${address} ${deployer.address} ${usdt} ${treasury} ${max} "${env.BASE_URI || ""}"`);
    console.log(`  2. 2026_asc_web3_ipfs 的 GitHub → Settings → Secrets and variables → Actions → Variables：NFT_V2_ADDRESS=${address}`);
    console.log(`  3. 網站 config.js：nftV2: "${address}", v2DeployBlock: ${block}, usdt: "${usdt}"`);
}

main().catch((e) => {
    console.error(e);
    process.exitCode = 1;
});
