// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

package org.ordec.intellij;

import com.intellij.lang.SyntaxTreeBuilder;
import com.intellij.psi.tree.IElementType;
import com.jetbrains.python.PyTokenTypes;
import com.jetbrains.python.parsing.StatementParsing;

import java.util.Set;

/**
 * Statement-level ORD delta, mirroring ord.lark: celldef, viewgen,
 * path_stmt/net_stmt, constrain_stmt and the node statements. All ORD
 * introducers are soft keywords, so every branch parses speculatively and
 * rolls back to plain Python on mismatch — the parser-level equivalent of
 * the GLR conflicts in the tree-sitter grammar.
 */
public class OrdStatementParsing extends StatementParsing {
    // soft keywords that must not open a node statement, same set as the
    // negative lookahead in the TextMate grammars
    private static final Set<String> NON_KIND_WORDS =
        Set.of("cell", "viewgen", "path", "net", "match", "case", "type", "anonymous");

    public OrdStatementParsing(OrdParser.OrdParsingContext context) {
        super(context);
    }

    @Override
    public void parseStatement() {
        if (parseOrdStatement()) {
            return;
        }
        super.parseStatement();
    }

    private boolean parseOrdStatement() {
        IElementType token = myBuilder.getTokenType();
        if (token == OrdElementTypes.CONSTRAIN_OP) {
            SyntaxTreeBuilder.Marker marker = myBuilder.mark();
            myBuilder.advanceLexer();
            myContext.getExpressionParser().parseExpression();
            endOfLine();
            marker.done(OrdElementTypes.CONSTRAIN_STATEMENT);
            return true;
        }
        if (token == PyTokenTypes.AT && parseDecoratedOrdDefinition()) {
            return true;
        }
        if (token != PyTokenTypes.IDENTIFIER) {
            return false;
        }
        String text = myBuilder.getTokenText();
        if ("cell".equals(text) && parseCellDefinition()) {
            return true;
        }
        if ("viewgen".equals(text) && parseViewgenDefinition()) {
            return true;
        }
        if (("path".equals(text) || "net".equals(text)) && parsePathNetStatement()) {
            return true;
        }
        boolean anonymous = "anonymous".equals(text);
        if (!anonymous && NON_KIND_WORDS.contains(text)) {
            return false;
        }
        return parseNodeStatement(anonymous);
    }

    // decorated: decorators (celldef | viewgen | ...) — Python's decorated
    // statement parsing only accepts def/class after decorators, so
    // decorated cell and viewgen definitions are handled here and any
    // other decorated statement rolls back to Python
    private boolean parseDecoratedOrdDefinition() {
        SyntaxTreeBuilder.Marker marker = myBuilder.mark();
        while (myBuilder.getTokenType() == PyTokenTypes.AT) {
            myBuilder.advanceLexer();
            int decoratorStart = myBuilder.getCurrentOffset();
            myContext.getExpressionParser().parseExpression();
            if (myBuilder.getCurrentOffset() == decoratorStart
                    || myBuilder.getTokenType() != PyTokenTypes.STATEMENT_BREAK) {
                marker.rollbackTo();
                return false;
            }
            myBuilder.advanceLexer();
        }
        if (myBuilder.getTokenType() == PyTokenTypes.IDENTIFIER) {
            String text = myBuilder.getTokenText();
            if (("cell".equals(text) && parseCellDefinition())
                    || ("viewgen".equals(text) && parseViewgenDefinition())) {
                marker.done(OrdElementTypes.DECORATED_DEFINITION);
                return true;
            }
        }
        marker.rollbackTo();
        return false;
    }

    // celldef: "cell" name ":" suite
    private boolean parseCellDefinition() {
        SyntaxTreeBuilder.Marker marker = myBuilder.mark();
        myBuilder.advanceLexer();
        if (myBuilder.getTokenType() == PyTokenTypes.IDENTIFIER) {
            myBuilder.advanceLexer();
            if (myBuilder.getTokenType() == PyTokenTypes.COLON) {
                myBuilder.advanceLexer();
                parseOrdSuite();
                marker.done(OrdElementTypes.CELL_DEFINITION);
                return true;
            }
        }
        marker.rollbackTo();
        return false;
    }

    // viewgen: "viewgen" name "->" test ":" suite
    private boolean parseViewgenDefinition() {
        SyntaxTreeBuilder.Marker marker = myBuilder.mark();
        myBuilder.advanceLexer();
        if (myBuilder.getTokenType() == PyTokenTypes.IDENTIFIER) {
            myBuilder.advanceLexer();
            if (myBuilder.getTokenType() == PyTokenTypes.RARROW) {
                myBuilder.advanceLexer();
                myContext.getExpressionParser().parseExpression();
                if (myBuilder.getTokenType() == PyTokenTypes.COLON) {
                    myBuilder.advanceLexer();
                    parseOrdSuite();
                    marker.done(OrdElementTypes.VIEWGEN_DEFINITION);
                    return true;
                }
            }
        }
        marker.rollbackTo();
        return false;
    }

