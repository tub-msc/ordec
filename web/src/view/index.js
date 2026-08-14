// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import { SvgView } from './svg.js';
import { ReportView } from './report.js';
import { LayoutView } from './layout.js';
import { DrcView } from './drc.js';
import { LvsView } from './lvs.js';

// Maps the type field of view messages to the class rendering that view type.
// The keys are protocol values sent by the server as msg.type; keep them in
// sync with the server side when adding or renaming a view.
export const viewClassOf = {
    svg: SvgView,
    report: ReportView,
    layout: LayoutView,
    drc: DrcView,
    lvs: LvsView,
};
