// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

const siSuffix = ['', 'm', 'μ', 'n'];

export function siFormat(numUnit, unit) {

    let num = numUnit * unit;
    let unitScaled = unit;

    let exp3x = 0;
    if(num == 0) {
        return '0';
    }
    while((Math.abs(num) < 1.0) && (unitScaled <= 1.0)) {
        num *= 1000.0;
        unitScaled *= 1000.0;
        exp3x += 1;
    }

    let suffix = siSuffix[exp3x];
    if(suffix === undefined) {
        suffix = `e-${exp3x*3}`;
    }

    let f;
    if(unitScaled >= 1.0) {
        // Hide decimal digits below library unit.
        f = num.toFixed(0);
    } else {
        // Otherwise, always 3 digits after decimal point.
        f = num.toFixed(3);
    }

    return f+suffix;
}