    // path_stmt/net_stmt: keyword context_target ("," context_target)*
    private boolean parsePathNetStatement() {
        SyntaxTreeBuilder.Marker marker = myBuilder.mark();
        myBuilder.advanceLexer();
        if (myBuilder.getTokenType() != PyTokenTypes.IDENTIFIER) {
            marker.rollbackTo();
            return false;
        }
        do {
            parseContextTarget();
        } while (matchToken(PyTokenTypes.COMMA));
        endOfLine();
        marker.done(OrdElementTypes.PATH_NET_STATEMENT);
        return true;
    }

    // node_stmt / node_stmt_nobody, optionally after "anonymous"
    private boolean parseNodeStatement(boolean anonymous) {
        SyntaxTreeBuilder.Marker marker = myBuilder.mark();
        if (anonymous) {
            myBuilder.advanceLexer();
        }
        // the kind is an atom_expr chain (Nmos, lib.Inv, rows[0], Vdc(dc=1)):
        // parse a full expression, which covers all trailers, and require it
        // to be directly followed by the target name
        int kindStart = myBuilder.getCurrentOffset();
        myContext.getExpressionParser().parseExpression();
        if (myBuilder.getCurrentOffset() == kindStart
                || myBuilder.getTokenType() != PyTokenTypes.IDENTIFIER) {
            marker.rollbackTo();
            return false;
        }
        parseContextTarget();
        if (myBuilder.getTokenType() == PyTokenTypes.COLON) {
            myBuilder.advanceLexer();
            parseOrdSuite();
            marker.done(OrdElementTypes.NODE_STATEMENT);
            return true;
        }
        while (matchToken(PyTokenTypes.COMMA)) {
            if (myBuilder.getTokenType() == PyTokenTypes.IDENTIFIER) {
                parseContextTarget();
            }
        }
        if (atEndOfStatement()) {
            endOfLine();
            marker.done(OrdElementTypes.NODE_STATEMENT_NOBODY);
            return true;
        }
        marker.rollbackTo();
        return false;
    }

    // context_target: name ("." name | "[" subscript "]")*
    private void parseContextTarget() {
        SyntaxTreeBuilder.Marker marker = myBuilder.mark();
        myBuilder.advanceLexer();
        while (true) {
            if (myBuilder.getTokenType() == PyTokenTypes.DOT) {
                myBuilder.advanceLexer();
                if (myBuilder.getTokenType() == PyTokenTypes.IDENTIFIER) {
                    myBuilder.advanceLexer();
                }
            } else if (myBuilder.getTokenType() == PyTokenTypes.LBRACKET) {
                myBuilder.advanceLexer();
                // subscriptlist in ord.lark allows slices and comma lists,
                // consume expressions and their separators tolerantly
                while (myBuilder.getTokenType() != PyTokenTypes.RBRACKET
                        && !atEndOfStatement()) {
                    if (myBuilder.getTokenType() == PyTokenTypes.COLON
                            || myBuilder.getTokenType() == PyTokenTypes.COMMA) {
                        myBuilder.advanceLexer();
                        continue;
                    }
                    int exprStart = myBuilder.getCurrentOffset();
                    myContext.getExpressionParser().parseExpression();
                    if (myBuilder.getCurrentOffset() == exprStart) {
                        break;
                    }
                }
                matchToken(PyTokenTypes.RBRACKET);
            } else {
                break;
            }
        }
        marker.done(OrdElementTypes.CONTEXT_TARGET);
    }

    // suite in ord.lark allows ORD simple statements in one-line suites,
    // but the inherited inline suite parsing bypasses parseStatement, so
    // one-line suites are parsed here through the ORD-aware statement
    // parsing and block suites delegate to Python
    private void parseOrdSuite() {
        if (myBuilder.getTokenType() == PyTokenTypes.STATEMENT_BREAK) {
            parseSuite();
            return;
        }
        while (!atEndOfStatement()) {
            int statementStart = myBuilder.getCurrentOffset();
            parseStatement();
            if (myBuilder.getCurrentOffset() == statementStart
                    || lineEndedSince(statementStart)) {
                break;
            }
        }
        endOfLine();
    }

    // statement parsing consumes the line-ending break itself, so the
    // one-line suite is over once the consumed span crossed a line end —
    // only semicolon-separated statements stay on the same line
    private boolean lineEndedSince(int start) {
        CharSequence text = myBuilder.getOriginalText();
        int end = Math.min(myBuilder.getCurrentOffset(), text.length());
        for (int i = start; i < end; i++) {
            if (text.charAt(i) == '\n') {
                return true;
            }
        }
        return false;
    }

    private boolean atEndOfStatement() {
        IElementType token = myBuilder.getTokenType();
        return token == null || token == PyTokenTypes.STATEMENT_BREAK
            || token == PyTokenTypes.DEDENT;
    }

    private void endOfLine() {
        if (myBuilder.getTokenType() == PyTokenTypes.STATEMENT_BREAK) {
            myBuilder.advanceLexer();
        }
    }
}
