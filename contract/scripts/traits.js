// 讀 ../traits.json，轉成合約 setOptions／setGachaPool 用的參數
const path = require("path");
const TRAITS = require(path.join(__dirname, "..", "..", "traits.json"));

/** 每一類：{ weights: [...], rare: [...] }（rare＝稀有或超稀有，要消耗背包道具） */
function optionArgs() {
    return TRAITS.categories.map((c) => ({
        weights: c.options.map((o) => TRAITS.weights[o.tier]),
        rare: c.options.map((o) => o.tier !== "normal")
    }));
}

/** 轉蛋獎池：所有稀有／超稀有配件 */
function gachaArgs() {
    const cats = [], idxs = [], weights = [];
    TRAITS.categories.forEach((c, ci) =>
        c.options.forEach((o, oi) => {
            if (o.tier === "normal") return;
            cats.push(ci);
            idxs.push(oi);
            weights.push(TRAITS.gacha[o.tier]);
        })
    );
    return { cats, idxs, weights, miss: TRAITS.gacha.miss };
}

module.exports = { TRAITS, optionArgs, gachaArgs };
