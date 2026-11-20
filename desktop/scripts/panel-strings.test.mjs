// WP4 strings: ko/en parity, no Latin in Korean values, no particle on a
// placeholder, no emoji, and no forbidden claims.
import assert from "node:assert/strict";
import test from "node:test";

const { WP4_STRINGS } = await import("../src/i18n/v2/wp4.ts");

test("every key has ko and en", () => {
  for (const [key, v] of Object.entries(WP4_STRINGS)) {
    assert.equal(typeof v.ko, "string", key);
    assert.equal(typeof v.en, "string", key);
    assert.ok(v.ko.length > 0 && v.en.length > 0, key);
    const holes = (s) => [...s.matchAll(/\{(\d+)\}/g)].map((m) => m[1]).sort().join(",");
    assert.equal(holes(v.ko), holes(v.en), `placeholders differ in ${key}`);
  }
});

test("Korean values carry no Latin letters", () => {
  for (const [key, v] of Object.entries(WP4_STRINGS)) {
    assert.doesNotMatch(v.ko, /[A-Za-z]/, key);
  }
});

test("no particle is attached to a placeholder", () => {
  const particle = /\}(이|가|을|를|은|는|과|와|의|에|로|으로|이나|나|도|만)(?![가-힣])/;
  for (const [key, v] of Object.entries(WP4_STRINGS)) {
    assert.doesNotMatch(v.ko, particle, key);
  }
});

test("no emoji, no exclamation, no forbidden claims", () => {
  for (const [key, v] of Object.entries(WP4_STRINGS)) {
    for (const s of [v.ko, v.en]) {
      assert.doesNotMatch(s, /\p{Extended_Pictographic}/u, key);
      assert.doesNotMatch(s, /!/, key);
      for (const bad of ["정확도 100%", "특정 모델 기반", "AI 탐지 회피", "AI 티 제거", "결재"]) {
        assert.equal(s.includes(bad), false, `${key} carries ${bad}`);
      }
    }
    for (const bad of ["진행합니다", "하는 것이 가능", "해당 ", "에 대한", "되어집"]) {
      assert.equal(v.ko.includes(bad), false, `${key} carries ${bad}`);
    }
  }
});
