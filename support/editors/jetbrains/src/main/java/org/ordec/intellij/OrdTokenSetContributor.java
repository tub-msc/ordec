// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

package org.ordec.intellij;

import com.intellij.psi.tree.TokenSet;
import com.jetbrains.python.PythonDialectsTokenSetContributorBase;
import org.jetbrains.annotations.NotNull;

/**
 * Tells the Python plugin's shared token sets about the ORD constructs, so
 * PSI utilities that walk statements and expressions treat them as such.
 */
public final class OrdTokenSetContributor extends PythonDialectsTokenSetContributorBase {
    @Override
    public @NotNull TokenSet getStatementTokens() {
        return TokenSet.create(
            OrdElementTypes.DECORATED_DEFINITION,
            OrdElementTypes.CELL_DEFINITION,
            OrdElementTypes.VIEWGEN_DEFINITION,
            OrdElementTypes.NODE_STATEMENT,
            OrdElementTypes.NODE_STATEMENT_NOBODY,
            OrdElementTypes.PATH_NET_STATEMENT,
            OrdElementTypes.CONSTRAIN_STATEMENT);
    }

    @Override
    public @NotNull TokenSet getExpressionTokens() {
        return TokenSet.create(OrdElementTypes.LOCAL_ATTRIBUTE);
    }
}
