// 查看 V2 狀態：npm run status:polygon
const { ethers } = require("hardhat");
require("dotenv").config();

async function main() {
    const nft = await ethers.getContractAt("AscCatSamuraiV2", process.env.NFT_V2_ADDRESS);
    const f = (x) => ethers.formatUnits(x, 6);
    const [r, c, ch, v, g] = await nft.prices();
    console.log(`owner ${await nft.owner()}｜收款 ${await nft.treasury()}`);
    console.log(`已鑄造 ${await nft.totalSupply()}｜下一個編號 ${await nft.nextId()}／上限 ${await nft.maxSupply()}｜販售 ${(await nft.saleOpen()) ? "開" : "關"}｜暫停 ${await nft.paused()}`);
    console.log(`價格（USDT）隨機 ${f(r)}｜自訂 ${f(c)}｜換裝 ${f(ch)}｜VIP ${f(v)}｜轉蛋 ${f(g)}｜隨機每人上限 ${await nft.maxRandomPerWallet()}`);
}

main().catch((e) => {
    console.error(e);
    process.exitCode = 1;
});
