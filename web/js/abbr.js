// SPDX-License-Identifier: EUPL-1.2
// Radioamatérské zkratky a Q-kódy pro příjem ve skluzu (M8, úroveň U4). Veřejné provozní konvence,
// seznam sestaven pro projekt. Jen znaky sady projektu, bez prozatímních znaků (prosignů).
export const ABBR = `
QRL QRM QRN QRO QRP QRQ QRS QRT QRU QRV QRX QRZ QSB QSL QSO QSY QTH QSK QRG QRK
CQ DE TU TNX TKS FB OM YL UR RST NAME OP WX RIG ANT PWR ES ABT AGN BCNU CUL GM GA GE GN GL HPE HI
PSE RPT SRI VY HR HW DX NR WKD BK CFM INFO SIG TEMP CONDX FER GUD NW OK RX TX TRX XTAL
5NN 599 579 73 88 2X 3X 100W 5W
`.trim().split(/\s+/);
