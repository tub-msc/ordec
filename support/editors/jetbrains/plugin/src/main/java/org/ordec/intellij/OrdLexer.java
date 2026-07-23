// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

package org.ordec.intellij;

import com.intellij.lexer.Lexer;
import com.intellij.lexer.LookAheadLexer;
import com.intellij.psi.TokenType;
import com.intellij.psi.tree.IElementType;
import com.jetbrains.python.PyTokenTypes;
import com.jetbrains.python.lexer.PythonIndentingLexer;

/**
 * Python lexer with the three token-level ORD extensions. Everything else
 * about ORD is handled at parser level on unchanged Python tokens.
 *
 * - SI-suffixed rationals (400n, 3.14u): number token and an adjacent
 *   single-letter suffix identifier merge into one FLOAT_LITERAL.
 * - Parameter names ($l in .$l and t.$w): '$' (BAD_CHARACTER to Python)
 *   and the adjacent identifier merge into one IDENTIFIER, which makes
 *   parameter access parse as ordinary attribute access.
 * - The constrain operator '!' (also BAD_CHARACTER, since Python only
 *   knows "!=") becomes CONSTRAIN_OP.
 */
public final class OrdLexer extends LookAheadLexer {
    private static final String SI_SUFFIXES = "afpnumkMGT";

    // parsing configuration
    public OrdLexer() {
        this(new PythonIndentingLexer());
    }

    // the same merges over any base, e.g. the highlighting lexer
    public OrdLexer(Lexer baseLexer) {
        super(baseLexer);
    }

    @Override
    protected void lookAhead(Lexer baseLexer) {
        IElementType type = baseLexer.getTokenType();
        if (type == PyTokenTypes.INTEGER_LITERAL || type == PyTokenTypes.FLOAT_LITERAL) {
            int numberEnd = baseLexer.getTokenEnd();
            baseLexer.advance();
            if (isAdjacentSiSuffix(baseLexer, numberEnd)) {
                addToken(baseLexer.getTokenEnd(), PyTokenTypes.FLOAT_LITERAL);
                baseLexer.advance();
            } else {
                // keep just the number, the already-advanced base lexer is
                // picked up by the next lookAhead round
                addToken(numberEnd, type);
            }
            return;
        }
        if (type == TokenType.BAD_CHARACTER) {
            char bad = baseLexer.getBufferSequence().charAt(baseLexer.getTokenStart());
            if (bad == '$') {
                int dollarEnd = baseLexer.getTokenEnd();
                baseLexer.advance();
                if (baseLexer.getTokenType() == PyTokenTypes.IDENTIFIER
                        && baseLexer.getTokenStart() == dollarEnd) {
                    addToken(baseLexer.getTokenEnd(), PyTokenTypes.IDENTIFIER);
                    baseLexer.advance();
                } else {
                    addToken(dollarEnd, TokenType.BAD_CHARACTER);
                }
                return;
            }
            if (bad == '!') {
                int end = baseLexer.getTokenEnd();
                baseLexer.advance();
                addToken(end, OrdElementTypes.CONSTRAIN_OP);
                return;
            }
        }
        super.lookAhead(baseLexer);
    }

    private static boolean isAdjacentSiSuffix(Lexer lexer, int expectedStart) {
        if (lexer.getTokenType() != PyTokenTypes.IDENTIFIER) {
            return false;
        }
        if (lexer.getTokenStart() != expectedStart
                || lexer.getTokenEnd() - lexer.getTokenStart() != 1) {
            return false;
        }
        return SI_SUFFIXES.indexOf(lexer.getBufferSequence().charAt(lexer.getTokenStart())) >= 0;
    }
}
