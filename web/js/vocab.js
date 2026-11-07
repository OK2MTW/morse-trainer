// SPDX-License-Identifier: EUPL-1.2
// 0.10.0: vocabulary of amateur radio operation – three lists trained alongside Morse: operating abbreviations, Q codes and
// call sign prefixes. Public conventions (ITU prefixes, Q codes, common CW abbreviations), compiled for the project.
// Only the codes are here; their meanings are translated: i18n keys vocab.<list>.<code>.
export const VOCAB_LISTS = ['abbr', 'q', 'pfx'];

/**
 * 0.10.6 (Martin): the official lists of the Czech amateur radio exam – CTU, exam questions with correct answers
 * (insert to ref. no. 26 273/2025-613, FAQ 06-2025), operating sections of classes A and N combined: Q codes,
 * abbreviations and call sign prefixes. Meanings in Czech as in the document (class A wording where the classes differ),
 * translated in i18n: vocab.<list>.<code>.
 * Line = item code | as the overview shows it | what the quiz may show (one at random): several forms of an abbreviation
 * (TNX, TKS), a Q code as a question (QRO?), the prefix series of a country with ranges expanded. A range never takes
 * another region's explicit prefix (Denmark without OX/OY/XP, France without TK, China without BV) – every quiz form
 * belongs to exactly one item (test). Item codes of earlier versions are kept where the item still exists (results stay).
 * A 4th column '+' = an extra item outside the CTU list (common in CW contacts, Martin 2026-11-07); marked in the overview.
 */
const ABBR_TABLE = `
AC | AC | AC
HRD | HRD | HRD
HAM | HAM | HAM
RPT | RPT | RPT
RF | RF | RF
ALC | ALC | ALC
RX | RX | RX
RIG | RIG | RIG
ALL | ALL | ALL
AGC | AGC | AGC
HW | HW? | HW?
HI | HI | HI
RST | RPRT, RST | RPRT RST
SHF | SHF | SHF
AM | AM | AM
AGN | AGN | AGN
I | I | I
SIGS | SIGS | SIGS
ANT | AER, ANT | AER ANT
SK | SK | SK
INFO | INFO | INFO
AS | AS | AS
IF | IF | IF
SKED | SKED | SKED
BCI | BCI | BCI
STN | STN | STN
SSB | SSB | SSB
SUNNY | SUNNY | SUNNY
CALL | CALL | CALL
K | K | K
CL | CL | CL
LF | LF | LF
SW | SW | SW
LID | LID | LID
SWR | PSV, SWR | PSV SWR
OVERCAST | OVERCAST | OVERCAST
CONDS | CONDS | CONDS
TEMP | TEMP | TEMP
LOG | LOG | LOG
CQ | CQ | CQ
TEST | TEST | TEST
TNX | TNX, TKS | TNX TKS
TVI | TVI | TVI
LW | LW | LW
DB | DB | DB
TX | TX | TX
DC | DC | DC
TO | TO | TO
LSB | LSB | LSB
ITU | ITU, UIT | ITU UIT
IARU | IARU | IARU
DIRECT | DIRECT | DIRECT
DR | DR | DR
AWARD | AWARD | AWARD
DX | DX | DX
UR | UR | UR
ELBUG | ELBUG | ELBUG
DE | DE | DE
FER | FER | FER
FB | FB | FB
TBS | TBS | TBS
UFB | UFB | UFB
FM | FM | FM
ONLY | ONLY | ONLY
OM | OM | OM
GA | GA | GA
GM | GM | GM
GE | GE | GE
GB | GB | GB
CUAGN | CUAGN | CUAGN
LIS | LIS | LIS
UNLIS | UNLIS | UNLIS
TRX | TRX | TRX
EL | EL | EL
UHF | UHF | UHF
MY | MY | MY
VFO | VFO | VFO
NO | NO | NO
SASE | SASE | SASE
CW | CW | CW
UTC | UTC | UTC
VHF | VHF | VHF
OK | OK | OK
FONE | FONE | FONE
VIA | VIA | VIA
OP | OP | OP
VY | VY | VY
WKD | WKD | WKD
OSCAR | OSCAR | OSCAR
GD | GD | GD
WTTS | WTTS | WTTS
WX | WX | WX
GL | GL | GL
CLOUDY | CLOUDY | CLOUDY
GLD | GLD | GLD
PA | PA | PA
XYL | XYL | XYL
PEP | PEP | PEP
YL | YL | YL
PSE | PSE | PSE
GN | GN | GN
PWR | PWR | PWR
73 | 73 | 73
88 | 88 | 88
GND | GND | GND
R | R | R
99 | 99 | 99
QSLN | QSLN | QSLN
AR | AR | AR
BK | BK | BK
HPE | HPE | HPE
AVC | AVC | AVC
CONDX | CONDX | CONDX
ABT | ABT | ABT
BUG | BUG | BUG
HR | HR | HR
CFM | CFM | CFM
ES | ES | ES
DWN | DWN | DWN
CPY | CPI, CPY | CPI CPY
HPY | HPY | HPY
KY | KY | KY
CUL | CUL | CUL
KA | KA | KA
NIL | NIL | NIL
SN | SN | SN
SWL | SWL | SWL
SURE | SURE | SURE
SRI | SRI, SRY | SRI SRY
MTR | MTR | MTR
NR | NR, NEAR | NR NEAR
NET | NET | NET
RCVD | RCVD | RCVD
SEND | SEND | SEND
UP | UP | UP
XMAS | XMAS | XMAS
USB | USB | USB
RFI | RFI | RFI
KN | KN | KN
DP | DP | DP
HF | HF | HF
AF | AF | AF
HV | HV, VN | HV VN
INPT | INPT | INPT
BFO | BFO | BFO
MIKE | MIKE | MIKE
BD | BD | BD
NAME | NAME | NAME
U | U | U
EXCUS | EXCUS | EXCUS
NW | NW | NW
OUTPUT | OUTPUT | OUTPUT
GMT | GMT | GMT
TU | TU | TU | +
BCNU | BCNU | BCNU | +
SIG | SIG | SIG | +
BURO | BURO | BURO | +
5NN | 5NN | 5NN | +
GUD | GUD | GUD | +
PDL | PDL | PDL | +
`;

