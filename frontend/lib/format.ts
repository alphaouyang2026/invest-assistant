/** How numbers and codes are written on screen. */

type Maybe = number | null | undefined;

const MINUS = "−"; // U+2212, as wide as the plus sign, so signed columns line up

const signed = (value: number, text: string) => (value > 0 ? `+${text}` : value < 0 ? `${MINUS}${text}` : text);

/** 0.24918 → "+24.92%", −0.1112 → "−11.12%"; null → "—". */
export const signedPercent = (value: Maybe, digits = 2) =>
  value === null || value === undefined ? "—" : signed(value, `${Math.abs(value * 100).toFixed(digits)}%`);

/** Yen, whole, with thousands separators. */
export const yen = (value: Maybe) =>
  value === null || value === undefined ? "" : Math.round(value).toLocaleString("en-US");

export const signedYen = (value: Maybe) =>
  value === null || value === undefined ? "" : signed(Math.round(value), yen(Math.abs(value)));

/** The class a number is coloured with: gains `up`, losses `down`. */
export const tone = (value: Maybe) =>
  value === null || value === undefined || value === 0 ? "" : value > 0 ? "up" : "down";

export const fixed = (value: Maybe, digits: number) =>
  value === null || value === undefined ? "—" : value.toFixed(digits);

/** J-Quants writes codes with a fifth digit, 0 for ordinary shares: 72030 is
 * the 7203 everyone knows. Any other fifth digit is kept. */
export const displayCode = (code: string) => (code.length === 5 && code.endsWith("0") ? code.slice(0, 4) : code);
