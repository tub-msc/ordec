// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

package org.ordec.intellij;

import com.intellij.lexer.Lexer;
import com.intellij.openapi.fileTypes.SyntaxHighlighter;
import com.intellij.openapi.fileTypes.SyntaxHighlighterFactory;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.vfs.VirtualFile;
import com.jetbrains.python.highlighting.PyHighlighter;
import com.jetbrains.python.lexer.PythonHighlightingLexer;
import com.jetbrains.python.psi.LanguageLevel;
import org.jetbrains.annotations.NotNull;
import org.jetbrains.annotations.Nullable;

/**
 * Reuses the Python plugin's lexer-based highlighting for ORD files, with
 * the highlighting lexer wrapped in the ORD token merges — editor coloring
 * runs on the highlighter's lexer, not the parser, so without the wrap the
 * '$' and '!' tokens would render as bad characters.
 */
public final class OrdSyntaxHighlighterFactory extends SyntaxHighlighterFactory {
    @Override
    public @NotNull SyntaxHighlighter getSyntaxHighlighter(
            @Nullable Project project, @Nullable VirtualFile virtualFile) {
        LanguageLevel level = LanguageLevel.getLatest();
        return new PyHighlighter(level) {
            @Override
            public @NotNull Lexer getHighlightingLexer() {
                return new OrdLexer(new PythonHighlightingLexer(level));
            }
        };
    }
}