const Q_TABLE = `
QRM | QRM | QRM
QRO | QRO? | QRO?
QRZ | QRZ | QRZ
QRX | QRX | QRX
QSB | QSB | QSB
QRS | QRS | QRS
QRT | QRT | QRT
QRP | QRP | QRP
QRV | QRV? | QRV?
QRU | QRU | QRU
QSL | QSL | QSL
QRL | QRL? | QRL?
QTH | QTH | QTH
QRN | QRN? | QRN?
QSO | QSO? | QSO?
QSY | QSY? | QSY?
QSV | QSV | QSV
QSK | QSK? | QSK?
QRJ | QRJ | QRJ
QRK | QRK? | QRK?
QSZ | QSZ | QSZ
QSD | QSD | QSD
QRG | QRG? | QRG?
QZF | QZF | QZF
QSX | QSX | QSX
QRA | QRA | QRA | +
QRH | QRH | QRH | +
QRI | QRI | QRI | +
QRQ | QRQ | QRQ | +
QSA | QSA | QSA | +
QSP | QSP | QSP | +
QTR | QTR | QTR | +
QRB | QRB | QRB | +
QTC | QTC | QTC | +
`;

const PFX_TABLE = `
OK | OL, OK | OL OK
PA | PA–PI | PA PB PC PD PE PF PG PH PI
DL | DA–DR | DA DB DC DD DE DF DG DH DI DJ DK DL DM DN DO DP DQ DR
SM | SA–SM, 7S, 8S | SA SB SC SD SE SF SG SH SI SJ SK SL SM 7S 8S
OE | OE | OE
OH | OF–OJ | OF OG OH OI OJ
OM | OM | OM
OZ | OU–OZ, XP, 5P, 5Q | OU OV OW OZ 5P 5Q
SP | HF, SN–SR, 3Z | HF SN SO SP SQ SR 3Z
LA | LA–LN, 3Y | LA LB LC LD LE LF LG LH LI LJ LK LL LM LN 3Y
F | F, FA–FZ, F1–F0, HW, TH, TK, TM, TO, TV | F FA FB FC FD FE FF FG FH FI FJ FK FL FM FN FO FP FQ FR FS FT FU FV FW FX FY FZ F1 F2 F3 F4 F5 F6 F7 F8 F9 F0 HW TH TM TO TV
EA | EA–EH | EA EB EC ED EE EF EG EH
I | I, IA–IZ | I IA IB IC ID IE IF IG IH II IJ IK IL IM IN IO IP IQ IR IS IT IU IV IW IX IY IZ
SV | SV–SZ, J4 | SV SW SX SY SZ J4
S5 | S5 | S5
LZ | LZ | LZ
HA | HA, HG | HA HG
YO | YO–YR | YO YP YQ YR
UR | EM–EO, UR–UZ | EM EN EO UR US UT UU UV UW UX UY UZ
CT | CQ–CU | CQ CR CS CT CU
UA | UA–UI | UA UB UC UD UE UF UG UH UI
K | K, N, W, AA–AK | K N W AA AB AC AD AE AF AG AH AI AJ AK
ES | ES | ES
VE | CF–CK, CY–CZ, VA–VE, VO, VX, VY, XJ–XO | CF CG CH CI CJ CK CY CZ VA VB VC VD VE VO VX VY XJ XK XL XM XN XO
LY | LY | LY
VK | VK | VK
YL | YL | YL
JA | JA–JS, 7J–7N, 8J–8N | JA JB JC JD JE JF JG JH JI JJ JK JL JM JN JO JP JQ JR JS 7J 7K 7L 7M 7N 8J 8K 8L 8M 8N
ON | ON–OT | ON OO OP OQ OR OS OT
PY | PP–PY | PP PQ PR PS PT PU PV PW PX PY
LX | LX | LX
ZS | ZR–ZU | ZR ZS ZT ZU
9A | 9A | 9A
LU | LO–LW | LO LP LQ LR LS LT LU LV LW
Z3 | Z3 | Z3
VU | VU | VU
HB | HB, HE | HB HE
GM | GM, GS | GM GS
EA8 | EA8–EH8 | EA8 EB8 EC8 ED8 EE8 EF8 EG8 EH8
C3 | C3 | C3
CU | CQ2–CU2 | CQ2 CR2 CS2 CT2 CU2
EA6 | EA6–EH6 | EA6 EB6 EC6 ED6 EE6 EF6 EG6 EH6
EA9 | EA9–EH9 | EA9 EB9 EC9 ED9 EE9 EF9 EG9 EH9
EI | EI, EJ | EI EJ
ER | ER | ER
EW | EU–EW | EU EV EW
G | G, GX | G GX
GD | GD, GT, MD | GD GT MD
GI | GI, GN, MI | GI GN MI
GJ | GJ, GH, MJ | GJ GH MJ
GU | GU, GP, MU | GU GP MU
GW | GW, GC, MW | GW GC MW
HB0 | HB0 | HB0
HV | HV | HV
IS0 | IS0, IM0 | IS0 IM0
JW | JW | JW
JX | JX | JX
OH0 | OH0 | OH0
OJ0 | OJ0 | OJ0
OX | OX, XP | OX XP
OY | OY | OY
SV5 | SV5–SZ5 | SV5 SW5 SX5 SY5 SZ5
SV9 | SV9–SZ9 | SV9 SW9 SX9 SY9 SZ9
T7 | T7 | T7
E7 | E7 | E7
TA | TA–TC, YM | TA TB TC YM
TF | TF | TF
TK | TK | TK
YU | YT–YU | YT YU
ZA | ZA | ZA
3A | 3A | 3A
9H | 9H | 9H
BV | BV | BV
BY | BA–BZ, B1–B0 | BA BB BC BD BE BF BG BH BI BJ BK BL BM BN BO BP BQ BR BS BT BU BW BX BY BZ B1 B2 B3 B4 B5 B6 B7 B8 B9 B0
CM | CL, CM, CO, T4 | CL CM CO T4
EK | EK | EK
HL | DS–DT, D7–D9, HL | DS DT D7 D8 D9 HL
P5 | P5–P9 | P5 P6 P7 P8 P9
HS | HS | HS
HZ | HZ, 7Z | HZ 7Z
XE | XE–XI | XE XF XG XH XI
ZL | ZL–ZM | ZL ZM
4O | 4O | 4O
4L | 4L | 4L
4X | 4X, 4Z | 4X 4Z
`;

