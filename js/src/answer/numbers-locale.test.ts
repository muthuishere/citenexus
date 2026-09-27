// ADR-0015 amendment 2026-09-27 — mirrors golang/answer/numbers_locale_test.go.
import { describe, expect, it } from "vitest";

// Load through the answer module: numbers.ts sits in an import cycle
// (numbers -> verify-guards-model -> … -> conflict -> numbers).
import "./answer.js";
import { numbersIn, verbatimIn } from "./numbers.js";

const NB = " ";
const NBSP = " ";

describe("numbersIn locale grouping", () => {
  const cases: [string, string, string[]][] = [
    ["Le montant est de 1 234,56.", "fr", ["1234.56"]],
    ["Le montant est de 1" + NB + "234,56.", "fr", ["1234.56"]],
    ["Der Betrag ist 1" + NBSP + "234" + NBSP + "567,89.", "de", ["1234567.89"]],
    ["De prijs is 1.234,56.", "de", ["1234.56"]],
    ["The total is 1 234.", "en", ["1", "234"]],
    ["Le total est 1 234 56.", "fr", ["1", "234", "56"]],
    ["Der Preis ist 1'234.50.", "de-CH", ["1234.5"]],
    ["Der Preis ist 1’234.50.", "de", ["1234.5"]],
    ["The price is 1'234.50.", "en", ["1234.5"]],
    ["The price is 1'23.", "en", ["1", "23"]],
    ["The fee is 1,00,000.", "en-IN", ["100000"]],
    ["शुल्क 12,34,567.89 है", "hi", ["1234567.89"]],
    ["The fee is 1,00,000.", "", ["?1,00,000"]],
    ["De prijs is 1.500.", "sv", ["1500"]],
    ["The price is 1.500.", "xx", ["?1.500"]],
  ];
  for (const [text, language, want] of cases) {
    it(`${text} (${language})`, () => {
      expect(numbersIn(text, language).map((m) => m.reading.key)).toEqual(want);
    });
  }
});

describe("verbatim numbers are whole numbers", () => {
  const vb = verbatimIn("Het budget is € 4.000, de toeslag € 0,12 en de fee € 12.750.", "nl");
  const cases: [string, string][] = [
    ["4.000", "4000"],
    ["12", "12"],
    ["0,12", "0.12"],
    ["12.75", "12.75"],
    ["4.00", "4"],
  ];
  for (const [claim, want] of cases) {
    it(claim, () => {
      expect(numbersIn("The amount is " + claim + " here.", "en", vb).map((m) => m.reading.key)).toEqual([want]);
    });
  }
});
