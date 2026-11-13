# SPDX-License-Identifier: EUPL-1.2
"""Python port of the pure functions of web/js/hwmidi.js (0.16.2) – the USB MIDI settings channel of CwKey
(morse-key-hw docs/midi-settings-spec.md, protocol 1). When hwmidi.js changes, update this copy too
(test_hwmidi.py checks the constants, the settings table and fragments of the JS)."""
import re
from pathlib import Path

HWMIDI_JS = (Path(__file__).resolve().parent.parent / 'web/js/hwmidi.js').read_text(encoding='utf-8')
CONSTS = {m.group(1): int(m.group(2), 0) for m in
          re.finditer(r'export const ([A-Z_0-9]+) = (0x[0-9A-Fa-f]+|\d+);', HWMIDI_JS)}
SETTINGS = [(int(m.group(1), 16), m.group(2), int(m.group(3), 0), int(m.group(4), 0)) for m in
            re.finditer(r"\[0x([0-9A-F]{2}), '([a-z_0-9]+)', (0x[0-9A-F]+|\d+), (0x[0-9A-F]+|\d+)\],", HWMIDI_JS)]
BY_ID = {s[0]: s for s in SETTINGS}
C = CONSTS
BOOT_CONFIRM = [0x55, 0x46, 0x32]
NAK_REASONS = ['', 'command', 'id', 'range', 'busy', 'unsupported', 'flash', 'confirm', 'frame']
CHIPS = ['F411', 'F401']


def to14(v):
    if not isinstance(v, int) or v < 0 or v > 16383:
        raise ValueError('range')
    return [v & 0x7f, (v >> 7) & 0x7f]


def from14(lo, hi):
    return (lo & 0x7f) | ((hi & 0x7f) << 7)


def frame(cmd, seq, payload=()):
    for b in payload:
        if not isinstance(b, int) or b < 0 or b > 127:
            raise ValueError('byte')
    return [0xF0, C['MIDI_MFR'], C['MIDI_ID0'], C['MIDI_ID1'], C['MIDI_PROTO'], cmd & 0x7f, seq & 0x7f, *payload, 0xF7]


def set_frame(seq, id_, value):
    s = BY_ID.get(id_)
    if not s:
        raise ValueError('id')
    if not isinstance(value, int) or value < s[2] or value > s[3]:
        raise ValueError('range')
    return frame(C['MIDI_SET'], seq, [id_, *to14(value)])


def boot_frame(seq):
    return frame(C['MIDI_ENTER_BOOTLOADER'], seq, BOOT_CONFIRM)


def parse(b):
    b = list(b or [])
    if len(b) < 8 or b[0] != 0xF0 or b[-1] != 0xF7:
        return None
    if b[1:5] != [C['MIDI_MFR'], C['MIDI_ID0'], C['MIDI_ID1'], C['MIDI_PROTO']]:
        return None
    body = b[5:-1]
    if any(x > 127 for x in body):
        return None
    return {'cmd': body[0], 'seq': body[1], 'payload': body[2:]}


def decode(m):
    if not m:
        return None
    p, cmd = m['payload'], m['cmd']
    if cmd == C['MIDI_INFO']:
        if len(p) < 8:
            return None
        caps = p[6]
        return {'type': 'info', 'seq': m['seq'], 'proto': p[0], 'version': f'{p[1]}.{p[2]}.{p[3]}',
                'chip': CHIPS[p[4]] if p[4] < len(CHIPS) else None,
                'caps': {'tone': bool(caps & C['MIDI_CAP_TONE']), 'ptt': bool(caps & C['MIDI_CAP_PTT']),
                         'boot': bool(caps & C['MIDI_CAP_BOOT'])},
                'name': ''.join(chr(x) for x in p[8:8 + p[7]])}
    if cmd in (C['MIDI_VALUE'], C['MIDI_CHANGED']):
        if len(p) < 3:
            return None
        s = BY_ID.get(p[0])
        return {'type': 'value' if cmd == C['MIDI_VALUE'] else 'changed', 'seq': m['seq'], 'id': p[0],
                'name': s[1] if s else None, 'value': from14(p[1], p[2])}
    if cmd == C['MIDI_ACK']:
        return None if len(p) < 1 else {'type': 'ack', 'seq': m['seq'], 'of': p[0]}
    if cmd == C['MIDI_NAK']:
        if len(p) < 2:
            return None
        return {'type': 'nak', 'seq': m['seq'], 'of': p[0], 'code': p[1],
                'reason': NAK_REASONS[p[1]] if p[1] < len(NAK_REASONS) and NAK_REASONS[p[1]] else 'unknown'}
    return None


def settings_map(values):
    return {v['name']: v['value'] for v in values or [] if v['name']}