/** list → {code: {show, quiz: [forms]}} */
export const VOCAB_ITEMS = {};
export const VOCAB = {};
for (const [list, table] of [['abbr', ABBR_TABLE], ['q', Q_TABLE], ['pfx', PFX_TABLE]]) {
  VOCAB_ITEMS[list] = {};
  for (const line of table.trim().split('\n')) {
    const [code, show, quiz, flag] = line.split('|').map((x) => x.trim());
    VOCAB_ITEMS[list][code] = { show, quiz: quiz.split(/\s+/), extra: flag === '+' };
  }
  VOCAB[list] = Object.keys(VOCAB_ITEMS[list]);
}
export const PFX = VOCAB_ITEMS.pfx;

/** How the overview shows an item (all its forms). */
export const vocabLabel = (list, code) => VOCAB_ITEMS[list][code]?.show ?? code;

/** What the quiz shows for an item: one of its forms (TNX or TKS, QRO?, one prefix of the country's series). */
export const vocabShown = (list, code, rng = Math.random) => {
  const q = VOCAB_ITEMS[list][code]?.quiz || [code];
  return q[Math.floor(rng() * q.length)];
};

/** 0.10.8: prosigns are sent as one sign without letter gaps (<CT> = KA). */
export const PROSIGNS = { AR: '<AR>', SK: '<SK>', KN: '<KN>', AS: '<AS>', KA: '<CT>' };

