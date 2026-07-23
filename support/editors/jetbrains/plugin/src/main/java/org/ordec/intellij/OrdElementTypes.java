// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

package org.ordec.intellij;

import com.intellij.psi.tree.IElementType;

/**
 * Element and token types for the ORD constructs, named after the rules in
 * ordec/ord/ord.lark (node_stmt and friends).
 */
public final class OrdElementTypes {
    // token produced by OrdLexer for the constrain operator '!'
    public static final IElementType CONSTRAIN_OP =
        new IElementType("ORD_CONSTRAIN_OP", OrdLanguage.INSTANCE);

    public static final IElementType DECORATED_DEFINITION =
        new IElementType("ORD_DECORATED_DEFINITION", OrdLanguage.INSTANCE);
    public static final IElementType CELL_DEFINITION =
        new IElementType("ORD_CELL_DEFINITION", OrdLanguage.INSTANCE);
    public static final IElementType VIEWGEN_DEFINITION =
        new IElementType("ORD_VIEWGEN_DEFINITION", OrdLanguage.INSTANCE);
    public static final IElementType NODE_STATEMENT =
        new IElementType("ORD_NODE_STATEMENT", OrdLanguage.INSTANCE);
    public static final IElementType NODE_STATEMENT_NOBODY =
        new IElementType("ORD_NODE_STATEMENT_NOBODY", OrdLanguage.INSTANCE);
    public static final IElementType PATH_NET_STATEMENT =
        new IElementType("ORD_PATH_NET_STATEMENT", OrdLanguage.INSTANCE);
    public static final IElementType CONSTRAIN_STATEMENT =
        new IElementType("ORD_CONSTRAIN_STATEMENT", OrdLanguage.INSTANCE);
    public static final IElementType CONTEXT_TARGET =
        new IElementType("ORD_CONTEXT_TARGET", OrdLanguage.INSTANCE);
    // leading-dot access to the current node, dotted_atom in ord.lark
    public static final IElementType LOCAL_ATTRIBUTE =
        new IElementType("ORD_LOCAL_ATTRIBUTE", OrdLanguage.INSTANCE);

    private OrdElementTypes() {
    }
}
