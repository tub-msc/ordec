// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

// WebSocket protocol types

export interface ViewInfo {
    name: string;
    auto_refresh: boolean;
}

export type ServerMessage =
    | { msg: 'viewlist'; views: ViewInfo[] }
    | { msg: 'exception'; exception: string }
    | { msg: 'view'; type: string; data: unknown; exception?: string }
    | { msg: 'localmodule_changed' };

// View system interfaces

export interface ViewInstance {
    update(data: any): void;
    destroy?(): void;
}

export interface ViewClass {
    new(resContent: HTMLElement): ViewInstance;
}

export interface ReportElementInstance {
    container: HTMLElement;
    update(data: any): void;
    destroy?(): void;
}

export interface ReportElementClass {
    new(container: HTMLElement, reportContext?: ReportContext): ReportElementInstance;
}

export interface ReportContext {
    plotGroups: PlotGroupManager;
}

export interface PlotGroupManager {
    register(plot: SyncablePlot, groupName: string | undefined): void;
    unregister(plot: SyncablePlot): void;
}

export interface SyncablePlot {
    setSyncCallbacks(callbacks: {
        onXDomainChange?: ((domain: number[]) => void) | null;
        onCrosshairXChange?: ((xValue: number | null) => void) | null;
    }): void;
    getXDomain(): number[] | null;
    setXDomain(domain: number[], options?: { suppressEvent?: boolean }): void;
    setCrosshairX(xValue: number, options?: { suppressEvent?: boolean }): void;
    clearCrosshair(options?: { suppressEvent?: boolean }): void;
    getHiddenNames(): Set<string>;
    setHiddenNames(names: Set<string>): void;
    getZoomState(): unknown;
    setZoomState(state: any): void;
    destroy(): void;
}

// Layout data types

export interface LayoutLayer {
    nid: number;
    path: string;
    styleCSS: string;
    styleCrossRect: boolean;
    styleStroke: number[] | null;
    styleFill: number[] | null;
    polys: LayoutPoly[];
    labels: LayoutLabel[];
    // Set during loading:
    shapeLineVerticesOffset: number;
    shapeLineVerticesCount: number;
    shapeTriVerticesOffset: number;
    shapeTriVerticesCount: number;
    labelVerticesOffset: number;
    labelVerticesCount: number;
}

export interface LayoutPoly {
    vertices: number[];
}

export interface LayoutLabel {
    pos: [number, number];
    text: string;
}

export interface LayoutData {
    extent: [number, number, number, number];
    unit: number;
    layers: LayoutLayer[];
}
