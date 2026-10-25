// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {ERC721} from "@openzeppelin/contracts/token/ERC721/ERC721.sol";

/// @notice 測試用 USDT（6 位小數，任何人都能 mint）
contract MockUSDT is ERC20 {
    constructor() ERC20("Test USDT", "tUSDT") {}

    function decimals() public pure override returns (uint8) {
        return 6;
    }

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }
}

/// @notice 測試用舊 NFT（任何人都能指定編號 mint）
contract MockOldNFT is ERC721 {
    constructor() ERC721("Old Cat", "OLD") {}

    function mint(address to, uint256 id) external {
        _mint(to, id);
    }
}
