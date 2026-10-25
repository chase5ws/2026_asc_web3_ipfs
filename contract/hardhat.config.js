require("@nomicfoundation/hardhat-toolbox");
require("dotenv").config();

const { DEPLOYER_PRIVATE_KEY, POLYGON_RPC_URL, AMOY_RPC_URL, POLYGONSCAN_API_KEY } = process.env;
const accounts = DEPLOYER_PRIVATE_KEY ? [DEPLOYER_PRIVATE_KEY] : [];

/** @type import("hardhat/config").HardhatUserConfig */
module.exports = {
    solidity: {
        version: "0.8.24",
        settings: { optimizer: { enabled: true, runs: 200 } }
    },
    networks: {
        polygon: { url: POLYGON_RPC_URL || "https://polygon-bor-rpc.publicnode.com", chainId: 137, accounts },
        // Polygon 測試網：先在這裡部署試跑（免費測試幣：https://faucet.polygon.technology）
        amoy: { url: AMOY_RPC_URL || "https://rpc-amoy.polygon.technology", chainId: 80002, accounts }
    },
    etherscan: { apiKey: POLYGONSCAN_API_KEY || "" }
};