def retries_for(cmd):
    return 0 if cmd in (C['MIDI_SAVE'], C['MIDI_ENTER_BOOTLOADER']) else C['MIDI_RETRIES']


def newer(available, installed):
    """Port of uf2.js newer()."""
    if not available:
        return False
    if not installed:
        return True

    def p(s):
        out = []
        for x in str(s).split('.'):
            m = re.match(r'\d+', x)
            out.append(int(m.group(0)) if m else 0)
        return out + [0] * 3
    a, b = p(available), p(installed)
    for i in range(3):
        if a[i] != b[i]:
            return a[i] > b[i]
    return False


def known_version(device_version, written_here):
    return device_version or written_here or None


def offer_update(available, device_version, written_here):
    return newer(available, known_version(device_version, written_here))


def chip_target(release, chip):
    if not chip:
        return None
    return next((t for t in (release or {}).get('targets') or [] if chip in str(t.get('mcu') or '')), None)


class FakeKey:
    """A key on the other end of the MIDI cable (protocol of the spec) – for tests of the request sequences."""

    def __init__(self, version=(0, 4, 0), chip=0, caps=7, busy=False):
        self.version, self.chip, self.caps, self.busy = version, chip, caps, busy
        self.values = {s[0]: {'wpm': 20, 'keyer_mode': 1, 'dah_ratio_x10': 30, 'weight_pct': 50, 'element_memory': 1,
                              'usb_mode': 0, 'sidetone_on': 1, 'tone_hz': 700, 'volume_pct': 100, 'ptt_enabled': 1,
                              'ptt_hang_ms': 500, 'stream_key': 0x68}.get(s[1], 0) for s in SETTINGS}
        self.boot = False

    def reply(self, msg):
        """One host message → list of key messages."""
        m = parse(msg)
        if not m:
            return []
        cmd, seq, p = m['cmd'], m['seq'], m['payload']
        out = lambda c, pl: [0xF0, 0x7D, 0x43, 0x4B, 1, c, seq, *pl, 0xF7]   # noqa: E731
        nak = lambda code: [out(C['MIDI_NAK'], [cmd, code])]                  # noqa: E731
        if cmd == C['MIDI_GET_INFO']:
            name = [ord(x) for x in 'CwKey']
            return [out(C['MIDI_INFO'], [1, *self.version, self.chip, 0, self.caps, len(name), *name])]
        if cmd == C['MIDI_GET_ALL']:
            return [out(C['MIDI_VALUE'], [i, *to14(v)]) for i, v in self.values.items()] + \
                [out(C['MIDI_ACK'], [cmd])]
        if cmd == C['MIDI_SET']:
            if p[0] not in BY_ID:
                return nak(2)
            v = from14(p[1], p[2])
            if not BY_ID[p[0]][2] <= v <= BY_ID[p[0]][3]:
                return nak(3)
            self.values[p[0]] = v
            return [out(C['MIDI_ACK'], [cmd])]
        if cmd == C['MIDI_ENTER_BOOTLOADER']:
            if p != BOOT_CONFIRM:
                return nak(7)
            if self.busy:
                return nak(4)
            self.boot = True
            return [out(C['MIDI_ACK'], [cmd])]
        return nak(1)

    def key_button(self):
        """KEY pressed: wpm to the next of 20/30/40/50/60 above → a CHANGED notification (seq 0)."""
        steps = [20, 30, 40, 50, 60]
        w = self.values[1]
        self.values[1] = next((s for s in steps if s > w), 20)
        return [0xF0, 0x7D, 0x43, 0x4B, 1, C['MIDI_CHANGED'], 0, 1, *to14(self.values[1]), 0xF7]


class KeyTempo:
    """Port of KeyTempo (0.16.4, Z-26): the key's tempo follows the user's QRS / QRQ to the VO."""

    def __init__(self, step):
        self.step = step
        self.orig = None
        self.wpm = None
        self.pending = None
        self.hand = False
        self.ours = False

    def known(self, wpm):
        if self.orig is None:
            self.orig = wpm
        if self.wpm is None:
            self.wpm = wpm

    def request(self, dir_):
        if self.wpm is None:
            return None
        self.hand = False
        base = self.pending if self.pending is not None else self.wpm
        w = min(C['KEY_WPM_MAX'], max(C['KEY_WPM_MIN'], round(base + dir_ * self.step)))
        self.pending = None if w == self.wpm else w
        return self.pending

    def sent(self, wpm):
        self.wpm = wpm
        if self.pending == wpm:
            self.pending = None
        self.ours = True

    def changed(self, wpm):
        self.wpm = wpm
        self.pending = None
        self.hand = True
        self.ours = False

    def restore_to(self):
        if self.ours and not self.hand and self.orig is not None and self.wpm != self.orig:
            return self.orig
        return None
