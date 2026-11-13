// SPDX-License-Identifier: EUPL-1.2
// 0.15.0: checks of a CwKey firmware image before it is written to the key's bootloader drive (the same rules as
// server/firmware.py check_uf2 – the Pi already checked the release; the browser checks again what it got, because
// TinyUF2 writes a block anywhere and a wrong address would damage the bootloader).
export const UF2_MAGIC0 = 0x0A324655;
export const UF2_MAGIC1 = 0x9E5D5157;
export const UF2_MAGIC_END = 0x0AB16F30;
export const UF2_FLAG_FAMILY = 0x00002000;
export const FLASH_END = 0x08080000;

/** Returns the number of blocks, or throws Error(reason) – reason is a code for the UI. */
export function checkUf2(buf, family, appBase, flashEnd = FLASH_END) {
  const n = buf.byteLength / 512;
  if (!buf.byteLength || !Number.isInteger(n)) throw new Error('size');
  const v = new DataView(buf);
  for (let i = 0; i < n; i++) {
    const o = i * 512;
    const u = (k) => v.getUint32(o + 4 * k, true);
    if (u(0) !== UF2_MAGIC0 || u(1) !== UF2_MAGIC1 || v.getUint32(o + 508, true) !== UF2_MAGIC_END) throw new Error('magic');
    if (!(u(2) & UF2_FLAG_FAMILY) || u(7) !== family) throw new Error('family');
    if (u(5) !== i || u(6) !== n) throw new Error('numbering');
    const addr = u(3), size = u(4);
    if (size === 0 || size > 476 || addr < appBase || addr + size > flashEnd) throw new Error('address');
  }
  return n;
}

/** INFO_UF2.TXT of the bootloader drive → {model, board}. */
export function parseInfo(text) {
  const get = (k) => (String(text || '').match(new RegExp(`^${k}:\\s*(.+?)\\s*$`, 'mi')) || [])[1] || '';
  return { model: get('Model'), board: get('Board-ID') };
}

/** The release target for this drive: Board-ID first, then Model, then the drive (folder) name. */
export function pickTarget(release, info, driveName = '') {
  const ts = release?.targets || [];
  return ts.find((t) => info.board && t.info_board_id === info.board)
    || ts.find((t) => info.model && t.info_model === info.model)
    || (!info.board && !info.model ? ts.find((t) => driveName && t.volume_label === driveName) : null)
    || null;
}

export async function sha256Hex(buf) {
  const h = await crypto.subtle.digest('SHA-256', buf);
  return [...new Uint8Array(h)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

/** Pure: should the app offer an update? Unknown installed version → yes (the first tests rewrite the same one). */
export function newer(available, installed) {
  if (!available) return false;
  if (!installed) return true;
  const p = (s) => String(s).split('.').map((x) => parseInt(x, 10) || 0);
  const [a, b] = [p(available), p(installed)];
  for (let i = 0; i < 3; i++) if ((a[i] || 0) !== (b[i] || 0)) return (a[i] || 0) > (b[i] || 0);
  return false;
}
