// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

package org.ordec.intellij;

import com.intellij.lang.SyntaxTreeBuilder;
import com.jetbrains.python.PyTokenTypes;
import com.jetbrains.python.parsing.ExpressionParsing;

/**
 * Expression-level ORD delta: the leading-dot access to the current node
 * (dotted_atom in ord.lark), e.g. `.align = North`, `.g -- y` or the bare
 * `.` — the only ORD expression form Python tokens cannot express. The
 * connection operator `--` needs no handling (it parses as subtraction of
 * a negation, exactly as in ord.lark), and `.$l`/`t.$w` parse as ordinary
 * attribute access thanks to the '$name' identifier merge in OrdLexer.
 */
public class OrdExpressionParsing extends ExpressionParsing {
    public OrdExpressionParsing(OrdParser.OrdParsingContext context) {
        super(context);
    }

    @Override
    public boolean parsePrimaryExpression(boolean isTargetExpression) {
        if (myBuilder.getTokenType() == PyTokenTypes.DOT) {
            SyntaxTreeBuilder.Marker marker = myBuilder.mark();
            myBuilder.advanceLexer();
            if (myBuilder.getTokenType() == PyTokenTypes.IDENTIFIER) {
                myBuilder.advanceLexer();
            }
            marker.done(OrdElementTypes.LOCAL_ATTRIBUTE);
            return true;
        }
        return super.parsePrimaryExpression(isTargetExpression);
    }
}
