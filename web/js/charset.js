// SPDX-License-Identifier: EUPL-1.2
// Character set of the trainer = the English (ITU + common extensions) set from morse-pro: 51 characters.

// Koch order as in LCWO, extended by characters LCWO does not have.
export const KOCH_ORDER = [
  'K', 'M', 'U', 'R', 'E', 'S', 'N', 'A', 'P', 'T', 'L', 'W', 'I', '.', 'J', 'Z', '=', 'F', 'O', 'Y',
  ',', 'V', 'G', '5', '/', 'Q', '9', '2', 'H', '3', '8', 'B', '?', '4', '7', 'C', '1', 'D', '6', '0', 'X',
  "'", '-', ':', '(', ')', '"', '@', '+', '&', '!',
];

// Morse codes – only for computing how similar characters sound (never shown to the user,
// the method is purely aural). Python tests read this table directly from this file.
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

// Characters that sound the same as a prosign – identical when receiving.
export const PROSIGN_ALIAS = { '=': 'BT', '+': 'AR', '(': 'KN', '&': 'AS' };

// Layout of the mobile keyboard (based on the US PC keyboard), 6 rows, no layers.
export const KEYBOARD_ROWS = [
  ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
  ['Q', 'W', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P'],
  ['A', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L', "'"],
  ['Z', 'X', 'C', 'V', 'B', 'N', 'M', ',', '.', '/'],
  ['?', '=', '+', '-', '(', ')', '"', ':'],
  ['@', '&', '!', 'REPEAT', 'PAUSE'],
];

// Converts a physical key press to a character of the set (null = ignore).
export function normalizeKey(key) {
  if (!key || key.length !== 1) return null;
  const k = key.toUpperCase();
  return KOCH_ORDER.includes(k) ? k : null;
}
