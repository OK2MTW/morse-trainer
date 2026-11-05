// SPDX-License-Identifier: EUPL-1.2
// Znaková sada trenažeru = anglická (ITU + běžná rozšíření) sada z morse-pro: 51 znaků.

// Kochovo pořadí podle LCWO, doplněné o znaky, které LCWO nemá.
export const KOCH_ORDER = [
  'K', 'M', 'U', 'R', 'E', 'S', 'N', 'A', 'P', 'T', 'L', 'W', 'I', '.', 'J', 'Z', '=', 'F', 'O', 'Y',
  ',', 'V', 'G', '5', '/', 'Q', '9', '2', 'H', '3', '8', 'B', '?', '4', '7', 'C', '1', 'D', '6', '0', 'X',
  "'", '-', ':', '(', ')', '"', '@', '+', '&', '!',
];

// Morseovy kódy – jen pro výpočet zvukové podobnosti znaků (uživateli se nikdy nezobrazují,
// metoda je čistě sluchová). Python testy čtou tuto tabulku přímo z tohoto souboru.
export const MORSE = Object.fromEntries([
  ['K', '-.-'], ['M', '--'], ['U', '..-'], ['R', '.-.'], ['E', '.'], ['S', '...'], ['N', '-.'], ['A', '.-'],
  ['P', '.--.'], ['T', '-'], ['L', '.-..'], ['W', '.--'], ['I', '..'], ['.', '.-.-.-'], ['J', '.---'],
  ['Z', '--..'], ['=', '-...-'], ['F', '..-.'], ['O', '---'], ['Y', '-.--'], [',', '--..--'], ['V', '...-'],
  ['G', '--.'], ['5', '.....'], ['/', '-..-.'], ['Q', '--.-'], ['9', '----.'], ['2', '..---'], ['H', '....'],
  ['3', '...--'], ['8', '---..'], ['B', '-...'], ['?', '..--..'], ['4', '....-'], ['7', '--...'],
  ['C', '-.-.'], ['1', '.----'], ['D', '-..'], ['6', '-....'], ['0', '-----'], ['X', '-..-'], ["'", '.----.'],
  ['-', '-....-'], [':', '---...'], ['(', '-.--.'], [')', '-.--.-'], ['"', '.-..-.'], ['@', '.--.-.'],
  ['+', '.-.-.'], ['&', '.-...'], ['!', '-.-.--'],
]);

// Znaky, které zní stejně jako prosign – při příjmu jsou totožné.
export const PROSIGN_ALIAS = { '=': 'BT', '+': 'AR', '(': 'KN', '&': 'AS' };

// Rozložení mobilní klávesnice (vychází z US PC klávesnice), 6 řad, bez vrstev.
export const KEYBOARD_ROWS = [
  ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
  ['Q', 'W', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P'],
  ['A', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L', "'"],
  ['Z', 'X', 'C', 'V', 'B', 'N', 'M', ',', '.', '/'],
  ['?', '=', '+', '-', '(', ')', '"', ':'],
  ['@', '&', '!', 'REPEAT', 'PAUSE'],
];

// Převod stisku fyzické klávesy na znak sady (null = ignorovat).
export function normalizeKey(key) {
  if (!key || key.length !== 1) return null;
  const k = key.toUpperCase();
  return KOCH_ORDER.includes(k) ? k : null;
}
