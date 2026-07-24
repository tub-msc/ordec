// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

package org.ordec.intellij;

import com.intellij.lang.SyntaxTreeBuilder;
import com.jetbrains.python.parsing.ExpressionParsing;
import com.jetbrains.python.parsing.ParsingContext;
import com.jetbrains.python.parsing.PyParser;
import com.jetbrains.python.parsing.StatementParsing;
import com.jetbrains.python.psi.LanguageLevel;
import org.jetbrains.annotations.NotNull;

/**
 * Python parser with the ORD statement and expression delta: a
 * ParsingContext subclass hands out the extended statement and expression
 * parsers.
 */
public final class OrdParser extends PyParser {
    @Override
    protected @NotNull ParsingContext createParsingContext(
            @NotNull SyntaxTreeBuilder builder, @NotNull LanguageLevel languageLevel) {
        return new OrdParsingContext(builder, languageLevel);
    }

    static final class OrdParsingContext extends ParsingContext {
        private final OrdStatementParsing statementParser;
        private final OrdExpressionParsing expressionParser;

        OrdParsingContext(SyntaxTreeBuilder builder, LanguageLevel languageLevel) {
            super(builder, languageLevel);
            statementParser = new OrdStatementParsing(this);
            expressionParser = new OrdExpressionParsing(this);
        }

        @Override
        public @NotNull StatementParsing getStatementParser() {
            return statementParser;
        }

        @Override
        public @NotNull ExpressionParsing getExpressionParser() {
            return expressionParser;
        }
    }
}
