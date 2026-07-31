// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

package org.ordec.intellij;

import com.intellij.codeInspection.InspectionSuppressor;
import com.intellij.codeInspection.SuppressQuickFix;
import com.intellij.psi.PsiElement;
import org.jetbrains.annotations.NotNull;
import org.jetbrains.annotations.Nullable;

import java.util.Set;

/**
 * Silences Python inspections that misfire on ORD code by construction:
 * Python scope analysis cannot see names bound by node and net statements
 * (unresolved references) and connection statements like a.d -- b.g are
 * expression statements by design (statement seems to have no effect).
 * This cannot move to an ORD language server later, since LSP servers only
 * add diagnostics and cannot switch off the IDE's own Python inspections.
 */
public final class OrdInspectionSuppressor implements InspectionSuppressor {
    private static final Set<String> SUPPRESSED_TOOLS = Set.of(
        "PyUnresolvedReferences",
        "PyStatementEffect");

    @Override
    public boolean isSuppressedFor(@NotNull PsiElement element, @NotNull String toolId) {
        return SUPPRESSED_TOOLS.contains(toolId)
            && element.getContainingFile() instanceof OrdParserDefinition.OrdFile;
    }

    @Override
    public SuppressQuickFix @NotNull [] getSuppressActions(
            @Nullable PsiElement element, @NotNull String toolId) {
        return SuppressQuickFix.EMPTY_ARRAY;
    }
}
