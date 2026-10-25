// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC721} from "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import {ERC721Enumerable} from "@openzeppelin/contracts/token/ERC721/extensions/ERC721Enumerable.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Ownable2Step} from "@openzeppelin/contracts/access/Ownable2Step.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Strings} from "@openzeppelin/contracts/utils/Strings.sol";

interface IOldNFT {
    function ownerOf(uint256 tokenId) external view returns (address);
}

/// @title AscCatSamuraiV2 - 配件記在鏈上的 NFT：隨機鑄造、VIP 自訂、轉蛋、換裝、舊 NFT 領回
/// @notice 配件類別固定 5 類（順序）：0 Wepon、1 Body、2 Clothes、3 Face、4 Dress。
///   每類的選項編號對照表在 2026_asc_web3_ipfs 的 traits.json。
///   付款一律用 USDT（Polygon），直接轉給 treasury（Safe 多簽），合約本身不存錢。
///
///   claim(ids)                舊合約 0~30 號的持有者免費領回同款（同編號、同配件）
///   randomMint()              任何人：隨機配件（費用 randomFee，可為 0；每個錢包有上限）
///   buyVip()                  付 vipFee 成為永久 VIP
///   customMint(traits)        VIP：自選配件，每次付 customFee
///   changeTraits(id, traits)  VIP：替自己的 NFT 換裝，每次付 changeFee
///   gacha(times)              VIP：轉蛋抽稀有配件，每抽付 gachaFee；抽中的配件放進背包
///
///   稀有配件（rare）不能直接選，要從背包消耗 1 個；換裝換下來的稀有配件會退回背包（不會消失）。
///   每一顆 NFT 的配件組合都不重複。
///
///   偽隨機（每次都會發出 RandomSeed 事件，任何人都能驗算）：
///     seed = keccak256(abi.encode(上一個區塊的 hash, block.prevrandao, 呼叫者, nonce))
///     隨機鑄造：第 c 類的 roll = uint256(keccak256(abi.encode(seed, c))) % 該類權重總和，
///               依權重順序落在哪個選項就是哪個；組合重複時 seed = keccak256(abi.encode(seed)) 重抽
///     轉蛋：roll = uint256(seed) % (獎池權重總和 + missWeight)，依獎池順序判斷，超過獎池＝沒中
contract AscCatSamuraiV2 is ERC721Enumerable, Ownable2Step, Pausable, ReentrancyGuard {
    using SafeERC20 for IERC20;
    using Strings for uint256;

    uint256 public constant CATS = 5;
    uint256 public constant MAX_GACHA_PER_TX = 10;
    uint256 private constant MAX_REROLL = 20;

    // 隨機的用途（RandomSeed 事件）
    uint8 public constant PURPOSE_MINT = 1;
    uint8 public constant PURPOSE_GACHA = 2;

    // Minted 事件的鑄造方式
    uint8 public constant KIND_CLAIM = 0;
    uint8 public constant KIND_RANDOM = 1;
    uint8 public constant KIND_CUSTOM = 2;
    uint8 public constant KIND_GIFT = 3;

    IERC20 public immutable usdt;
    IOldNFT public immutable oldNft;
    uint256 public immutable legacyCount;

    address public treasury;
    string private _base;
    uint256 public maxSupply;
    uint256 public nextId;
    bool public saleOpen;
    bool public legacyLocked;

    uint256 public randomFee;
    uint256 public customFee;
    uint256 public changeFee;
    uint256 public vipFee;
    uint256 public gachaFee;
    uint256 public maxRandomPerWallet; // 0 = 不限

    struct Option {
        uint16 weight; // 隨機鑄造的權重（0 = 隨機抽不到）
        bool rare; // true = 自訂／換裝要消耗背包裡的道具
    }
    Option[][CATS] private _options;

    struct Prize {
        uint8 cat;
        uint8 idx;
        uint16 weight;
    }
    Prize[] private _pool;
    uint32 public missWeight;

    mapping(uint256 => uint40) private _traits; // tokenId => 打包後的配件
    mapping(uint40 => uint256) private _comboTokenPlus1; // 配件組合 => tokenId + 1（0 = 沒人用）
    mapping(uint256 => bool) public legacyReady; // 舊編號已設定配件
    mapping(address => bool) public isVip;
    mapping(address => uint256) public randomMinted;
    mapping(address => uint256) public totalPaid;
    mapping(address => mapping(uint16 => uint256)) private _items; // 背包：使用者 => (cat<<8|idx) => 數量
    uint256 public nonce;

    event Minted(uint256 indexed tokenId, address indexed to, uint8 kind, uint40 traits);
    event TraitsChanged(uint256 indexed tokenId, address indexed owner, uint40 oldTraits, uint40 newTraits);
    event RandomSeed(address indexed user, uint8 indexed purpose, uint256 indexed ref, bytes32 prevBlockHash, uint256 prevrandao, uint256 nonce, bytes32 seed);
    event GachaPull(address indexed user, bytes32 seed, uint256 roll, uint256 totalWeight, bool hit, uint8 cat, uint8 idx);
    event ItemChanged(address indexed user, uint8 cat, uint8 idx, uint256 balance);
    event VipChanged(address indexed user, bool vip);
    event Paid(address indexed user, string what, uint256 amount);
    event PricesChanged(uint256 randomFee, uint256 customFee, uint256 changeFee, uint256 vipFee, uint256 gachaFee);
    event OptionsChanged(uint256 cat, uint256 count);
    event GachaPoolChanged(uint256 prizes, uint256 missWeight);
    event TreasuryChanged(address treasury);
    event SaleChanged(bool open, uint256 maxRandomPerWallet);
    event MaxSupplyChanged(uint256 maxSupply);
    event BaseURIChanged(string baseURI);
    event LegacyLocked();

    error ZeroAddress();
    error SaleClosed();
    error SoldOut();
    error NotVip();
    error AlreadyVip();
    error WalletLimit();
    error BadTrait(uint256 cat, uint256 idx);
    error ComboTaken(uint256 tokenId);
    error NoItem(uint256 cat, uint256 idx);
    error NotTokenOwner(uint256 tokenId);
    error NoChange();
    error BadAmount();
    error NotLegacy(uint256 tokenId);
    error LegacyNotReady(uint256 tokenId);
    error NotOldOwner(uint256 tokenId);
    error IsLocked();
    error LengthMismatch();
    error CannotShrink();
    error NoRandomResult();
    error EmptyPool();

    constructor(
        address initialOwner,
        address usdt_,
        address treasury_,
        address oldNft_,
        uint256 legacyCount_,
        uint256 maxSupply_,
        string memory baseURI_
    ) ERC721("Asc Cat Samurai V2", "ACS2") Ownable(initialOwner) {
        if (usdt_ == address(0) || treasury_ == address(0)) revert ZeroAddress();
        if (maxSupply_ < legacyCount_) revert BadAmount();
        usdt = IERC20(usdt_);
        treasury = treasury_;
        oldNft = IOldNFT(oldNft_);
        legacyCount = legacyCount_;
        maxSupply = maxSupply_;
        nextId = legacyCount_;
        _base = baseURI_;
    }

    // ───────────────────────────── 使用者 ─────────────────────────────

    /// @notice 舊合約的持有者免費領回同編號、同配件的 V2
    function claim(uint256[] calldata ids) external whenNotPaused nonReentrant {
        for (uint256 i; i < ids.length; ++i) {
            uint256 id = ids[i];
            if (id >= legacyCount) revert NotLegacy(id);
            if (!legacyReady[id]) revert LegacyNotReady(id);
            if (oldNft.ownerOf(id) != msg.sender) revert NotOldOwner(id);
            _safeMint(msg.sender, id); // 已領過會 revert（ERC721InvalidSender）
            emit Minted(id, msg.sender, KIND_CLAIM, _traits[id]);
        }
    }

    /// @notice 隨機鑄造一顆
    function randomMint() external whenNotPaused nonReentrant returns (uint256 id) {
        if (!saleOpen) revert SaleClosed();
        if (maxRandomPerWallet != 0 && randomMinted[msg.sender] >= maxRandomPerWallet) revert WalletLimit();
        id = _takeId();
        randomMinted[msg.sender]++;
        _pay(randomFee, "random");

        bytes32 seed = _seed(PURPOSE_MINT, id);
        uint40 combo;
        bool ok;
        for (uint256 r; r < MAX_REROLL; ++r) {
            combo = _rollCombo(seed);
            if (_comboTokenPlus1[combo] == 0) {
                ok = true;
                break;
            }
            seed = keccak256(abi.encode(seed));
        }
        if (!ok) revert NoRandomResult();
        _setTraits(id, combo);
        _safeMint(msg.sender, id);
        emit Minted(id, msg.sender, KIND_RANDOM, combo);
    }

    /// @notice 付費成為永久 VIP
    function buyVip() external whenNotPaused nonReentrant {
        if (isVip[msg.sender]) revert AlreadyVip();
        _pay(vipFee, "vip");
        isVip[msg.sender] = true;
        emit VipChanged(msg.sender, true);
    }

    /// @notice VIP：自選配件鑄造（稀有配件會從背包消耗 1 個）
    function customMint(uint8[5] calldata t) external whenNotPaused nonReentrant returns (uint256 id) {
        if (!saleOpen) revert SaleClosed();
        if (!isVip[msg.sender]) revert NotVip();
        id = _takeId();
        _pay(customFee, "custom");
        uint40 combo = _pack(t);
        for (uint256 c; c < CATS; ++c) {
            _checkOption(c, t[c]);
            if (_options[c][t[c]].rare) _useItem(msg.sender, c, t[c]);
        }
        _setTraits(id, combo);
        _safeMint(msg.sender, id);
        emit Minted(id, msg.sender, KIND_CUSTOM, combo);
    }

    /// @notice VIP：替自己的 NFT 換裝；換下來的稀有配件退回背包，換上的稀有配件從背包消耗
    function changeTraits(uint256 id, uint8[5] calldata t) external whenNotPaused nonReentrant {
        if (ownerOf(id) != msg.sender) revert NotTokenOwner(id);
        if (!isVip[msg.sender]) revert NotVip();
        uint40 oldCombo = _traits[id];
        uint40 combo = _pack(t);
        if (combo == oldCombo) revert NoChange();
        _pay(changeFee, "change");
        for (uint256 c; c < CATS; ++c) {
            uint8 o = uint8(oldCombo >> (8 * c));
            if (o == t[c]) continue;
            _checkOption(c, t[c]);
            if (o < _options[c].length && _options[c][o].rare) _addItem(msg.sender, c, o, 1);
            if (_options[c][t[c]].rare) _useItem(msg.sender, c, t[c]);
        }
        delete _comboTokenPlus1[oldCombo];
        _setTraits(id, combo);
        emit TraitsChanged(id, msg.sender, oldCombo, combo);
    }

    /// @notice VIP：轉蛋，一次 1~10 抽
    function gacha(uint256 times) external whenNotPaused nonReentrant {
        if (!isVip[msg.sender]) revert NotVip();
        if (times == 0 || times > MAX_GACHA_PER_TX) revert BadAmount();
        if (_pool.length == 0) revert EmptyPool();
        _pay(gachaFee * times, "gacha");
        uint256 total = missWeight;
        for (uint256 i; i < _pool.length; ++i) total += _pool[i].weight;
        for (uint256 n; n < times; ++n) {
            bytes32 seed = _seed(PURPOSE_GACHA, n);
            uint256 roll = uint256(seed) % total;
            uint256 acc;
            bool hit;
            uint8 cat;
            uint8 idx;
            for (uint256 i; i < _pool.length; ++i) {
                acc += _pool[i].weight;
                if (roll < acc) {
                    hit = true;
                    cat = _pool[i].cat;
                    idx = _pool[i].idx;
                    break;
                }
            }
            if (hit) _addItem(msg.sender, cat, idx, 1);
            emit GachaPull(msg.sender, seed, roll, total, hit, cat, idx);
        }
    }

    // ───────────────────────────── 查詢 ─────────────────────────────

    function traitsOf(uint256 id) external view returns (uint8[5] memory t) {
        _requireOwned(id);
        uint40 p = _traits[id];
        for (uint256 c; c < CATS; ++c) t[c] = uint8(p >> (8 * c));
    }

    /// @notice 給自動出圖程式用：一次讀 [from, to) 的存在與否與打包後的配件
    function traitsRange(uint256 from, uint256 to) external view returns (bool[] memory exists, uint40[] memory traits) {
        if (to > nextId) to = nextId;
        if (from > to) from = to;
        exists = new bool[](to - from);
        traits = new uint40[](to - from);
        for (uint256 i = from; i < to; ++i) {
            exists[i - from] = _ownerOf(i) != address(0);
            traits[i - from] = _traits[i];
        }
    }

    /// @notice 配件組合是否已被使用（回傳 tokenId，沒人用回傳 type(uint256).max）
    function comboOwner(uint8[5] calldata t) external view returns (uint256) {
        uint256 p = _comboTokenPlus1[_pack(t)];
        return p == 0 ? type(uint256).max : p - 1;
    }

    function itemBalance(address user, uint8 cat, uint8 idx) external view returns (uint256) {
        return _items[user][_key(cat, idx)];
    }

    /// @notice 一次讀某人整個背包：回傳每類每個選項的數量（依 traits.json 順序）
    function backpack(address user) external view returns (uint256[][5] memory out) {
        for (uint256 c; c < CATS; ++c) {
            out[c] = new uint256[](_options[c].length);
            for (uint256 i; i < _options[c].length; ++i) out[c][i] = _items[user][_key(uint8(c), uint8(i))];
        }
    }

    function options(uint256 cat) external view returns (uint16[] memory weights, bool[] memory rare) {
        Option[] storage o = _options[cat];
        weights = new uint16[](o.length);
        rare = new bool[](o.length);
        for (uint256 i; i < o.length; ++i) {
            weights[i] = o[i].weight;
            rare[i] = o[i].rare;
        }
    }

    function gachaPool() external view returns (Prize[] memory prizes, uint32 miss) {
        return (_pool, missWeight);
    }

    function prices() external view returns (uint256, uint256, uint256, uint256, uint256) {
        return (randomFee, customFee, changeFee, vipFee, gachaFee);
    }

    function tokenURI(uint256 id) public view override returns (string memory) {
        _requireOwned(id);
        return bytes(_base).length > 0 ? string.concat(_base, id.toString(), ".json") : "";
    }

    // ───────────────────────────── owner ─────────────────────────────

    function setPrices(uint256 random_, uint256 custom_, uint256 change_, uint256 vip_, uint256 gacha_) external onlyOwner {
        (randomFee, customFee, changeFee, vipFee, gachaFee) = (random_, custom_, change_, vip_, gacha_);
        emit PricesChanged(random_, custom_, change_, vip_, gacha_);
    }

    function setSale(bool open, uint256 maxRandomPerWallet_) external onlyOwner {
        saleOpen = open;
        maxRandomPerWallet = maxRandomPerWallet_;
        emit SaleChanged(open, maxRandomPerWallet_);
    }

    function setTreasury(address t) external onlyOwner {
        if (t == address(0)) revert ZeroAddress();
        treasury = t;
        emit TreasuryChanged(t);
    }

    function setBaseURI(string calldata b) external onlyOwner {
        _base = b;
        emit BaseURIChanged(b);
        emit BatchMetadataUpdate(0, type(uint256).max);
    }

    /// @notice 只能調高，不能低於已用到的編號
    function setMaxSupply(uint256 m) external onlyOwner {
        if (m < maxSupply) revert CannotShrink();
        maxSupply = m;
        emit MaxSupplyChanged(m);
    }

    /// @notice 設定某類的選項（可改權重／稀有，也可新增選項；選項數量不能減少，避免已鑄造的配件失效）
    function setOptions(uint256 cat, uint16[] calldata weights, bool[] calldata rare) external onlyOwner {
        if (cat >= CATS) revert BadTrait(cat, 0);
        if (weights.length != rare.length) revert LengthMismatch();
        if (weights.length < _options[cat].length || weights.length > 255) revert CannotShrink();
        delete _options[cat];
        for (uint256 i; i < weights.length; ++i) _options[cat].push(Option(weights[i], rare[i]));
        emit OptionsChanged(cat, weights.length);
    }

    function setGachaPool(uint8[] calldata cats, uint8[] calldata idxs, uint16[] calldata weights, uint32 miss) external onlyOwner {
        if (cats.length != idxs.length || cats.length != weights.length) revert LengthMismatch();
        delete _pool;
        for (uint256 i; i < cats.length; ++i) {
            _checkOption(cats[i], idxs[i]);
            _pool.push(Prize(cats[i], idxs[i], weights[i]));
        }
        missWeight = miss;
        emit GachaPoolChanged(cats.length, miss);
    }

    /// @notice 設定舊 0~30 號的配件（領回前要先設定；lockLegacy 之後不能再改）
    function setLegacyTraits(uint256[] calldata ids, uint8[5][] calldata t) external onlyOwner {
        if (legacyLocked) revert IsLocked();
        if (ids.length != t.length) revert LengthMismatch();
        for (uint256 i; i < ids.length; ++i) {
            uint256 id = ids[i];
            if (id >= legacyCount) revert NotLegacy(id);
            if (_ownerOf(id) != address(0)) revert IsLocked();
            if (legacyReady[id]) delete _comboTokenPlus1[_traits[id]];
            for (uint256 c; c < CATS; ++c) _checkOption(c, t[i][c]);
            _setTraits(id, _pack(t[i]));
            legacyReady[id] = true;
        }
    }

    function lockLegacy() external onlyOwner {
        legacyLocked = true;
        emit LegacyLocked();
    }

    function setVip(address user, bool vip) external onlyOwner {
        isVip[user] = vip;
        emit VipChanged(user, vip);
    }

    /// @notice 活動用：直接發配件到某人背包
    function giveItems(address user, uint8 cat, uint8 idx, uint256 amount) external onlyOwner {
        _checkOption(cat, idx);
        _addItem(user, cat, idx, amount);
    }

    /// @notice 活動用：免費送一顆指定配件的 NFT（不消耗背包）
    function gift(address to, uint8[5] calldata t) external onlyOwner returns (uint256 id) {
        id = _takeId();
        for (uint256 c; c < CATS; ++c) _checkOption(c, t[c]);
        uint40 combo = _pack(t);
        _setTraits(id, combo);
        _safeMint(to, id);
        emit Minted(id, to, KIND_GIFT, combo);
    }

    function pause() external onlyOwner {
        _pause();
    }

    function unpause() external onlyOwner {
        _unpause();
    }

    /// @notice 救回誤轉進合約的代幣
    function rescueERC20(address token, address to, uint256 amount) external onlyOwner {
        IERC20(token).safeTransfer(to, amount);
    }

    // ───────────────────────────── 內部 ─────────────────────────────

    function _takeId() private returns (uint256 id) {
        id = nextId;
        if (id >= maxSupply) revert SoldOut();
        nextId = id + 1;
    }

    function _pay(uint256 amount, string memory what) private {
        if (amount == 0) return;
        usdt.safeTransferFrom(msg.sender, treasury, amount);
        totalPaid[msg.sender] += amount;
        emit Paid(msg.sender, what, amount);
    }

    function _seed(uint8 purpose, uint256 ref) private returns (bytes32 seed) {
        uint256 n = nonce++;
        bytes32 prev = blockhash(block.number - 1);
        seed = keccak256(abi.encode(prev, block.prevrandao, msg.sender, n));
        emit RandomSeed(msg.sender, purpose, ref, prev, block.prevrandao, n, seed);
    }

    function _rollCombo(bytes32 seed) private view returns (uint40 combo) {
        for (uint256 c; c < CATS; ++c) {
            Option[] storage o = _options[c];
            uint256 total;
            for (uint256 i; i < o.length; ++i) total += o[i].weight;
            if (total == 0) revert BadTrait(c, 0);
            uint256 roll = uint256(keccak256(abi.encode(seed, c))) % total;
            uint256 acc;
            for (uint256 i; i < o.length; ++i) {
                acc += o[i].weight;
                if (roll < acc) {
                    combo |= uint40(i) << uint40(8 * c);
                    break;
                }
            }
        }
    }

    function _setTraits(uint256 id, uint40 combo) private {
        uint256 used = _comboTokenPlus1[combo];
        if (used != 0 && used - 1 != id) revert ComboTaken(used - 1);
        _comboTokenPlus1[combo] = id + 1;
        _traits[id] = combo;
        emit MetadataUpdate(id);
    }

    function _checkOption(uint256 c, uint256 idx) private view {
        if (c >= CATS || idx >= _options[c].length) revert BadTrait(c, idx);
    }

    function _useItem(address user, uint256 c, uint256 idx) private {
        uint16 k = _key(uint8(c), uint8(idx));
        uint256 b = _items[user][k];
        if (b == 0) revert NoItem(c, idx);
        _items[user][k] = b - 1;
        emit ItemChanged(user, uint8(c), uint8(idx), b - 1);
    }

    function _addItem(address user, uint256 c, uint256 idx, uint256 amount) private {
        uint16 k = _key(uint8(c), uint8(idx));
        uint256 b = _items[user][k] + amount;
        _items[user][k] = b;
        emit ItemChanged(user, uint8(c), uint8(idx), b);
    }

    function _pack(uint8[5] calldata t) private pure returns (uint40 p) {
        for (uint256 c; c < CATS; ++c) p |= uint40(t[c]) << uint40(8 * c);
    }

    function _key(uint8 c, uint8 idx) private pure returns (uint16) {
        return (uint16(c) << 8) | idx;
    }

    // ERC-4906：讓 OpenSea 知道 metadata 有更新
    event MetadataUpdate(uint256 _tokenId);
    event BatchMetadataUpdate(uint256 _fromTokenId, uint256 _toTokenId);

    function supportsInterface(bytes4 interfaceId) public view override returns (bool) {
        return interfaceId == bytes4(0x49064906) || super.supportsInterface(interfaceId);
    }
}
