# SPDX-License-Identifier: EUPL-1.2
"""0.16.2 USB MIDI settings channel of CwKey (tests/hwmidi.py = port of web/js/hwmidi.js): frames, 14-bit numbers,
decoding of the key's answers, ranges, the firmware offer with the version read from the key."""
import unittest

from tests import hwmidi as M

C = M.C


class TestHwMidi(unittest.TestCase):
    def test_constants_match_the_spec(self):
        self.assertEqual((C['MIDI_MFR'], C['MIDI_ID0'], C['MIDI_ID1'], C['MIDI_PROTO']), (0x7D, 0x43, 0x4B, 1))
        self.assertEqual([C[k] for k in ('MIDI_GET_INFO', 'MIDI_GET_ALL', 'MIDI_GET', 'MIDI_SET', 'MIDI_SAVE',
                                         'MIDI_RESET_DEFAULTS', 'MIDI_ENTER_BOOTLOADER')], list(range(1, 8)))
        self.assertEqual([C[k] for k in ('MIDI_INFO', 'MIDI_VALUE', 'MIDI_ACK', 'MIDI_NAK', 'MIDI_CHANGED')],
                         list(range(0x41, 0x46)))
        self.assertEqual((C['MIDI_TIMEOUT'], C['MIDI_RETRIES'], C['MIDI_SAVE_TIMEOUT']), (500, 1, 6000))
        self.assertEqual(len(M.SETTINGS), 14)
        self.assertEqual(M.BY_ID[0x01], (1, 'wpm', 5, 60))
        self.assertEqual(M.BY_ID[0x0E], (14, 'stream_key', 0x04, 0x73))
        for frag in ("export const BOOT_CONFIRM = [0x55, 0x46, 0x32];",
                     "export const NAK_REASONS = ['', 'command', 'id', 'range', 'busy', 'unsupported', 'flash', 'confirm', 'frame'];",
                     "export const CHIPS = ['F411', 'F401'];", "export const MIDI_PORT = 'CW Key';",
                     'return [0xF0, MIDI_MFR, MIDI_ID0, MIDI_ID1, MIDI_PROTO, cmd & 0x7f, seq & 0x7f, ...payload, 0xF7];',
                     'return cmd === MIDI_SAVE || cmd === MIDI_ENTER_BOOTLOADER ? 0 : MIDI_RETRIES;',
                     'return deviceVersion || writtenHere || null;',
                     "if (!Number.isInteger(value) || value < s[2] || value > s[3]) throw new Error('range');",
                     "version: `${p[1]}.${p[2]}.${p[3]}`, chip: CHIPS[p[4]] ?? null,",
                     "if (d.type === 'changed') { this.onChanged?.(d); return; }",
                     "this.access = await navigator.requestMIDIAccess({ sysex: true });"):
            self.assertIn(frag, M.HWMIDI_JS)

    def test_14bit(self):
        for v in (0, 1, 127, 128, 700, 3000, 16383):
            self.assertEqual(M.from14(*M.to14(v)), v)
        self.assertEqual(M.to14(700), [0x3C, 0x05])
        for bad in (-1, 16384, 2.5):
            with self.assertRaises(ValueError):
                M.to14(bad)

    def test_frames(self):
        self.assertEqual(M.frame(C['MIDI_GET_INFO'], 5), [0xF0, 0x7D, 0x43, 0x4B, 1, 1, 5, 0xF7])
        self.assertEqual(M.frame(1, 200)[6], 200 & 0x7f)
        self.assertEqual(M.set_frame(3, 0x09, 700), [0xF0, 0x7D, 0x43, 0x4B, 1, 4, 3, 9, 0x3C, 0x05, 0xF7])
        self.assertEqual(M.boot_frame(9), [0xF0, 0x7D, 0x43, 0x4B, 1, 7, 9, 0x55, 0x46, 0x32, 0xF7])
        with self.assertRaises(ValueError):
            M.frame(1, 1, [128])
        for id_, v, err in ((0x01, 4, 'range'), (0x01, 61, 'range'), (0x0D, 49, 'range'), (0x7F, 1, 'id')):
            with self.assertRaises(ValueError) as cm:
                M.set_frame(1, id_, v)
            self.assertEqual(str(cm.exception), err)
        self.assertEqual(M.set_frame(1, 0x01, 60)[7:10], [1, 60, 0])

    def test_parse_ignores_foreign_traffic(self):
        self.assertIsNone(M.parse([0x90, 60, 100]))                                 # a note
        self.assertIsNone(M.parse([0xF0, 0x7D, 0x00, 0x00, 1, 0x41, 0, 0xF7]))      # other 0x7D SysEx
        self.assertIsNone(M.parse([0xF0, 0x7D, 0x43, 0x4B, 2, 0x41, 0, 0xF7]))      # another protocol version
        self.assertIsNone(M.parse([0xF0, 0x7D, 0x43, 0x4B, 1, 0x41, 0, 0x80, 0xF7]))
        self.assertIsNone(M.parse([0xF0, 0x7D, 0x43, 0x4B, 1, 0x41]))                # unterminated
        self.assertIsNone(M.decode(M.parse([0xF0, 0x7D, 0x43, 0x4B, 1, 0x41, 0, 1, 0xF7])))   # short INFO
        self.assertIsNone(M.decode(M.parse([0xF0, 0x7D, 0x43, 0x4B, 1, 0x50, 0, 1, 0xF7])))   # unknown answer

    def test_info_values_ack_nak(self):
        key = M.FakeKey(version=(0, 4, 0), chip=1, caps=7)
        info = M.decode(M.parse(key.reply(M.frame(C['MIDI_GET_INFO'], 7))[0]))
        self.assertEqual((info['type'], info['seq'], info['version'], info['chip'], info['name'], info['proto']),
                         ('info', 7, '0.4.0', 'F401', 'CwKey', 1))
        self.assertEqual(info['caps'], {'tone': True, 'ptt': True, 'boot': True})
        self.assertFalse(M.decode(M.parse(M.FakeKey(caps=3).reply(M.frame(1, 1))[0]))['caps']['boot'])
        self.assertIsNone(M.decode(M.parse(M.FakeKey(chip=5).reply(M.frame(1, 1))[0]))['chip'])
        msgs = [M.decode(M.parse(x)) for x in key.reply(M.frame(C['MIDI_GET_ALL'], 8))]
        self.assertEqual(msgs[-1], {'type': 'ack', 'seq': 8, 'of': C['MIDI_GET_ALL']})
        s = M.settings_map(msgs[:-1])
        self.assertEqual((s['wpm'], s['tone_hz'], s['ptt_hang_ms'], s['stream_key']), (20, 700, 500, 0x68))
        # an unknown id from a newer FW is ignored, the rest keeps working
        unknown = M.decode(M.parse([0xF0, 0x7D, 0x43, 0x4B, 1, 0x42, 8, 0x30, 5, 0, 0xF7]))
        self.assertIsNone(unknown['name'])
        self.assertEqual(M.settings_map(msgs[:-1] + [unknown]), s)
        ack = M.decode(M.parse(key.reply(M.set_frame(9, 0x01, 25))[0]))
        self.assertEqual((ack['type'], ack['of'], key.values[1]), ('ack', C['MIDI_SET'], 25))
        nak = M.decode(M.parse(key.reply(M.frame(C['MIDI_SET'], 10, [1, 0, 1]))[0]))   # 128 WPM sent raw
        self.assertEqual((nak['type'], nak['of'], nak['code'], nak['reason']), ('nak', C['MIDI_SET'], 3, 'range'))
        self.assertEqual(M.decode(M.parse([0xF0, 0x7D, 0x43, 0x4B, 1, 0x44, 1, 4, 0, 0xF7]))['reason'], 'unknown')

    def test_key_button_changed(self):
        key = M.FakeKey()
        key.values[1] = 25
        d = M.decode(M.parse(key.key_button()))
        self.assertEqual((d['type'], d['seq'], d['name'], d['value']), ('changed', 0, 'wpm', 30))
        key.values[1] = 60
        self.assertEqual(M.decode(M.parse(key.key_button()))['value'], 20)

    def test_bootloader(self):
        key = M.FakeKey()
        d = M.decode(M.parse(key.reply(M.boot_frame(3))[0]))
        self.assertEqual((d['type'], d['of'], key.boot), ('ack', C['MIDI_ENTER_BOOTLOADER'], True))
        busy = M.FakeKey(busy=True)
        d = M.decode(M.parse(busy.reply(M.boot_frame(4))[0]))
        self.assertEqual((d['reason'], busy.boot), ('busy', False))
        bad = M.FakeKey()
        d = M.decode(M.parse(bad.reply(M.frame(C['MIDI_ENTER_BOOTLOADER'], 5, [0x55, 0x46]))[0]))
        self.assertEqual((d['reason'], bad.boot), ('confirm', False))
        self.assertEqual(M.retries_for(C['MIDI_ENTER_BOOTLOADER']), 0)
        self.assertEqual(M.retries_for(C['MIDI_SAVE']), 0)
        self.assertEqual(M.retries_for(C['MIDI_GET_INFO']), 1)

    def test_update_offer(self):
        # with the version from the key the offer comes only for a newer FW
        self.assertFalse(M.offer_update('0.4.0', '0.4.0', None))
        self.assertFalse(M.offer_update('0.4.0', '0.4.0', '0.3.0'))     # the key knows better than this device
        self.assertTrue(M.offer_update('0.4.1', '0.4.0', '0.4.1'))
        self.assertFalse(M.offer_update('0.3.0', '0.4.0', None))       # an older release is never offered
        # without MIDI as before 0.16.2: what this device wrote last, nothing → offered
        self.assertTrue(M.offer_update('0.4.0', None, '0.3.0'))
        self.assertFalse(M.offer_update('0.4.0', None, '0.4.0'))
        self.assertTrue(M.offer_update('0.4.0', None, None))
        self.assertFalse(M.offer_update(None, '0.4.0', None))

    def test_chip_target(self):
        rel = {'targets': [{'mcu': 'STM32F411CE', 'file': 'a.uf2'}, {'mcu': 'STM32F401CC/CD/CE', 'file': 'b.uf2'}]}
        self.assertEqual(M.chip_target(rel, 'F401')['file'], 'b.uf2')
        self.assertEqual(M.chip_target(rel, 'F411')['file'], 'a.uf2')
        self.assertIsNone(M.chip_target(rel, None))
        self.assertIsNone(M.chip_target(rel, 'F446'))
        self.assertIsNone(M.chip_target(None, 'F411'))


if __name__ == '__main__':
    unittest.main()