/** 0.10.9: lists whose mastered items make up the copy-behind content `abbr` (and the abbreviation share of `mix`). */
export const COPY_VOCAB_LISTS = ['abbr', 'q'];

/**
 * 0.10.9 (Martin): copy-behind abbreviations come only from items mastered in the vocabulary trainer – every quiz form
 * of a mastered abbreviation or Q code (TNX and TKS, QRO?), without prosigns (copy behind sends letters with gaps).
 * stat(list, code) = [n, wrong, lastOk]. Sorted, without duplicates. Python port: tests/content.py copy_abbr_forms.
 */
export function copyAbbrForms(stat) {
  const out = new Set();
  for (const list of COPY_VOCAB_LISTS) {
    for (const code of VOCAB[list]) {
      if (!mastered(stat(list, code))) continue;
      for (const f of VOCAB_ITEMS[list][code].quiz) if (!PROSIGNS[f]) out.add(f);
    }
  }
  return [...out].sort();
}

/** Items of a list in overview order: abbreviations and Q codes alphabetically, prefixes by the country name. */
export function vocabSorted(list, meaning, locale) {
  const codes = [...VOCAB[list]];
  if (list === 'pfx') return codes.sort((a, b) => meaning(a).localeCompare(meaning(b), locale));
  return codes.sort((a, b) => a.localeCompare(b, 'en', { numeric: true }));
}

/** Item {list, code}; its meaning is t(`vocab.${list}.${code}`). */
export const vocabKey = (list, code) => `vocab.${list}.${code}`;

export const VOCAB_MASTER_N = 3;      // an item counts as mastered after ≥ 3 answers …
export const VOCAB_MASTER_ACC = 0.8;  // … with ≥ 80 % right and the last answer right
export const VOCAB_RETRY_AFTER = 3;   // a wrong item comes back after this many other questions
export const VOCAB_RECENT = 5;        // … and an item does not repeat within this many questions

/** Mastered = enough answers, mostly right, the last one right. s = [n, wrong, lastOk] or undefined. */
export function mastered(s) {
  return !!s && s[0] >= VOCAB_MASTER_N && (s[0] - s[1]) / s[0] >= VOCAB_MASTER_ACC - 1e-9 && s[2] === 1;
}

/**
 * Weight for picking an item: unseen items and items with errors more often (Laplace-smoothed error rate).
 * s = [n, wrong] of the item (server + this session together).
 */
export function vocabWeight(s) {
  const n = s ? s[0] : 0;
  const wrong = s ? s[1] : 0;
  if (!n) return 2;
  return 0.5 + 4 * ((wrong + 1) / (n + 2));
}
